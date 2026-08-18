"""历史查询子 Agent 的城市过滤：非白名单城市（如临沂）也必须能按城市筛选。

KNOWN_CITIES 只是「有经纬度坐标的城市」，不是城市全集；历史行程里的
临沂等城市不在坐标表里，但用户问「我去临沂的行程」时必须能过滤命中。
"""

from xiao_wen.agents.history_agent import _itinerary_matches, _mentioned_cities


def test_mentioned_cities_includes_non_whitelist_history_city():
    q = "我去临沂的行程"
    its = [{"from_city": "临沂", "to_city": "北京"}]
    assert "临沂" in _mentioned_cities(q, its)


def test_mentioned_cities_still_recognizes_whitelist():
    assert "北京" in _mentioned_cities("去北京的行程", [])
    assert "哈尔滨" in _mentioned_cities("哈尔滨的出差记录", [])


def test_mentioned_cities_ignores_placeholders():
    its = [{"from_city": "待定", "to_city": "出差"}]
    assert _mentioned_cities("出差的行程", its) == []


def test_itinerary_matches_filters_by_non_whitelist_city():
    its = [
        {"from_city": "临沂", "to_city": "北京"},
        {"from_city": "上海", "to_city": "广州"},
    ]
    cities = _mentioned_cities("我去临沂的行程", its)
    matched = [it for it in its if _itinerary_matches(it, cities)]
    assert matched == [{"from_city": "临沂", "to_city": "北京"}]


def test_mentioned_cities_dedupes_and_orders_whitelist_first():
    q = "北京和临沂的行程"
    its = [{"from_city": "临沂", "to_city": "北京"}]
    cities = _mentioned_cities(q, its)
    assert cities.index("北京") < cities.index("临沂")
