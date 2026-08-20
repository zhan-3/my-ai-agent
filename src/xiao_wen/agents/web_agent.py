"""内置子 Agent：联网查询（多 Agent 架构的子 Agent 实体）

真实现：xiao_wen.web 的 ToolNode 图（ReAct 循环：天气/汇率/空气质量），
带短期记忆上下文注入（指代消解）。web_query 原实现随子 Agent 化拆入本模块。
"""

INTENT = "联网查询"
DESCRIPTION = "用户要查实时信息（天气、汇率、空气质量、当地时间/时差） → 联网查询。"

from typing import Any  # noqa: E402

from xiao_wen import web as _web  # noqa: E402


def _web_query(question: str, ctx: str = "无") -> tuple[str, str]:
    """执行联网 ReAct，并显式标记实时结果是否有工具 observation。"""
    msgs: list[Any] = [_web.SYSTEM]
    if ctx != "无":
        msgs.append(("system", f"以下是本次对话上文，新问题可能省略了主语（如「那上海呢」）：\n{ctx}"))
    msgs.append(("human", question))
    result = _web.app.invoke({"messages": msgs})
    expected = set()
    if any(word in question for word in ("天气", "气温", "下雨", "降雨", "台风", "雷暴")):
        expected.add("get_weather")
    if any(
        word in question
        for word in ("汇率", "兑换", "兑", "换多少", "等于多少", "美元", "人民币", "欧元", "日元", "港币", "英镑")
    ):
        expected.add("get_currency_rate")
    if any(word in question for word in ("空气质量", "PM2.5", "雾霾")):
        expected.add("get_air_quality")
    if any(word in question for word in ("时差", "几点", "当地时间", "当地几点", "现在时间")):
        expected.add("get_local_time")
    tool_messages = [message for message in result["messages"] if message.type == "tool"]
    used = {message.name for message in tool_messages}
    if not expected or not expected.issubset(used):
        return "暂时无法获取可靠实时信息，请稍后重试。", "unavailable"
    # 去重：ReAct 可能重复调用同一工具返回相同内容（如连续两次越界日期提示），保留首次
    seen: list[str] = []
    for message in tool_messages:
        if message.name in expected:
            content = str(message.content).strip()
            if content and content not in seen:
                seen.append(content)
    tool_text = "\n".join(seen)
    if any(word in tool_text for word in ("失败", "服务可能不稳定", "暂时无法")):
        return tool_text, "unavailable"
    if any(word in tool_text for word in ("未找到", "仅支持", "不支持", "无法识别", "已经过去", "超出")):
        return tool_text, "invalid"
    return tool_text, "grounded"


def run(state) -> dict:
    """真实现：联网查询（天气/汇率/空气质量）+ 短期记忆上下文"""
    question = state["user_input"]
    answer, status = _web_query(question, state.get("recent", "无"))
    return {"answer": answer, "realtime_status": status}
