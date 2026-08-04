"""
Network-free end-to-end smoke tests for every API endpoint.

Seeds synthetic OHLCV data into a temporary SQLite database (so no Yahoo
Finance access is required) and exercises each Flask route, asserting status
codes and response structure. Mirrors the manual audit harness so the feature
audit stays regression-protected.
"""
import datetime as dt
import os
import tempfile
import unittest

import numpy as np
import pandas as pd

import database as db


def _gen(n=900, start=100.0, seed=0):
    """Synthetic but realistic OHLCV (geometric brownian motion + cycle)."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0004, 0.015, n) + 0.01 * np.sin(np.linspace(0, 30, n)) / 10
    close = start * np.cumprod(1 + rets)
    dates = pd.bdate_range(end=dt.date(2025, 6, 20), periods=n)
    df = pd.DataFrame(
        {
            "open": close * (1 + rng.normal(0, 0.005, n)),
            "high": close * (1 + np.abs(rng.normal(0, 0.008, n))),
            "low": close * (1 - np.abs(rng.normal(0, 0.008, n))),
            "close": close,
            "volume": rng.integers(1_000_000, 50_000_000, n).astype(float),
        },
        index=dates,
    )
    df["high"] = df[["open", "high", "low", "close"]].max(axis=1)
    df["low"] = df[["open", "high", "low", "close"]].min(axis=1)
    return df


class EndpointSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Point the DB layer at a throwaway file and seed it.
        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        cls._orig_db_path = db.DB_PATH
        db.DB_PATH = cls._tmp.name
        db.init_db()

        for i, (sym, grp) in enumerate([("AAPL", "Tech"), ("MSFT", "Tech"), ("SPY", "")]):
            db.add_symbol(sym)
            if grp:
                db.set_symbol_group(sym, grp)
            daily = _gen(seed=i)
            weekly = (
                daily.resample("W-FRI")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna()
            )
            db.upsert_ohlcv(sym, "daily", daily)
            db.upsert_ohlcv(sym, "weekly", weekly)
            db.update_last_fetch(sym)

        import app as app_module

        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls._orig_db_path
        try:
            os.unlink(cls._tmp.name)
        except OSError:
            pass

    # ── helpers ────────────────────────────────────────────────────────────
    def _ok(self, path):
        r = self.client.get(path)
        self.assertEqual(r.status_code, 200, f"{path} -> {r.status_code}: {r.get_json()}")
        return r.get_json()

    # ── symbols ────────────────────────────────────────────────────────────
    def test_list_symbols(self):
        data = self._ok("/api/symbols")
        self.assertTrue(any(s["symbol"] == "AAPL" for s in data))

    def test_add_symbol_empty_rejected(self):
        r = self.client.post("/api/symbols", json={"symbol": ""})
        self.assertEqual(r.status_code, 400)

    def test_group_assignment(self):
        r = self.client.put("/api/symbols/AAPL/group", json={"group_tag": "MegaTech"})
        self.assertEqual(r.status_code, 200)
        row = next(s for s in self._ok("/api/symbols") if s["symbol"] == "AAPL")
        self.assertEqual(row["group_tag"], "MegaTech")

    # ── ohlcv ──────────────────────────────────────────────────────────────
    def test_ohlcv_daily(self):
        data = self._ok("/api/ohlcv/AAPL?freq=daily&limit=300")
        self.assertEqual(len(data), 300)
        self.assertTrue(all(k in data[0] for k in ("date", "open", "high", "low", "close", "volume")))

    def test_ohlcv_bad_freq(self):
        self.assertEqual(self.client.get("/api/ohlcv/AAPL?freq=monthly").status_code, 400)

    def test_ohlcv_missing_symbol_404(self):
        self.assertEqual(self.client.get("/api/ohlcv/NOPE").status_code, 404)

    # ── indicators ─────────────────────────────────────────────────────────
    def test_indicators(self):
        d = self._ok("/api/indicators/AAPL?freq=daily&kama=10,20,50")
        for key in ("kama_10", "bb_upper", "rsi_14", "macd_hist", "cci", "trend_score"):
            self.assertIn(key, d)
        self.assertTrue(any(p["value"] is not None for p in d["trend_score"]))

    def test_indicators_bad_kama(self):
        self.assertEqual(self.client.get("/api/indicators/AAPL?kama=abc").status_code, 400)

    # ── stats / knn / backtest ─────────────────────────────────────────────
    def test_stats(self):
        d = self._ok("/api/stats/AAPL")
        self.assertIsNotNone(d["metrics"]["volatility"])
        self.assertEqual(len(d["kama_cross_analysis"]), 6)
        # Trend-score validation: one row per score level -3..+3
        self.assertEqual([r["score"] for r in d["trend_score_analysis"]], list(range(-3, 4)))

    def test_knn(self):
        d = self._ok("/api/knn/AAPL?k=15")
        self.assertEqual(len(d["neighbors"]), 15)
        self.assertIn("summary", d)

    def test_backtest(self):
        d = self._ok("/api/backtest/AAPL")
        self.assertGreater(len(d["top10"]), 0)
        self.assertGreater(len(d["equity_curve"]), 0)
        # Walk-forward contract: holdout metrics + split point + costs
        self.assertIn("best_oos", d)
        self.assertIn("benchmark_oos", d)
        self.assertRegex(d["split_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertGreater(d["cost_bps"], 0)
        # Underwater series for the drawdown pane
        point = d["equity_curve"][0]
        self.assertIn("dd", point)
        self.assertIn("bench_dd", point)
        self.assertTrue(all(p["dd"] <= 1e-9 for p in d["equity_curve"]))

    # ── adaptive trend / scans ─────────────────────────────────────────────
    def test_adaptive_trend(self):
        d = self._ok("/api/adaptive-trend/AAPL?freq=daily&method=kama")
        for key in ("sb", "mb", "lb", "mrt", "mdb", "medium_state", "entry_long", "atr"):
            self.assertIn(key, d)
        # Observed hit-rate stats for the system's own long rules
        self.assertIn("system_stats", d)
        if d["system_stats"] is not None:
            self.assertIn("tp_rate", d["system_stats"])

    def test_adaptive_trend_bad_method(self):
        self.assertEqual(self.client.get("/api/adaptive-trend/AAPL?method=foo").status_code, 400)

    def test_trend_scan(self):
        d = self._ok("/api/trend-scan?freq=daily&method=kama&rsi_period=14")
        row = next(x for x in d if x["symbol"] == "AAPL")
        for key in ("price", "rsi", "kama10_pct", "signal", "mrt", "mdb"):
            self.assertIn(key, row)

    def test_scanner_multiframe(self):
        d = self._ok("/api/scanner")
        row = next(x for x in d if x["symbol"] == "AAPL")
        self.assertIsNotNone(row["d"])
        self.assertIn("rsi_14", row["d"])
        # Monthly frame must compute via the pandas 'ME' alias (no fallback).
        self.assertIsNotNone(row["m"])

    def test_data_manager_ticker_lists(self):
        d = self._ok("/api/data-manager/ticker-lists")
        self.assertGreaterEqual(len(d), 10)
        self.assertTrue(all({"id", "label", "tickers"} <= set(c) for c in d))

    def test_index_served(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"FinDash", r.data)


class SystemStatsTests(unittest.TestCase):
    """Pin the exit-classification semantics of adaptive_trend._system_stats."""

    def test_flip_exit_not_misclassified_as_stop(self):
        # On the regime-flip bar the ratchet band resets to the SHORT side
        # (above price). If the stop is tested before the regime check, the
        # flip is recorded as a profitable stop-out at a fictitious price.
        import adaptive_trend as at

        idx    = pd.date_range("2024-01-01", periods=6, freq="D")
        close  = pd.Series([100.0, 101.0, 102.0, 101.0, 95.0, 94.0], index=idx)
        open_  = close.copy()
        high   = close + 1.0
        low    = close - 1.0
        medium = pd.Series([0, 1, 1, 1, -1, -1], index=idx)
        entry  = pd.Series([False, True, False, False, False, False], index=idx)
        # Long-regime stop sits below price; on the flip bar (i=4) the band
        # has reset above price (105) and the TP band below (80).
        mrt = pd.Series([np.nan, 90.0, 90.0, 90.0, 105.0, 105.0], index=idx)
        mdb = pd.Series([np.nan, 120.0, 120.0, 120.0, 80.0, 80.0], index=idx)

        st = at._system_stats(open_, high, low, close, medium, entry, mrt, mdb)

        self.assertEqual(st["trades"], 1)
        self.assertEqual(st["flip_exits"], 1)
        self.assertEqual(st["stop_hits"], 0)
        self.assertEqual(st["tp_hits"], 0)
        # Exit at the flip bar's close (95) from entry 101 → a loss
        self.assertLess(st["avg_ret"], 0)
        self.assertEqual(st["win_rate"], 0.0)
        # Per-trade payload for chart markers
        trade = st["trade_list"][0]
        self.assertEqual(trade["outcome"], "flip")
        self.assertEqual(trade["entry_date"], "2024-01-02")
        self.assertEqual(trade["exit_date"], "2024-01-05")

    def test_genuine_stop_and_tp_still_classified(self):
        import adaptive_trend as at

        idx    = pd.date_range("2024-01-01", periods=8, freq="D")
        close  = pd.Series([100.0, 101.0, 96.0, 100.0, 102.0, 110.0, 111.0, 112.0], index=idx)
        open_  = close.copy()
        high   = close + 1.0
        low    = close - 1.0
        medium = pd.Series([0, 1, 1, 1, 1, 1, 1, 1], index=idx)
        entry  = pd.Series([False, True, False, True, False, False, False, False], index=idx)
        mrt    = pd.Series([np.nan] + [96.0] * 7, index=idx)
        mdb    = pd.Series([np.nan] + [108.0] * 7, index=idx)

        st = at._system_stats(open_, high, low, close, medium, entry, mrt, mdb)

        # Trade 1 (entry@101): low tags 96 stop on bar 2.
        # Trade 2 (entry@100): high tags 108 TP on bar 5.
        self.assertEqual(st["stop_hits"], 1)
        self.assertEqual(st["tp_hits"], 1)
        self.assertEqual(st["flip_exits"], 0)


if __name__ == "__main__":
    unittest.main()
