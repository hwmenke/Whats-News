import os
import unittest

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")
from unittest.mock import patch

import numpy as np
import pandas as pd

import conditional_dist as cd


def _frame(close, index=None):
    n = len(close)
    index = index if index is not None else pd.date_range("2020-01-01", periods=n, freq="B")
    close = np.asarray(close, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1_000.0),
        },
        index=index,
    )


class FeatureParsingTests(unittest.TestCase):
    def setUp(self):
        self.df = _frame(100 + np.arange(60, dtype=float))

    def test_price_aliases_return_close(self):
        for alias in ("price", "close", "C"):
            pd.testing.assert_series_equal(
                cd.resolve_feature(alias, self.df), self.df["close"], check_names=False
            )

    def test_moving_average_matches_pandas(self):
        got = cd.resolve_feature("MA(50)", self.df)
        pd.testing.assert_series_equal(got, self.df["close"].rolling(50).mean(), check_names=False)
        # SMA is an alias for MA.
        pd.testing.assert_series_equal(cd.resolve_feature("SMA(50)", self.df), got, check_names=False)

    def test_ema_matches_pandas(self):
        got = cd.resolve_feature("EMA(20)", self.df)
        pd.testing.assert_series_equal(
            got, self.df["close"].ewm(span=20, adjust=False).mean(), check_names=False
        )

    def test_rsi_default_window(self):
        got = cd.resolve_feature("RSI(14)", self.df)
        self.assertEqual(len(got), len(self.df))
        valid = got.dropna()
        self.assertTrue(((valid >= 0) & (valid <= 100)).all())

    def test_bad_specs_raise(self):
        for bad in ("MA", "not a feature!", "RSI(", "sma()"):
            with self.assertRaises(cd.ConditionError):
                cd.resolve_feature(bad, self.df)


class ConditionEvalTests(unittest.TestCase):
    def test_constant_threshold_and_nan_excluded(self):
        df = _frame([10, 11, 9, 8, 12, 7])
        mask = cd.evaluate_condition(df, {"left": "price", "op": "<", "right": 10})
        expected = df["close"] < 10
        pd.testing.assert_series_equal(mask, expected, check_names=False)

    def test_feature_vs_feature(self):
        df = _frame(100 + np.sin(np.linspace(0, 12, 120)) * 8 + np.linspace(0, 5, 120))
        mask = cd.evaluate_condition(df, {"left": "MA(20)", "op": ">", "right": "MA(50)"})
        ma20, ma50 = df["close"].rolling(20).mean(), df["close"].rolling(50).mean()
        expected = (ma20 > ma50).reindex(df.index).fillna(False)
        pd.testing.assert_series_equal(mask, expected, check_names=False)
        # Warmup bars (NaN MA) must be excluded, never counted as matches.
        self.assertFalse(mask.iloc[:49].any())

    def test_and_combination(self):
        df = _frame(100 + np.arange(80, dtype=float))
        conds = [
            {"left": "price", "op": ">", "right": "MA(20)"},
            {"left": "price", "op": ">", "right": 150},
        ]
        mask = cd.build_mask(df, conds)
        expected = (df["close"] > df["close"].rolling(20).mean()) & (df["close"] > 150)
        pd.testing.assert_series_equal(mask, expected.fillna(False), check_names=False)

    def test_unsupported_operator_raises(self):
        df = _frame([1, 2, 3])
        with self.assertRaises(cd.ConditionError):
            cd.evaluate_condition(df, {"left": "price", "op": "==", "right": 1})


class ForwardReturnTests(unittest.TestCase):
    def test_no_lookahead_and_tail_is_nan(self):
        close = pd.Series([10, 11, 12, 13, 14, 15], dtype=float)
        fr = cd.forward_returns(close, 2)
        # value[t] uses close[t+2] only.
        self.assertAlmostEqual(fr.iloc[0], 12 / 10 - 1)
        self.assertAlmostEqual(fr.iloc[1], 13 / 11 - 1)
        self.assertAlmostEqual(fr.iloc[3], 15 / 13 - 1)
        # Last `horizon` bars have no future and must be NaN.
        self.assertTrue(np.isnan(fr.iloc[-1]))
        self.assertTrue(np.isnan(fr.iloc[-2]))


class DistributionTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(7)
        steps = rng.normal(0.0005, 0.02, 900)
        self.close = 100.0 * np.cumprod(1.0 + steps)
        self.df = _frame(self.close)

    @patch("conditional_dist.db.get_ohlcv_df")
    def test_matches_independent_recompute(self, mock_df):
        mock_df.return_value = self.df
        conds = [{"left": "RSI(14)", "op": "<", "right": 45}]
        result = cd.compute_conditional_distribution("AAPL", conds, horizons=[5, 10])

        close = self.df["close"]
        rsi = cd._rsi(close, 14)
        mask = (rsi < 45).reindex(self.df.index).fillna(False)
        self.assertEqual(result["match_count"], int(mask.sum()))
        self.assertEqual(result["bar_count"], len(self.df))

        for h in (5, 10):
            fr = close.pct_change(h).shift(-h)
            cond_r = fr[mask].dropna()
            block = result["by_horizon"][str(h)]["conditional"]
            self.assertEqual(block["count"], int(len(cond_r)))
            self.assertAlmostEqual(block["mean"], float(cond_r.mean()), places=9)
            self.assertAlmostEqual(block["median"], float(cond_r.median()), places=9)
            self.assertAlmostEqual(block["win_rate"], float((cond_r > 0).mean()), places=9)
            self.assertAlmostEqual(block["p05"], float(np.percentile(cond_r, 5)), places=9)

            base_r = fr.dropna()
            base_block = result["by_horizon"][str(h)]["baseline"]
            self.assertEqual(base_block["count"], int(len(base_r)))
            self.assertAlmostEqual(base_block["mean"], float(base_r.mean()), places=9)

    @patch("conditional_dist.db.get_ohlcv_df")
    def test_histogram_bins_shared_and_counts_consistent(self, mock_df):
        mock_df.return_value = self.df
        result = cd.compute_conditional_distribution(
            "AAPL", [{"left": "price", "op": ">", "right": "MA(50)"}], horizons=[5]
        )
        hist = result["by_horizon"]["5"]["hist"]
        self.assertEqual(len(hist["centers"]), 30)
        self.assertEqual(len(hist["conditional"]), 30)
        self.assertEqual(len(hist["baseline"]), 30)
        # Conditional counts cannot exceed the conditional sample size.
        self.assertLessEqual(sum(hist["conditional"]), result["by_horizon"]["5"]["conditional"]["count"])

    @patch("conditional_dist.db.get_ohlcv_df")
    def test_empty_match_is_graceful(self, mock_df):
        mock_df.return_value = self.df
        result = cd.compute_conditional_distribution(
            "AAPL", [{"left": "RSI(14)", "op": "<", "right": -5}], horizons=[5]
        )
        block = result["by_horizon"]["5"]["conditional"]
        self.assertEqual(result["match_count"], 0)
        self.assertEqual(block["count"], 0)
        self.assertIsNone(block["mean"])

    @patch("conditional_dist.db.get_ohlcv_df")
    def test_no_conditions_matches_all_bars(self, mock_df):
        mock_df.return_value = self.df
        result = cd.compute_conditional_distribution("AAPL", [], horizons=[5])
        self.assertEqual(result["match_count"], len(self.df))
        block = result["by_horizon"]["5"]
        self.assertEqual(block["conditional"]["count"], block["baseline"]["count"])

    @patch("conditional_dist.db.get_ohlcv_df")
    def test_bad_condition_raises_condition_error(self, mock_df):
        mock_df.return_value = self.df
        with self.assertRaises(cd.ConditionError):
            cd.compute_conditional_distribution(
                "AAPL", [{"left": "BOGUS(3)", "op": "<", "right": 1}], horizons=[5]
            )

    @patch("conditional_dist.db.get_ohlcv_df")
    def test_missing_symbol_returns_error(self, mock_df):
        mock_df.return_value = pd.DataFrame()
        result = cd.compute_conditional_distribution("ZZZZ", [], horizons=[5])
        self.assertIn("error", result)


class ApiRouteTests(unittest.TestCase):
    def setUp(self):
        import app as app_module
        self.client = app_module.app.test_client()
        self.df = _frame(100 + np.sin(np.linspace(0, 20, 400)) * 10 + np.linspace(0, 8, 400))

    @patch("conditional_dist.db.get_ohlcv_df")
    def test_post_returns_distribution(self, mock_df):
        mock_df.return_value = self.df
        resp = self.client.post(
            "/api/conditional-distribution/AAPL",
            json={"conditions": [{"left": "RSI(14)", "op": "<", "right": 40}], "horizons": [5, 10]},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIn("by_horizon", data)
        self.assertIn("5", data["by_horizon"])
        self.assertIn("10", data["by_horizon"])

    @patch("conditional_dist.db.get_ohlcv_df")
    def test_bad_feature_returns_400(self, mock_df):
        mock_df.return_value = self.df
        resp = self.client.post(
            "/api/conditional-distribution/AAPL",
            json={"conditions": [{"left": "NOPE", "op": "<", "right": 1}]},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())

    def test_bad_horizon_returns_400(self):
        resp = self.client.post(
            "/api/conditional-distribution/AAPL",
            json={"conditions": [], "horizons": [0]},
        )
        self.assertEqual(resp.status_code, 400)


if __name__ == "__main__":
    unittest.main()
