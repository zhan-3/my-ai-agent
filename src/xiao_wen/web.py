"""联网查询模块 —— LangGraph ToolNode（ReAct 循环）
跑法：uv run python -m xiao_wen.web
依赖：无新依赖。天气用 open-meteo（免费无需 key），汇率用 open.er-api.com（免费无需 key）

设计要点：
- @tool 装饰器：函数 → 工具（docstring 是给 LLM 看的说明书，必须写清参数含义）
- llm.bind_tools([...])：给 LLM 挂上工具清单，LLM 在回答时自主决定「要不要调工具、调哪个、传什么参」
- ToolNode：langgraph.prebuilt 提供的现成工具执行节点
- ReAct 循环：agent 节点 → (LLM 想调工具?) → tools 节点 → 回 agent → …直到 LLM 认为信息够了直接回答
"""

import logging
import os
import time
from datetime import date as _date
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

import requests
from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict

from xiao_wen import llm
from xiao_wen.reference_data import CITY_COORDS, CITY_TIMEZONES

logger = logging.getLogger("xiao_wen.web")

# ---- 网络工具：代理 + 重试（免费 API 不稳定，工程上必须健壮）----


def _proxies():
    """从环境变量读代理（如 Clash 127.0.0.1:7897）；无代理环境返回 None 即直连"""
    proxies = {}
    for scheme in ("http", "https"):
        url = os.environ.get(f"{scheme.upper()}_PROXY") or os.environ.get(f"{scheme}_proxy")
        if url:
            proxies[scheme] = url
    return proxies or None


def _get_json(url, params=None, headers=None, retries=2):
    """GET + 解析 JSON + 自动重试（默认重试 2 次，每次间隔 1 秒）"""
    last = None
    for _ in range(retries + 1):
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15, proxies=_proxies())
            r.raise_for_status()  # 非 2xx（404/429/500）立即抛异常进重试，防错误 JSON 被当正常数据
            return r.json()
        except Exception as e:
            last = e
            time.sleep(1)
    raise RuntimeError(f"请求失败（已重试 {retries} 次）：{url}") from last


# ---- 1. 定义工具（@tool：函数 → 工具）----


# 城市经纬度表：单一来源 xiao_wen.reference_data.CITY_COORDS（本地内置，零依赖）
def _nominatim(city: str) -> dict | None:
    """Nominatim 地理编码：返回首个结果（含 lat/lon/display_name），失败返回 None"""
    geo = _get_json(
        "https://nominatim.openstreetmap.org/search",
        params={"q": city, "format": "json", "limit": 1, "accept-language": "zh"},
        headers={"User-Agent": "xiao-wen-travel-assistant/1.0"},
    )
    return geo[0] if geo else None


def _geocode(city: str) -> tuple[float, float]:
    """城市名 → 经纬度：优先本地表（零依赖），未收录才走 Nominatim（免费但限流）"""
    if city in CITY_COORDS:
        return CITY_COORDS[city]
    geo = _nominatim(city)
    if not geo:
        raise ValueError(f"未找到城市：{city}")
    return float(geo["lat"]), float(geo["lon"])


def _timezone_of(city: str) -> str:
    """城市名 → IANA 时区：中国城市统一 Asia/Shanghai，本地表优先，未收录走 open-meteo geocoding（仅英文名有效）"""
    if city in CITY_COORDS or city in CITY_TIMEZONES:
        return CITY_TIMEZONES.get(city, "Asia/Shanghai")
    geo = _get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "format": "json"},
    )
    results = geo.get("results")
    if not results:
        raise ValueError(f"未找到城市时区：{city}")
    return results[0]["timezone"]


def is_overseas(city: str) -> bool | None:
    """判定城市是否境外（用于行程预算币种）：港澳台按境外处理。

    本地国际城市表（含港澳台）时区非 Asia/Shanghai → 境外；中国城市表 → 境内；
    兜底用 Nominatim display_name 是否含「中国」判定；无法判定返回 None（调用方不显示金额）。
    """
    if city in CITY_TIMEZONES:
        return CITY_TIMEZONES[city] != "Asia/Shanghai"
    if city in CITY_COORDS:
        return False
    try:
        geo = _nominatim(city)
    except Exception as exc:
        logger.warning("is_overseas 判定失败 city=%s：%s", city, exc)
        return None
    if not geo:
        return None
    return "中国" not in geo.get("display_name", "")


def time_diff_from_beijing(city: str) -> float | None:
    """城市与北京时差（小时），无法确定时区返回 None。正值=比北京早，负值=比北京晚。"""
    try:
        local_off = datetime.now(ZoneInfo(_timezone_of(city))).utcoffset() or timedelta(0)
        bj_off = datetime.now(ZoneInfo("Asia/Shanghai")).utcoffset() or timedelta(0)
        return (local_off - bj_off).total_seconds() / 3600
    except Exception as exc:
        logger.warning("time_diff_from_beijing 计算失败 city=%s：%s", city, exc)
        return None


@tool
def get_weather(city: str, date: str = "今天") -> str:
    """查询指定城市指定日期的天气。city：城市名，如「北京」「上海」「杭州」；
    date：今天/明天/后天 或 YYYY-MM-DD（仅支持未来 7 天预报）"""
    try:
        # ① 日期先本地解析（今天→0、明天→1、YYY-MM-DD→对应天）：过去日期/超 7 天立即报错，不发网络请求
        idx = _date_index(date)
        # ② 地理编码：本地城市表优先，未收录城市走 OSM Nominatim
        lat, lon = _geocode(city)
        # ③ 天气：open-meteo daily 预报（免费无需 key），按 idx 取对应天
        daily_fields = (
            "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
            "uv_index_max,apparent_temperature_max,wind_speed_10m_max"
        )
        daily = _get_json(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": daily_fields,
                "timezone": "auto",
            },
        )["daily"]
        wmo = {
            0: "晴",
            1: "大部晴朗",
            2: "多云",
            3: "阴",
            45: "雾",
            48: "雾凇",
            51: "小毛毛雨",
            53: "毛毛雨",
            55: "大毛毛雨",
            61: "小雨",
            63: "中雨",
            65: "大雨",
            71: "小雪",
            73: "中雪",
            75: "大雪",
            80: "小阵雨",
            81: "中阵雨",
            82: "大阵雨",
            95: "雷暴",
            96: "雷暴伴冰雹",
            99: "雷暴伴大冰雹",
        }
        desc = wmo.get(daily["weather_code"][idx], f"天气代码{daily['weather_code'][idx]}")
        uv = daily["uv_index_max"][idx]
        uv_level = "低" if uv <= 2 else "中" if uv <= 5 else "高" if uv <= 7 else "很高" if uv <= 10 else "极高"
        return (
            f"{city} {daily['time'][idx]} 天气：{desc}，最高 {daily['temperature_2m_max'][idx]}°C / "
            f"最低 {daily['temperature_2m_min'][idx]}°C，体感最高 {daily['apparent_temperature_max'][idx]}°C，"
            f"降水概率 {daily['precipitation_probability_max'][idx]}%，"
            f"紫外线指数 {uv}（{uv_level}），最大风速 {daily['wind_speed_10m_max'][idx]}km/h"
        )
    except ValueError as e:
        return str(e)
    except Exception as e:
        logger.warning("查询天气失败 city=%s date=%s：%s", city, date, e)
        return f"查询天气失败（服务可能不稳定，请稍后再试）：{type(e).__name__}"


def _date_index(date: str) -> int:
    """日期 → open-meteo daily 数组索引：今天→0、明天→1、后天→2、YYYY-MM-DD→按差值；
    过去/超 7 天/无法识别 抛 ValueError"""
    today = _date.today()
    d = date.strip()
    rel = {"今天": 0, "今日": 0, "明天": 1, "明日": 1, "后天": 2, "昨天": -1, "昨日": -1, "前天": -2}
    if d in rel:
        if rel[d] < 0:
            raise ValueError(f"不支持查询过去日期：{date}")
        return rel[d]
    try:
        target = _date.fromisoformat(d)
    except ValueError:
        raise ValueError(f"无法识别的日期：{date}（支持 今天/明天/后天 或 YYYY-MM-DD）") from None
    diff = (target - today).days
    if diff < 0:
        raise ValueError(f"不支持查询过去日期：{date}")
    if diff > 6:
        raise ValueError(f"仅支持未来 7 天预报（{today} 至 {today + timedelta(days=6)}）")
    return diff


@tool
def get_currency_rate(from_currency: str, to_currency: str) -> str:
    """查询两种货币的实时汇率。参数为三位货币代码：USD 美元、CNY 人民币、EUR 欧元、JPY 日元、GBP 英镑、HKD 港币"""
    try:
        # 取 1 USD = X 全量表，交叉换算出任意币种对（一次请求即可）
        data = _get_json("https://api.exchangerate-api.com/v4/latest/USD")
        rates = data["rates"]
        fc, tc = from_currency.upper(), to_currency.upper()
        if fc not in rates or tc not in rates:
            return f"不支持的货币代码：{from_currency}/{to_currency}"
        rate = (1.0 / rates[fc]) * rates[tc]  # 1 单位 from = ? to
        return f"当前汇率：1 {fc} = {rate:.4f} {tc}"
    except Exception as e:
        logger.warning("查询汇率失败 %s→%s：%s", from_currency, to_currency, e)
        return f"查询汇率失败（服务可能不稳定，请稍后再试）：{type(e).__name__}"


@tool
def get_air_quality(city: str) -> str:
    """查询指定城市的当前空气质量。city：城市名，如「北京」「上海」「杭州」"""
    try:
        # ① 地理编码：与 get_weather 共用 _geocode（本地 CITY_COORDS 优先，未收录才走 nominatim）
        lat, lon = _geocode(city)
        # ② 空气质量：air-quality-api 只收经纬度（不认城市名）
        cur = _get_json(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,ozone,sulphur_dioxide",
                "timezone": "auto",
            },
        )["current"]
        return (
            f"{city}当前空气质量：PM2.5 {cur['pm2_5']} μg/m³，PM10 {cur['pm10']} μg/m³，"
            f"CO {cur['carbon_monoxide']} μg/m³"
        )
    except ValueError:
        return f"未找到城市：{city}"
    except Exception as e:
        logger.warning("查询空气质量失败 city=%s：%s", city, e)
        return f"查询空气质量失败（服务可能不稳定，请稍后再试）：{type(e).__name__}"


@tool
def get_local_time(city: str) -> str:
    """查询指定城市当前当地时间及与北京时间的时差。city：城市名，如「纽约」「东京」「伦敦」"""
    try:
        tz_name = _timezone_of(city)
        local = datetime.now(ZoneInfo(tz_name))
        diff_hours = time_diff_from_beijing(city)
        if diff_hours is None:
            rel = "时差未知"
        elif abs(diff_hours) < 0.01:
            rel = "与北京时间相同"
        else:
            rel = f"比北京时间{'早' if diff_hours > 0 else '晚'}{abs(diff_hours):.0f}小时"
        return f"{city} 当前当地时间 {local.strftime('%Y-%m-%d %H:%M')}（{tz_name}），{rel}"
    except ValueError as e:
        return str(e)
    except Exception as e:
        logger.warning("查询当地时间失败 city=%s：%s", city, e)
        return f"查询当地时间失败（服务可能不稳定，请稍后再试）：{type(e).__name__}"


tools = [get_weather, get_currency_rate, get_air_quality, get_local_time]
# ---- 2. 图：agent(LLM+工具) ⇄ tools(ToolNode) 的 ReAct 循环 ----


class State(TypedDict):
    messages: Annotated[list, add_messages]  # add_messages：消息累加（不是覆盖）


def agent_node(state: State):
    """LLM 决定：直接回答 or 调用工具。返回新消息（可能带 tool_calls）"""
    return {"messages": [_llm_with_tools().invoke(state["messages"])]}


tool_node = ToolNode(tools)  # 执行 LLM 请求的工具，结果作为 tool 消息返回


def route_after_agent(state: State):
    """条件边：最后一条消息有 tool_calls → 去 tools 执行；否则 → 结束"""
    last = state["messages"][-1]
    return "tools" if last.tool_calls else END


graph = StateGraph(State)
graph.add_node("agent", agent_node)
graph.add_node("tools", tool_node)
graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
graph.set_entry_point("agent")
app = graph.compile()


@lru_cache
def _llm_with_tools():
    """联网查询 ReAct 的绑定 LLM：懒构建（首次调用才构造），熔断守卫由接缝统一提供"""
    return llm.get_llm().bind_tools(tools)


SYSTEM = SystemMessage(
    content=(
        "你是晓问差旅助手的「联网查询」模块，负责回答需要实时信息的问题。"
        "涉及天气、汇率或空气质量时，必须调用对应工具获取真实数据，再基于结果回答；"
        "与实时信息无关的问题，直接说明这不属于联网查询范围。"
    )
)


def ask(question: str):
    print("=" * 56)
    print("用户：", question)
    result = app.invoke({"messages": [SYSTEM, ("human", question)]})
    for m in result["messages"]:
        if m.type == "ai" and m.tool_calls:
            tc = m.tool_calls[0]
            print(f"  ↳ LLM 决定调用工具：{tc['name']}({tc['args']})")
        elif m.type == "tool":
            print(f"  ↳ 工具返回：{str(m.content)[:90]}")
    print("回答：", result["messages"][-1].content)


if __name__ == "__main__":
    ask("北京今天天气怎么样？")
    ask("我要去美国出差，现在 1 美元能换多少人民币？")
    ask("帮我看看东京今天的天气适合穿什么")
    ask("报销要在多长时间内提交？")  # 负例：非实时问题，应拒绝
