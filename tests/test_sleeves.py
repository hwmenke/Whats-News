"""Curated Macro sleeves + EMA series on stored close."""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ["DATA_SERVICE_MODE"] = "embedded"

import data_client
import database as db
import ticker_lists as tl
import indicators as ind
import app as app_module


class SleeveApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "sleeves.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_sleeves_are_yahoo_etf_proxies(self):
        ids = {s["id"] for s in tl.MACRO_SLEEVES}
        self.assertIn("core", ids)
        self.assertIn("countries", ids)
        self.assertIn("sectors", ids)
        self.assertGreaterEqual(len(ids), 12)
        core = tl.get_sleeve("core")
        self.assertEqual(core["tickers"], ["SPY", "QQQ", "IWM"])
        self.assertTrue(all(t.isupper() for s in tl.MACRO_SLEEVES for t in s["tickers"]))

    def test_list_and_seed_sleeve(self):
        listed = self.client.get("/api/sleeves")
        self.assertEqual(listed.status_code, 200)
        body = listed.get_json()
        self.assertGreaterEqual(len(body["sleeves"]), 5)
        self.assertIn("ETF", body.get("note", ""))

        seeded = self.client.post("/api/sleeves/core/seed")
        self.assertIn(seeded.status_code, (200, 201))
        data = seeded.get_json()
        self.assertEqual(sorted(data["added"]), ["IWM", "QQQ", "SPY"])
        self.assertEqual(data["group_tag"], "sleeve:core")

        desk = self.client.get("/api/symbols?desk=1").get_json()
        tags = {s["symbol"]: s.get("group_tag") for s in desk}
        self.assertEqual(tags["SPY"], "sleeve:core")

        again = self.client.post("/api/sleeves/unknown/seed")
        self.assertEqual(again.status_code, 404)

    def test_snapshot_empty_desk_is_200(self):
        res = self.client.get("/api/portfolio/snapshot")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json().get("ready_count"), 0)

    def test_indicators_include_ema(self):
        db.add_symbol("SPY")
        idx = pd.date_range("2024-01-01", periods=40, freq="D")
        close = np.linspace(100, 120, 40)
        frame = pd.DataFrame(
            {
                "open": close - 0.2,
                "high": close + 0.4,
                "low": close - 0.4,
                "close": close,
                "volume": np.full(40, 1_000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv("SPY", "daily", frame)
        with patch.object(ind, "db") as md:
            md.get_ohlcv_df.return_value = frame
            pack = ind.compute_indicators("SPY", "daily")
        self.assertIn("ema_10", pack)
        self.assertIn("ema_20", pack)
        self.assertGreater(len(pack["ema_10"]), 10)
        last_ema = pack["ema_10"][-1]["value"]
        self.assertIsNotNone(last_ema)


if __name__ == "__main__":
    unittest.main()
