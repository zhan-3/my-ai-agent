"""联网查询工具测试（本地，无真实网络请求）

C7：get_air_quality 与 get_weather 共用 _geocode（本地 CITY_COORDS 优先），
常用城市零依赖、不打 nominatim；未知城市给友好文案。
"""
from xiao_wen import web


def test_air_quality_known_city_uses_local_coords(monkeypatch):
    """北京在本地 CITY_COORDS → 不打 nominatim（零依赖承诺），只调空气质量 API"""
    urls = []

    def fake_get(url, params=None, headers=None, retries=2):
        urls.append(url)
        if "nominatim" in url:
            raise AssertionError("已知城市不应触发地理编码网络请求")
        return {"current": {"pm10": 30, "pm2_5": 10, "carbon_monoxide": 0.4,
                            "nitrogen_dioxide": 20, "ozone": 50, "sulphur_dioxide": 5}}

    monkeypatch.setattr(web, "_get_json", fake_get)
    out = web.get_air_quality.func("北京")
    assert "PM2.5 10" in out and "北京" in out
    assert all("nominatim" not in u for u in urls)
    assert any("air-quality-api" in u for u in urls)


def test_air_quality_unknown_city_friendly(monkeypatch):
    """未收录城市：走 _geocode → 未找到 → 友好文案（不伪装成服务故障）"""

    def raise_geo(city):
        raise ValueError(f"未找到城市：{city}")

    monkeypatch.setattr(web, "_geocode", raise_geo)
    out = web.get_air_quality.func("不存在的城市")
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
