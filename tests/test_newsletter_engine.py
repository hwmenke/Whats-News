"""Tests for newsletter_engine.py — compute_newsletter_data."""
import pytest
import pandas as pd
import numpy as np


@pytest.fixture
def synth_series(synth_ohlcv):
    """Close price Series with DatetimeIndex from the shared synth fixture."""
    s = synth_ohlcv["close"].copy()
    s.index = pd.DatetimeIndex(s.index)
    return s


def _patch_newsletter(monkeypatch, synth_ohlcv, symbols=None):
    import database as db
    if symbols is None:
        symbols = ["AAPL"]
    monkeypatch.setattr(db, "list_symbols",
        lambda: [{"symbol": s} for s in symbols])
    monkeypatch.setattr(db, "get_ohlcv_df",
        lambda symbol, freq="daily", limit=800: synth_ohlcv.tail(limit))


def test_compute_newsletter_data_keys(monkeypatch, synth_ohlcv):
    import newsletter_engine as ne
    _patch_newsletter(monkeypatch, synth_ohlcv)

    result = ne.compute_newsletter_data(n_charts=5)
    assert "charts"       in result
    assert "edition_date" in result


def test_compute_newsletter_data_charts_is_list(monkeypatch, synth_ohlcv):
    import newsletter_engine as ne
    _patch_newsletter(monkeypatch, synth_ohlcv)

    result = ne.compute_newsletter_data(n_charts=5)
    assert isinstance(result["charts"], list)


def test_compute_newsletter_data_no_symbols(monkeypatch):
    import database as db
    import newsletter_engine as ne
    monkeypatch.setattr(db, "list_symbols", lambda: [])

    result = ne.compute_newsletter_data()
    assert "error" in result
    assert result["charts"] == []


def test_compute_newsletter_data_chart_has_required_keys(monkeypatch, synth_ohlcv):
    import newsletter_engine as ne
    _patch_newsletter(monkeypatch, synth_ohlcv)

    result = ne.compute_newsletter_data(n_charts=3)
    if not result.get("charts"):
        pytest.skip("No charts generated (insufficient data or feature engineering skipped)")

    chart = result["charts"][0]
    for key in ("symbol", "label", "chart_type", "last", "chartjs_config"):
        assert key in chart, f"Chart missing key: {key}"


def test_compute_newsletter_data_respects_n_charts(monkeypatch, synth_ohlcv):
    import newsletter_engine as ne
    # Provide 3 symbols, request only 2
    _patch_newsletter(monkeypatch, synth_ohlcv, symbols=["AAPL", "MSFT", "GOOGL"])

    result = ne.compute_newsletter_data(n_charts=2)
    assert len(result.get("charts", [])) <= 2


def test_engineer_features_returns_dict(synth_series):
    import newsletter_engine as ne

    ctx = ne.engineer_features(synth_series, "AAPL")
    assert isinstance(ctx, dict)
    assert "symbol" in ctx
    assert ctx["symbol"] == "AAPL"


def test_engineer_features_has_numeric_score(synth_series):
    """interest_score is added by score_and_select, not engineer_features directly."""
    import newsletter_engine as ne

    ctx = ne.engineer_features(synth_series, "AAPL")
    # After score_and_select the score is injected
    selected = ne.score_and_select([ctx], n=1)
    if not selected:
        pytest.skip("No context selected")
    score = selected[0].get("interest_score")
    assert score is not None
    assert isinstance(score, (int, float))


def test_score_and_select_returns_sorted(synth_series):
    import newsletter_engine as ne

    ctx = ne.engineer_features(synth_series, "AAPL")
    selected = ne.score_and_select([ctx, ctx, ctx], n=2)
    assert len(selected) <= 2
    # Scores should be descending
    scores = [c.get("interest_score", 0) for c in selected]
    assert scores == sorted(scores, reverse=True)
