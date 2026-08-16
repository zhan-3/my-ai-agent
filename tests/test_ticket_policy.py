from datetime import date

from xiao_wen import ticket_policy


def test_parse_sale_until_from_official_page():
    html = "<span>售至<span>08月30日</span></span>"
    assert ticket_policy._parse_sale_until(html, date(2026, 8, 16)) == date(2026, 8, 30)


def test_parse_sale_until_rolls_year_forward():
    html = "<span>售至<span>01月05日</span></span>"
    assert ticket_policy._parse_sale_until(html, date(2026, 12, 20)) == date(2027, 1, 5)


def test_validate_ticket_dates_checks_both_legs(monkeypatch):
    monkeypatch.setattr(
        ticket_policy,
        "latest_query_date",
        lambda today=None: (date(2026, 8, 30), "测试官方范围"),
    )
    today = date(2026, 8, 16)

    assert ticket_policy.validate_ticket_dates("2026-08-20", "2026-08-23", today=today) is None
    assert "返程日期不能早于" in (ticket_policy.validate_ticket_dates("2026-08-20", "2026-08-19", today=today) or "")
    assert "超出当前可查询范围" in (ticket_policy.validate_ticket_dates("2026-08-20", "2026-08-31", today=today) or "")


def test_validate_ticket_dates_fallback_is_15_days_including_today(monkeypatch):
    monkeypatch.setattr(ticket_policy, "official_sale_until", lambda today=None: None)
    today = date(2026, 8, 16)

    assert ticket_policy.validate_ticket_dates("2026-08-30", today=today) is None
    assert "2026-08-30" in (ticket_policy.validate_ticket_dates("2026-08-31", today=today) or "")
