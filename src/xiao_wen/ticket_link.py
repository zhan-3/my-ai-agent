"""铁路 12306 官方预填链接的统一生成入口。"""

from __future__ import annotations

from urllib.parse import quote

from xiao_wen.stations import resolve_station
from xiao_wen.ticket_policy import validate_ticket_dates

URL = "https://kyfw.12306.cn/otn/leftTicket/init"


def build_ticket_url(origin: str, destination: str, travel_date: str, return_date: str = "") -> tuple[str, str | None]:
    """返回官方预填 URL 和错误信息；不生成未经日期/车站核验的链接。"""
    date_error = validate_ticket_dates(travel_date, return_date)
    if date_error:
        return "", date_error
    try:
        from_station = resolve_station(origin)
        to_station = resolve_station(destination)
    except Exception:
        return "", "暂时无法读取12306官方车站数据，请稍后重试；未生成未经核验的车站链接。"
    if not from_station or not to_station:
        return "", f"无法从12306官方车站数据确认“{origin}”或“{destination}”对应的唯一车站，请补充具体车站。"
    dates = f"{travel_date},{return_date}" if return_date else travel_date
    query = (
        f"linktypeid={'wf' if return_date else 'dc'}"
        f"&fs={quote(f'{from_station[0]},{from_station[1]}', safe=',')}"
        f"&ts={quote(f'{to_station[0]},{to_station[1]}', safe=',')}"
        f"&date={quote(dates, safe=',')}"
        "&flag=N,N,Y"
    )
    return f"{URL}?{query}", None


def ticket_label(origin: str, destination: str, travel_date: str, return_date: str = "") -> str:
    """生成给用户看的票务入口文案。"""
    url, error = build_ticket_url(origin, destination, travel_date, return_date)
    if error:
        return error
    dates = f"出发日期 {travel_date}"
    if return_date:
        dates += f"，返程日期 {return_date}"
    return (
        f"已生成铁路12306官方预填查询入口：{origin} → {destination}，{dates}\n"
        f"{url}\n"
        "车站名称和电报码来自12306官方车站数据；请在12306页面确认实际车次、余票、票价和乘车人信息；晓问不代购票。"
    )
