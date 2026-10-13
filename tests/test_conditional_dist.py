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

    def test_ema_missing_quotes_do_not_match_filters(self):
        for missing in (np.nan, np.inf, -np.inf):
            with self.subTest(missing=missing):
                df = _frame([10, 12, missing, 16])
                ema = cd.resolve_feature("EMA(2)", df)
                self.assertTrue(pd.isna(ema.iloc[2]))
                expected = df["close"].replace([np.inf, -np.inf], np.nan).ewm(
                    span=2, adjust=False
                ).mean()
                pd.testing.assert_series_equal(ema.iloc[[0, 1, 3]], expected.iloc[[0, 1, 3]])
                for left, right in (("EMA(2)", 0), (20, "EMA(2)")):
                    mask = cd.evaluate_condition(
                        df, {"left": left, "op": ">", "right": right}
                    )
                    self.assertEqual(mask.tolist(), [True, True, False, True])

    def test_macd_family_matches_pandas(self):
        close = self.df["close"]
        line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
        signal = line.ewm(span=9, adjust=False).mean()
        for feature, expected in (("MACD", line), ("MACD_LINE", line),
                                  ("MACD_SIGNAL", signal), ("MACD_HIST", line - signal)):
            with self.subTest(feature=feature):
                pd.testing.assert_series_equal(cd.resolve_feature(feature, self.df), expected)

    def test_macd_family_missing_quotes_do_not_match_filters(self):
        for missing in (np.nan, np.inf, -np.inf):
            df = _frame([10, 12, missing, 16])
            clean = _frame([10, 12, np.nan, 16])
            for feature in ("MACD", "MACD_LINE", "MACD_SIGNAL", "MACD_HIST"):
                with self.subTest(missing=missing, feature=feature):
                    result = cd.resolve_feature(feature, df)
                    self.assertTrue(pd.isna(result.iloc[2]))
                    self.assertTrue(np.isfinite(result.iloc[[0, 1, 3]]).all())
                    pd.testing.assert_series_equal(result, cd.resolve_feature(feature, clean))
                    for left, right in ((feature, -100), (100, feature)):
                        mask = cd.evaluate_condition(df, {"left": left, "op": ">", "right": right})
                        self.assertEqual(mask.tolist(), [True, True, False, True])

    def test_rsi_default_window(self):
        got = cd.resolve_feature("RSI(14)", self.df)
        self.assertEqual(len(got), len(self.df))
        valid = got.dropna()
        self.assertTrue(((valid >= 0) & (valid <= 100)).all())

    def test_bad_specs_raise(self):
        for bad in ("MA", "not a feature!", "RSI(", "sma()"):
            with self.assertRaises(cd.ConditionError):
                cd.resolve_feature(bad, self.df)

    def test_rsi_period_validation_preserves_default_and_positive_periods(self):
        with self.assertRaisesRegex(cd.ConditionError, "RSI period must be positive"):
            cd.resolve_feature("RSI(0)", self.df)
        pd.testing.assert_series_equal(
            cd.resolve_feature("RSI", self.df), cd.resolve_feature("RSI(14)", self.df)
        )
        for period in (1, 5, 14):
            with self.subTest(period=period):
                result = cd.resolve_feature(f"RSI({period})", self.df)
                self.assertTrue(result.iloc[:period].isna().all())
                self.assertTrue((result.iloc[period:] == 100).all())

    def test_rsi_rising_prices_match_overbought_filter_after_warmup(self):
        rsi = cd.resolve_feature("RSI(14)", self.df)
        self.assertTrue(rsi.iloc[:14].isna().all())
        self.assertTrue((rsi.iloc[14:] == 100).all())
        mask = cd.build_mask(
            self.df, [{"left": "RSI(14)", "op": ">", "right": 70}]
        )
        self.assertFalse(mask.iloc[:14].any())
        self.assertTrue(mask.iloc[14:].all())

    def test_rsi_falling_flat_and_mixed_prices(self):
        falling = cd._rsi(_frame(100 - np.arange(60))["close"])
        self.assertTrue(falling.iloc[:14].isna().all())
        self.assertTrue((falling.iloc[14:] == 0).all())
        flat = cd._rsi(_frame(np.full(60, 100))["close"])
        self.assertTrue(flat.isna().all())
        close = _frame(100 + np.sin(np.arange(60)) * 5)["close"]
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(
            alpha=1 / 14, min_periods=14, adjust=False
        ).mean()
        loss = (-delta).clip(lower=0).ewm(
            alpha=1 / 14, min_periods=14, adjust=False
        ).mean()
        expected = 100 - 100 / (1 + gain / loss)
        pd.testing.assert_series_equal(cd._rsi(close), expected)

    def test_roc_matches_pandas(self):
        got = cd.resolve_feature("ROC(20)", self.df)
        pd.testing.assert_series_equal(got, self.df["close"].pct_change(20) * 100.0, check_names=False)
        with self.assertRaises(cd.ConditionError):
            cd.resolve_feature("ROC", self.df)

    def test_roc_missing_endpoints_do_not_match_momentum_filters(self):
        for missing in (np.nan, np.inf, -np.inf):
            with self.subTest(missing=missing):
                df = _frame([10, missing, 12, 15])
                roc = cd.resolve_feature("ROC(1)", df)
                self.assertTrue(roc.iloc[:3].isna().all())
                self.assertAlmostEqual(roc.iloc[3], 25.0)
                mask = cd.build_mask(
                    df, [{"left": "ROC(1)", "op": ">=", "right": 0}]
                )
                self.assertEqual(mask.tolist(), [False, False, False, True])
                # A missing intermediate quote does not invalidate finite endpoints.
                self.assertAlmostEqual(cd.resolve_feature("ROC(2)", df).iloc[2], 20.0)

    def test_roc_zero_baselines_and_overflow_are_unavailable(self):
        roc = cd.resolve_feature("ROC(1)", _frame([0, 10, 0, 1e-308, 1e308]))
        self.assertTrue(pd.isna(roc.iloc[1]))
        self.assertEqual(roc.iloc[2], -100.0)
        self.assertTrue(pd.isna(roc.iloc[4]))


class DescribeTests(unittest.TestCase):
    def test_std_is_none_for_single_sample(self):
        d = cd._describe(pd.Series([0.03]))
        self.assertEqual(d["count"], 1)
        self.assertIsNone(d["std"])
        self.assertIsNone(d["skew"])
        self.assertEqual(d["mean"], 0.03)


class ConditionEvalTests(unittest.TestCase):
    def test_nonfinite_features_never_match_comparisons(self):
        df = _frame([np.nan, np.inf, -np.inf, 0, 10])
        for feature in ("price", "open", "high", "low", "volume"):
            df["volume"] = df["close"]
            for op in cd.OPS:
                for left, right in ((feature, 5), (5, feature)):
                    with self.subTest(feature=feature, op=op, left=left):
                        mask = cd.evaluate_condition(
                            df, {"left": left, "op": op, "right": right}
                        )
                        self.assertFalse(mask.iloc[:3].any())
                        expected = cd.OPS[op](
                            cd._operand(left, df), cd._operand(right, df)
                        )
                        pd.testing.assert_series_equal(mask.iloc[3:], expected.iloc[3:])

    def test_nonfinite_constants_never_match(self):
        df = _frame([0, 10])
        for value in (np.nan, np.inf, -np.inf, "NaN", "Infinity", "-Infinity"):
            for left, right in (("price", value), (value, "price"), (value, 5)):
                for op in cd.OPS:
                    with self.subTest(value=value, left=left, op=op):
                        mask = cd.evaluate_condition(
                            df, {"left": left, "op": op, "right": right}
                        )
                        self.assertEqual(mask.tolist(), [False, False])

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
    def test_missing_endpoints_do_not_manufacture_forward_returns(self):
        for missing in (np.nan, np.inf, -np.inf):
            with self.subTest(missing=missing):
                close = pd.Series([10, missing, 12, 15, 18], dtype=float)
                fr = cd.forward_returns(close, 1)
                self.assertTrue(fr.iloc[:2].isna().all())
                self.assertAlmostEqual(fr.iloc[2], 15 / 12 - 1)
                self.assertTrue(pd.isna(fr.iloc[-1]))
                # Only endpoints matter for a multi-day return.
                self.assertAlmostEqual(cd.forward_returns(close, 2).iloc[0], 0.2)

    def test_zero_baselines_and_overflow_returns_are_unavailable(self):
        close = pd.Series([0, 10, 0, 1e-308, 1e308], dtype=float)
        fr = cd.forward_returns(close, 1)
        self.assertTrue(pd.isna(fr.iloc[0]))
        self.assertEqual(fr.iloc[1], -1.0)
        self.assertTrue(pd.isna(fr.iloc[3]))
        self.assertTrue(pd.isna(fr.iloc[4]))

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
    @patch("conditional_dist.db.get_ohlcv_df")
    def test_invalid_endpoints_are_excluded_from_statistics_and_histograms(self, mock_df):
        mock_df.return_value = _frame([10, np.nan, 12, np.inf, 15, 0, 18, 21])
        result = cd.compute_conditional_distribution("AAPL", [], horizons=[1])
        block = result["by_horizon"]["1"]
        for name in ("conditional", "baseline"):
            self.assertEqual(block[name]["count"], 2)
            self.assertAlmostEqual(block[name]["mean"], (-1 + 21 / 18 - 1) / 2)
        self.assertEqual(sum(block["hist"]["conditional"]), 2)
        self.assertEqual(sum(block["hist"]["baseline"]), 2)

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
    def test_effective_count_discounts_overlap(self, mock_df):
        mock_df.return_value = self.df
        result = cd.compute_conditional_distribution(
            "AAPL", [{"left": "RSI(14)", "op": "<", "right": 60}], horizons=[10]
        )
        block = result["by_horizon"]["10"]["conditional"]
        self.assertAlmostEqual(block["effective_count"], round(block["count"] / 10, 1))
        self.assertLess(block["effective_count"], block["count"])
        self.assertIn("Matched", result["message"])
        self.assertEqual(result["return_unit"], "fraction")

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

    @patch("conditional_dist.db.get_ohlcv_df")
    def test_malformed_operators_return_400(self, mock_df):
        mock_df.return_value = self.df
        for key in ("op", "operator"):
            for operator in ([], {}, ["<"], {"value": "<"}, True, 1):
                with self.subTest(key=key, operator=operator):
                    resp = self.client.post(
                        "/api/conditional-distribution/AAPL",
                        json={"conditions": [{"left": "price", key: operator, "right": 100}]},
                    )
                    self.assertEqual(resp.status_code, 400)
                    self.assertIn("Unsupported operator", resp.get_json()["error"])

    @patch("conditional_dist.db.get_ohlcv_df")
    def test_zero_rsi_period_returns_400_for_either_operand(self, mock_df):
        mock_df.return_value = self.df
        for condition in (
            {"left": "RSI(0)", "op": "<", "right": 30},
            {"left": 30, "op": "<", "right": "rsi( 0 )"},
            {"feature": "RSI(0)", "operator": "<", "value": 30},
        ):
            with self.subTest(condition=condition):
                response = self.client.post(
                    "/api/conditional-distribution/AAPL",
                    json={"conditions": [condition]},
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("RSI period must be positive", response.get_json()["error"])

    def test_bad_horizon_returns_400(self):
        resp = self.client.post(
            "/api/conditional-distribution/AAPL",
            json={"conditions": [], "horizons": [0]},
        )
        self.assertEqual(resp.status_code, 400)

    @patch("conditional_dist.compute_conditional_distribution")
    def test_malformed_horizons_rejected_before_calculation(self, compute):
        for horizons in ([1.9], [True], [False], [float("inf")],
                         [None], [{}], [[5]], "5", {"5": 10}, 5):
            with self.subTest(horizons=horizons):
                resp = self.client.post(
                    "/api/conditional-distribution/AAPL",
                    json={"conditions": [], "horizons": horizons},
                )
                self.assertEqual(resp.status_code, 400)
                self.assertIn("error", resp.get_json())
        compute.assert_not_called()

    @patch("conditional_dist.compute_conditional_distribution")
    def test_integer_horizons_and_empty_defaults_preserved(self, compute):
        compute.return_value = {"by_horizon": {}}
        for horizons, expected in (([1, 250], [1, 250]),
                                   (["5", "10"], [5, 10]),
                                   ([], [5, 10])):
            with self.subTest(horizons=horizons):
                resp = self.client.post(
                    "/api/conditional-distribution/AAPL",
                    json={"conditions": [], "horizons": horizons},
                )
                self.assertEqual(resp.status_code, 200)
                compute.assert_called_with("AAPL", [], expected)


if __name__ == "__main__":
    unittest.main()
