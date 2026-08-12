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


pref_prompt = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """你是企业差旅助手的偏好提取器，输出严格 JSON。
从用户原话提取偏好，键名必须严格为英文：
- category：严格是六词之一：住宿、餐饮、交通、预算、常驻城市、其他
- content：偏好内容一句话
- is_update：布尔。用户表达「现在/改成/以后/不再/其实是」等更新语气时 true，否则 false。
  示例：「我喜欢住汉庭」→ false（新增）；「我现在常住上海」→ true（更新常驻城市）
输出示例：{{"category": "住宿", "content": "喜欢住全季酒店", "is_update": false}}，
更新示例：{{"category": "常驻城市", "content": "上海", "is_update": true}}。""",
        ),
        ("human", "{input}"),
    ]
)


@lru_cache
def _pref_model():
    return pref_prompt | llm.get_llm().with_structured_output(PreferenceRecord, method="json_mode")


def run(state) -> dict:
    r = _pref_model().invoke({"input": state["user_input"]})
    assert isinstance(r, PreferenceRecord)
    # 追加/覆盖区分：is_update=True 时替换同类别旧条目（如「我现在常住上海」）
    session_id = state.get("session_id", "default")
    rec = add_or_update_preference(r.category, r.content, r.is_update, session_id=session_id)
    act = "更新" if r.is_update else "新增"
    return {"answer": f"✅ 已{act}偏好：{rec['category']}｜{rec['content']}（{rec['ts']}）"}
