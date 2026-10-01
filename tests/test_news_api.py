import os
import unittest
os.environ.setdefault("DATA_SERVICE_MODE", "embedded")
from unittest.mock import patch, MagicMock

import app as app_module
import news_service


class NewsApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        news_service.clear_cache()

    @patch("app.md.list_symbol_codes")
    def test_get_all_news_empty_watchlist(self, mock_list_symbol_codes):
        mock_list_symbol_codes.return_value = []

        response = self.client.get("/api/news")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["articles"], [])
        self.assertEqual(data["message"], "No symbols in watchlist")
        self.assertEqual(data["symbol_count"], 0)
        self.assertEqual(data["article_count"], 0)
        self.assertEqual(data["source"], "Yahoo Finance")
        self.assertIn("fetched_at", data)

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
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
    @patch("app.md.list_symbol_codes")
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
        self.assertEqual(data["articles"][0]["symbol"], "AAPL")
        self.assertEqual(data["articles"][0]["symbols"], ["AAPL", "MSFT"])

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
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
    @patch("app.md.list_symbol_codes")
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


def _news_item(title, url="https://example.com/a", **extra):
    content = {
        "title": title,
        "summary": "Summary",
        "pubDate": "2026-08-21T10:00:00Z",
        "provider": {"displayName": "Test News", "url": "https://test.com"},
    }
    if url:
        content["canonicalUrl"] = {"url": url}
    content.update(extra)
    return {"content": content}


def _ticker_with(items):
    ticker = MagicMock()
    ticker.news = items
    return ticker


class NewsEnhancementTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()
        news_service.clear_cache()

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_multi_symbol_merge_keeps_primary_symbol(self, mock_symbols, mock_ticker_class):
        mock_symbols.return_value = ["MSFT", "AAPL"]
        mock_ticker_class.side_effect = lambda sym: _ticker_with(
            [_news_item(f"Big tech rally lifts {sym}", url="https://example.com/shared")]
        )

        data = self.client.get("/api/news").get_json()

        self.assertEqual(data["article_count"], 1)
        article = data["articles"][0]
        self.assertEqual(article["symbols"], ["MSFT", "AAPL"])
        self.assertEqual(article["symbol"], "MSFT")

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_dedupes_by_normalized_title_when_url_missing(self, mock_symbols, mock_ticker_class):
        mock_symbols.return_value = ["AAPL", "MSFT"]
        titles = {"AAPL": "Chip Stocks Surge!", "MSFT": "chip stocks surge"}
        mock_ticker_class.side_effect = lambda sym: _ticker_with([_news_item(titles[sym], url="")])

        data = self.client.get("/api/news").get_json()

        self.assertEqual(data["article_count"], 1)
        self.assertEqual(data["articles"][0]["symbols"], ["AAPL", "MSFT"])

    @patch("app.yf.Ticker")
    def test_earnings_headline_tagged(self, mock_ticker_class):
        mock_ticker_class.return_value = _ticker_with(
            [_news_item("Apple earnings beat estimates, raises guidance")]
        )

        data = self.client.get("/api/news/AAPL").get_json()

        self.assertEqual(data["articles"][0]["tags"], ["earnings", "guidance"])

    def test_tag_headline_event_types(self):
        cases = {
            "Analyst upgrades XYZ to Buy": ["upgrade"],
            "Bank downgrades XYZ": ["downgrade"],
            "XYZ to acquire ABC in $2B deal": ["mna"],
            "XYZ announces public offering": ["offering"],
            "FDA approves XYZ drug": ["fda"],
            "Stocks drift sideways": [],
        }
        for title, expected in cases.items():
            self.assertEqual(news_service.tag_headline(title), expected, title)

    @patch("app.yf.Ticker")
    def test_thumbnail_included_when_present(self, mock_ticker_class):
        thumb = {"originalUrl": "https://img.test/o.jpg", "resolutions": [
            {"url": "https://img.test/170.jpg", "width": 170, "height": 128, "tag": "170x128"},
            {"url": "https://img.test/50.jpg", "width": 50, "height": 50, "tag": "50x50"},
        ]}
        mock_ticker_class.return_value = _ticker_with([
            _news_item("With image", url="https://example.com/1", thumbnail=thumb),
            _news_item("No image", url="https://example.com/2"),
        ])

        articles = self.client.get("/api/news/AAPL").get_json()["articles"]
        by_title = {a["title"]: a for a in articles}

        self.assertEqual(by_title["With image"]["thumbnail"], "https://img.test/170.jpg")
        self.assertNotIn("thumbnail", by_title["No image"])

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_second_call_served_from_cache(self, mock_symbols, mock_ticker_class):
        mock_symbols.return_value = ["AAPL", "MSFT"]
        mock_ticker_class.side_effect = lambda sym: _ticker_with(
            [_news_item(f"{sym} headline", url=f"https://example.com/{sym}")]
        )

        first = self.client.get("/api/news").get_json()
        second = self.client.get("/api/news").get_json()

        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(mock_ticker_class.call_count, 2)
        self.assertEqual(second["article_count"], 2)
        self.assertIn("fetched_at", second)

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_cache_shared_between_endpoints(self, mock_symbols, mock_ticker_class):
        mock_symbols.return_value = ["AAPL"]
        mock_ticker_class.return_value = _ticker_with([_news_item("Apple headline")])

        self.client.get("/api/news")
        single = self.client.get("/api/news/AAPL").get_json()

        self.assertTrue(single["cached"])
        self.assertEqual(mock_ticker_class.call_count, 1)

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_refresh_bypasses_cache(self, mock_symbols, mock_ticker_class):
        mock_symbols.return_value = ["AAPL"]
        mock_ticker_class.return_value = _ticker_with([_news_item("Apple headline")])

        self.client.get("/api/news")
        data = self.client.get("/api/news?refresh=1").get_json()

        self.assertFalse(data["cached"])
        self.assertEqual(mock_ticker_class.call_count, 2)

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_throttle_error_surfaced(self, mock_symbols, mock_ticker_class):
        mock_symbols.return_value = ["AAPL", "MSFT"]

        def create_ticker(sym):
            if sym == "MSFT":
                raise Exception("Too Many Requests. Rate limited.")
            return _ticker_with([_news_item("Apple headline")])

        mock_ticker_class.side_effect = create_ticker

        data = self.client.get("/api/news").get_json()

        self.assertEqual(data["article_count"], 1)
        self.assertTrue(data["rate_limited"])
        self.assertEqual(data["errors"][0]["symbol"], "MSFT")
        self.assertEqual(data["errors"][0]["code"], "yahoo_throttle")
        self.assertIn("rate-limiting", data["errors"][0]["error"])

    @patch("app.yf.Ticker")
    def test_symbol_throttle_returns_429(self, mock_ticker_class):
        mock_ticker_class.side_effect = Exception("429 Too Many Requests")

        response = self.client.get("/api/news/AAPL")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.get_json()["code"], "yahoo_throttle")

    @patch("app.yf.Ticker")
    def test_errors_are_not_cached(self, mock_ticker_class):
        mock_ticker_class.side_effect = Exception("boom")
        self.client.get("/api/news/AAPL")
        mock_ticker_class.side_effect = None
        mock_ticker_class.return_value = _ticker_with([_news_item("Recovered")])

        data = self.client.get("/api/news/AAPL").get_json()

        self.assertEqual(data["article_count"], 1)
        self.assertFalse(data["cached"])


if __name__ == "__main__":
    unittest.main()
