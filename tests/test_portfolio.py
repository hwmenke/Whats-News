import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import app as app_module
import database as db
import portfolio


class PortfolioSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "p.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _seed(self, symbol="AAPL", n=80):
        db.add_symbol(symbol)
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        close = 100 + np.linspace(0, 10, n) + np.sin(np.linspace(0, 6, n)) * 2
        df = pd.DataFrame(
            {
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": np.full(n, 1_000_000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv(symbol, "daily", df)

    def test_snapshot_ready(self):
        self._seed()
        snap = portfolio.snapshot_symbol("AAPL")
        self.assertTrue(snap["ready"])
        self.assertIn(snap["regime"], ("uptrend", "downtrend", "range"))
        self.assertIsNotNone(snap["rsi14"])
        self.assertIsNotNone(snap["stop_long_1_5atr"])

    def test_portfolio_endpoint(self):
        self._seed("AAPL")
        self._seed("MSFT", n=90)
        res = self.client.get("/api/portfolio/snapshot")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["ready_count"], 2)
        self.assertEqual(len(data["tape"]), 2)
        ranks = {r["symbol"]: r["rs_rank_21d"] for r in data["symbols"] if r.get("ready")}
        self.assertEqual(sorted(ranks.values()), [1, 2])
        self.assertIn(data["symbols"][0].get("alert"), (None, "RSI_OB", "RSI_OS"))

    def test_pm_desk_endpoint(self):
        self._seed("AAPL")
        res = self.client.get("/api/pm-desk/AAPL")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ready"])

    def test_pm_desk_missing(self):
        db.add_symbol("ZZZ")
        res = self.client.get("/api/pm-desk/ZZZ")
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
