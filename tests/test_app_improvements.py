import os
import unittest
os.environ.setdefault("DATA_SERVICE_MODE", "embedded")
from unittest.mock import patch, MagicMock

import app as app_module


def _article(title, url):
    return {
        "content": {
            "title": title,
            "summary": "summary",
            "pubDate": "2026-08-21T10:00:00Z",
            "canonicalUrl": {"url": url},
            "provider": {"displayName": "Test", "url": "https://test.com"},
        }
    }


class KnnValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_knn_k_must_be_integer(self):
        response = self.client.get("/api/knn/AAPL?k=abc")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "k must be an integer"})

    def test_knn_k_out_of_range(self):
        for bad in ("0", "-3", "101"):
            response = self.client.get(f"/api/knn/AAPL?k={bad}")
            self.assertEqual(response.status_code, 400, bad)
            self.assertIn("error", response.get_json())

    @patch("app.knn_model.compute_knn_lookalike")
    def test_knn_valid_k_passes_through(self, mock_knn):
        mock_knn.return_value = {"symbol": "AAPL", "neighbors": []}
        response = self.client.get("/api/knn/AAPL?k=5")
        self.assertEqual(response.status_code, 200)
        mock_knn.assert_called_once_with("AAPL", k=5)

    @patch("app.knn_model.compute_knn_lookalike")
    def test_knn_unexpected_error_is_json_500(self, mock_knn):
        mock_knn.side_effect = RuntimeError("boom")
        response = self.client.get("/api/knn/AAPL")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {"error": "boom"})


class BacktestErrorTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    @patch("app.backtester.run_optimization")
    def test_backtest_unexpected_error_is_json_500(self, mock_bt):
        mock_bt.side_effect = RuntimeError("calc failed")
        response = self.client.get("/api/backtest/AAPL")
        self.assertEqual(response.status_code, 500)
        data = response.get_json()
        self.assertIn("error", data)
        self.assertIn("calc failed", data["error"])

    @patch("app.backtester.run_optimization")
    def test_backtest_error_dict_is_404(self, mock_bt):
        mock_bt.return_value = {"error": "No data. Fetch the symbol first."}
        response = self.client.get("/api/backtest/AAPL")
        self.assertEqual(response.status_code, 404)


class TrendScanValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_trend_scan_rsi_period_must_be_integer(self):
        response = self.client.get("/api/trend-scan?rsi_period=abc")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "rsi_period must be an integer"})

    def test_trend_scan_rsi_period_out_of_range(self):
        for bad in ("1", "0", "101"):
            response = self.client.get(f"/api/trend-scan?rsi_period={bad}")
            self.assertEqual(response.status_code, 400, bad)

    @patch("app.md.list_symbol_codes")
    def test_trend_scan_empty_watchlist(self, mock_codes):
        mock_codes.return_value = []
        response = self.client.get("/api/trend-scan?rsi_period=14")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), [])


class FetchBatchValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    @patch("app.data_client.use_embedded", return_value=True)
    def test_fetch_batch_bad_delay_is_400(self, _mock_embedded):
        response = self.client.post(
            "/api/data-manager/fetch-batch",
            json={"tickers": ["AAPL"], "delay": "fast"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "delay must be a number"})


class UniverseValidationTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_universe_archive_bad_delay_is_400(self):
        response = self.client.post("/api/universe/archive", json={"delay": "lots"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "delay must be a number"})

    def test_universe_archive_bad_limit_is_400(self):
        response = self.client.post("/api/universe/archive", json={"limit": "many"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "limit must be an integer"})

    def test_universe_refresh_bad_delay_is_400(self):
        response = self.client.post("/api/universe/refresh", json={"delay": "soon"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "delay must be a number"})


class NewsCacheTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        app_module._news_cache.clear()

    def tearDown(self):
        app_module._news_cache.clear()

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_all_news_second_call_served_from_cache(self, mock_codes, mock_ticker_cls):
        mock_codes.return_value = ["AAPL"]
        ticker = MagicMock()
        ticker.news = [_article("Apple hits new high", "https://example.com/a1")]
        mock_ticker_cls.return_value = ticker

        first = self.client.get("/api/news")
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.get_json().get("cached"))

        second = self.client.get("/api/news")
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json().get("cached"))
        self.assertEqual(second.get_json()["article_count"], 1)
        # Yahoo hit only once — the second call came from cache.
        self.assertEqual(mock_ticker_cls.call_count, 1)

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_all_news_refresh_bypass_refetches(self, mock_codes, mock_ticker_cls):
        mock_codes.return_value = ["AAPL"]
        ticker = MagicMock()
        ticker.news = [_article("Apple hits new high", "https://example.com/a1")]
        mock_ticker_cls.return_value = ticker

        self.client.get("/api/news")
        refetched = self.client.get("/api/news?refresh=1")
        self.assertEqual(refetched.status_code, 200)
        self.assertFalse(refetched.get_json().get("cached"))
        self.assertEqual(mock_ticker_cls.call_count, 2)

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_all_news_cache_keyed_by_symbol_set(self, mock_codes, mock_ticker_cls):
        mock_codes.return_value = ["AAPL"]
        ticker = MagicMock()
        ticker.news = [_article("Apple news", "https://example.com/a1")]
        mock_ticker_cls.return_value = ticker
        self.client.get("/api/news")

        mock_codes.return_value = ["AAPL", "MSFT"]
        ticker2 = MagicMock()
        ticker2.news = [_article("MSFT news", "https://example.com/m1")]
        mock_ticker_cls.return_value = ticker2
        changed = self.client.get("/api/news")
        self.assertFalse(changed.get_json().get("cached"))


if __name__ == "__main__":
    unittest.main()
