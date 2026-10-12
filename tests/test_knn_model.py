"""Regression coverage for historical lookalike outcomes."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import knn_model


class KnnModelTests(unittest.TestCase):
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
