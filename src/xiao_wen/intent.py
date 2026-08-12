"""意图识别模块：prompt + schema + classify 的单一来源（C3，取代 system/scheduler 双份副本）

- 超集 prompt：六意图 + 边界 + 多意图拆分（subtasks）+ 指代消解提示
- 单一接口：classify(recent, user_input) -> IntentResult(intent, reason, subtasks)
- 链懒构建（走 LLM 单一接缝，熔断守卫自动继承）
"""
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel

from xiao_wen import llm

INTENT_VALUES = ("行程规划", "偏好记录", "历史查询", "知识问答", "联网查询", "其他")

intent_prompt = ChatPromptTemplate.from_messages([
    ("system", """你是企业差旅助手的意图分类器，输出严格 JSON。规则：
- 用户请助理安排行程、出差计划 → 行程规划
- 用户陈述个人偏好（住宿/餐饮/出行风格）→ 偏好记录
- 用户问历史对话/历史行程 → 历史查询
- 用户问差旅政策、报销、预订流程 → 知识问答
- 用户要查实时信息（天气、航班、交通）→ 联网查询
- 以上都不像 → 其他
边界：本助手只服务企业差旅。个人休闲/旅游规划、非差旅问题一律归「其他」。
参考最近对话理解省略/指代（如「那上海呢」指上一轮提到的城市）。

【多意图拆分】一句话里包含多个独立请求时（用"顺便/还有/以及/和"连接），
把每个独立请求拆成一条 subtasks（各自带 intent 和原文）；单一请求时 subtasks 为空数组 []。

输出键名必须严格为英文：
- "intent"：主导意图（严格六词之一），多意图时取第一个
- "reason"：一句话理由
- "subtasks"：数组，每项键名严格为 intent（六词之一）和 text（该子请求原文）
示例（单）：{{"intent": "行程规划", "reason": "要求安排出差行程", "subtasks": []}}
示例（多）：{{"intent": "知识问答", "reason": "包含政策和天气两个请求",
  "subtasks": [{{"intent": "知识问答", "text": "出差住宿标准是什么"}},
               {{"intent": "联网查询", "text": "北京今天天气怎么样"}}]}}"""),
    ("human", "最近对话：\n{recent}\n\n当前用户输入：{input}"),
])


class SubTask(BaseModel):
    intent: Literal["行程规划", "偏好记录", "历史查询", "知识问答", "联网查询", "其他"]
    text: str


class Intent(BaseModel):
    intent: Literal["行程规划", "偏好记录", "历史查询", "知识问答", "联网查询", "其他"]
    reason: str
    subtasks: list[SubTask] = []


@dataclass
class IntentResult:
    intent: str
    reason: str
    subtasks: list[dict]  # [{intent, text}, ...]


@lru_cache
def _intent_model():
    return intent_prompt | llm.get_llm().with_structured_output(Intent, method="json_mode")


def classify(recent: str, user_input: str) -> IntentResult:
    """意图分类：recent=最近对话（短期记忆，指代消解），user_input=当前输入

    返回 intent/reason/subtasks；subtasks 为空数组表示单意图（原路由路径不变）。
    """
    r = _intent_model().invoke({"recent": recent, "input": user_input})
    assert isinstance(r, Intent)
    return IntentResult(
        intent=r.intent,
        reason=r.reason,
        subtasks=[s.model_dump() for s in r.subtasks],
    )
