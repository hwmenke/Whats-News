import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import app as app_module
import stats
import indicator_cache as cache


class ApiValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_ohlcv_limit_must_be_integer(self):
        response = self.client.get("/api/ohlcv/AAPL?limit=abc")

        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertEqual(body["code"], "VALIDATION")
        self.assertIn("integer", body["message"])

    def test_ohlcv_limit_must_be_positive(self):
        response = self.client.get("/api/ohlcv/AAPL?limit=0")

        self.assertEqual(response.status_code, 400)
        body = response.get_json()
        self.assertEqual(body["code"], "VALIDATION")
        self.assertIn("positive", body["message"])


class StatsEdgeCaseTests(unittest.TestCase):
    def setUp(self):
        cache.bump_version("AAPL")

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
