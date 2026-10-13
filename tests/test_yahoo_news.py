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
    def test_boolean_legacy_timestamps_remain_unavailable(self):
        ticker = MagicMock()
        ticker.news = [
            {"title": "Boolean date", "providerPublishTime": True},
            {"title": "False date", "providerPublishTime": False},
            {"title": "Valid date", "providerPublishTime": 1_724_000_000},
        ]
        factory = lambda symbol: ticker
        watchlist = yahoo_news.watchlist_news(["AAPL"], ticker_factory=factory)
        symbol, status = yahoo_news.symbol_news("AAPL", ticker_factory=factory)
        self.assertEqual(status, 200)
        self.assertNotIn("errors", watchlist)
        for result in (watchlist, symbol):
            self.assertEqual(result["article_count"], 3)
            self.assertEqual(result["articles"][0]["title"], "Valid date")
            self.assertTrue(result["articles"][0]["publish_time"].startswith("2024-08-18"))
            self.assertEqual(
                [article["publish_time"] for article in result["articles"][1:]],
                ["", ""],
            )

    def test_symbol_news_sorts_publication_instants_and_keeps_missing_dates_last(self):
        dates = [
            "2026-08-21T10:00:00+02:00",
            "invalid",
            "2026-08-21T09:30:00Z",
            "2026-08-21T05:00:00-04:00",
            "",
            "2026-08-21T09:15:00",
        ]
        ticker = MagicMock()
        ticker.news = [
            {"content": {"title": f"Headline {index}", "pubDate": date}}
            for index, date in enumerate(dates)
        ]
        result, status = yahoo_news.symbol_news(
            "aapl", ticker_factory=lambda symbol: ticker
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["symbol"], "AAPL")
        self.assertEqual(result["article_count"], len(dates))
        self.assertEqual(
            [article["publish_time"] for article in result["articles"]],
            [dates[2], dates[5], dates[3], dates[0], dates[1], dates[4]],
        )
        self.assertEqual(
            [article["title"] for article in result["articles"]],
            ["Headline 2", "Headline 5", "Headline 3", "Headline 0",
             "Headline 1", "Headline 4"],
        )

    def test_malformed_urls_preserve_headlines_and_valid_fallbacks(self):
        for malformed in ([], {"unexpected": "value"}, 42, True, "   "):
            with self.subTest(url=malformed):
                ticker = MagicMock()
                ticker.news = [
                    {"content": {
                        "title": "Modern fallback",
                        "canonicalUrl": {"url": malformed},
                        "clickThroughUrl": {"url": "https://example.com/modern"},
                    }},
                    {"title": "Legacy fallback", "link": malformed,
                     "url": "https://example.com/legacy"},
                    {"title": "No valid URL", "link": malformed},
                    {"title": "Valid headline", "link": "https://example.com/valid"},
                ]
                factory = lambda symbol: ticker
                watchlist = yahoo_news.watchlist_news(["AAPL"], ticker_factory=factory)
                symbol, status = yahoo_news.symbol_news("AAPL", ticker_factory=factory)
                self.assertEqual(status, 200)
                self.assertNotIn("errors", watchlist)
                for result in (watchlist, symbol):
                    self.assertEqual(result["article_count"], 4)
                    self.assertEqual(
                        [article["url"] for article in result["articles"]],
                        ["https://example.com/modern", "https://example.com/legacy",
                         "", "https://example.com/valid"],
                    )

    def test_malformed_entries_are_skipped_without_losing_real_headlines(self):
        ticker = MagicMock()
        ticker.news = [
            None,
            "invalid entry",
            42,
            [],
            {},
            {"title": "Real headline", "link": "https://example.com/real"},
        ]
        factory = lambda symbol: ticker
        watchlist = yahoo_news.watchlist_news(["AAPL"], ticker_factory=factory)
        symbol, status = yahoo_news.symbol_news("AAPL", ticker_factory=factory)
        self.assertEqual(status, 200)
        self.assertNotIn("errors", watchlist)
        for result in (watchlist, symbol):
            self.assertEqual(result["article_count"], 1)
            self.assertEqual(result["articles"][0]["title"], "Real headline")
            self.assertEqual(result["articles"][0]["url"], "https://example.com/real")

    def test_sorts_publication_instants_across_timezones(self):
        dates = [
            "2026-08-21T10:00:00+02:00",
            "invalid",
            "2026-08-21T09:30:00Z",
            "2026-08-21T05:00:00-04:00",
            "",
            "2026-08-21T09:15:00",
        ]
        ticker = MagicMock()
        ticker.news = [
            {"content": {"title": "Headline", "pubDate": date}}
            for date in dates
        ]
        result = yahoo_news.watchlist_news(
            ["AAPL"], ticker_factory=lambda symbol: ticker
        )
        self.assertNotIn("errors", result)
        self.assertEqual(result["article_count"], len(dates))
        self.assertEqual(
            [article["publish_time"] for article in result["articles"]],
            [dates[2], dates[5], dates[3], dates[0], dates[1], dates[4]],
        )

    def test_invalid_legacy_timestamp_preserves_ticker_headlines(self):
        for timestamp in (float("inf"), 10**100, "invalid", -1, None):
            with self.subTest(timestamp=timestamp):
                ticker = MagicMock()
                ticker.news = [
                    {
                        "title": "Headline with invalid date",
                        "link": "https://example.com/invalid-date",
                        "providerPublishTime": timestamp,
                    },
                    {
                        "title": "Headline with valid date",
                        "link": "https://example.com/valid-date",
                        "providerPublishTime": 1_724_000_000,
                    },
                ]
                result = yahoo_news.watchlist_news(
                    ["AAPL"], ticker_factory=lambda symbol: ticker
                )
                self.assertNotIn("errors", result)
                self.assertEqual(result["article_count"], 2)
                self.assertEqual(result["articles"][0]["title"], "Headline with valid date")
                self.assertEqual(result["articles"][1]["publish_time"], "")
                self.assertEqual(
                    result["articles"][1]["title"], "Headline with invalid date"
                )

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
