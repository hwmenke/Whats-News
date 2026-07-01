"""Tests for jeff_scanner.py — compute_jeff_scan."""
import pytest
import pandas as pd


def _patch_jeff(monkeypatch, synth_ohlcv):
    """Patch all DB + external calls jeff_scanner makes."""
    import database as db
    import jeff_scanner as js

    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=1000: synth_ohlcv.tail(limit))
    monkeypatch.setattr(db, "list_symbols",
        lambda: [{"symbol": "AAPL", "sector": "Technology",
                  "next_earnings": None, "watchlist_tier": "watchlist",
                  "last_fetch": "2024-06-01", "notes": ""}])
    monkeypatch.setattr(db, "list_positions",
        lambda include_closed=True: [])
    monkeypatch.setattr(db, "list_alerts",
        lambda symbol=None: [])

    # Bypass the indicator cache so every call goes straight to the function
    monkeypatch.setattr(js, "cache",
        type("FakeCache", (), {
            "get_or_compute": staticmethod(lambda _ns, _sym, _freq, fn, **kw: fn())
        })())


def test_compute_jeff_scan_returns_list(monkeypatch, synth_ohlcv):
    import jeff_scanner as js
    _patch_jeff(monkeypatch, synth_ohlcv)

    rows = js.compute_jeff_scan(["AAPL"])
    assert isinstance(rows, list)
    assert len(rows) == 1


def test_compute_jeff_scan_row_has_required_keys(monkeypatch, synth_ohlcv):
    import jeff_scanner as js
    _patch_jeff(monkeypatch, synth_ohlcv)

    rows = js.compute_jeff_scan(["AAPL"])
    row  = rows[0]

    required = {"symbol", "grade", "score", "rvol", "sector"}
    for key in required:
        assert key in row, f"Row missing key: {key}"


def test_compute_jeff_scan_symbol_matches(monkeypatch, synth_ohlcv):
    import jeff_scanner as js
    _patch_jeff(monkeypatch, synth_ohlcv)

    rows = js.compute_jeff_scan(["AAPL"])
    assert rows[0]["symbol"] == "AAPL"


def test_compute_jeff_scan_empty_symbols(monkeypatch, synth_ohlcv):
    import jeff_scanner as js
    _patch_jeff(monkeypatch, synth_ohlcv)

    rows = js.compute_jeff_scan([])
    assert rows == []


def test_compute_jeff_scan_grade_is_valid(monkeypatch, synth_ohlcv):
    import jeff_scanner as js
    _patch_jeff(monkeypatch, synth_ohlcv)

    rows = js.compute_jeff_scan(["AAPL"])
    grade = rows[0].get("grade", "")
    assert grade in ("A", "B", "C", "D", ""), f"Unexpected grade: {grade!r}"


def test_compute_jeff_scan_score_is_numeric(monkeypatch, synth_ohlcv):
    import jeff_scanner as js
    _patch_jeff(monkeypatch, synth_ohlcv)

    rows  = js.compute_jeff_scan(["AAPL"])
    score = rows[0].get("score")
    assert isinstance(score, (int, float))
