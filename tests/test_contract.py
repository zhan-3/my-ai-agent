"""HTTP 契约模型：TripPlan 验证/降级 + MemorySnapshot 建模（OpenAPI schema 的数据源）"""

from xiao_wen.contract import MemorySnapshot, TripDay, TripPlan, plan_or_none


def test_plan_or_none_valid_plan():
    plan = {
        "summary": "北京出差 4 天",
        "reasons": ["按差旅标准选住宿"],
        "date_is_vague": False,
        "days": [
            {
                "date": "2026-10-08",
                "transport": "高铁 G1",
                "hotel": "汉庭",
                "activities": ["上午开会"],
                "notes": "",
            }
        ],
    }
    r = plan_or_none(plan)
    assert isinstance(r, TripPlan)
    assert r.summary == "北京出差 4 天"
    assert isinstance(r.days[0], TripDay)
    assert r.days[0].activities == ["上午开会"]


def test_plan_or_none_none_and_empty():
    assert plan_or_none(None) is None
    assert plan_or_none({}) is None


def test_plan_or_none_malformed_degrades():
    """结构不符（缺 days）→ None：答案文本仍在，展示层有回退通道"""
    assert plan_or_none({"summary": "只有一句话"}) is None


def test_plan_or_none_ignores_extra_keys():
    r = plan_or_none({"summary": "s", "reasons": [], "days": [], "unexpected": "忽略"})
    assert r is not None and not hasattr(r, "unexpected")


def test_memory_snapshot_tolerates_extra_fields():
    """记忆条目带 ts 等额外字段：契约模型忽略（pydantic 默认）"""
    snap = MemorySnapshot.model_validate(
        {
            "preferences": [{"category": "常驻城市", "content": "上海", "ts": "2026-01-01"}],
            "itineraries": [{"from_city": "上海", "to_city": "北京", "ts": "2026-01-01"}],
        }
    )
    assert snap.preferences[0].category == "常驻城市"
    assert snap.itineraries[0].from_city == "上海"
    assert snap.itineraries[0].duration_days is None  # 缺字段 → None（容忍旧数据）
