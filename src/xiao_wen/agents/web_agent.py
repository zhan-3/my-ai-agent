"""内置子 Agent：联网查询（多 Agent 架构的子 Agent 实体）

真实现：xiao_wen.web 的 ToolNode 图（ReAct 循环：天气/汇率/空气质量），
带短期记忆上下文注入（指代消解）。web_query 原实现随 worker 拆入本模块。
"""
INTENT = "联网查询"
DESCRIPTION = "用户要查实时信息（指定城市天气、汇率、空气质量）→ 联网查询。"

from typing import Any  # noqa: E402

from xiao_wen import web as _web  # noqa: E402


def _web_query(question: str, ctx: str = "无") -> str:
    """调 xiao_wen.web 的 ToolNode 图（ReAct 循环），返回最终回答文本。ctx=短期记忆上下文，支持指代消解"""
    msgs: list[Any] = [_web.SYSTEM]
    if ctx != "无":
        msgs.append(("system", f"以下是本次对话上文，新问题可能省略了主语（如「那上海呢」）：\n{ctx}"))
    msgs.append(("human", question))
    result = _web.app.invoke({"messages": msgs})
    return result["messages"][-1].content


def run(state) -> dict:
    """真实现：联网查询（天气/汇率/空气质量）+ 短期记忆上下文"""
    return {"answer": _web_query(state["user_input"], state.get("recent", "无"))}
