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


class StatsKamaTests(unittest.TestCase):
    def test_quote_gaps_restart_warmup_and_recover(self):
        for period in stats.KAMA_PERIODS:
            for missing in (np.nan, np.inf, -np.inf):
                for gap in (0, period - 1, period + 5):
                    with self.subTest(period=period, missing=missing, gap=gap):
                        close = pd.Series(
                            [100 + i + i % 7 for i in range(160)], dtype=float,
                            index=pd.date_range("2026-01-01", periods=160),
                        )
                        close.iloc[gap] = missing
                        result = stats._kama(close, window=period)
                        self.assertTrue(result.iloc[gap:gap + period].isna().all())
                        self.assertEqual(result.iloc[gap + period], close.iloc[gap + period])
                        self.assertTrue(np.isfinite(result.iloc[gap + period:]).all())
                        pd.testing.assert_series_equal(
                            result.iloc[gap + 1:],
                            stats._kama(close.iloc[gap + 1:], window=period),
                        )
                        pd.testing.assert_series_equal(
                            result.iloc[:gap], stats._kama(close.iloc[:gap], window=period),
                        )

    def test_complete_history_preserves_recursive_updates(self):
        for period in stats.KAMA_PERIODS:
            with self.subTest(period=period):
                close = pd.Series(range(160), dtype=float)
                result = stats._kama(close, window=period)
                self.assertTrue(result.iloc[:period - 1].isna().all())
                expected = float(period - 1)
                self.assertEqual(result.iloc[period - 1], expected)
                for i in range(period, len(close)):
                    expected += (2.0 / 3.0) ** 2 * (close.iloc[i] - expected)
                    self.assertAlmostEqual(result.iloc[i], expected)


class StatsEdgeCaseTests(unittest.TestCase):
    def test_invalid_kama_distances_do_not_create_crossovers(self):
        index = pd.date_range("2026-01-01", periods=30)
        frame = pd.DataFrame({"close": np.full(30, 100.0)}, index=index)
        for invalid in (np.inf, -np.inf, np.nan, 1e-308, 0.0):
            with self.subTest(invalid=invalid):
                estimates = pd.Series([101.0, invalid] + [99.0] * 28, index=index)
                with patch.object(stats.db, "get_ohlcv_df", return_value=frame), patch.object(
                    stats, "_kama", return_value=estimates,
                ):
                    result = stats.compute_stats("TEST")
                for crossing in result["kama_cross_analysis"]:
                    self.assertEqual(crossing["count_1d"], 0)
                    self.assertEqual(crossing["count_5d"], 0)
                for horizon in ("fwd_1d", "fwd_5d"):
                    for bins in result["kama_distance_analysis"][horizon].values():
                        self.assertTrue(bins)
                        self.assertTrue(all(item["value"] == 0.0 for item in bins))

        estimates = pd.Series([101.0] + [99.0] * 29, index=index)
        with patch.object(stats.db, "get_ohlcv_df", return_value=frame), patch.object(
            stats, "_kama", return_value=estimates,
        ):
            result = stats.compute_stats("TEST")
        for crossing in result["kama_cross_analysis"]:
            self.assertEqual(crossing["count_1d"], 1 if crossing["direction"] == "bull" else 0)

    def test_stats_rsi_preserves_quote_gaps_and_recovers(self):
        for missing in (np.nan, np.inf, -np.inf):
            for prices in (
                np.arange(100.0, 140.0),
                100 + np.sin(np.arange(40)) * 5,
            ):
                with self.subTest(missing=missing, prices=prices.tolist()):
                    close = pd.Series(prices, index=pd.date_range("2026-01-01", periods=40))
                    close.iloc[25] = missing
                    result = stats._rsi(close)
                    self.assertTrue(result.iloc[:14].isna().all())
                    self.assertTrue(pd.isna(result.iloc[25]))
                    self.assertTrue(np.isfinite(result.iloc[26:]).all())
                    cleaned = close.replace([np.inf, -np.inf], np.nan)
                    delta = cleaned.diff()
                    gain = delta.clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
                    loss = (-delta).clip(lower=0).ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
                    expected = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
                    expected = expected.mask((loss == 0) & (gain > 0), 100.0).where(cleaned.notna())
                    pd.testing.assert_series_equal(result, expected)

    @patch("stats._rsi")
    @patch("stats.db.get_ohlcv_df")
    def test_infinite_closes_preserve_daily_and_forward_return_gaps(self, mock_get_ohlcv_df, mock_rsi):
        index = pd.date_range("2024-01-01", periods=12)
        mock_rsi.return_value = pd.Series(np.arange(12, dtype=float), index=index)
        for invalid in (np.inf, -np.inf):
            with self.subTest(invalid=invalid):
                frame = pd.DataFrame(
                    {"close": [100.0, 110.0, 120.0, 130.0, 140.0, invalid,
                               160.0, 170.0, 180.0, 190.0, 200.0, 210.0]},
                    index=index,
                )
                mock_get_ohlcv_df.return_value = frame
                result = stats.compute_stats("TEST")
                self.assertEqual(sum(item["count"] for item in result["distribution"]), 9)
                expected_daily = [110 / 100 - 1, 120 / 110 - 1, 130 / 120 - 1,
                                  140 / 130 - 1, 170 / 160 - 1, 180 / 170 - 1,
                                  190 / 180 - 1, 200 / 190 - 1, 210 / 200 - 1]
                self.assertAlmostEqual(result["metrics"]["avg_daily_ret"], np.mean(expected_daily))
                self.assertEqual(result["metrics"]["win_rate"], 1.0)
                np.testing.assert_allclose(
                    [item["value"] for item in result["rsi_analysis"]["fwd_5d"]],
                    [160 / 110 - 1, 170 / 120 - 1, 180 / 130 - 1,
                     190 / 140 - 1, 210 / 160 - 1],
                )
                self.assertEqual(frame.loc[index[5], "close"], invalid)

    @patch("stats._rsi")
    @patch("stats.db.get_ohlcv_df")
    def test_nonfinite_returns_are_excluded_from_statistics(self, mock_get_ohlcv_df, mock_rsi):
        index = pd.date_range("2024-01-01", periods=8)
        mock_get_ohlcv_df.return_value = pd.DataFrame(
            {"close": [0.0, 100.0, 110.0, 132.0, 145.2, 174.24, 191.664, 230.0]},
            index=index,
        )
        mock_rsi.return_value = pd.Series(np.arange(8, dtype=float), index=index)

        result = stats.compute_stats("TEST")

        self.assertAlmostEqual(result["metrics"]["avg_daily_ret"], (0.7 + 230 / 191.664 - 1) / 6)
        self.assertEqual(sum(item["count"] for item in result["distribution"]), 6)
        daily = result["rsi_analysis"]["fwd_1d"]
        self.assertEqual(len(daily), 6)
        np.testing.assert_allclose([item["value"] for item in daily], [0.1, 0.2, 0.1, 0.2, 0.1, 230 / 191.664 - 1])
        forward = result["rsi_analysis"]["fwd_5d"]
        self.assertEqual(len(forward), 2)
        np.testing.assert_allclose([item["value"] for item in forward],
                                   [191.664 / 100.0 - 1, 230 / 110.0 - 1])

    @patch("stats._rsi")
    @patch("stats.db.get_ohlcv_df")
    def test_forward_returns_skip_missing_endpoint_closes(self, mock_get_ohlcv_df, mock_rsi):
        index = pd.date_range("2024-01-01", periods=12)
        mock_get_ohlcv_df.return_value = pd.DataFrame(
            {"close": [100.0, 110.0, 120.0, 130.0, 140.0, np.nan,
                       160.0, 170.0, 180.0, 190.0, 200.0, 210.0]},
            index=index,
        )
        mock_rsi.return_value = pd.Series(np.arange(12, dtype=float), index=index)

        result = stats.compute_stats("TEST")

        expected = [160 / 110 - 1, 170 / 120 - 1, 180 / 130 - 1,
                    190 / 140 - 1, 210 / 160 - 1]
        actual = [item["value"] for item in result["rsi_analysis"]["fwd_5d"]]
        np.testing.assert_allclose(actual, expected)

    @patch("stats.db.get_ohlcv_df")
    def test_missing_closes_do_not_create_daily_returns(self, mock_get_ohlcv_df):
        for closes, expected_return, expected_count in (
            ([100.0, np.nan, 120.0, 132.0], 0.1, 1),
            ([100.0, np.nan, 120.0], None, 0),
        ):
            with self.subTest(closes=closes):
                mock_get_ohlcv_df.return_value = pd.DataFrame(
                    {"close": closes},
                    index=pd.date_range("2024-01-01", periods=len(closes)),
                )
                result = stats.compute_stats("TEST")
                if expected_return is None:
                    self.assertIsNone(result["metrics"]["avg_daily_ret"])
                    self.assertIsNone(result["metrics"]["win_rate"])
                else:
                    self.assertAlmostEqual(result["metrics"]["avg_daily_ret"], expected_return)
                    self.assertEqual(result["metrics"]["win_rate"], 1.0)
                self.assertEqual(
                    sum(item["count"] for item in result["distribution"]),
                    expected_count,
                )

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
