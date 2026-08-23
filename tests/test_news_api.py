import unittest
from unittest.mock import patch, MagicMock

import app as app_module
import database as db


class NewsApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    @patch("app.db.list_symbol_codes")
    def test_get_all_news_empty_watchlist(self, mock_list_symbol_codes):
        mock_list_symbol_codes.return_value = []

        response = self.client.get("/api/news")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["articles"], [])
        self.assertEqual(data["message"], "No symbols in watchlist")

    @patch("app.yf.Ticker")
    @patch("app.db.list_symbol_codes")
    def test_get_all_news_with_articles(self, mock_list_symbol_codes, mock_ticker_class):
        mock_list_symbol_codes.return_value = ["AAPL"]
        
        mock_ticker = MagicMock()
        mock_ticker.news = [
            {
                "content": {
                    "title": "Apple hits new high",
                    "summary": "Apple stock reaches record",
                    "pubDate": "2026-08-21T10:00:00Z",
                    "canonicalUrl": {"url": "https://example.com/apple1"},
                    "provider": {"displayName": "Test News", "url": "https://test.com"}
                }
            }
        ]
        mock_ticker_class.return_value = mock_ticker

        response = self.client.get("/api/news")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["source"], "Yahoo Finance")
        self.assertEqual(data["symbol_count"], 1)
        self.assertEqual(data["article_count"], 1)
        self.assertEqual(len(data["articles"]), 1)
        
        article = data["articles"][0]
        self.assertEqual(article["symbol"], "AAPL")
        self.assertEqual(article["title"], "Apple hits new high")
        self.assertEqual(article["url"], "https://example.com/apple1")
        self.assertEqual(article["provider"], "Test News")

    @patch("app.yf.Ticker")
    @patch("app.db.list_symbol_codes")
    def test_get_all_news_deduplicates_by_url(self, mock_list_symbol_codes, mock_ticker_class):
        mock_list_symbol_codes.return_value = ["AAPL", "MSFT"]
        
        def create_ticker(symbol):
            mock_ticker = MagicMock()
            mock_ticker.news = [
                {
                    "content": {
                        "title": f"Tech news for {symbol}",
                        "summary": "Market update",
                        "pubDate": "2026-08-21T10:00:00Z",
                        "canonicalUrl": {"url": "https://example.com/same-article"},
                        "provider": {"displayName": "Test News", "url": "https://test.com"}
                    }
                }
            ]
            return mock_ticker
        
        mock_ticker_class.side_effect = create_ticker

        response = self.client.get("/api/news")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["article_count"], 1)

    @patch("app.yf.Ticker")
    @patch("app.db.list_symbol_codes")
    def test_get_all_news_no_news_available(self, mock_list_symbol_codes, mock_ticker_class):
        mock_list_symbol_codes.return_value = ["AAPL"]
        
        mock_ticker = MagicMock()
        mock_ticker.news = []
        mock_ticker_class.return_value = mock_ticker

        response = self.client.get("/api/news")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["article_count"], 0)
        self.assertEqual(len(data["articles"]), 0)

    @patch("app.yf.Ticker")
    @patch("app.db.list_symbol_codes")
    def test_get_all_news_handles_errors(self, mock_list_symbol_codes, mock_ticker_class):
        mock_list_symbol_codes.return_value = ["AAPL", "INVALID"]
        
        def create_ticker(symbol):
            mock_ticker = MagicMock()
            if symbol == "AAPL":
                mock_ticker.news = [
                    {
                        "content": {
                            "title": "Apple news",
                            "summary": "Test",
                            "pubDate": "2026-08-21T10:00:00Z",
                            "canonicalUrl": {"url": "https://example.com/apple"},
                            "provider": {"displayName": "Test", "url": "https://test.com"}
                        }
                    }
                ]
            else:
                mock_ticker.news.__getitem__.side_effect = Exception("API error")
                raise Exception("API error")
            return mock_ticker
        
        mock_ticker_class.side_effect = create_ticker

        response = self.client.get("/api/news")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["article_count"], 1)
        self.assertIn("errors", data)
        self.assertEqual(len(data["errors"]), 1)

    @patch("app.yf.Ticker")
    def test_get_symbol_news_with_articles(self, mock_ticker_class):
        mock_ticker = MagicMock()
        mock_ticker.news = [
            {
                "content": {
                    "title": "Apple news",
                    "summary": "Test summary",
                    "pubDate": "2026-08-21T10:00:00Z",
                    "canonicalUrl": {"url": "https://example.com/apple"},
                    "provider": {"displayName": "Test News", "url": "https://test.com"}
                }
            }
        ]
        mock_ticker_class.return_value = mock_ticker

        response = self.client.get("/api/news/AAPL")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["symbol"], "AAPL")
        self.assertEqual(data["source"], "Yahoo Finance")
        self.assertEqual(data["article_count"], 1)
        self.assertEqual(len(data["articles"]), 1)

    @patch("app.yf.Ticker")
    def test_get_symbol_news_no_news(self, mock_ticker_class):
        mock_ticker = MagicMock()
        mock_ticker.news = []
        mock_ticker_class.return_value = mock_ticker

        response = self.client.get("/api/news/AAPL")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["symbol"], "AAPL")
        self.assertEqual(data["message"], "No news available for AAPL")
        self.assertEqual(len(data["articles"]), 0)

    @patch("app.yf.Ticker")
    def test_get_symbol_news_error(self, mock_ticker_class):
        mock_ticker_class.side_effect = Exception("Network error")

        response = self.client.get("/api/news/AAPL")
        data = response.get_json()

        self.assertEqual(response.status_code, 500)
        self.assertEqual(data["symbol"], "AAPL")
        self.assertIn("error", data)
        self.assertEqual(data["error"], "Network error")

    @patch("app.yf.Ticker")
    def test_get_symbol_news_normalizes_symbol(self, mock_ticker_class):
        mock_ticker = MagicMock()
        mock_ticker.news = []
        mock_ticker_class.return_value = mock_ticker

        response = self.client.get("/api/news/aapl")
        data = response.get_json()

        mock_ticker_class.assert_called_once_with("AAPL")
        self.assertEqual(data["symbol"], "AAPL")

    @patch("app.yf.Ticker")
    def test_news_article_uses_clickthrough_url_fallback(self, mock_ticker_class):
        mock_ticker = MagicMock()
        mock_ticker.news = [
            {
                "content": {
                    "title": "Test",
                    "summary": "Test summary",
                    "pubDate": "2026-08-21T10:00:00Z",
                    "clickThroughUrl": {"url": "https://example.com/fallback"},
                    "provider": {"displayName": "Test", "url": "https://test.com"}
                }
            }
        ]
        mock_ticker_class.return_value = mock_ticker

        response = self.client.get("/api/news/AAPL")
        data = response.get_json()

        self.assertEqual(data["articles"][0]["url"], "https://example.com/fallback")

    @patch("app.yf.Ticker")
    def test_news_article_defaults_provider(self, mock_ticker_class):
        mock_ticker = MagicMock()
        mock_ticker.news = [
            {
                "content": {
                    "title": "Test",
                    "pubDate": "2026-08-21T10:00:00Z",
                    "canonicalUrl": {"url": "https://example.com/test"},
                    "provider": {}
                }
            }
        ]
        mock_ticker_class.return_value = mock_ticker

        response = self.client.get("/api/news/AAPL")
        data = response.get_json()

        self.assertEqual(data["articles"][0]["provider"], "Yahoo Finance")
        self.assertEqual(data["articles"][0]["provider_url"], "https://finance.yahoo.com/")


if __name__ == "__main__":
    unittest.main()
