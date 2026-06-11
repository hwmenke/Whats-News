"""Tests for econ_calendar — date rules, ranges, merge logic."""
from datetime import date

import econ_calendar as ec


def test_nth_weekday_first_friday():
    # June 2026: the 1st is a Monday, so first Friday = June 5
    assert ec._nth_weekday(2026, 6, 4, 1) == date(2026, 6, 5)


def test_third_friday_opex():
    # June 2026 third Friday = June 19
    assert ec._nth_weekday(2026, 6, 4, 3) == date(2026, 6, 19)


def test_busday_adjust_weekend():
    sat = date(2026, 6, 13)
    sun = date(2026, 6, 14)
    assert ec._busday_adjust(sat) == date(2026, 6, 12)   # → Friday
    assert ec._busday_adjust(sun) == date(2026, 6, 15)   # → Monday
    wed = date(2026, 6, 10)
    assert ec._busday_adjust(wed) == wed


def test_nth_business_day():
    # June 2026 starts on Monday → 1st bd = Jun 1, 3rd bd = Jun 3
    assert ec._nth_business_day(2026, 6, 1) == date(2026, 6, 1)
    assert ec._nth_business_day(2026, 6, 3) == date(2026, 6, 3)


def test_builtin_events_range_and_shape():
    start, end = date(2026, 6, 1), date(2026, 7, 31)
    events = ec.builtin_events(start, end)
    assert events, "should produce events"
    for e in events:
        assert start.isoformat() <= e["date"] <= end.isoformat()
        assert e["importance"] in (1, 2, 3)
        assert e["category"] in ec.CATEGORY_COLORS
        assert isinstance(e["approx"], bool)

    types = {e["type"] for e in events}
    # June 2026 has a FOMC meeting (Jun 17) and July too (Jul 29)
    assert "FOMC" in types
    assert "NFP" in types
    assert "CPI" in types
    assert "OPEX" in types or "QUAD-WITCH" in types


def test_fomc_dates_are_exact():
    events = ec.builtin_events(date(2026, 1, 1), date(2026, 12, 31))
    fomc = [e for e in events if e["type"] == "FOMC"]
    assert len(fomc) == 8
    assert all(not e["approx"] for e in fomc)
    assert any(e["date"] == "2026-06-17" for e in fomc)


def test_quad_witching_in_quarterly_months():
    events = ec.builtin_events(date(2026, 1, 1), date(2026, 12, 31))
    qw = [e for e in events if e["type"] == "QUAD-WITCH"]
    months = sorted(int(e["date"][5:7]) for e in qw)
    assert months == [3, 6, 9, 12]


def test_get_events_no_fred_key():
    events = ec.get_events(date(2026, 6, 1), date(2026, 6, 30), fred_api_key=None)
    assert events
    assert events == sorted(events, key=lambda e: (e["date"], -e["importance"]))


def test_fred_merge_supersedes_nearby_estimates(monkeypatch):
    start, end = date(2026, 6, 1), date(2026, 6, 30)

    # Fake FRED says CPI lands Jun 10 (builtin estimate would be ~Jun 12,
    # the business-day-adjusted 13th which is a Saturday)
    fake_fred = [ec._ev(date(2026, 6, 10), "CPI", "CPI Release", "inflation", 3, approx=False)]
    monkeypatch.setattr(ec, "fetch_fred_release_dates", lambda *a, **k: fake_fred)

    events = ec.get_events(start, end, fred_api_key="fake")
    cpi = [e for e in events if e["type"] == "CPI"]
    assert len(cpi) == 1
    assert cpi[0]["date"] == "2026-06-10"
    assert cpi[0]["approx"] is False
