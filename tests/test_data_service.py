import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

# Analysis tests talk to DB through market_data in embedded mode (no HTTP).
os.environ["DATA_SERVICE_MODE"] = "embedded"

import database as db
import data_client
import market_data as md
import app as app_module
from data_service.app import app as data_app


class EmbeddedMarketDataTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "test.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_list_and_ohlcv_roundtrip(self):
        md.add_symbol("AAPL")
        codes = md.list_symbol_codes()
        self.assertIn("AAPL", codes)
        self.assertEqual(md.get_ohlcv("AAPL"), [])

    def test_analysis_health(self):
        client = app_module.app.test_client()
        res = client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["service"], "whats-news")
        self.assertEqual(body["layer"], "analysis")
        self.assertEqual(body["data_mode"], "embedded")


class DataServiceApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "data.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        self.client = data_app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_health(self):
        res = self.client.get("/api/health")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ok"])
        self.assertEqual(res.get_json()["service"], "data")

    def test_symbols_and_codes(self):
        res = self.client.post("/api/symbols", json={"symbol": "msft"})
        self.assertEqual(res.status_code, 201)
        codes = self.client.get("/api/symbols/codes").get_json()
        self.assertEqual(codes["symbols"], ["MSFT"])

    def test_ohlcv_missing(self):
        res = self.client.get("/api/ohlcv/AAPL")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), [])

    @patch("data_service.app.fetcher.fetch_and_store")
    def test_fetch_symbol(self, mock_fetch):
        mock_fetch.return_value = {"symbol": "AAPL", "daily_rows": 10, "weekly_rows": 2}
        res = self.client.post("/api/fetch/AAPL")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["daily_rows"], 10)

    def test_ticker_lists(self):
        res = self.client.get("/api/data-manager/ticker-lists")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.get_json(), list)


class AnalysisProxiesDataTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "prox.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_add_symbol_via_analysis_app(self):
        res = self.client.post("/api/symbols", json={"symbol": "GOOG"})
        self.assertIn(res.status_code, (200, 201))
        symbols = self.client.get("/api/symbols").get_json()
        self.assertTrue(any(s["symbol"] == "GOOG" for s in symbols))

    def test_ohlcv_validation_still_on_analysis_app(self):
        res = self.client.get("/api/ohlcv/AAPL?limit=abc")
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
