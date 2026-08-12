"""行程规划纯逻辑测试：必填要素缺失检查 + 结果可读性格式（无需 LLM）

行程 worker 逻辑内嵌于 xiao_wen.system 完整系统（0005 历史版已归档 teaching/archive/），
这里加载成品系统测其内部纯函数（模块顶层只构造模型，不调用 API）。
"""
from typing import Any

from xiao_wen import system as _itinerary

TripRequest = _itinerary.TripRequest
ItineraryPlan = _itinerary.ItineraryPlan


def _req(**kw):
    base: dict[str, Any] = dict(to_city="北京", from_city="上海", start_date="2026-10-08",
                                duration_days=4, purpose="开会", via_cities="", transport="",
                                hotel_pref="无", budget_pref="中等")
    base.update(kw)
    return TripRequest(**base)


def test_missing_full_request_is_empty():
    assert _itinerary._missing(_req()) == []


def test_missing_detects_each_field():
    assert "目的城市" in _itinerary._missing(_req(to_city="待定"))
    assert "出发城市" in _itinerary._missing(_req(from_city="未知"))
    assert "出发日期" in _itinerary._missing(_req(start_date=""))
    assert "出差天数" in _itinerary._missing(_req(duration_days=0))
    assert "出差天数" in _itinerary._missing(_req(duration_days=-1))


def test_format_plan_readable_with_reasons():
    day = _itinerary.DayPlan(
        date="2026-10-08", transport="高铁 G2 次 07:00 上海虹桥→11:28 北京南",
        hotel="全季酒店（国贸店）", activities=["峰会"], notes="带好身份证")
    plan = ItineraryPlan(
        summary="10月8日从上海乘高铁赴北京开会4天",
        days=[day],
        reasons=["避开早高峰，选择上午班次"],
    )
    text = _itinerary.format_plan(plan)
    assert "10月8日" in text
    assert "高铁 G2 次" in text          # 每日交通
    assert "💡 安排理由" in text          # 基础项 E：安排理由
    assert "避开早高峰" in text
    assert "带好身份证" in text            # 备注（注意事项）


def test_format_plan_no_reasons_ok():
    plan = ItineraryPlan(summary="行程规划：示例", days=[], reasons=[])
    text = _itinerary.format_plan(plan)
    assert "示例" in text
    assert "💡 安排理由" not in text
