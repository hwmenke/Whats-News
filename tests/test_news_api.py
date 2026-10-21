import os
import unittest
os.environ.setdefault("DATA_SERVICE_MODE", "embedded")
from unittest.mock import patch, MagicMock

import app as app_module
import news_service


class _OfflineNewsMixin:
    """Keep unit tests off the network: no RSS fallback, no backoff sleeps."""

    def setUp(self):
        self.client = app_module.app.test_client()
        news_service.clear_cache()
        self._retry = news_service.RETRY_DELAYS
        self._interval = news_service.MIN_INTERVAL_SEC
        news_service.RETRY_DELAYS = ()
        news_service.MIN_INTERVAL_SEC = 0
        self._rss = patch("news_service._fetch_yahoo_rss", return_value=[])
        self.rss = self._rss.start()

    def tearDown(self):
        self._rss.stop()
        news_service.RETRY_DELAYS = self._retry
        news_service.MIN_INTERVAL_SEC = self._interval


def _rss_article(symbol, title, url="https://finance.yahoo.com/rss-story"):
    return {
        "symbol": symbol,
        "symbols": [symbol],
        "title": title,
        "summary": "RSS summary",
        "url": url,
        "publish_time": "2026-10-07T14:00:00+00:00",
        "provider": "Yahoo Finance",
        "provider_url": "https://finance.yahoo.com/",
        "tags": [],
        "feed": "yahoo_rss",
    }


class NewsApiTests(_OfflineNewsMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()

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


class NewsEnhancementTests(_OfflineNewsMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()

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

    @patch("app.yf.Ticker")
    def test_throttle_backoff_then_yfinance_success(self, mock_ticker_class):
        news_service.RETRY_DELAYS = (0, 0)
        calls = {"n": 0}

        def create_ticker(symbol):
            calls["n"] += 1
            if calls["n"] < 3:
                raise Exception("429 Too Many Requests")
            return _ticker_with([_news_item("Recovered after backoff")])

        mock_ticker_class.side_effect = create_ticker
        data = self.client.get("/api/news/AAPL").get_json()

        self.assertEqual(calls["n"], 3)
        self.assertEqual(data["article_count"], 1)
        self.assertEqual(data["feeds"], ["yfinance"])
        self.rss.assert_not_called()

    @patch("app.yf.Ticker")
    def test_empty_yfinance_falls_back_to_rss(self, mock_ticker_class):
        mock_ticker_class.return_value = _ticker_with([])
        self.rss.return_value = [_rss_article("AAPL", "Apple headline from RSS")]

        data = self.client.get("/api/news/AAPL").get_json()

        self.assertEqual(data["article_count"], 1)
        self.assertEqual(data["articles"][0]["title"], "Apple headline from RSS")
        self.assertEqual(data["articles"][0]["feed"], "yahoo_rss")
        self.assertEqual(data["feeds"], ["yahoo_rss"])
        self.assertEqual(data["source"], "Yahoo Finance")
        self.rss.assert_called()

    @patch("app.yf.Ticker")
    def test_throttled_yfinance_falls_back_to_rss(self, mock_ticker_class):
        mock_ticker_class.side_effect = Exception("Too Many Requests. Rate limited.")
        self.rss.return_value = [_rss_article("AAPL", "RSS after throttle")]

        response = self.client.get("/api/news/AAPL")
        data = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["article_count"], 1)
        self.assertEqual(data["feeds"], ["yahoo_rss"])
        self.assertNotIn("error", data)

    @patch("app.yf.Ticker")
    def test_unsafe_urls_are_dropped(self, mock_ticker_class):
        mock_ticker_class.return_value = _ticker_with([
            _news_item("Script link", url="javascript:alert(1)",
                       provider={"displayName": "Evil", "url": "javascript:alert(2)"}),
            _news_item("Data link", url="data:text/html,<script>alert(3)</script>"),
            _news_item("Good link", url="https://example.com/good"),
        ])

        articles = self.client.get("/api/news/AAPL").get_json()["articles"]
        by_title = {a["title"]: a for a in articles}

        self.assertEqual(by_title["Script link"]["url"], "")
        self.assertEqual(by_title["Script link"]["provider_url"], "https://finance.yahoo.com/")
        self.assertEqual(by_title["Data link"]["url"], "")
        self.assertEqual(by_title["Good link"]["url"], "https://example.com/good")

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_throttled_refresh_keeps_cached_headlines(self, mock_symbols, mock_ticker_class):
        mock_symbols.return_value = ["AAPL"]
        mock_ticker_class.return_value = _ticker_with([_news_item("Cached Apple headline")])
        self.client.get("/api/news")

        mock_ticker_class.side_effect = Exception("429 Too Many Requests")
        data = self.client.get("/api/news?refresh=1").get_json()

        self.assertEqual(data["article_count"], 1)
        self.assertEqual(data["articles"][0]["title"], "Cached Apple headline")
        self.assertTrue(data["stale"])
        self.assertTrue(data["errors"][0]["stale"])
        self.assertTrue(data["rate_limited"])

        single = self.client.get("/api/news/AAPL?refresh=1")
        self.assertEqual(single.status_code, 200)
        self.assertEqual(single.get_json()["article_count"], 1)
        self.assertTrue(single.get_json()["stale"])

    def test_parse_rss_tolerates_bad_dates_and_unsafe_links(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>Bad date story</title>
            <link>javascript:alert(1)</link>
            <description>&amp;lt;script&amp;gt;alert(1)&amp;lt;/script&amp;gt;Body</description>
            <pubDate>not a date</pubDate>
          </item>
          <item>
            <title>Good story</title>
            <link>https://finance.yahoo.com/good</link>
            <pubDate>Wed, 07 Oct 2026 14:45:22 +0000</pubDate>
          </item>
        </channel></rss>"""
        articles = news_service._parse_rss_feed(xml, "AAPL")
        self.assertEqual([a["title"] for a in articles], ["Bad date story", "Good story"])
        self.assertEqual(articles[0]["publish_time"], "")
        self.assertEqual(articles[0]["url"], "")
        self.assertNotIn("<script>", articles[0]["summary"])
        self.assertEqual(articles[1]["url"], "https://finance.yahoo.com/good")

    def test_parse_rss_feed_maps_pubdate(self):
        xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>Apple earnings beat &amp; raises outlook</title>
            <link>https://finance.yahoo.com/story</link>
            <description>Quarterly &lt;b&gt;results&lt;/b&gt; were strong.</description>
            <pubDate>Wed, 07 Oct 2026 14:45:22 +0000</pubDate>
          </item>
        </channel></rss>"""
        articles = news_service._parse_rss_feed(xml, "AAPL")
        self.assertEqual(len(articles), 1)
        article = articles[0]
        self.assertEqual(article["symbol"], "AAPL")
        self.assertEqual(article["feed"], "yahoo_rss")
        self.assertIn("earnings", article["tags"])
        self.assertEqual(article["publish_time"], "2026-10-07T14:45:22+00:00")
        self.assertNotIn("<b>", article["summary"])
        self.assertIn("results", article["summary"])


if __name__ == "__main__":
    unittest.main()
