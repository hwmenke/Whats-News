"""Monthly bars are resampled from stored daily — not invented prices."""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ["DATA_SERVICE_MODE"] = "embedded"

import data_client
import database as db
import app as app_module


class MonthlyOhlcvTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "m.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_monthly_from_daily_is_month_end_ohlc(self):
        daily = [
            {"date": "2024-01-02", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 100},
            {"date": "2024-01-31", "open": 11, "high": 15, "low": 10, "close": 14, "volume": 200},
            {"date": "2024-02-01", "open": 14, "high": 16, "low": 13, "close": 15, "volume": 50},
            {"date": "2024-02-29", "open": 15, "high": 17, "low": 14, "close": 16, "volume": 75},
        ]
        monthly = data_client.monthly_from_daily(daily)
        self.assertEqual(len(monthly), 2)
        jan = monthly[0]
        self.assertEqual(jan["open"], 10)
        self.assertEqual(jan["high"], 15)
        self.assertEqual(jan["low"], 9)
        self.assertEqual(jan["close"], 14)
        self.assertEqual(jan["volume"], 300)

    def test_ohlcv_monthly_endpoint(self):
        db.add_symbol("AAPL")
        idx = pd.date_range("2024-01-01", periods=45, freq="D")
        frame = pd.DataFrame(
            {
                "open": np.linspace(100, 110, 45),
                "high": np.linspace(101, 111, 45),
                "low": np.linspace(99, 109, 45),
                "close": np.linspace(100.5, 110.5, 45),
                "volume": np.full(45, 1000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv("AAPL", "daily", frame)
        res = self.client.get("/api/ohlcv/AAPL?freq=monthly")
        self.assertEqual(res.status_code, 200)
        rows = res.get_json()
        self.assertGreaterEqual(len(rows), 2)
        self.assertIn("date", rows[0])
        self.assertIn("close", rows[0])

    def test_trend_scan_empty_watchlist_is_200(self):
        res = self.client.get("/api/trend-scan?desk=1")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), [])

    def test_scanner_desk_empty_is_200(self):
        res = self.client.get("/api/scanner?universe=0")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), [])


if __name__ == "__main__":
    unittest.main()
