"""SPEC 25/27 Fractal D — estimator sanity + honest API (no invented D)."""

import math
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ["DATA_SERVICE_MODE"] = "embedded"

import data_client
import database as db
import fractal_scan as fs
import app as app_module


def _gbm(n, seed, mu=0.0, sigma=0.01):
    rng = np.random.default_rng(seed)
    r = rng.normal(mu, sigma, n)
    return 100.0 * np.exp(np.cumsum(r))


class FractalMathTests(unittest.TestCase):
    def test_random_walk_mean_near_one_point_five(self):
        d65 = []
        d130 = []
        for seed in range(20):
            px = _gbm(500, seed, mu=0.0, sigma=0.012)
            a = fs.hurst_D(px[-65:])
            b = fs.hurst_D(px[-130:])
            self.assertIsNotNone(a)
            self.assertIsNotNone(b)
            d65.append(a)
            d130.append(b)
        mean65 = float(np.mean(d65))
        mean130 = float(np.mean(d130))
        self.assertLess(abs(mean65 - 1.50), 0.08, f"mean D65={mean65}")
        self.assertLess(abs(mean130 - 1.50), 0.08, f"mean D130={mean130}")

    def test_strong_trend_low_d(self):
        rng = np.random.default_rng(7)
        r = 0.005 + rng.normal(0, 0.0004, 200)
        px = 100.0 * np.exp(np.cumsum(r))
        d65 = fs.hurst_D(px[-65:])
        d130 = fs.hurst_D(px[-130:])
        self.assertIsNotNone(d65)
        self.assertIsNotNone(d130)
        self.assertGreaterEqual(d65, 0.85)
        self.assertLessEqual(d65, 1.25)
        self.assertGreaterEqual(d130, 0.85)
        self.assertLessEqual(d130, 1.25)

    def test_choppy_high_d(self):
        rng = np.random.default_rng(3)
        r = np.zeros(260)
        for t in range(1, 260):
            r[t] = -0.97 * r[t - 1] + rng.normal(0, 0.008)
        px = 100.0 * np.exp(np.cumsum(r))
        d130 = fs.hurst_D(px[-130:])
        self.assertIsNotNone(d130)
        self.assertGreaterEqual(d130, 1.70)

    def test_flat_low_d_is_not_fragile(self):
        rng = np.random.default_rng(1)
        r = 0.0004 + rng.normal(0, 0.00015, 80)
        px = 100.0 * np.exp(np.cumsum(r))
        pack = fs.window_pack(px, 65)
        self.assertIsNotNone(pack["d"])
        self.assertLessEqual(pack["d"], 1.40)
        self.assertLessEqual(abs(pack["move"]), 5.0)
        self.assertNotEqual(pack["read"], "FRAGILE")
        self.assertEqual(fs.reading(1.20, 3.0), "orderly")
        self.assertEqual(fs.reading(1.20, 8.0), "FRAGILE")

    def test_short_or_invalid_is_null(self):
        self.assertIsNone(fs.hurst_D([100.0]))
        self.assertIsNone(fs.hurst_D([]))
        self.assertIsNone(fs.hurst_D([100.0, math.nan, 101.0]))
        self.assertIsNone(fs.measure_symbol("ZZ", closes=[100.0]))
        gappy = list(_gbm(80, 2, mu=0.0, sigma=0.01))
        gappy[-3] = math.nan
        pack = fs.window_pack(gappy, 65)
        self.assertIsNone(pack["d"])
        self.assertIsNone(pack["move"])


class FractalApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "fractal.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _put_closes(self, symbol, closes, start="2020-01-02"):
        db.add_symbol(symbol)
        idx = pd.bdate_range(start, periods=len(closes))
        close = np.asarray(closes, dtype=float)
        frame = pd.DataFrame(
            {
                "open": close - 0.1,
                "high": close + 0.3,
                "low": close - 0.3,
                "close": close,
                "volume": np.full(len(close), 1_000_000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv(symbol, "daily", frame)

    def test_status_available_in_repo(self):
        body = self.client.get("/api/fractal/status").get_json()
        self.assertTrue(body["available"])
        self.assertIn("SPEC 25/27", body["source"])
        self.assertNotIn("win_rate", body)
        self.assertNotIn("70%", str(body))

    def test_scan_empty_or_null_without_bars(self):
        res = self.client.get("/api/fractal/scan?desk=1")
        self.assertEqual(res.status_code, 200)
        payload = res.get_json()
        self.assertTrue(payload["available"])
        for row in payload.get("rows") or []:
            self.assertIsNone(row.get("d_65d"))
            self.assertIsNone(row.get("d_130d"))
        keys = {str(k).lower() for k in payload}
        self.assertNotIn("d_hat", keys)
        self.assertNotIn("70%", str(payload).lower())

    def test_scan_real_d_from_stored_closes(self):
        px = _gbm(220, 11, mu=0.0, sigma=0.01)
        self._put_closes("SPY", px)
        scan = self.client.get("/api/fractal/scan?desk=1").get_json()
        spy = next(r for r in scan["rows"] if r["symbol"] == "SPY")
        self.assertIsNotNone(spy["d_65d"])
        self.assertIsNotNone(spy["d_130d"])
        self.assertIsNotNone(spy["move_65d"])
        self.assertIsInstance(spy["read"], str)


if __name__ == "__main__":
    unittest.main()
