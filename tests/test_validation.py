from typing import Any

from xiao_wen import trip_planner
from xiao_wen.validation import validate_trip


def request(**overrides: Any):
    values: dict[str, Any] = {
        "from_city": "上海",
        "to_city": "北京",
        "start_date": "2026-03-05",
        "duration_days": 3,
        "people_count": 1,
        "hotel_pref": "无",
        "budget_pref": "中等",
    }
    values.update(overrides)
    return trip_planner.TripRequest(**values)


def day(day_date: str, hotel: str = "全季酒店"):
    return trip_planner.DayPlan(
        date=day_date,
        transport="高铁",
        hotel=hotel,
        activities=["公务：开会"],
        notes="",
    )


def plan(*days):
    return trip_planner.ItineraryPlan(days=list(days), summary="北京出差", reasons=[])


def test_validate_trip_accepts_contiguous_days_and_policy_evidence():
    result = validate_trip(
        request(),
        plan(day("2026-03-05"), day("2026-03-06"), day("2026-03-07")),
        policy_text="一线城市住宿标准 500 元/晚",
        evidence_ids=("ev-001",),
    )
    assert result.passed
    assert result.blocking_issues == []
    assert result.evidence_ids == ("ev-001",)


def test_validate_trip_blocks_missing_day():
    result = validate_trip(
        request(),
        plan(day("2026-03-05"), day("2026-03-07")),
    )
    assert not result.passed
    assert any(issue.code == "day_count_mismatch" for issue in result.blocking_issues)


def test_validate_trip_blocks_non_contiguous_dates():
    result = validate_trip(
        request(),
        plan(day("2026-03-05"), day("2026-03-07"), day("2026-03-08")),
    )
    assert any(issue.code == "date_not_contiguous" for issue in result.blocking_issues)


def test_validate_trip_blocks_policy_claim_without_evidence():
    result = validate_trip(
        request(),
        plan(
            trip_planner.DayPlan(
                date="2026-03-05",
                transport="高铁",
                hotel="按一线城市 1800 元/晚标准住宿",
                activities=["公务：开会"],
                notes="",
            ),
            day("2026-03-06"),
            day("2026-03-07"),
        ),
    )
    assert any(issue.code == "unsupported_policy_claim" for issue in result.blocking_issues)


def test_validate_trip_allows_empty_candidate_for_legacy_dry_runs():
    result = validate_trip(request(), plan())
    assert result.passed
    assert any(issue.code == "empty_plan" for issue in result.warnings)
