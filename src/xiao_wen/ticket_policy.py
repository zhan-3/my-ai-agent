"""12306 车票预售期：优先读取铁路官方页面，失败时保守回退。"""

from __future__ import annotations

import re
from datetime import date, timedelta
from functools import lru_cache

import requests

OFFICIAL_ADVANCE_URL = "https://mobile.12306.cn/weixin/wxcore/ysqcx"
DEFAULT_ADVANCE_DAYS = 14  # 15 天含当天，因此距今天 14 天


def _parse_sale_until(html: str, today: date | None = None) -> date | None:
    """从官方预售期页面解析“售至 MM月DD日”，并补齐年份。"""
    match = re.search(r"售至\s*<[^>]*>\s*(\d{1,2})月(\d{1,2})日", html)
    if not match:
        match = re.search(r"售至\s*(\d{1,2})月(\d{1,2})日", html)
    if not match:
        return None
    today = today or date.today()
    month, day = int(match.group(1)), int(match.group(2))
    year = today.year
    try:
        result = date(year, month, day)
    except ValueError:
        return None
    if result < today - timedelta(days=30):
        result = date(year + 1, month, day)
    return result


@lru_cache(maxsize=1)
def official_sale_until(today: date | None = None) -> date | None:
    """读取官方动态售票截止日；网络或格式异常返回 None。"""
    today = today or date.today()
    try:
        response = requests.get(OFFICIAL_ADVANCE_URL, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        return _parse_sale_until(response.text, today)
    except (OSError, requests.RequestException):
        return None


def latest_query_date(today: date | None = None) -> tuple[date, str]:
    """返回最远日期及来源说明；官方失败时按 15 天含当天保守估计。"""
    today = today or date.today()
    official = official_sale_until(today)
    if official:
        return official, "12306官方预售期页面"
    return today + timedelta(days=DEFAULT_ADVANCE_DAYS), "通常预售期（15天含当天，官方页面可能临时调整）"


def validate_ticket_dates(travel_date: str, return_date: str = "", *, today: date | None = None) -> str | None:
    """校验去程/返程是否在当前预售窗口内；合法返回 None。"""
    try:
        today = today or date.today()
        outbound = date.fromisoformat(travel_date)
        inbound = date.fromisoformat(return_date) if return_date else None
    except ValueError:
        return None
    latest, source = latest_query_date(today)
    if outbound < today:
        return f"出发日期 {travel_date} 已经过去。"
    if outbound > latest:
        return f"出发日期 {travel_date} 超出当前可查询范围，通常最远为 {latest.isoformat()}（依据：{source}）。"
    if inbound:
        if inbound < outbound:
            return "返程日期不能早于出发日期。"
        if inbound > latest:
            return f"返程日期 {return_date} 超出当前可查询范围，通常最远为 {latest.isoformat()}（依据：{source}）。"
    return None
