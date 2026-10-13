"""Regression tests for optimizer drawdown against starting equity."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import backtester


class DrawdownTests(unittest.TestCase):
    @patch("backtester._compute_trend_score")
    @patch("backtester.db.get_ohlcv_df")
    def test_flat_benchmark_leaves_undefined_sharpe_unavailable(self, mock_data, mock_trend):
        index = pd.date_range("2024-01-01", periods=220)
        close = pd.Series(100.0, index=index)
        mock_data.return_value = pd.DataFrame({"close": close})
        mock_trend.return_value = pd.Series(np.nan, index=index)

        benchmark = backtester.run_optimization("TEST")["benchmark"]

        self.assertIsNone(benchmark["sharpe"])
        self.assertEqual(benchmark["ann_ret"], 0.0)
        self.assertEqual(benchmark["ann_vol"], 0.0)
        self.assertEqual(benchmark["max_dd"], 0.0)

    def test_strategy_returns_do_not_bridge_invalid_quotes(self):
        for invalid in (np.nan, np.inf, -np.inf):
            with self.subTest(invalid=invalid):
                close = pd.Series([100.0, invalid, 200.0, 220.0])
                fast = pd.Series(2.0, index=close.index)
                slow = pd.Series(1.0, index=close.index)
                result = backtester._run_strategy(close, fast, slow)
                self.assertAlmostEqual(result["ann_ret"], 25.2)
                self.assertEqual(result["win_rate"], 1.0)
                self.assertEqual(result["max_dd"], 0.0)

    def test_daily_returns_omit_zero_baselines_and_overflow(self):
        close = pd.Series([0.0, 100.0, 0.0, 1e-300, 1e300])
        result = backtester._daily_returns(close)
        self.assertTrue(result.iloc[[0, 1, 3, 4]].isna().all())
        self.assertEqual(result.iloc[2], -1.0)

    @patch("backtester._compute_trend_score")
    @patch("backtester.db.get_ohlcv_df")
    def test_benchmark_and_curve_do_not_bridge_missing_quotes(self, mock_data, mock_trend):
        index = pd.date_range("2024-01-01", periods=220)
        close = pd.Series([100.0, np.nan] + [200.0] * 218, index=index)
        mock_data.return_value = pd.DataFrame({"close": close})
        mock_trend.return_value = pd.Series(np.nan, index=index)

        result = backtester.run_optimization("TEST")

        self.assertEqual(result["benchmark"]["ann_ret"], 0.0)
        self.assertEqual(result["benchmark"]["max_dd"], 0.0)
        self.assertTrue(result["equity_curve"])
        self.assertTrue(all(point["benchmark"] == 1.0 for point in result["equity_curve"]))

    def test_zero_volatility_preserves_strategy_metrics(self):
        for prices, ann_ret, max_dd, win_rate in (
            ([100.0, 50.0, 25.0], -126.0, -0.75, 0.0),
            ([100.0, 200.0, 400.0], 252.0, 0.0, 1.0),
            ([100.0, 100.0, 100.0], 0.0, 0.0, 0.0),
        ):
            with self.subTest(prices=prices):
                close = pd.Series(prices)
                fast = pd.Series(2.0, index=close.index)
                slow = pd.Series(1.0, index=close.index)
                result = backtester._run_strategy(close, fast, slow)
                self.assertEqual(result["ann_ret"], ann_ret)
                self.assertEqual(result["ann_vol"], 0.0)
                self.assertIsNone(result["sharpe"])
                self.assertEqual(result["max_dd"], max_dd)
                self.assertEqual(result["n_trades"], 1)
                self.assertEqual(result["win_rate"], win_rate)

    def test_strategy_drawdown_includes_starting_equity_and_later_peaks(self):
        for prices, expected in (
            ([100.0, 80.0, 60.0], -0.4),
            ([100.0, 120.0, 90.0], -0.25),
            ([100.0, 110.0, 130.0], 0.0),
        ):
            with self.subTest(prices=prices):
                close = pd.Series(prices)
                fast = pd.Series(2.0, index=close.index)
                slow = pd.Series(1.0, index=close.index)
                result = backtester._run_strategy(close, fast, slow)
                self.assertAlmostEqual(result["max_dd"], expected)

    @patch("backtester._compute_trend_score")
    @patch("backtester.db.get_ohlcv_df")
    def test_optimizer_benchmark_counts_first_bar_loss(self, mock_data, mock_trend):
        index = pd.date_range("2024-01-01", periods=220)
        # Synthetic regression prices: an initial loss followed by flat closes.
        close = pd.Series([100.0] + [80.0] * 219, index=index)
        mock_data.return_value = pd.DataFrame({"close": close})
        mock_trend.return_value = pd.Series(np.nan, index=index)

        result = backtester.run_optimization("TEST")

        self.assertAlmostEqual(result["benchmark"]["max_dd"], -0.2)


if __name__ == "__main__":
    unittest.main()
