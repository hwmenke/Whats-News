import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import database as db
import stage_analysis
import setup_scanner


class StageAnalysisTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "stage.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _seed_weekly(self, symbol, closes):
        db.add_symbol(symbol)
        n = len(closes)
        idx = pd.date_range("2023-01-01", periods=n, freq="W")
        arr = np.array(closes, dtype=float)
        df = pd.DataFrame(
            {
                "open": arr - 0.2,
                "high": arr + 1.0,
                "low": arr - 1.0,
                "close": arr,
                "volume": np.full(n, 1e6),
            },
            index=idx,
        )
        db.upsert_ohlcv(symbol, "weekly", df)
        # Minimal daily so setup scanner ready path can run if needed
        daily_idx = pd.date_range("2024-01-01", periods=60, freq="D")
        dclose = np.linspace(arr[-1] * 0.9, arr[-1], 60)
        ddf = pd.DataFrame(
            {
                "open": dclose - 0.1,
                "high": dclose + 0.5,
                "low": dclose - 0.5,
                "close": dclose,
                "volume": np.full(60, 1e6),
            },
            index=daily_idx,
        )
        db.upsert_ohlcv(symbol, "daily", ddf)

    def test_stage2_advancing(self):
        # Rising series well above rising SMA
        closes = list(np.linspace(40, 100, 60))
        self._seed_weekly("ADV", closes)
        out = stage_analysis.classify_stage("ADV")
        self.assertTrue(out["ready"])
        self.assertEqual(out["stage"], 2)

    def test_stage4_declining(self):
        closes = list(np.linspace(100, 40, 60))
        self._seed_weekly("DEC", closes)
        out = stage_analysis.classify_stage("DEC")
        self.assertTrue(out["ready"])
        self.assertEqual(out["stage"], 4)

    def test_setup_families_in_scan(self):
        closes = list(np.linspace(40, 100, 60))
        self._seed_weekly("ADV", closes)
        with patch("setup_scanner.md.list_symbols_with_ohlcv", return_value=["ADV"]):
            out = setup_scanner.scan_setups(symbols=["ADV"], limit=10)
        self.assertIn("families", out)
        self.assertIn("qullamaggie", out["families"])
        self.assertIn("stage", out["families"])
        self.assertTrue(any(r.get("stage") for r in out["results"] if r.get("ready")))


if __name__ == "__main__":
    unittest.main()
