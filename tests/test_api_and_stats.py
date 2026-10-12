import os
import unittest
os.environ.setdefault("DATA_SERVICE_MODE", "embedded")
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd

import app as app_module
import stats


class ApiValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_ohlcv_limit_must_be_integer(self):
        response = self.client.get("/api/ohlcv/AAPL?limit=abc")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "limit must be an integer"})


    def test_health_endpoint(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("service"), "whats-news")
        self.assertIn("symbol_count", data)

    def test_ohlcv_limit_must_be_positive(self):
        response = self.client.get("/api/ohlcv/AAPL?limit=0")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "limit must be a positive integer"})


class StatsEdgeCaseTests(unittest.TestCase):
    def test_stats_rsi_handles_lossless_prices_without_filling_warmup(self):
        index = pd.date_range("2024-01-01", periods=30)
        for closes, expected in (
            (np.arange(100.0, 130.0), 100.0),
            (np.arange(130.0, 100.0, -1.0), 0.0),
            (np.full(30, 100.0), None),
        ):
            with self.subTest(expected=expected):
                result = stats._rsi(pd.Series(closes, index=index))
                self.assertTrue(result.iloc[:14].isna().all())
                pd.testing.assert_index_equal(result.index, index)
                if expected is None:
                    self.assertTrue(result.isna().all())
                else:
                    self.assertTrue((result.iloc[14:] == expected).all())

        close = pd.Series([100.0, 102.0, 101.0, 103.0, 102.0], index=index[:5])
        gain = close.diff().clip(lower=0).ewm(alpha=0.5, min_periods=2, adjust=False).mean()
        loss = (-close.diff()).clip(lower=0).ewm(alpha=0.5, min_periods=2, adjust=False).mean()
        expected = 100.0 - 100.0 / (1.0 + gain / loss)
        pd.testing.assert_series_equal(stats._rsi(close, window=2), expected)

    @patch("stats.db.get_ohlcv_df")
    def test_max_drawdown_includes_initial_value_and_later_peaks(self, mock_get_ohlcv_df):
        for closes, expected in (
            ([100.0, 80.0], -0.2),
            ([100.0, 80.0, 60.0], -0.4),
            ([100.0, 120.0, 90.0], -0.25),
            ([100.0, 110.0, 120.0], 0.0),
        ):
            with self.subTest(closes=closes):
                mock_get_ohlcv_df.return_value = pd.DataFrame(
                    {"close": closes},
                    index=pd.date_range("2024-01-01", periods=len(closes)),
                )
                result = stats.compute_stats("TEST")
                self.assertAlmostEqual(result["metrics"]["max_drawdown"], expected)

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


if __name__ == "__main__":
    unittest.main()
