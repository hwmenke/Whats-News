"""Tests for quant_lab.py — feature engine, four models, composite dials."""

import json

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def long_ohlcv():
    """~1000 bars of trending + mean-reverting synthetic OHLCV."""
    rng = np.random.default_rng(11)
    n = 1000
    idx = pd.date_range("2021-06-01", periods=n, freq="B")
    ret = rng.normal(0.0003, 0.014, n) + 0.0015 * np.sin(np.linspace(0, 10 * np.pi, n))
    close = 100 * np.exp(np.cumsum(ret))
    high = close * (1 + rng.uniform(0, 0.01, n))
    low = close * (1 - rng.uniform(0, 0.01, n))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.002, n))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close,
         "volume": rng.integers(1_000_000, 9_000_000, n).astype(float)},
        index=idx,
    )


@pytest.fixture
def ql_result(monkeypatch, long_ohlcv):
    import database as db
    import quant_lab
    monkeypatch.setattr(db, "get_ohlcv_df",
                        lambda symbol, freq="daily", limit=1000: long_ohlcv.tail(limit))
    return quant_lab._compute_inner("TEST")


def test_result_is_json_safe(ql_result):
    assert "error" not in ql_result
    json.dumps(ql_result, allow_nan=False)  # raises on NaN/inf


def test_composite_scores_bounded(ql_result):
    comp = ql_result["composite"]
    assert -100 <= comp["valuation"] <= 100
    assert -100 <= comp["direction"] <= 100
    assert comp["conviction"] in ("LOW", "MED", "HIGH")
    for key in ("cta", "knn", "exh_kick", "fv_edge_1w"):
        assert key in comp["components"]


def test_fair_value_sections(ql_result):
    fv = ql_result["fair_value"]
    assert len(fv["bins"]) == 7
    assert sum(b["n"] for b in fv["bins"]) > 400
    assert sum(b["current"] for b in fv["bins"]) <= 1
    s = fv["series"]
    n = len(s["dates"])
    assert all(len(s[k]) == n for k in ("close", "fv", "up1", "dn1", "up2", "dn2"))
    # bands ordered where defined
    for i in range(n):
        if s["up2"][i] is not None:
            assert s["dn2"][i] < s["dn1"][i] < s["fv"][i] < s["up1"][i] < s["up2"][i]


def test_knn_fan_monotone(ql_result):
    knn = ql_result["knn"]
    assert knn is not None and knn["k"] >= 10
    fan = knn["fan"]
    for i in range(21):
        assert fan["10"][i] <= fan["25"][i] <= fan["50"][i] <= fan["75"][i] <= fan["90"][i]
    assert all(len(a["path"]) == 21 for a in knn["analogs"])
    for h in knn["horizons"]:
        assert 0.0 <= h["p_up"] <= 1.0


def test_knn_analogs_do_not_overlap(ql_result):
    dates = sorted(pd.Timestamp(a["date"]) for a in ql_result["knn"]["analogs"])
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    assert all(g >= 6 for g in gaps)


def test_cta_series_aligned(ql_result):
    cta = ql_result["cta"]
    s = cta["series"]
    assert len(s["dates"]) == len(s["equity"]) == len(s["bh"]) == len(s["forecast"])
    assert s["equity"][0] == 100.0
    assert -100 <= cta["score"] <= 100
    assert abs(cta["position"]) <= 2.0


def test_exhaustion_events_and_stats(ql_result):
    exh = ql_result["exhaustion"]
    assert -100 <= exh["score"] <= 100
    n = len(exh["series"]["close"])
    assert len(exh["series"]["e"]) == n
    for ev in exh["events"]:
        assert 0 <= ev["i"] < n
        assert ev["side"] in (1, -1)
    assert exh["stats"]["base"]["fwd21"] is not None


def test_insufficient_data_error(monkeypatch, long_ohlcv):
    import database as db
    import quant_lab
    monkeypatch.setattr(db, "get_ohlcv_df",
                        lambda symbol, freq="daily", limit=1000: long_ohlcv.head(100))
    result = quant_lab._compute_inner("TEST")
    assert "error" in result
