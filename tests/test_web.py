"""联网查询工具测试（本地，无真实网络请求）

C7：get_air_quality 与 get_weather 共用 _geocode（本地 CITY_COORDS 优先），
常用城市零依赖、不打 nominatim；未知城市给友好文案。
"""

import pytest
import requests

from xiao_wen import web


def test_get_json_raises_on_non_2xx(monkeypatch):
    """非 2xx 响应（如 500 返回错误 JSON）应触发重试并最终抛异常，不静默返回错误内容"""
    calls = {"n": 0}

    class FakeResponse:
        def raise_for_status(self):
            raise requests.HTTPError("500 Server Error")

        def json(self):
            return {"error": "internal"}

    def fake_get(url, params=None, headers=None, timeout=None, proxies=None):
        calls["n"] += 1
        return FakeResponse()

    monkeypatch.setattr(web.requests, "get", fake_get)
    monkeypatch.setattr(web.time, "sleep", lambda s: None)  # 跳过重试间隔
    with pytest.raises(RuntimeError, match="已重试"):
        web._get_json("https://example.com/api")
    assert calls["n"] == 3  # 首次 + 2 次重试


def test_web_agent_weather_grounding_requires_weather_tool(monkeypatch):
    from langchain_core.messages import AIMessage, ToolMessage

    from xiao_wen.agents import web_agent

    class App:
        def __init__(self, tool_name):
            self.tool_name = tool_name

        def invoke(self, _state):
            return {
                "messages": [
                    ToolMessage(content="工具结果", tool_call_id="call-1", name=self.tool_name),
                    AIMessage(content="北京晴 25°C"),
                ]
            }

    monkeypatch.setattr(web_agent._web, "app", App("get_currency_rate"))
    assert web_agent._web_query("北京天气") == ("暂时无法获取可靠实时信息，请稍后重试。", "unavailable")
    monkeypatch.setattr(web_agent._web, "app", App("get_weather"))
    assert web_agent._web_query("北京天气") == ("工具结果", "grounded")


def test_air_quality_known_city_uses_local_coords(monkeypatch):
    """北京在本地 CITY_COORDS → 不打 nominatim（零依赖承诺），只调空气质量 API"""
    urls = []

    def fake_get(url, params=None, headers=None, retries=2):
        urls.append(url)
        if "nominatim" in url:
            raise AssertionError("已知城市不应触发地理编码网络请求")
        return {
            "current": {
                "pm10": 30,
                "pm2_5": 10,
                "carbon_monoxide": 0.4,
                "nitrogen_dioxide": 20,
                "ozone": 50,
                "sulphur_dioxide": 5,
            }
        }

    monkeypatch.setattr(web, "_get_json", fake_get)
    out = web.get_air_quality.func("北京")  # type: ignore[attr-defined]
    assert "PM2.5 10" in out and "北京" in out
    assert all("nominatim" not in u for u in urls)
    assert any("air-quality-api" in u for u in urls)


def test_air_quality_unknown_city_friendly(monkeypatch):
    """未收录城市：走 _geocode → 未找到 → 友好文案（不伪装成服务故障）"""

    def raise_geo(city):
        raise ValueError(f"未找到城市：{city}")

    monkeypatch.setattr(web, "_geocode", raise_geo)
    out = web.get_air_quality.func("不存在的城市")  # type: ignore[attr-defined]
    assert "未找到城市" in out
    assert "服务" not in out


def test_geocode_prefers_local_table(monkeypatch):
    """_geocode 对常用城市直接命中本地表，不发起请求"""
    calls = []

    def fake_get(url, params=None, headers=None, retries=2):
        calls.append(url)
        raise AssertionError("不应发起请求")

    monkeypatch.setattr(web, "_get_json", fake_get)
    assert web._geocode("杭州") == web.CITY_COORDS["杭州"]
    assert calls == []


def test_date_index_relative_and_absolute():
    """_date_index：今天→0、明天→1、后天→2、YYYY-MM-DD→按差值；过去/超 7 天/无法识别 抛 ValueError"""
    from datetime import date as _date
    from datetime import timedelta

    assert web._date_index("今天") == 0
    assert web._date_index("明天") == 1
    assert web._date_index("后天") == 2
    today = _date.today()
    assert web._date_index(today.isoformat()) == 0
    assert web._date_index((today + timedelta(days=3)).isoformat()) == 3
    for bad in ["昨天", "2020-01-01", (today + timedelta(days=7)).isoformat(), "下周"]:
        try:
            web._date_index(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"应拒绝：{bad}")


def test_weather_tomorrow_uses_daily_forecast(monkeypatch):
    """get_weather(date=明天)：取 daily 预报第 1 天（最高/最低/降水概率），超 7 天本地短路不发请求"""
    from datetime import date as _date
    from datetime import timedelta

    def fake_get(url, params=None, headers=None, retries=2):
        assert params["daily"], "应请求 daily 预报而非 current"
        days = [_date.today() + timedelta(days=i) for i in range(7)]
        return {
            "daily": {
                "time": [d.isoformat() for d in days],
                "weather_code": [0, 1, 2, 3, 45, 48, 51],
                "temperature_2m_max": [30.0] * 7,
                "temperature_2m_min": [22.0] * 7,
                "precipitation_probability_max": [10] * 7,
                "uv_index_max": [6.0] * 7,
                "apparent_temperature_max": [32.0] * 7,
                "wind_speed_10m_max": [12.0] * 7,
            }
        }

    monkeypatch.setattr(web, "_get_json", fake_get)
    out = web.get_weather.func("杭州", "明天")  # type: ignore[attr-defined]
    assert (_date.today() + timedelta(days=1)).isoformat() in out
    assert "最高 30.0°C" in out and "最低 22.0°C" in out and "降水概率 10%" in out
    assert "紫外线指数 6.0（高）" in out and "体感最高 32.0°C" in out and "最大风速 12.0km/h" in out


def test_weather_out_of_range_short_circuits_locally(monkeypatch):
    """超 7 天/过去日期：本地直接报错，不发任何网络请求"""
    from datetime import date as _date
    from datetime import timedelta

    def boom(url, params=None, headers=None, retries=2):
        raise AssertionError("日期非法不应发起请求")

    monkeypatch.setattr(web, "_get_json", boom)
    out = web.get_weather.func("北京", (_date.today() + timedelta(days=30)).isoformat())  # type: ignore[attr-defined]
    assert "仅支持未来 7 天" in out
    out2 = web.get_weather.func("北京", "昨天")  # type: ignore[attr-defined]
    assert "不支持查询过去日期" in out2


def test_local_time_known_city_and_timezone(monkeypatch):
    """get_local_time：中国城市 Asia/Shanghai，国际城市用本地时区表，不发 geocoding 请求"""

    def boom(*a, **k):
        raise AssertionError("本地表城市不应发起 geocoding 请求")

    monkeypatch.setattr(web, "_get_json", boom)
    assert web._timezone_of("北京") == "Asia/Shanghai"
    assert web._timezone_of("纽约") == "America/New_York"
    assert web._timezone_of("东京") == "Asia/Tokyo"
    assert web._timezone_of("伦敦") == "Europe/London"
    out_ny = web.get_local_time.func("纽约")  # type: ignore[attr-defined]
    assert "America/New_York" in out_ny and "比北京时间晚" in out_ny
    out_bj = web.get_local_time.func("北京")  # type: ignore[attr-defined]
    assert "与北京时间相同" in out_bj


def test_local_time_unknown_city_friendly(monkeypatch):
    """未收录城市：geocoding 无结果 → 友好文案（不伪装成服务故障）"""
    monkeypatch.setattr(web, "_get_json", lambda *a, **k: {"results": []})
    out = web.get_local_time.func("不存在的城市")  # type: ignore[attr-defined]
    assert "未找到城市时区" in out


def test_web_agent_local_time_grounding(monkeypatch):
    from langchain_core.messages import AIMessage, ToolMessage

    from xiao_wen.agents import web_agent

    class App:
        def __init__(self, tool_name):
            self.tool_name = tool_name

        def invoke(self, _state):
            return {
                "messages": [
                    ToolMessage(content="纽约当前当地时间...", tool_call_id="call-1", name=self.tool_name),
                    AIMessage(content="纽约现在几点..."),
                ]
            }

    monkeypatch.setattr(web_agent._web, "app", App("get_weather"))
    assert web_agent._web_query("纽约现在几点") == ("暂时无法获取可靠实时信息，请稍后重试。", "unavailable")
    monkeypatch.setattr(web_agent._web, "app", App("get_local_time"))
    assert web_agent._web_query("纽约现在几点") == ("纽约当前当地时间...", "grounded")


def test_is_overseas_local_tables_and_nominatim(monkeypatch):
    """境外判定：中国城市表→境内，国际城市表（含港澳台）→境外，兜底 Nominatim display_name 含「中国」"""
    assert web.is_overseas("北京") is False
    assert web.is_overseas("纽约") is True
    assert web.is_overseas("香港") is True
    assert web.is_overseas("澳门") is True
    monkeypatch.setattr(web, "_nominatim", lambda c: {"display_name": "临沂市, 山东省, 中国"})
    assert web.is_overseas("临沂") is False
    monkeypatch.setattr(web, "_nominatim", lambda c: {"display_name": "奥兰多, 美国"})
    assert web.is_overseas("奥兰多") is True
    monkeypatch.setattr(web, "_nominatim", lambda c: None)
    assert web.is_overseas("未知名城") is None


def test_time_diff_from_beijing():
    """时差：东京早 1 小时、北京 0；纽约受夏令时影响 -12 或 -13。"""
    tokyo = web.time_diff_from_beijing("东京")
    assert tokyo is not None
    assert abs(tokyo - 1.0) < 0.01
    assert web.time_diff_from_beijing("北京") == 0.0
    assert web.time_diff_from_beijing("纽约") in (-12.0, -13.0)
