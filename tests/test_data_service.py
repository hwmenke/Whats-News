import json
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
        self.assertEqual(res.status_code, 404)

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

    @patch("data_service.app.fetcher.fetch_and_store")
    def test_refresh_passes_overlap_and_preserves_default(self, mock_fetch):
        db.add_symbol("AAPL")
        mock_fetch.return_value = {"symbol": "AAPL"}
        for body, expected in ((None, 3), ({}, 3), ({"overlap_days": 0}, 0),
                               ({"overlap_days": 7}, 7)):
            with self.subTest(body=body):
                mock_fetch.reset_mock()
                response = self.client.post("/api/refresh", json=body)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), [{"symbol": "AAPL"}])
                mock_fetch.assert_called_once_with("AAPL", overlap_days=expected)

    @patch("data_service.app.fetcher.fetch_and_store")
    def test_refresh_rejects_invalid_overlap_before_fetching(self, mock_fetch):
        db.add_symbol("AAPL")
        for value in (-1, True, False, None, "7", 1.5, [], {}):
            with self.subTest(value=value):
                response = self.client.post("/api/refresh", json={"overlap_days": value})
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())
        response = self.client.post("/api/refresh", json=[7])
        self.assertEqual(response.status_code, 400)
        mock_fetch.assert_not_called()

    def test_http_refresh_sends_overlap_to_service(self):
        with patch.object(data_client, "DATA_SERVICE_MODE", "http"), \
                patch.object(data_client, "_request", return_value=[]) as request:
            self.assertEqual(data_client.refresh_all(overlap_days=7), [])
        request.assert_called_once_with(
            "POST", "/api/refresh", body={"overlap_days": 7}, timeout=600.0
        )

    def test_desk_query_hides_universe_archive(self):
        db.add_symbol("AAPL")
        db.add_universe_symbols({"ZZUNIV": ["sp500"]})
        all_syms = {s["symbol"] for s in self.client.get("/api/symbols").get_json()}
        desk = {s["symbol"] for s in self.client.get("/api/symbols?desk=1").get_json()}
        self.assertIn("AAPL", all_syms)
        self.assertIn("ZZUNIV", all_syms)
        self.assertIn("AAPL", desk)
        self.assertNotIn("ZZUNIV", desk)

    def test_news_empty_watchlist(self):
        res = self.client.get("/api/news")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["articles"], [])
        self.assertEqual(res.get_json()["message"], "No symbols in watchlist")

    @patch("yahoo_news.yf.Ticker")
    def test_news_matches_analysis_contract(self, mock_ticker_class):
        db.add_symbol("AAPL")
        mock_ticker = MagicMock()
        mock_ticker.news = [
            {
                "content": {
                    "title": "Apple hits new high",
                    "summary": "Apple stock reaches record",
                    "pubDate": "2026-08-21T10:00:00Z",
                    "canonicalUrl": {"url": "https://example.com/apple1"},
                    "provider": {"displayName": "Test News", "url": "https://test.com"},
                }
            }
        ]
        mock_ticker_class.return_value = mock_ticker
        res = self.client.get("/api/news")
        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data["source"], "Yahoo Finance")
        self.assertEqual(data["articles"][0]["symbol"], "AAPL")
        self.assertEqual(data["articles"][0]["title"], "Apple hits new high")

    @patch("yahoo_news.yf.Ticker")
    def test_symbol_news(self, mock_ticker_class):
        mock_ticker = MagicMock()
        mock_ticker.news = []
        mock_ticker_class.return_value = mock_ticker
        res = self.client.get("/api/news/aapl")
        data = res.get_json()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(data["symbol"], "AAPL")
        mock_ticker_class.assert_called_once_with("AAPL")


class SymbolInputValidationTests(unittest.TestCase):
    def test_invalid_inputs_are_rejected_before_watchlist_writes(self):
        for application, target in ((app_module.app, "app.md"),
                                    (data_app, "data_service.app.db")):
            client = application.test_client()
            with patch(f"{target}.add_symbol") as single, patch(f"{target}.add_symbols") as bulk:
                bodies = [None, [], ["AAPL"], "AAPL", 7, True,
                          *({"symbol": value} for value in (None, 7, True, [], {})),
                          *({"symbols": value} for value in (None, False, "AAPL", {})),
                          *({"symbols": ["AAPL", value]} for value in (None, 7, True, [], {}))]
                for body in bodies:
                    with self.subTest(app=application.name, body=body):
                        response = client.post("/api/symbols", data=json.dumps(body),
                                               content_type="application/json")
                        self.assertEqual(response.status_code, 400)
                        self.assertIn("error", response.get_json())
                single.assert_not_called()
                bulk.assert_not_called()

    def test_valid_bulk_strings_remain_normalized_and_deduplicated(self):
        for application in (app_module.app, data_app):
            with tempfile.TemporaryDirectory() as directory, patch.object(
                db, "DB_PATH", os.path.join(directory, "symbols.db")
            ), patch.object(data_client, "DATA_SERVICE_MODE", "embedded"):
                db.init_db()
                client = application.test_client()
                response = client.post("/api/symbols", json={"symbols": [" aapl ", "AAPL", "", "msft"]})
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.get_json()["added"], ["AAPL", "MSFT"])
                self.assertEqual(db.list_symbol_codes(), ["AAPL", "MSFT"])
                response = client.post("/api/symbols", json={"symbols": []})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json()["added"], [])


class SymbolGroupValidationTests(unittest.TestCase):
    def test_malformed_json_returns_json_errors_without_group_writes(self):
        for application, target in ((app_module.app, "app.md"),
                                    (data_app, "data_service.app.db")):
            client = application.test_client()
            with patch(f"{target}.set_symbol_group") as write:
                for body in ('', '{', '{"group_tag": "tech"',
                             '{"group_tag": "tech",}', 'null trailing'):
                    with self.subTest(app=application.name, body=body):
                        response = client.put("/api/symbols/aapl/group", data=body,
                                              content_type="application/json")
                        self.assertEqual(response.status_code, 400)
                        self.assertTrue(response.is_json)
                        self.assertIn("error", response.get_json())
                write.assert_not_called()

    def test_invalid_inputs_are_rejected_before_group_writes(self):
        for application, target in ((app_module.app, "app.md"),
                                    (data_app, "data_service.app.db")):
            client = application.test_client()
            with patch(f"{target}.set_symbol_group") as write:
                bodies = [None, [], ["tech"], "tech", 7, False,
                          *({"group_tag": value} for value in (None, 7, True, [], {}))]
                for body in bodies:
                    with self.subTest(app=application.name, body=body):
                        response = client.put("/api/symbols/aapl/group", data=json.dumps(body),
                                              content_type="application/json")
                        self.assertEqual(response.status_code, 400)
                        self.assertIn("error", response.get_json())
                write.assert_not_called()

    def test_valid_tags_are_trimmed_and_can_be_cleared(self):
        for application in (app_module.app, data_app):
            with tempfile.TemporaryDirectory() as directory, patch.object(
                db, "DB_PATH", os.path.join(directory, "groups.db")
            ), patch.object(data_client, "DATA_SERVICE_MODE", "embedded"):
                db.init_db()
                db.add_symbol("AAPL")
                client = application.test_client()
                for body, expected in (({"group_tag": "  tech  "}, "tech"),
                                       ({"group_tag": ""}, ""), ({}, "")):
                    with self.subTest(app=application.name, body=body):
                        response = client.put("/api/symbols/aapl/group", json=body)
                        self.assertEqual(response.status_code, 200)
                        self.assertEqual(db.list_symbols()[0]["group_tag"], expected)


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
