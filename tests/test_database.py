import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import database as db
import app as app_module


class DatabaseScaleTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "test_finance.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_wal_mode_enabled(self):
        stats = db.get_db_stats()
        self.assertEqual(stats["journal_mode"].lower(), "wal")

    def test_bulk_add_symbols(self):
        result = db.add_symbols(["aapl", "MSFT", "aapl", "GOOG", ""])
        self.assertEqual(result["added"], ["AAPL", "MSFT", "GOOG"])
        self.assertEqual(result["skipped"], [])

        again = db.add_symbols(["AAPL", "TSLA"])
        self.assertEqual(again["added"], ["TSLA"])
        self.assertEqual(again["skipped"], ["AAPL"])
        self.assertEqual(len(db.list_symbol_codes()), 4)

    def test_upsert_ohlcv_vectorized_and_idempotent(self):
        idx = pd.date_range("2024-01-01", periods=250, freq="D")
        frame = pd.DataFrame(
            {
                "open": np.linspace(100, 125, 250),
                "high": np.linspace(101, 126, 250),
                "low": np.linspace(99, 124, 250),
                "close": np.linspace(100.5, 125.5, 250),
                "volume": np.full(250, 1_000_000.0),
            },
            index=idx,
        )
        db.add_symbol("AAPL")
        n1 = db.upsert_ohlcv("AAPL", "daily", frame)
        n2 = db.upsert_ohlcv("AAPL", "daily", frame)
        self.assertEqual(n1, 250)
        self.assertEqual(n2, 250)

        rows = db.get_ohlcv("AAPL", "daily", limit=500)
        self.assertEqual(len(rows), 250)
        self.assertEqual(rows[0]["date"], "2024-01-01")
        self.assertEqual(
            db.get_latest_ohlcv_date("AAPL", "daily"),
            idx[-1].strftime("%Y-%m-%d"),
        )
        self.assertEqual(
            db.get_max_ohlcv_date("daily"),
            idx[-1].strftime("%Y-%m-%d"),
        )

    def test_many_tickers_roundtrip(self):
        tickers = [f"T{i:04d}" for i in range(200)]
        result = db.add_symbols(tickers)
        self.assertEqual(len(result["added"]), 200)

        idx = pd.date_range("2024-01-01", periods=30, freq="D")
        frame = pd.DataFrame(
            {
                "open": np.full(30, 10.0),
                "high": np.full(30, 11.0),
                "low": np.full(30, 9.0),
                "close": np.full(30, 10.5),
                "volume": np.full(30, 1000.0),
            },
            index=idx,
        )
        for sym in tickers[:50]:
            db.upsert_ohlcv(sym, "daily", frame)

        stats = db.get_db_stats()
        self.assertEqual(stats["symbol_count"], 200)
        self.assertEqual(stats["daily_rows"], 50 * 30)
        self.assertGreaterEqual(stats["size_bytes"], 0)

        codes = db.list_symbol_codes()
        self.assertEqual(len(codes), 200)
        self.assertEqual(codes[0], "T0000")

    def test_optimize_db_returns_stats(self):
        db.add_symbol("MSFT")
        out = db.optimize_db()
        self.assertEqual(out["symbol_count"], 1)
        self.assertEqual(out["journal_mode"].lower(), "wal")

    def test_universe_symbols_and_desk_filter(self):
        mapping = {
            "AAPL": ["sp500"],
            "ARCH": ["russell2000"],
        }
        result = db.add_universe_symbols(mapping)
        self.assertIn("ARCH", result["added"])
        self.assertEqual(len(db.list_symbol_codes()), 2)

        desk = db.list_desk_symbols()
        desk_syms = {r["symbol"] for r in desk}
        self.assertNotIn("ARCH", desk_syms)

        db.add_symbol("MSFT")
        desk2 = db.list_desk_symbols()
        self.assertIn("MSFT", {r["symbol"] for r in desk2})

        ok = db.promote_to_desk("ARCH")
        self.assertTrue(ok)
        desk3 = {r["symbol"] for r in db.list_desk_symbols()}
        self.assertIn("ARCH", desk3)

    def test_list_symbols_with_ohlcv_min_bars(self):
        db.add_symbols(["A", "B"])
        idx = pd.date_range("2024-01-01", periods=35, freq="D")
        frame = pd.DataFrame(
            {
                "open": np.full(35, 10.0),
                "high": np.full(35, 11.0),
                "low": np.full(35, 9.0),
                "close": np.full(35, 10.5),
                "volume": np.full(35, 1000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv("A", "daily", frame)
        have = db.list_symbols_with_ohlcv("daily", min_bars=30)
        self.assertEqual(have, ["A"])


class DbApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "api_finance.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_bulk_symbols_endpoint(self):
        response = self.client.post(
            "/api/symbols",
            json={"symbols": ["aapl", "MSFT", "AAPL"]},
        )
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertEqual(data["added"], ["AAPL", "MSFT"])
        self.assertEqual(data["skipped"], [])

    def test_db_stats_endpoint(self):
        db.add_symbols(["AAPL", "MSFT"])
        response = self.client.get("/api/db/stats")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["symbol_count"], 2)
        self.assertEqual(data["journal_mode"].lower(), "wal")

    def test_db_optimize_endpoint(self):
        response = self.client.post("/api/db/optimize")
        self.assertEqual(response.status_code, 200)
        self.assertIn("symbol_count", response.get_json())

    def test_universe_registry(self):
        response = self.client.get("/api/universe/registry")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertGreaterEqual(len(data.get("indices", [])), 5)

    def test_setups_catalog(self):
        response = self.client.get("/api/setups/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertIn("EP", response.get_json().get("setups", {}))

    def test_promote_symbol_endpoint(self):
        db.add_universe_symbols({"PROMO": ["sp500"]})
        response = self.client.post("/api/symbols/PROMO/promote")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json().get("promoted"))

    def test_symbols_desk_filter(self):
        db.add_universe_symbols({"U1": ["sp500"]})
        db.add_symbol("DESK1")
        all_resp = self.client.get("/api/symbols")
        desk_resp = self.client.get("/api/symbols?desk=1")
        self.assertEqual(len(all_resp.get_json()), 2)
        self.assertEqual(len(desk_resp.get_json()), 1)
        self.assertEqual(desk_resp.get_json()[0]["symbol"], "DESK1")


if __name__ == "__main__":
    unittest.main()
