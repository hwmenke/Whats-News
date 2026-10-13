"""Regression coverage for historical lookalike outcomes."""

import unittest
import json
from unittest.mock import patch

import numpy as np
import pandas as pd

import knn_model


class KnnModelTests(unittest.TestCase):
    @patch("knn_model._kama")
    @patch("knn_model.db.get_ohlcv_df")
    def test_nonfinite_features_are_excluded_before_scaling(self, get_data, kama):
        dates = pd.date_range("2025-01-01", periods=140)
        close = pd.Series(100 + np.arange(140) + np.sin(np.arange(140)), index=dates)
        frame = pd.DataFrame({
            "close": close, "high": close + 2, "low": close - 2,
            "volume": 1000.0 + np.arange(140),
        })
        get_data.side_effect = lambda *args, **kwargs: frame.copy()
        for invalid_index in (80, 139):
            with self.subTest(invalid_index=invalid_index):
                def overflowing_kama(prices, window):
                    values = pd.Series(100.0, index=prices.index)
                    values.iloc[invalid_index] = 1e-310
                    return values

                kama.side_effect = overflowing_kama
                with np.errstate(over="ignore"):
                    result = knn_model.compute_knn_lookalike("TEST", k=90)
                if invalid_index == 139:
                    self.assertEqual(result, {
                        "error": "Latest bar has incomplete features for TEST",
                    })
                else:
                    self.assertNotIn("error", result)
                    self.assertEqual(len(result["neighbors"]), 90)
                    self.assertNotIn(
                        dates[80].strftime("%Y-%m-%d"),
                        [row["date"] for row in result["neighbors"]],
                    )
                    json.dumps(result, allow_nan=False)

    @patch("knn_model.db.get_ohlcv_df")
    def test_missing_latest_features_do_not_use_an_older_current_state(self, get_data):
        dates = pd.date_range("2025-01-01", periods=140)
        close = pd.Series(100 + np.arange(140) + np.sin(np.arange(140)), index=dates)
        frame = pd.DataFrame({
            "close": close, "high": close + 2, "low": close - 2,
            "volume": 1000.0 + np.arange(140),
        })
        get_data.side_effect = lambda *args, **kwargs: frame.copy()
        valid = knn_model.compute_knn_lookalike("TEST", k=1)
        self.assertEqual(valid["as_of"], dates[-1].strftime("%Y-%m-%d"))

        frame.loc[dates[-1], "volume"] = np.nan
        with patch("knn_model.NearestNeighbors") as nearest_neighbors:
            result = knn_model.compute_knn_lookalike("TEST", k=1)
        self.assertEqual(result, {"error": "Latest bar has incomplete features for TEST"})
        nearest_neighbors.assert_not_called()

    def test_safe_float_omits_nonfinite_values(self):
        for value in (None, np.nan, np.inf, -np.inf, "inf", "invalid"):
            with self.subTest(value=value):
                self.assertIsNone(knn_model._safe_float(value))
        for value in (0, -1, 1.5, "2.5"):
            self.assertEqual(knn_model._safe_float(value), float(value))

    @patch("knn_model.NearestNeighbors")
    @patch("knn_model._kama")
    @patch("knn_model.db.get_ohlcv_df")
    def test_overflowing_neighbor_return_is_unavailable(
        self, get_data, kama, nearest_neighbors
    ):
        dates = pd.date_range("2025-01-01", periods=140)
        close = pd.Series(100 + np.arange(140) + np.sin(np.arange(140)), index=dates)
        close.iloc[80] = 1e-310
        frame = pd.DataFrame({
            "close": close, "high": close + 2, "low": close - 2,
            "volume": 1000 + np.arange(140),
        })
        get_data.return_value = frame
        kama.side_effect = lambda prices, window: pd.Series(100.0, index=prices.index)
        model = nearest_neighbors.return_value

        def select_overflow_row(current):
            valid = frame[[
                "rsi14", "vol20_ann", "macd_hist", "cci_norm", "vol_ratio",
                "kama_dist_10", "kama_dist_20", "kama_dist_50",
            ]].dropna()
            idx = valid.index.get_loc(dates[80])
            return np.array([[0.0]]), np.array([[idx]])

        model.kneighbors.side_effect = select_overflow_row
        result = knn_model.compute_knn_lookalike("TEST", k=1)
        self.assertEqual(result["neighbors"][0]["date"], "2025-03-22")
        for horizon in (1, 5, 20):
            key = f"fwd_{horizon}d"
            self.assertIsNone(result["neighbors"][0][key])
            self.assertTrue(all(value is None for value in result["summary"][key].values()))
        json.dumps(result, allow_nan=False)

    @patch("knn_model.NearestNeighbors")
    @patch("knn_model._kama")
    @patch("knn_model.db.get_ohlcv_df")
    def test_missing_future_closes_leave_neighbor_outcomes_unavailable(
        self, get_data, kama, nearest_neighbors
    ):
        dates = pd.date_range("2025-01-01", periods=140)
        close = pd.Series(100 + np.arange(140) + np.sin(np.arange(140)), index=dates)
        frame = pd.DataFrame({
            "close": close, "high": close + 2, "low": close - 2,
            "volume": 1000 + np.arange(140),
        })
        frame.loc[dates[100], "close"] = np.nan
        get_data.return_value = frame
        # Keep KAMA finite so this test isolates return endpoint handling.
        kama.side_effect = lambda prices, window: pd.Series(100.0, index=prices.index)
        model = nearest_neighbors.return_value
        # Return every historical feature row so each horizon can be inspected.
        model.kneighbors.side_effect = lambda current: (
            np.zeros((1, len(model.fit.call_args.args[0]))),
            np.arange(len(model.fit.call_args.args[0])).reshape(1, -1),
        )

        result = knn_model.compute_knn_lookalike("TEST", k=1)
        neighbors = {row["date"]: row for row in result["neighbors"]}
        for horizon in (1, 5, 20):
            with self.subTest(horizon=horizon):
                row = neighbors[dates[100 - horizon].strftime("%Y-%m-%d")]
                self.assertIsNone(row[f"fwd_{horizon}d"])
                valid = neighbors[dates[99 - horizon].strftime("%Y-%m-%d")]
                self.assertAlmostEqual(
                    valid[f"fwd_{horizon}d"],
                    close.iloc[99] / close.iloc[99 - horizon] - 1,
                )
        self.assertTrue(pd.isna(frame.loc[dates[101], "vol20_ann"]))
