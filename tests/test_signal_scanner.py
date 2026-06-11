"""Tests for signal_scanner.py — routine registry and watchlist scan."""

import json

import numpy as np
import pandas as pd
import pytest


def _make_df(seed: int, n: int = 900) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ret = rng.normal(0.0004, 0.015, n) + 0.002 * np.sin(np.linspace(0, 12 * np.pi, n))
    close = 100 * np.exp(np.cumsum(ret))
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame(
        {"open": np.r_[close[0], close[:-1]], "high": close * 1.01,
         "low": close * 0.99, "close": close,
         "volume": rng.integers(1_000_000, 9_000_000, n).astype(float)},
        index=idx,
    )


@pytest.fixture
def scan_env(monkeypatch):
    import database as db
    frames = {"AAA": _make_df(1), "BBB": _make_df(2), "TINY": _make_df(3, n=100)}
    monkeypatch.setattr(db, "get_ohlcv_df",
                        lambda s, freq="daily", limit=1000: frames[s].tail(limit))
    monkeypatch.setattr(db, "list_symbols",
                        lambda: [{"symbol": s} for s in frames])
    return frames


def test_routine_catalog():
    import signal_scanner as sc
    cat = sc.routine_catalog()
    assert len(cat) >= 8
    ids = [r["id"] for r in cat]
    assert len(ids) == len(set(ids))                       # unique ids
    assert all(r["label"] and r["desc"] for r in cat)


def test_scan_structure(scan_env):
    import signal_scanner as sc
    result = sc.scan_symbols()
    json.dumps(result, allow_nan=False)
    assert result["n_symbols"] == 3
    # short-history symbol is reported, not silently dropped
    assert any(s["symbol"] == "TINY" for s in result["skipped"])
    for sig in result["signals"]:
        assert sig["side"] in ("bull", "bear", "watch")
        assert 0 <= sig["strength"] <= 100
        assert sig["routine"] and sig["detail"] and sig["date"]
    # strength-sorted descending
    strengths = [s["strength"] for s in result["signals"]]
    assert strengths == sorted(strengths, reverse=True)


def test_scan_routine_filter(scan_env):
    import signal_scanner as sc
    result = sc.scan_symbols(["AAA"], ["val_extreme", "td9"])
    assert all(s["routine"] in ("val_extreme", "td9") for s in result["signals"])
    # catalog still lists everything (UI needs the full set for toggles)
    assert len(result["routines"]) == len(sc.routine_catalog())


def test_broken_routine_does_not_kill_scan(scan_env, monkeypatch):
    import signal_scanner as sc

    def boom(ctx):
        raise RuntimeError("kaput")

    monkeypatch.setattr(sc, "ROUTINES",
                        sc.ROUTINES + [{"id": "boom", "label": "BOOM",
                                        "desc": "always fails", "fn": boom}])
    result = sc._scan_one_inner("AAA")
    errs = [s for s in result["signals"] if s.get("error")]
    assert len(errs) == 1 and "kaput" in errs[0]["detail"]
