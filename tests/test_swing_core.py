"""Tests for swing_core.py — swing_data_for and grade_from_swing."""
import pytest
import pandas as pd
import numpy as np


def test_swing_data_for_keys(monkeypatch, synth_ohlcv):
    import database as db
    import swing_core as sc

    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=260: synth_ohlcv)

    result = sc.swing_data_for("AAPL")

    expected_keys = {
        "adr_pct", "rvol", "atr_mult_50ma", "lod_dist_atr",
        "vcp_score", "range_pos_52w", "last_close", "atr_14",
    }
    for key in expected_keys:
        assert key in result, f"Missing key: {key}"


def test_swing_data_for_types(monkeypatch, synth_ohlcv):
    import database as db
    import swing_core as sc

    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=260: synth_ohlcv)

    result = sc.swing_data_for("AAPL")
    assert isinstance(result["adr_pct"], float)
    assert isinstance(result["rvol"], float)
    assert isinstance(result["last_close"], float)
    assert result["last_close"] > 0


def test_swing_data_for_insufficient_data(monkeypatch):
    import database as db
    import swing_core as sc

    # Only 5 rows — below the 20-row minimum
    tiny = pd.DataFrame({
        "open":   [100] * 5,
        "high":   [101] * 5,
        "low":    [99]  * 5,
        "close":  [100] * 5,
        "volume": [1e6] * 5,
    })
    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=260: tiny)

    with pytest.raises(ValueError, match="Insufficient"):
        sc.swing_data_for("AAPL")


def test_swing_data_for_empty_df(monkeypatch):
    import database as db
    import swing_core as sc

    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=260: pd.DataFrame())

    with pytest.raises(ValueError):
        sc.swing_data_for("AAPL")


def test_grade_from_swing_keys(monkeypatch, synth_ohlcv):
    import database as db
    import swing_core as sc

    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=260: synth_ohlcv)

    sd = sc.swing_data_for("AAPL")
    result = sc.grade_from_swing(sd)

    assert "grade"   in result
    assert "score"   in result
    assert "factors" in result


def test_grade_from_swing_valid_grade(monkeypatch, synth_ohlcv):
    import database as db
    import swing_core as sc

    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=260: synth_ohlcv)

    sd = sc.swing_data_for("AAPL")
    result = sc.grade_from_swing(sd)

    assert result["grade"] in ("A", "B", "C", "")


def test_grade_from_swing_factors_structure(monkeypatch, synth_ohlcv):
    import database as db
    import swing_core as sc

    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=260: synth_ohlcv)

    sd = sc.swing_data_for("AAPL")
    result = sc.grade_from_swing(sd)

    assert isinstance(result["factors"], list)
    for f in result["factors"]:
        assert "label" in f
        assert "bull"  in f
        assert "pts"   in f


def test_grade_from_swing_extended_stock_scores_lower():
    """A stock far above its 50-MA should score lower than one near it."""
    import swing_core as sc

    base_sd = {
        "atr_mult_50ma": 1.0, "rvol": 1.5, "lod_dist_atr": 0.2,
        "vcp_score": 1.0, "range_pos_52w": 0.9, "adr_pct": 5.0,
        "last_close": 100, "atr_14": 2,
    }
    extended_sd = dict(base_sd, atr_mult_50ma=6.0)

    base_result     = sc.grade_from_swing(base_sd)
    extended_result = sc.grade_from_swing(extended_sd)

    assert base_result["score"] > extended_result["score"], \
        "Extended stock should score lower than near-MA stock"
