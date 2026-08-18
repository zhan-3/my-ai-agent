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
    if any(word in question for word in ("汇率", "兑换", "换多少")):
        expected.add("get_currency_rate")
    if any(word in question for word in ("空气质量", "PM2.5", "雾霾")):
        expected.add("get_air_quality")
    tool_messages = [message for message in result["messages"] if message.type == "tool"]
    used = {message.name for message in tool_messages}
    if not expected or not expected.issubset(used):
        return "暂时无法获取可靠实时信息，请稍后重试。", "unavailable"
    tool_text = "\n".join(str(message.content) for message in tool_messages if message.name in expected)
    if any(word in tool_text for word in ("失败", "服务可能不稳定", "暂时无法")):
        return tool_text, "unavailable"
    if any(word in tool_text for word in ("未找到", "仅支持", "不支持", "无法识别", "已经过去", "超出")):
        return tool_text, "invalid"
    return tool_text, "grounded"


def _normalize_date(value: str) -> str:
    if match := re.fullmatch(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})日?", value):
        return f"{match.group(1)}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"
    if match := re.fullmatch(r"(\d{1,2})月(\d{1,2})日?", value):
        return f"{date.today().year}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"
    return value


def _date_values(text: str) -> list[str]:
    pattern = r"20\d{2}-\d{1,2}-\d{1,2}|20\d{2}年\d{1,2}月\d{1,2}日?|\d{1,2}月\d{1,2}日?"
    return [_normalize_date(match.group(0)) for match in re.finditer(pattern, text)]


def _ticket_request(question: str, recent: str) -> tuple[str, str, str, str] | None:
    """从明确票务问题和当前行程上文提取站点/城市/日期，避免把查票重新路由成规划。"""
    text = f"{question}\n{recent}"
    dates = _date_values(question) + _date_values(recent)
    travel_date = dates[0] if dates else ""
    if "明天" in question:
        travel_date = (date.today() + timedelta(days=1)).isoformat()
    elif "后天" in question:
        travel_date = (date.today() + timedelta(days=2)).isoformat()
    date_pattern = r"(20\d{2}-\d{1,2}-\d{1,2}|20\d{2}年\d{1,2}月\d{1,2}日?|\d{1,2}月\d{1,2}日?)"
    return_match = re.search(rf"(?:返程|回来|返回|回程)[^0-9]{{0,10}}{date_pattern}", question)
    if not return_match:
        return_match = re.search(rf"{date_pattern}[^，,。]{{0,6}}(?:返程|回来|返回|回程)", question)
    return_date = _normalize_date(return_match.group(1)) if return_match else (dates[1] if len(dates) > 1 else "")
    station_match = re.search(r"从([^\s，,到]+)到([^\s，,的]+)", question)
    if station_match:
        return station_match.group(1), station_match.group(2), travel_date, return_date
    origin_match = re.search(r"从([^\s，,，。]+)(?:出发|去)", text)
    destination_match = re.search(r"(?:去|到)([^\s，,，。]+?)(?:出差|开会|的行程|$)", text)
    if origin_match and destination_match and travel_date:
        return origin_match.group(1), destination_match.group(1), travel_date, return_date
    positioned = sorted((text.find(city), -len(city), city) for city in KNOWN_CITIES if city in text)
    cities = list(dict.fromkeys(city for _, _, city in positioned))
    if len(cities) >= 2 and travel_date:
        return cities[0], cities[1], travel_date, return_date
    return None


def run(state) -> dict:
    """真实现：联网查询（天气/汇率/空气质量/铁路12306查询入口）+ 短期记忆上下文"""
    question = state["user_input"]
    if any(
        word in question
        for word in ("车票", "车次", "余票", "高铁票", "火车票", "12306", "铁路", "高铁", "动车", "票价", "购票")
    ) and any(word in question for word in ("查", "看", "查询", "有没有", "票", "余", "购", "买", "价格", "时刻")):
        request = _ticket_request(question, state.get("recent", ""))
        if request:
            answer = _web.search_train_tickets.func(*request)  # type: ignore[attr-defined]
            if "https://kyfw.12306.cn/otn/leftTicket/init" in answer and "不代购票" in answer:
                status = "official"
            elif "暂时无法读取" in answer:
                status = "unavailable"
            else:
                status = "invalid"
            return {"answer": answer, "ticket_status": status}
    answer, status = _web_query(question, state.get("recent", "无"))
    return {"answer": answer, "realtime_status": status}
