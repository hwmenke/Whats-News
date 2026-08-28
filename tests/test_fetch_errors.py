import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import app as app_module
import data_fetcher as fetcher
import database as db
from data_service.app import app as data_app


class ClassifyYahooErrorTests(unittest.TestCase):
    def test_throttle_from_message(self):
        out = fetcher.classify_yahoo_error("Too Many Requests")
        self.assertEqual(out["code"], "yahoo_throttle")
        self.assertEqual(out["retry_after_sec"], 60)
        self.assertIn("minute", out["error"])
        self.assertEqual(fetcher.fetch_error_http_status(out), 429)

    def test_throttle_from_exception_class_name(self):
        class YFRateLimitError(Exception):
            pass

        out = fetcher.classify_yahoo_error(YFRateLimitError("429 Client Error"))
        self.assertEqual(out["code"], "yahoo_throttle")

    def test_generic_fetch_failure(self):
        out = fetcher.classify_yahoo_error("No data returned for XYZ")
        self.assertEqual(out["code"], "fetch_failed")
        self.assertEqual(fetcher.fetch_error_http_status(out), 400)

    def test_success_status(self):
        self.assertEqual(fetcher.fetch_error_http_status({"daily_rows": 10}), 200)


class FetchAndStoreThrottleTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path_patch = patch.object(db, "DB_PATH", os.path.join(self._tmpdir.name, "t.db"))
        self._path_patch.start()
        db.init_db()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    @patch("data_fetcher.yf.Ticker")
    def test_fetch_and_store_classifies_throttle(self, mock_ticker_cls):
        mock = MagicMock()
        mock.history.side_effect = Exception("Too Many Requests")
        mock_ticker_cls.return_value = mock
        result = fetcher.fetch_and_store("AAPL")
        self.assertEqual(result["symbol"], "AAPL")
        self.assertEqual(result["code"], "yahoo_throttle")
        self.assertIn("error", result)


class FetchEndpointThrottleTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path_patch = patch.object(db, "DB_PATH", os.path.join(self._tmpdir.name, "api.db"))
        self._path_patch.start()
        db.init_db()
        self.client = app_module.app.test_client()
        self.data_client = data_app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    @patch("app.md.fetch_symbol")
    def test_analysis_fetch_returns_429(self, mock_fetch):
        mock_fetch.return_value = {
            "symbol": "MSFT",
            "error": "Yahoo is rate-limiting. Try again in a minute.",
            "code": "yahoo_throttle",
            "retry_after_sec": 60,
        }
        res = self.client.post("/api/fetch/MSFT")
        self.assertEqual(res.status_code, 429)
        body = res.get_json()
        self.assertEqual(body["code"], "yahoo_throttle")
        self.assertIn("minute", body["error"])

    @patch("data_service.app.fetcher.fetch_and_store")
    def test_data_service_fetch_returns_429(self, mock_fetch):
        mock_fetch.return_value = {
            "symbol": "NVDA",
            "error": "Yahoo is rate-limiting. Try again in a minute.",
            "code": "yahoo_throttle",
            "retry_after_sec": 60,
        }
        res = self.data_client.post("/api/fetch/NVDA")
        self.assertEqual(res.status_code, 429)
        self.assertEqual(res.get_json()["code"], "yahoo_throttle")


if __name__ == "__main__":
    unittest.main()
