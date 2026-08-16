"""内置子 Agent：联网查询（多 Agent 架构的子 Agent 实体）

真实现：xiao_wen.web 的 ToolNode 图（ReAct 循环：天气/汇率/空气质量），
带短期记忆上下文注入（指代消解）。web_query 原实现随子 Agent 化拆入本模块。
"""

INTENT = "联网查询"
DESCRIPTION = "用户要查实时信息（天气、汇率、空气质量）或生成铁路12306车次查询入口 → 联网查询。"

import re  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from typing import Any  # noqa: E402

from xiao_wen import web as _web  # noqa: E402
from xiao_wen.reference_data import KNOWN_CITIES  # noqa: E402


def _web_query(question: str, ctx: str = "无") -> str:
    """调 xiao_wen.web 的 ToolNode 图（ReAct 循环），返回最终回答文本。ctx=短期记忆上下文，支持指代消解"""
    msgs: list[Any] = [_web.SYSTEM]
    if ctx != "无":
        msgs.append(("system", f"以下是本次对话上文，新问题可能省略了主语（如「那上海呢」）：\n{ctx}"))
    msgs.append(("human", question))
    result = _web.app.invoke({"messages": msgs})
    return result["messages"][-1].content


def _ticket_request(question: str, recent: str) -> tuple[str, str, str, str] | None:
    """从明确票务问题和当前行程上文提取站点/城市/日期，避免把查票重新路由成规划。"""
    text = f"{question}\n{recent}"
    date_match = re.search(r"20\d{2}-\d{2}-\d{2}", text)
    travel_date = date_match.group(0) if date_match else ""
    if not travel_date:
        cn_date = re.search(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})日?", text)
        if cn_date:
            travel_date = f"{cn_date.group(1)}-{int(cn_date.group(2)):02d}-{int(cn_date.group(3)):02d}"
        else:
            short_date = re.search(r"(\d{1,2})月(\d{1,2})日?", text)
            if short_date:
                travel_date = f"{date.today().year}-{int(short_date.group(1)):02d}-{int(short_date.group(2)):02d}"
    if "明天" in question:
        travel_date = (date.today() + timedelta(days=1)).isoformat()
    elif "后天" in question:
        travel_date = (date.today() + timedelta(days=2)).isoformat()
    return_match = re.search(r"(?:返程|回来|返回|回程)[^0-9]*(20\d{2}-\d{2}-\d{2})", text)
    return_date = return_match.group(1) if return_match else ""
    station_match = re.search(r"从([^\s，,到]+)到([^\s，,的]+)", question)
    if station_match:
        return station_match.group(1), station_match.group(2), travel_date, return_date
    origin_match = re.search(r"从([^\s，,，。]+)(?:出发|去)", text)
    destination_match = re.search(r"(?:去|到)([^\s，,，。]+?)(?:出差|开会|的行程|$)", text)
    if origin_match and destination_match and travel_date:
        return origin_match.group(1), destination_match.group(1), travel_date, return_date
    cities = [city for city in sorted(KNOWN_CITIES, key=len, reverse=True) if city in text]
    if len(cities) >= 2 and travel_date:
        return cities[-1], cities[0], travel_date, return_date
    return None


def run(state) -> dict:
    """真实现：联网查询（天气/汇率/空气质量/铁路12306查询入口）+ 短期记忆上下文"""
    question = state["user_input"]
    if any(word in question for word in ("车票", "车次", "余票", "高铁票")) and any(
        word in question for word in ("查", "看", "查询", "有没有")
    ):
        request = _ticket_request(question, state.get("recent", ""))
        if request:
            return {"answer": _web.search_train_tickets.func(*request)}  # type: ignore[attr-defined]
    return {"answer": _web_query(question, state.get("recent", "无"))}
