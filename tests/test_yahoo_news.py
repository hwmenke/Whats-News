"""Unit tests for Yahoo news normalization (no live network)."""

import unittest
from unittest.mock import MagicMock

import yahoo_news


class ArticleFromItemTests(unittest.TestCase):
    def test_content_shape_matches_dash_contract(self):
        item = {
            "content": {
                "title": "Apple hits new high",
                "summary": "Apple stock reaches record",
                "pubDate": "2026-08-21T10:00:00Z",
                "canonicalUrl": {"url": "https://example.com/apple1"},
                "provider": {"displayName": "Test News", "url": "https://test.com"},
            }
        }
        article = yahoo_news.article_from_item(item, symbol="AAPL")
        self.assertEqual(article["symbol"], "AAPL")
        self.assertEqual(article["title"], "Apple hits new high")
        self.assertEqual(article["url"], "https://example.com/apple1")
        self.assertEqual(article["provider"], "Test News")
        self.assertEqual(article["provider_url"], "https://test.com")
        self.assertEqual(article["publish_time"], "2026-08-21T10:00:00Z")

    def test_clickthrough_fallback_and_default_provider(self):
        item = {
            "content": {
                "title": "Test",
                "pubDate": "2026-08-21T10:00:00Z",
                "clickThroughUrl": {"url": "https://example.com/fallback"},
                "provider": {},
            }
        }
        article = yahoo_news.article_from_item(item)
        self.assertEqual(article["url"], "https://example.com/fallback")
        self.assertEqual(article["provider"], "Yahoo Finance")
        self.assertEqual(article["provider_url"], "https://finance.yahoo.com/")
        self.assertNotIn("symbol", article)

    def test_legacy_yfinance_shape(self):
        item = {
            "title": "Old format",
            "link": "https://example.com/legacy",
            "publisher": "Reuters",
            "providerPublishTime": 1_724_000_000,
        }
        article = yahoo_news.article_from_item(item, symbol="MSFT")
        self.assertEqual(article["title"], "Old format")
        self.assertEqual(article["url"], "https://example.com/legacy")
        self.assertEqual(article["provider"], "Reuters")
        self.assertTrue(article["publish_time"].startswith("2024-08-18"))
        self.assertEqual(article["symbol"], "MSFT")


class WatchlistNewsTests(unittest.TestCase):
    def test_empty_watchlist(self):
        result = yahoo_news.watchlist_news([])
        self.assertEqual(result["articles"], [])
        self.assertEqual(result["message"], "No symbols in watchlist")

    def test_dedupes_by_url_across_symbols(self):
        def factory(symbol):
            ticker = MagicMock()
            ticker.news = [
                {
                    "content": {
                        "title": f"Tech news for {symbol}",
                        "pubDate": "2026-08-21T10:00:00Z",
                        "canonicalUrl": {"url": "https://example.com/same-article"},
                        "provider": {"displayName": "Test News"},
                    }
                }
            ]
            return ticker

        result = yahoo_news.watchlist_news(["AAPL", "MSFT"], ticker_factory=factory)
        self.assertEqual(result["article_count"], 1)
        self.assertEqual(result["source"], "Yahoo Finance")
        self.assertEqual(result["symbol_count"], 2)


if __name__ == "__main__":
    unittest.main()
