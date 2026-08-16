"""联网查询工具测试（本地，无真实网络请求）

C7：get_air_quality 与 get_weather 共用 _geocode（本地 CITY_COORDS 优先），
常用城市零依赖、不打 nominatim；未知城市给友好文案。
"""

import pytest
import requests

from xiao_wen import ticket_link, web


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


def test_search_train_tickets_generates_official_prefill_url(monkeypatch):
    station_codes = {
        "临沂北": ("临沂北", "UMK"),
        "广州南": ("广州南", "IZQ"),
    }

    def fake_resolve(value):
        return station_codes.get(value)

    monkeypatch.setattr(ticket_link, "resolve_station", fake_resolve)
    out = web.search_train_tickets.func("临沂北", "广州南", "2026-08-18")  # type: ignore[attr-defined]
    assert "铁路12306官方预填查询入口" in out
    assert "linktypeid=dc" in out
    assert "fs=%E4%B8%B4%E6%B2%82%E5%8C%97,UMK" in out
    assert "ts=%E5%B9%BF%E5%B7%9E%E5%8D%97,IZQ" in out
    assert "date=2026-08-18" in out
    assert "flag=N,N,Y" in out
    assert "不代购票" in out


def test_search_train_tickets_rejects_unverified_station(monkeypatch):
    monkeypatch.setattr(ticket_link, "resolve_station", lambda value: None)
    out = web.search_train_tickets.func("未知", "北京", "2026-08-18")  # type: ignore[attr-defined]
    assert "无法从12306官方车站数据确认" in out


def test_search_train_tickets_prefills_return_date(monkeypatch):
    station_codes = {"临沂北": ("临沂北", "UMK"), "北京南": ("北京南", "VNP")}

    def fake_resolve(value):
        return station_codes.get(value)

    monkeypatch.setattr(ticket_link, "resolve_station", fake_resolve)
    out = web.search_train_tickets.func("临沂北", "北京南", "2026-08-20", "2026-08-23")  # type: ignore[attr-defined]
    assert "linktypeid=wf" in out
    assert "date=2026-08-20,2026-08-23" in out
    assert "返程日期 2026-08-23" in out


def test_search_train_tickets_rejects_date_outside_sale_window(monkeypatch):
    monkeypatch.setattr(
        web, "ticket_label", lambda origin, destination, travel_date, return_date="": "超出当前可查询范围"
    )
    out = web.search_train_tickets.func("临沂北", "北京南", "2026-08-31")  # type: ignore[attr-defined]
    assert "超出当前可查询范围" in out


def test_search_train_tickets_rejects_invalid_date():
    out = web.search_train_tickets.func("临沂北", "广州南", "下周")  # type: ignore[attr-defined]
    assert "无法识别出发日期" in out


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
            }
        }

    monkeypatch.setattr(web, "_get_json", fake_get)
    out = web.get_weather.func("杭州", "明天")  # type: ignore[attr-defined]
    assert (_date.today() + timedelta(days=1)).isoformat() in out
    assert "最高 30.0°C" in out and "最低 22.0°C" in out and "降水概率 10%" in out


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
