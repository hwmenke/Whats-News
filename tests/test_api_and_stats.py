import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import app as app_module
import stats
import risk
import journal
import scorecards
import regime as regime_mod
import database as db


class ApiValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_ohlcv_limit_must_be_integer(self):
        response = self.client.get("/api/ohlcv/AAPL?limit=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "limit must be an integer"})

    def test_ohlcv_limit_must_be_positive(self):
        response = self.client.get("/api/ohlcv/AAPL?limit=0")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "limit must be a positive integer"})


class StatsEdgeCaseTests(unittest.TestCase):
    @patch("stats.db.get_ohlcv_df")
    def test_compute_stats_returns_none_for_flat_series(self, mock_get_ohlcv_df):
        index = pd.date_range("2024-01-01", periods=40, freq="D")
        mock_get_ohlcv_df.return_value = pd.DataFrame(
            {
                "open": [100.0] * 40,
                "high": [100.0] * 40,
                "low": [100.0] * 40,
                "close": [100.0] * 40,
                "volume": [1_000.0] * 40,
            },
            index=index,
        )

        result = stats.compute_stats("AAPL")

        self.assertEqual(result["metrics"]["volatility"], 0.0)
        self.assertIsNone(result["metrics"]["sharpe"])
        self.assertEqual(result["metrics"]["avg_daily_ret"], 0.0)
        self.assertEqual(result["metrics"]["win_rate"], 0.0)
        self.assertTrue(result["distribution"])
        self.assertEqual(result["rsi_analysis"]["fwd_1d"], [])
        self.assertEqual(result["rsi_analysis"]["fwd_5d"], [])
        self.assertEqual(sorted(result["kama_distance_analysis"]["fwd_1d"].keys()), ["10", "20", "50"])
        self.assertTrue(all(not values for values in result["kama_distance_analysis"]["fwd_1d"].values()))
        self.assertEqual(len(result["kama_cross_analysis"]), 6)
        self.assertTrue(all(item["count_1d"] == 0 for item in result["kama_cross_analysis"]))

    @patch("stats.db.get_ohlcv_df")
    def test_compute_stats_builds_kama_analyses_for_non_flat_series(self, mock_get_ohlcv_df):
        index = pd.date_range("2024-01-01", periods=160, freq="D")
        close = 100 + np.sin(np.linspace(0, 18, 160)) * 6 + np.linspace(0, 4, 160)
        mock_get_ohlcv_df.return_value = pd.DataFrame(
            {
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": np.full(160, 1_000.0),
            },
            index=index,
        )

        result = stats.compute_stats("AAPL")

        self.assertTrue(result["kama_distance_analysis"]["fwd_1d"]["10"])
        self.assertTrue(result["kama_distance_analysis"]["fwd_5d"]["20"])
        self.assertEqual(len(result["kama_cross_analysis"]), 6)
        self.assertGreater(sum(item["count_1d"] for item in result["kama_cross_analysis"]), 0)


class RiskMathTests(unittest.TestCase):
    def test_long_sizing(self):
        r = risk.position_size(100000, 1.0, 50, 47.5)
        self.assertEqual(r["risk_per_share"], 2.5)
        self.assertEqual(r["shares"], 400)          # 1000 / 2.5
        self.assertEqual(r["pct_of_equity"], 20.0)  # 400*50 / 100000

    def test_short_sizing(self):
        r = risk.position_size(100000, 0.5, 20, 21, direction="short")
        self.assertEqual(r["shares"], 500)          # 500 / 1
        self.assertIsNone(r["warning"])

    def test_entry_equals_stop_is_error(self):
        r = risk.position_size(100000, 1.0, 50, 50)
        self.assertIn("error", r)

    def test_long_with_inverted_stop_warns(self):
        r = risk.position_size(100000, 1.0, 50, 52)
        self.assertIsNotNone(r["warning"])

    def test_tight_stop_flags_position_cap(self):
        # A very tight stop implies a position far over the 30% overnight cap.
        r = risk.position_size(100000, 1.0, 50, 49.9)
        self.assertTrue(r["exceeds_position_cap"])
        self.assertLess(r["capped_shares"], r["shares"])
        self.assertTrue(any("cap" in w for w in r["warnings"]))


class JournalMetricsTests(unittest.TestCase):
    def _r(self, direction, entry, stop, exit_price):
        row = {"symbol": "X", "direction": direction, "status": "closed",
               "entry_price": entry, "stop_price": stop, "shares": 100,
               "exit_price": exit_price}
        return journal.compute_trade_metrics(row)

    def test_r_multiple_sign_all_quadrants(self):
        self.assertEqual(self._r("long", 50, 47.5, 60)["r_multiple"], 4.0)
        self.assertEqual(self._r("long", 50, 47.5, 47.5)["r_multiple"], -1.0)
        self.assertEqual(self._r("short", 20, 21, 16)["r_multiple"], 4.0)
        self.assertEqual(self._r("short", 20, 21, 22)["r_multiple"], -2.0)

    def test_result_labels(self):
        self.assertEqual(self._r("long", 50, 47.5, 60)["result"], "win")
        self.assertEqual(self._r("long", 50, 47.5, 40)["result"], "loss")

    def test_cumulative_expectancy(self):
        trades = [
            {"r_multiple": 4.0, "initial_risk_usd": 1000, "pnl": 4000},
            {"r_multiple": -1.0, "initial_risk_usd": 1000, "pnl": -1000},
            {"r_multiple": -1.0, "initial_risk_usd": 1000, "pnl": -1000},
        ]
        with patch("journal.list_trades", side_effect=lambda s=None: trades if s == "closed" else []):
            stats_out = journal.cumulative_stats()
        self.assertEqual(stats_out["total_closed"], 3)
        self.assertEqual(stats_out["wins"], 1)
        self.assertAlmostEqual(stats_out["batting_average"], 33.33, places=1)
        # expectancy = 1/3*4 + 2/3*(-1) = 0.666...
        self.assertAlmostEqual(stats_out["expectancy_r"], 0.67, places=2)
        self.assertEqual(stats_out["total_r_closed"], 2.0)


class JournalApiTests(unittest.TestCase):
    def setUp(self):
        self._orig_path = db.DB_PATH
        self._tmp = tempfile.mktemp(suffix=".db")
        db.DB_PATH = self._tmp
        db.init_db()
        self.client = app_module.app.test_client()

    def tearDown(self):
        db.DB_PATH = self._orig_path
        if os.path.exists(self._tmp):
            os.remove(self._tmp)

    @patch("journal.db.get_ohlcv_df")
    def test_open_close_lifecycle(self, mock_df):
        mock_df.return_value = pd.DataFrame({"close": [50.0, 55.0]})
        r = self.client.post("/api/journal/trades", json={
            "symbol": "aapl", "direction": "long",
            "entry_price": 50, "stop_price": 47.5, "shares": 400})
        self.assertEqual(r.status_code, 201)
        tid = r.get_json()["id"]

        openg = self.client.get("/api/journal/trades?status=open").get_json()
        self.assertEqual(len(openg), 1)
        self.assertEqual(openg[0]["r_multiple"], 2.0)  # (55-50)/2.5 live

        closed = self.client.post(f"/api/journal/trades/{tid}/close",
                                  json={"exit_price": 60}).get_json()
        self.assertEqual(closed["r_multiple"], 4.0)
        self.assertEqual(closed["result"], "win")

        s = self.client.get("/api/journal/stats").get_json()
        self.assertEqual(s["total_closed"], 1)
        self.assertEqual(s["total_pnl_usd"], 4000.0)


class RiskApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_size_happy_path(self):
        r = self.client.post("/api/risk/size",
                             json={"equity": 100000, "risk_pct": 1, "entry": 50, "stop": 47.5})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["shares"], 400)

    def test_size_entry_equals_stop(self):
        r = self.client.post("/api/risk/size",
                             json={"equity": 100000, "risk_pct": 1, "entry": 50, "stop": 50})
        self.assertEqual(r.status_code, 400)

    def test_size_missing_fields(self):
        r = self.client.post("/api/risk/size", json={"equity": 100000})
        self.assertEqual(r.status_code, 400)


def _trend_df(n=260, start=50, step=0.4, vol_last=None):
    close = np.linspace(start, start + step * n, n)
    df = pd.DataFrame({
        "open": close - 0.1, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": np.full(n, 1_000_000.0),
    }, index=pd.date_range("2023-01-01", periods=n, freq="D"))
    if vol_last:
        df.iloc[-1, df.columns.get_loc("volume")] = vol_last
    return df


def _burst_df():
    """A quiet rising base, a down day, then a 6%+ range-expansion pop on volume."""
    n = 180
    close = np.concatenate([np.linspace(60.0, 108.0, n - 15), np.full(15, 108.0)])
    base_noise = np.array([0.3, -0.2, 0.1, -0.3, 0.2, -0.1, 0.2,
                           -0.2, 0.1, -0.3, 0.2, -0.1, 0.0, -0.5, 0.0])
    close[-15:] = 108.0 + base_noise
    high = close + 0.4
    low = close - 0.4
    openp = close.copy()
    vol = np.full(n, 1_000_000.0)
    prev = close[-2]                    # down day relative to close[-3]
    last = prev * 1.06                  # +6% pop closing at the high
    close[-1] = high[-1] = last
    low[-1] = openp[-1] = prev
    vol[-1] = 3_000_000.0
    return pd.DataFrame(
        {"open": openp, "high": high, "low": low, "close": close, "volume": vol},
        index=pd.date_range("2023-01-01", periods=n, freq="D"),
    )


class ScorecardTests(unittest.TestCase):
    @patch("scorecards.db.get_ohlcv_df")
    def test_momentum_burst_detected(self, mock_df):
        mock_df.return_value = _burst_df()
        res = scorecards.scan_symbol("TEST")
        self.assertIsNotNone(res)
        types = {s["type"] for s in res["setups"]}
        self.assertIn("momentum_burst", types)

    @patch("scorecards.db.get_ohlcv_df")
    def test_extended_uptrend_not_a_burst(self, mock_df):
        # A smooth, always-up series is "extended" — the burst detector must
        # NOT fire even on a final pop, because price is up many days running.
        df = _trend_df(200, vol_last=3_000_000.0)
        prev = df["close"].iloc[-2]
        last = prev * 1.06
        df.iloc[-1, df.columns.get_loc("close")] = last
        df.iloc[-1, df.columns.get_loc("high")] = last
        mock_df.return_value = df
        res = scorecards.scan_symbol("TEST")
        types = set() if not res else {s["type"] for s in res.get("setups", [])}
        self.assertNotIn("momentum_burst", types)

    @patch("scorecards.db.get_ohlcv_df")
    def test_insufficient_data_skipped(self, mock_df):
        mock_df.return_value = _trend_df(50)
        self.assertIsNone(scorecards.scan_symbol("TEST"))


class RegimeTests(unittest.TestCase):
    @patch("regime.db.list_symbols", return_value=[{"symbol": "SPY"}, {"symbol": "QQQ"}])
    @patch("regime.db.get_ohlcv_df")
    def test_strong_uptrend_is_offensive(self, mock_df, _mock_syms):
        # Strong uptrend that also prints an explosive 4%+ up day on volume,
        # which is what "Offensive" requires (up4 > down4 in breadth).
        df = _trend_df(260, start=100, step=0.5, vol_last=4_000_000.0)
        prev = df["close"].iloc[-2]
        last = prev * 1.05
        for col in ("close", "high"):
            df.iloc[-1, df.columns.get_loc(col)] = last
        mock_df.return_value = df
        out = regime_mod.compute_regime()
        self.assertEqual(out["regime"], "Offensive")

    @patch("regime.db.list_symbols", return_value=[])
    @patch("regime.db.get_ohlcv_df", return_value=pd.DataFrame())
    def test_missing_index_is_unknown(self, _mock_df, _mock_syms):
        out = regime_mod.compute_regime()
        self.assertEqual(out["regime"], "Unknown")


class CockpitAnalyticsTests(unittest.TestCase):
    def test_performance_breakdown(self):
        import cockpit_analytics as ca
        closed = [
            {"r_multiple": 3.0, "pnl": 1500, "setup_type": "EP",
             "direction": "long", "exit_date": "2024-02-10", "id": 1},
            {"r_multiple": -1.0, "pnl": -500, "setup_type": "breakout",
             "direction": "long", "exit_date": "2024-02-08", "id": 2},
            {"r_multiple": 2.0, "pnl": 800, "setup_type": "EP",
             "direction": "long", "exit_date": "2024-03-01", "id": 3},
        ]
        with patch("cockpit_analytics.journal.list_trades",
                   side_effect=lambda s=None: closed if s == "closed" else []):
            out = ca.compute_performance()
        self.assertEqual(out["overall"]["count"], 3)
        self.assertEqual(out["overall"]["total_r"], 4.0)
        self.assertEqual(len(out["equity_curve"]), 3)
        # EP grouped: two trades totalling 5R
        ep = next(s for s in out["by_setup"] if s["setup"] == "EP")
        self.assertEqual(ep["count"], 2)
        self.assertEqual(ep["total_r"], 5.0)
        # drawdown: curve sorted by date -> -1R then +3 then +2; peak after first win
        self.assertGreaterEqual(out["overall"]["max_drawdown_r"], 1.0)


class ManagementCueTests(unittest.TestCase):
    @patch("journal.db.get_ohlcv_df")
    def test_partial_cue_at_2r(self, mock_df):
        mock_df.return_value = pd.DataFrame({"close": list(range(40, 100))})
        row = {"status": "open", "symbol": "AAPL", "direction": "long",
               "entry_price": 50, "stop_price": 45, "entry_date": "2024-01-10"}
        cues, _ = journal._management_cues(row, {"r_multiple": 2.5})
        self.assertTrue(any("partial" in c["text"].lower() for c in cues))

    @patch("journal.db.get_ohlcv_df")
    def test_stop_breach_cue(self, mock_df):
        mock_df.return_value = pd.DataFrame({"close": list(range(40, 100))})
        row = {"status": "open", "symbol": "AAPL", "direction": "long",
               "entry_price": 50, "stop_price": 45, "entry_date": "2024-01-10"}
        cues, _ = journal._management_cues(row, {"r_multiple": -1.2})
        self.assertTrue(any(c["level"] == "danger" for c in cues))


if __name__ == "__main__":
    unittest.main()
