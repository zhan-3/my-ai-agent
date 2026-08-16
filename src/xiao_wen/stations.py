"""铁路车站电报码解析。

车站数据只接受中国铁路 12306 官方前端发布的 station_name.js，
不使用第三方站点列表或手工编造的电报码。
"""

from __future__ import annotations

import re
from functools import lru_cache

import requests

OFFICIAL_STATION_URL = "https://kyfw.12306.cn/otn/resources/js/framework/station_name.js"

# 城市级输入无法唯一决定车站时，按常见城际出发站做产品默认值；
# 最终名称和电报码仍必须在官方 station_name.js 中实际存在。
_PREFERRED_STATIONS = {
    "临沂": "临沂北",
    "北京": "北京南",
}


def _parse_station_names(payload: str) -> dict[str, str]:
    """解析官方 station_names 字符串中的“站名 -> 电报码”。"""
    result: dict[str, str] = {}
    for record in payload.split("@")[1:]:
        fields = record.split("|")
        if len(fields) >= 3:
            name, code = fields[1].strip(), fields[2].strip()
            if name and re.fullmatch(r"[A-Z]{3}", code):
                result[name] = code
    if not result:
        raise ValueError("12306 官方车站数据为空或格式已变化")
    return result


@lru_cache(maxsize=1)
def official_station_codes() -> dict[str, str]:
    """读取并缓存 12306 官方车站数据；失败时明确抛错，不返回猜测值。"""
    response = requests.get(
        OFFICIAL_STATION_URL,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://kyfw.12306.cn/otn/leftTicket/init"},
        timeout=15,
    )
    response.raise_for_status()
    return _parse_station_names(response.text)


def resolve_station(value: str, codes: dict[str, str] | None = None) -> tuple[str, str] | None:
    """将车站或城市解析成官方站名和电报码；无法唯一解析时返回 None。"""
    table = codes if codes is not None else official_station_codes()
    value = value.strip()
    if value in table:
        return value, table[value]
    preferred = _PREFERRED_STATIONS.get(value)
    if preferred and preferred in table:
        return preferred, table[preferred]
    return None
