import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import database as db
import watchlist_filters as wf


class WatchlistFilterTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "wf.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()

        idx = pd.date_range("2024-01-01", periods=80, freq="D")
        close = np.linspace(100, 130, 80)
        volume = np.full(80, 1_000_000.0)
        volume[-1] = 3_000_000.0
        close[-1] = 135.0
        df = pd.DataFrame(
            {
                "open": np.concatenate([close[:-1] - 0.1, [132.0]]),
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": volume,
            },
            index=idx,
        )
        db.add_symbol("HOT")
        db.upsert_ohlcv("HOT", "daily", df)
        db.add_symbol("COLD")
        flat = np.full(80, 50.0)
        df2 = pd.DataFrame(
            {
                "open": flat - 0.1,
                "high": flat + 0.5,
                "low": flat - 0.5,
                "close": flat,
                "volume": np.full(80, 500_000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv("COLD", "daily", df2)

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_catalog_has_fields(self):
        cat = wf.catalog_for_api()
        self.assertGreater(len(cat["fields"]), 20)
        self.assertIn("presets", cat)

    def test_apply_filter_near_high(self):
        out = wf.apply_filter(
            rules=[{"field": "is_near_high", "op": "is_true"}],
            scope="with_data",
            limit=50,
        )
        syms = out["symbols"]
        self.assertIn("HOT", syms)

    def test_compare_between(self):
        self.assertTrue(wf._compare("between", 5, [0, 10]))
        self.assertFalse(wf._compare("between", 15, [0, 10]))


if __name__ == "__main__":
    unittest.main()
