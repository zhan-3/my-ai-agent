"""意图识别模块：prompt + schema + classify 的单一来源（C3，多 Agent 架构动态词汇表）

- 动态词汇表：意图清单来自子 Agent 注册表（set_intents(manifest) 注入），
  分类 prompt 由 manifest 的 INTENT/DESCRIPTION 动态组装——新增子 Agent 主管零改动（渐进式披露）
- 静态规则：边界 / 指代消解 / 多意图拆分（subtasks）/ JSON 键名约束
- 单一接口：classify(recent, user_input) -> IntentResult(intent, reason, subtasks)
- 链懒构建（走 LLM 单一接缝，熔断守卫自动继承）
"""

from dataclasses import dataclass
from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from xiao_wen import llm

# 模块级当前词汇表：None = 未注入，classify 时从注册表 discover() 取默认（六内置 + 外部扩展）
_current_intents: list[dict] | None = None


def set_intents(manifest: list[dict]) -> None:
    """注入意图词汇表（注册表 manifest：每条含 INTENT / DESCRIPTION）

    词汇表变化时同时失效 _intent_model 缓存——运行中热插拔（重新发现 →
    重新注入）后，下一次 classify 会用新词汇表重建 prompt，不依赖时序。
    """
    global _current_intents  # noqa: PLW0603 —— 词汇表注入是模块级状态的刻意设计
    _current_intents = list(manifest)
    _intent_model.cache_clear()


def _intents() -> list[dict]:
    """当前意图清单；未注入时回退到注册表自动发现（默认六内置 + 外部扩展）"""
    if _current_intents is not None:
        return _current_intents
    from xiao_wen import plugin_registry  # 懒导入：避免 intent → registry 循环依赖

    return plugin_registry.discover()


def _build_prompt(intents: list[dict]) -> ChatPromptTemplate:
    """组装分类 prompt：静态规则头（边界/拆分/指代）+ 动态意图清单（渐进式披露）"""
    # 动态部分单独拼接（无花括号转义问题）；静态部分用普通字符串保留 {{ }} 模板转义
    catalog = "\n".join(f"- {m['INTENT']}：{m['DESCRIPTION']}" for m in intents)
    system_msg = (
        "你是企业差旅助手的意图分类器，输出严格 JSON。规则：\n"
        f"可用意图（严格选一，不在清单内或与业务无关的一律归「其他」）：\n{catalog}\n"
        "边界：本助手只服务企业差旅。个人休闲/旅游规划、非差旅问题一律归「其他」。\n"
        "参考最近对话理解省略/指代（如「那上海呢」指上一轮提到的城市）。\n\n"
        '【多意图拆分】一句话里包含多个独立请求时（用"顺便/还有/以及/和"连接），\n'
        "把每个独立请求拆成一条 subtasks（各自带 intent 和原文）；单一请求时 subtasks 为空数组 []。\n\n"
        "输出键名必须严格为英文：\n"
        '- "intent"：主导意图（严格清单内之一），多意图时取第一个\n'
        '- "reason"：一句话理由\n'
        '- "subtasks"：数组，每项键名严格为 intent（清单内之一）和 text（该子请求原文）\n'
        '示例（单）：{{"intent": "行程规划", "reason": "要求安排出差行程", "subtasks": []}}\n'
        '示例（多）：{{"intent": "知识问答", "reason": "包含政策和天气两个请求",\n'
        '  "subtasks": [{{"intent": "知识问答", "text": "出差住宿标准是什么"}},\n'
        '               {{"intent": "联网查询", "text": "北京今天天气怎么样"}}]}}'
    )
    return ChatPromptTemplate.from_messages(
        [
            ("system", system_msg),
            ("human", "最近对话：\n{recent}\n\n当前用户输入：{input}"),
        ]
    )


class SubTask(BaseModel):
    intent: str  # 动态词汇表内之一（注入后由 prompt 约束 + classify 兜底归「其他」）
    text: str


class Intent(BaseModel):
    intent: str
    reason: str
    subtasks: list[SubTask] = []


@dataclass
class IntentResult:
    intent: str
    reason: str
    subtasks: list[SubTask]  # 多意图拆分子任务（单意图时为空数组）


@lru_cache
def _intent_model():
    return _build_prompt(_intents()) | llm.get_llm().with_structured_output(Intent, method="json_mode")


def classify(recent: str, user_input: str) -> IntentResult:
    """意图分类：recent=最近对话（短期记忆，指代消解），user_input=当前输入

    返回 intent/reason/subtasks；subtasks 为空数组表示单意图（原路由路径不变）。
    意图不在当前词汇表内（LLM 幻觉）时兜底归「其他」。
    """
    r = _intent_model().invoke({"recent": recent, "input": user_input})
    assert isinstance(r, Intent)
    known = {m["INTENT"] for m in _intents()}
    subtasks = [s if s.intent in known else SubTask(intent="其他", text=s.text) for s in r.subtasks]
    intent = r.intent if r.intent in known else "其他"
    return IntentResult(intent=intent, reason=r.reason, subtasks=subtasks)
