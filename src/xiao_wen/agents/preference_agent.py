"""内置子 Agent：偏好记录（多 Agent 架构的子 Agent 实体）

偏好提取 prompt/schema 随实现迁入本模块（原 xiao_wen.system），
记忆写入收口于深模块 xiao_wen.memory（追加/覆盖 is_update 语义）。
"""

INTENT = "偏好记录"
DESCRIPTION = "用户陈述个人偏好（住宿、餐饮、出行风格、常驻城市、预算）→ 偏好记录。"

from functools import lru_cache  # noqa: E402
from typing import Literal  # noqa: E402

from langchain_core.prompts import ChatPromptTemplate  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from xiao_wen import llm  # noqa: E402
from xiao_wen.memory import add_or_update_preference  # noqa: E402


class PreferenceRecord(BaseModel):
    """用户偏好记录"""

    category: Literal["住宿", "餐饮", "交通", "预算", "常驻城市", "其他"]
    content: str = Field(description="偏好内容的一句话")
    is_update: bool = Field(default=False, description="True=覆盖同类别旧条目；False=新增")


class PreferenceList(BaseModel):
    """一条消息可能含多个偏好（如「我喜欢住汉庭，常住上海」→ 住宿 + 常驻城市两条）"""

    records: list[PreferenceRecord] = Field(description="从原话提取的全部偏好；疑问句/无偏好陈述时返回空数组 []")


pref_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是企业差旅助手的偏好提取器，输出严格 JSON。
从用户原话提取**全部**偏好（一条消息可能含多个事实，必须逐个提取）。
**只提取用户陈述的偏好事实**：疑问句、询问、请求不提取！
例如「我常住哪里？」「我的住宿偏好是什么？」「帮我记一下」都不是偏好陈述 → records 返回空数组 []。
顶层键名必须为 records（数组，可为空），每项键名为：
- category：严格是六词之一：住宿、餐饮、交通、预算、常驻城市、其他
- content：偏好内容一句话
- is_update：布尔。用户表达「现在/改成/以后/不再/其实是」等更新语气时 true，否则 false。
示例：「我喜欢住汉庭，常住上海」→
{{"records": [
  {{"category": "住宿", "content": "喜欢住汉庭", "is_update": false}},
  {{"category": "常驻城市", "content": "上海", "is_update": true}}
]}}
单个偏好：「我喜欢住全季」→ {{"records": [{{"category": "住宿", "content": "喜欢住全季", "is_update": false}}]}}。"""
        ),
        ("human", "{input}"),
    ]
)


@lru_cache
def _pref_model():
    return pref_prompt | llm.get_llm().with_structured_output(PreferenceList, method="json_mode")


def run(state) -> dict:
    r = _pref_model().invoke({"input": state["user_input"]})
    assert isinstance(r, PreferenceList)
    # 追加/覆盖区分：is_update=True 时替换同类别旧条目（如「我现在常住上海」）
    if not r.records:
        # 疑问句/非偏好陈述：不写任何记忆（防止垃圾数据污染长期记忆）
        return {"answer": "这是询问而非偏好陈述——如果你告诉我「我常住上海」「我喜欢住汉庭」这类信息，我会帮你记下。"}
    session_id = state.get("session_id", "default")
    lines: list[str] = []
    for rec in r.records:
        stored = add_or_update_preference(rec.category, rec.content, rec.is_update, session_id=session_id)
        act = "更新" if rec.is_update else "新增"
        lines.append(f"✅ 已{act}偏好：{stored['category']}｜{stored['content']}（{stored['ts']}）")
    return {"answer": "\n".join(lines) if lines else "✅ 已记录偏好"}
