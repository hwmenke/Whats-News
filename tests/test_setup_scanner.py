import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import database as db
import setup_scanner


class SetupScannerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "setup_scan.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()

        idx = pd.date_range("2024-01-01", periods=60, freq="D")
        self.frame = pd.DataFrame(
            {
                "open": np.linspace(100, 130, 60),
                "high": np.linspace(101, 135, 60),
                "low": np.linspace(99, 128, 60),
                "close": np.linspace(100.5, 132, 60),
                "volume": np.full(60, 2_000_000.0),
            },
            index=idx,
        )
        db.add_symbol("TEST1")
        db.upsert_ohlcv("TEST1", "daily", self.frame)

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_scan_setups_returns_catalog(self):
        with patch("setup_scanner.md.list_symbols_with_ohlcv", return_value=["TEST1"]):
            out = setup_scanner.scan_setups(limit=10)
        self.assertIn("setup_catalog", out)
        self.assertIn("EP", out["setup_catalog"])
        self.assertEqual(out["scanned"], 1)
        self.assertGreaterEqual(out["count"], 0)

    def test_scan_filters_by_setup_tag(self):
        fake_row = {
            "symbol": "TEST1",
            "ready": True,
            "setups": ["EP", "NEAR_HIGH"],
            "setup_score": 2,
            "change_pct": 1.0,
        }
        with patch("setup_scanner._scan_one_setup", return_value=fake_row):
            out = setup_scanner.scan_setups(symbols=["TEST1"], setup_filter="EP")
        self.assertEqual(out["count"], 1)
        with patch("setup_scanner._scan_one_setup", return_value=fake_row):
            out2 = setup_scanner.scan_setups(symbols=["TEST1"], setup_filter="DARVAS_BOX")
        self.assertEqual(out2["count"], 0)


if __name__ == "__main__":
    unittest.main()
