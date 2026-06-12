"""Tests for fair_value_lab.py — anchors, walk-forward validation, PCA panel."""

import json

import numpy as np
import pandas as pd
import pytest


def _ou_df(seed=3, n=1500, phi=0.952):
    """OU process around a slow log-trend — genuine mean reversion."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-06-01", periods=n, freq="B")
    trend = np.linspace(np.log(80), np.log(160), n)
    x = np.zeros(n)
    for i in range(1, n):
        x[i] = phi * x[i - 1] + rng.normal(0, 0.011)
    close = np.exp(trend + x)
    return pd.DataFrame({"open": np.r_[close[0], close[:-1]], "high": close * 1.008,
                         "low": close * 0.992, "close": close,
                         "volume": rng.integers(1_000_000, 9_000_000, n).astype(float)},
                        index=idx)


def _factor_universe(n_assets=12, n=1300, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2021-01-04", periods=n, freq="B")
    f1 = rng.normal(0.0004, 0.012, n)
    f2 = rng.normal(0, 0.006, n)
    frames = {}
    for i in range(n_assets):
        ret = (0.6 + 0.8 * rng.random()) * f1 + rng.normal(0, 0.7) * f2 \
              + rng.normal(0, 0.006, n)
        close = 100 * np.exp(np.cumsum(ret))
        frames[f"SYM{i:02d}"] = pd.DataFrame(
            {"open": np.r_[close[0], close[:-1]], "high": close * 1.008,
             "low": close * 0.992, "close": close,
             "volume": rng.integers(1_000_000, 9_000_000, n).astype(float)}, index=idx)
    return frames


@pytest.fixture(autouse=True)
def fresh_panel_memo():
    import fair_value_lab as fvl
    fvl._PANEL_MEMO.clear()
    yield
    fvl._PANEL_MEMO.clear()


def test_trend_model_detects_ou_reversion(monkeypatch):
    import database as db
    import fair_value_lab as fvl
    df = _ou_df()
    monkeypatch.setattr(db, "get_ohlcv_df", lambda s, freq="daily", limit=1000: df.tail(limit))
    r = fvl._compute_inner("OU", "trend")
    assert "error" not in r
    json.dumps(r, allow_nan=False)
    v = r["validation"]
    # a true OU process must be recognised as exploitable
    assert v["h21"]["hit"] >= 0.6
    assert v["h21"]["ic"] > 0.1
    assert v["h21"]["slope"] < 0            # rich → expected down
    assert v["verdict"] in ("STRONG", "OK")
    assert v["price_work"]["price_share"] > 0.4


def test_series_and_dist_shapes(monkeypatch):
    import database as db
    import fair_value_lab as fvl
    df = _ou_df(seed=8)
    monkeypatch.setattr(db, "get_ohlcv_df", lambda s, freq="daily", limit=1000: df.tail(limit))
    r = fvl._compute_inner("OU", "trend")
    s = r["series"]
    n = len(s["dates"])
    assert all(len(s[k]) == n for k in ("close", "fv", "up1", "dn1", "up2", "dn2", "z"))
    for i in range(n):
        if s["up2"][i] is not None:
            assert s["dn2"][i] < s["dn1"][i] < s["fv"][i] < s["up1"][i] < s["up2"][i]
    assert 200 <= len(r["dist"]["z_hist"]) <= 504
    assert 0.0 <= r["current"]["pct_emp"] <= 1.0


def test_pca_model(monkeypatch):
    import database as db
    import fair_value_lab as fvl
    frames = _factor_universe()
    monkeypatch.setattr(db, "get_ohlcv_df",
                        lambda s, freq="daily", limit=1000: frames[s].tail(limit))
    monkeypatch.setattr(db, "list_symbols", lambda: [{"symbol": s} for s in frames])
    r = fvl._compute_inner("SYM00", "pca")
    assert "error" not in r
    json.dumps(r, allow_nan=False)
    assert r["meta"]["n_universe"] == 12
    assert abs(r["current"]["z"]) < 6.1
    ps = r["validation"]["price_work"]
    if ps["price_share"] is not None:
        assert 0.0 <= ps["price_share"] <= 1.0
    hook = fvl.pca_divergence("SYM00")
    assert hook is not None and np.isfinite(hook["z"])


def test_pca_flags_idiosyncratic_runup(monkeypatch):
    """A purely idiosyncratic run-up must register as a large PCA divergence
    (the anchor is built from peers, so it cannot follow the move)."""
    import database as db
    import fair_value_lab as fvl
    frames = _factor_universe()
    df = frames["SYM00"]
    boosted = df.copy()
    bump = np.exp(np.linspace(0.0, 0.25, 25))            # +28% over 25 bars
    for col in ("open", "high", "low", "close"):
        boosted.loc[boosted.index[-25:], col] = df[col].iloc[-25:].values * bump
    frames["SYM00"] = boosted
    monkeypatch.setattr(db, "get_ohlcv_df",
                        lambda s, freq="daily", limit=1000: frames[s].tail(limit))
    monkeypatch.setattr(db, "list_symbols", lambda: [{"symbol": s} for s in frames])
    hook = fvl.pca_divergence("SYM00")
    assert hook is not None and hook["z"] > 1.5


def test_pca_needs_enough_universe(monkeypatch):
    import database as db
    import fair_value_lab as fvl
    frames = _factor_universe(n_assets=3)
    monkeypatch.setattr(db, "get_ohlcv_df",
                        lambda s, freq="daily", limit=1000: frames[s].tail(limit))
    monkeypatch.setattr(db, "list_symbols", lambda: [{"symbol": s} for s in frames])
    r = fvl._compute_inner("SYM00", "pca")
    assert "error" in r
    assert fvl.pca_divergence("SYM00") is None


def test_td_routines_split():
    import pandas as pd
    import signal_scanner as sc
    ids = [r["id"] for r in sc.routine_catalog()]
    assert "td9" in ids and "td13" in ids and "pca_divergence" in ids

    def ctx_with_td(count):
        st = pd.DataFrame({"td": [count / 6.5]})
        return {"st": st, "symbol": "X"}

    td9  = next(r["fn"] for r in sc.ROUTINES if r["id"] == "td9")
    td13 = next(r["fn"] for r in sc.ROUTINES if r["id"] == "td13")
    assert td9(ctx_with_td(9)) is not None and td13(ctx_with_td(9)) is None
    assert td9(ctx_with_td(13)) is None and td13(ctx_with_td(13)) is not None
    assert td13(ctx_with_td(-13))["side"] == "bull"
    assert td9(ctx_with_td(5)) is None and td13(ctx_with_td(5)) is None


def test_sector_panel_preferred(monkeypatch):
    """Symbols with ≥ PCA_MIN_SECTOR tagged peers get a sector panel;
    untagged symbols fall back to the watchlist panel."""
    import database as db
    import fair_value_lab as fvl
    frames = _factor_universe()
    tags = {s: ("tech" if i < 6 else "") for i, s in enumerate(frames)}
    monkeypatch.setattr(db, "get_ohlcv_df",
                        lambda s, freq="daily", limit=1000: frames[s].tail(limit))
    monkeypatch.setattr(db, "list_symbols",
                        lambda: [{"symbol": s, "group_tag": tags[s]} for s in frames])

    panel, scope = fvl._panel_for("SYM00")
    assert scope == "sector:tech"
    assert panel.shape[1] == 6 and "SYM00" in panel.columns

    panel2, scope2 = fvl._panel_for("SYM08")          # untagged
    assert scope2 == "watchlist"
    assert panel2.shape[1] == 12

    r = fvl._compute_inner("SYM00", "pca")
    assert "error" not in r
    assert r["meta"]["panel_scope"] == "sector:tech"
