"""意图识别模块：prompt + schema + classify 的单一来源（C3，多 Agent 架构动态词汇表）

- 动态词汇表：意图清单来自子 Agent 注册表（set_intents(manifest) 注入），
  分类 prompt 由 manifest 的 INTENT/DESCRIPTION 动态组装——新增子 Agent 主管零改动（渐进式披露）
- 静态规则：边界 / 指代消解 / 多意图拆分（subtasks）/ JSON 键名约束
- 单一接口：classify(recent, user_input) -> IntentResult(intent, reason, subtasks)
- 链懒构建（走 LLM 单一接缝，熔断守卫自动继承）
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from xiao_wen import llm

# 模块级当前词汇表：None = 未注入，classify 时从注册表 discover() 取默认（六内置 + 外部扩展）
_current_intents: list[dict] | None = None

# 意图级 few-shot 示例（第二阶段：示例是提升准确率最快的手段）。
# 键=INTENT（内置六意图）；外部插件意图无示例时自动跳过（DESCRIPTION 可自带说明）。
_EXAMPLES: dict[str, list[str]] = {
    "行程规划": [
        "帮我规划10月1日去广州出差2天的行程",
        "下周去上海开会，帮我安排一下住宿和交通",
        "帮我订一张去北京的机票",  # 行程相关动作（即使无法直接执行）→ 行程规划
        "查一下回程日期有没有航班",  # 航班查询（行程相关动作，即使无航班工具）→ 行程规划+追问
        "帮我查查10月8日有没有去深圳的航班",
        "上海",  # （上下文：助手刚追问「请补充出发城市」）→ 补全行程要素
        "4天",  # （上下文：助手刚追问「出差几天」）→ 补全行程要素
    ],
    "偏好记录": [
        "我喜欢住汉庭酒店",
        "我常住上海，不吃辣",
        "我之前说不吃辣，现在改成吃辣",  # 更新语气也是陈述
    ],
    "历史查询": [
        "我上次的行程是什么",
        "我常住哪里",
        "我上次住的酒店叫什么",  # 问自己的历史记录，即使带住宿词
    ],
    "知识问答": [
        "出差打车能报销吗",
        "一线城市的住宿标准是多少",
    ],
    "联网查询": [
        "北京明天天气怎么样",
        "今天美元兑人民币汇率多少",
    ],
    "其他": [
        "杭州有什么好玩的旅游景点",  # 个人休闲 → 其他
        "帮我写一首诗",
        "我住哪里比较好",  # 咨询建议，非查记忆非陈述 → 其他
    ],
}

# 边界情况规则（第二阶段）：模棱两可时的处理优先级，明示给模型
_BOUNDARY_RULES = (
    "边界情况（模棱两可时按此优先级）：\n"
    "· 行程相关动作（订票/订酒店/安排/规划出行/查航班/查车次），即使助手无法直接执行 → 行程规划（会追问细节）；\n"
    "· 待补全续接：**若最近对话中助手在追问行程要素**（回复含「请补充/还缺」），\n"
    "  用户本轮直接补充要素（城市/日期/天数/地点，哪怕只有一个词）→ 行程规划（续接未完成的行程）；\n"
    "  若该句同时是偏好陈述（含常住/喜欢/不吃/习惯等）→ 主导意图仍为行程规划，subtasks 追加偏好记录；\n"
    "  上一轮没有追问行程要素时，「我常住上海」这类纯陈述 → 偏好记录。\n"
    "· 查询类（问政策/问记忆/问实时信息）按内容归类，不因含行动词就归行程规划；\n"
    "· 一句话含多个独立请求 → 拆 subtasks（主导意图取第一个）；\n"
    "· 拿不准且与差旅无关 → 其他（兜底）。\n"
)


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
    catalog_lines = []
    for m in intents:
        line = f"- {m['INTENT']}：{m['DESCRIPTION']}"
        ex = _EXAMPLES.get(m["INTENT"])
        if ex:
            line += " 典型：" + "；".join(ex)
        catalog_lines.append(line)
    catalog = "\n".join(catalog_lines)
    system_msg = (
        "你是企业差旅助手的意图分类器，输出严格 JSON。规则：\n"
        f"可用意图（严格选一，不在清单内或与业务无关的一律归「其他」）：\n{catalog}\n"
        f"{_BOUNDARY_RULES}"
        "边界：本助手只服务企业差旅。个人休闲/旅游规划、非差旅问题一律归「其他」。\n"
        "区分陈述与询问：用户**陈述**偏好事实（如「我喜欢住汉庭」）→ 偏好记录；\n"
        "用户**询问**自己的偏好/常驻地/记忆（如「我常住哪里」「我的住宿偏好是什么」）是查询记忆 → 历史查询。\n"
        "咨询类（「住哪里比较好」「推荐哪家酒店」「应该注意什么」）不是查记忆也不是陈述，→ 其他。\n"
        "参考最近对话理解省略/指代（如「那上海呢」指上一轮提到的城市）。\n"
        "指代句（以「那/那呢/然后呢/那…呢/接下来」开头、省略了主体）：**先识别句中的查询对象**——\n"
        "问天气/汇率/实时信息 → 联网查询；问政策/报销 → 知识问答；\n"
        "问行程要素（预算/住宿/交通安排）且上文在规划行程 → 行程规划；\n"
        "问自己的记录 → 历史查询；否则沿用上一轮意图。\n\n"
        '【多意图拆分】一句话里包含多个独立请求时（用"顺便/还有/以及/和"连接），\n'
        "把每个独立请求拆成一条 subtasks（各自带 intent 和原文）；单一请求时 subtasks 为空数组 []。\n\n"
        "输出键名必须严格为英文：\n"
        '- "intent"：主导意图（严格清单内之一），多意图时取第一个\n'
        '- "reason"：一句话理由，写明关键判断依据（引用了哪条规则/示例，或指代了哪轮上文）\n'
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


# ---- 多意图拆分兜底（ticket 07） ----
# 强拆分标记：只有前接子句分隔符（，。；！？）才算拆分点
# （「我还有事」的「还有」前无分隔符 → 不拆，防误拆）
_SPLIT_MARKERS = re.compile(r"顺便|顺带|顺道|另外|还有")
_CLause_SEPARATOR = re.compile(r"[，,。;；!！?？]\s*$")


def _split_subtasks(user_input: str) -> list[str]:
    """确定性切句：返回每个拆分点之后的子句（去尾标点），无拆分点返回空。

    仅切强标记（顺便/顺带/顺道/另外/还有）且标记前接子句分隔符的位置；
    多标记时按标记间分段，避免后段吞掉更靠后的标记。
    """
    marks = [
        (m.start(), m.end())
        for m in _SPLIT_MARKERS.finditer(user_input)
        if _CLause_SEPARATOR.search(user_input[: m.start()])
    ]
    chunks = []
    for i, (_, e) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(user_input)
        seg = user_input[e:end].strip(" ，,。;；!！?？")
        if seg:
            chunks.append(seg)
    return chunks


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
    result = IntentResult(intent=intent, reason=r.reason, subtasks=subtasks)
    # 待补全续接（规则兑底）：LLM 分类不稳时（同场景可能归偏好/其他），
    # 只要 recent 里助手在追问行程要素、本轮是简短补充 → 确定性修正为行程规划。
    result = _recover_pending(recent, user_input, result)
    # 拆分兜底：主导意图清晰但 LLM 把「顺便/还有X」整句吞掉（subtasks 空）→
    # 在强拆分标记处确定性切句，尾部子句再分类补进 subtasks（防次要请求被静默丢弃）
    if not result.subtasks:
        for chunk in _split_subtasks(user_input):
            sub = classify(recent, chunk)
            if sub.intent in (result.intent, "其他"):
                continue  # 子句与主导同意图（已被覆盖）或属闲聊 → 不进并行
            result.subtasks.append(SubTask(intent=sub.intent, text=chunk))
    # 归一化：多意图契约 = subtasks 含全部请求（主导在前，text=完整输入）——
    # LLM 常只把次要请求放进 subtasks、漏掉主导（黄金集锁定 [主导, 次要] 形状；
    # dispatch 的同类兜底仍在，此处让 classify 自身契约自洽）
    if result.subtasks and not any(s.intent == result.intent for s in result.subtasks):
        result.subtasks.insert(0, SubTask(intent=result.intent, text=user_input))
    return result


# ---- 待补全续接（规则兑底：确定性，不依赖 LLM 稳定性） ----

# recent 里助手的追问标记（行程要素追问的确认回复文案）
_PENDING_MARKS = ("请补充", "还缺", "请提供")
# 放弃/转向词：用户不想继续时尊重，不强行续接
_ABANDON_WORDS = ("算了", "不用", "取消", "不要了", "没事了", "回头再说")
# 强查询意图词：问历史/统计/知识/实时信息时尊重原意图，不做续接修正
_QUERY_WORDS = ("上次", "去过", "历史", "统计", "画像", "天气", "汇率", "报销", "标准", "政策", "规定", "怎么")
# 偏好陈述词：续接同时也在记偏好 → 并行处理两件事（行程补全 + 偏好记录）
_PREF_STATEMENT_WORDS = ("常住", "喜欢", "不吃", "忌口", "习惯", "口味", "偏好")


def _recover_pending(recent: str, user_input: str, result: IntentResult) -> IntentResult:
    """待补全续接规则：助手上一轮在追问行程要素（recent 含「请补充/还缺」），
    本轮输入是简短补充（无放弃词、无强查询词）→ 修正主导意图为行程规划；
    若原意图是偏好记录且句子含偏好词 → subtasks 追加偏好记录（并行记偏好 + 续接）。

    为什么需要：LLM 分类对「我现在常住上海」在追问上下文的归属不稳定（
    实测同 prompt 两次结果不同：一次行程规划+并行、一次纯偏好记录），
    规则兜底保证续接确定性。"""
    if not recent or not any(m in recent for m in _PENDING_MARKS):
        return result
    q = user_input.strip()
    if not q or any(w in q for w in _ABANDON_WORDS + _QUERY_WORDS):
        return result
    # 主导意图已是行程规划（LLM 直接归对）→ 仍需确保偏好记录进 subtasks：
    # 「追问上下文的偏好陈述」同时是补全+记偏好两件事，不依赖 LLM 原分类
    if result.intent == "行程规划" and any(w in q for w in _PREF_STATEMENT_WORDS):
        if not any(s.intent == "偏好记录" for s in result.subtasks):
            return IntentResult(
                intent=result.intent,
                reason=result.reason,
                subtasks=[*result.subtasks, SubTask(intent="偏好记录", text=q)],
            )
        return result
    if result.intent not in ("偏好记录", "其他"):
        return result
    subs = list(result.subtasks)
    if any(w in q for w in _PREF_STATEMENT_WORDS) and not any(s.intent == "偏好记录" for s in subs):
        subs.append(SubTask(intent="偏好记录", text=q))
    note = "（同时记偏好）" if subs else ""
    return IntentResult(
        intent="行程规划",
        reason=f"规则兑底：上一轮在追问行程要素，本轮「{q}」视为补全{note}",
        subtasks=subs,
    )
