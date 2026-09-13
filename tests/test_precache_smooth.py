"""Tests for the precache/smoothness layer (TTL caches, knobs, prewarm).

Covers: cache hit/miss/refresh + cached flag, TTL expiry, per-request caps
as JSON 400s, prewarm failure tolerance, in-flight dedupe, and the
read-only cache stats endpoint.
"""
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import app as app_module
import precache
import database as db


def _news_item(title, url, pubdate="2026-08-21T10:00:00Z"):
    return {
        "content": {
            "title": title,
            "summary": "summary",
            "pubDate": pubdate,
            "canonicalUrl": {"url": url},
            "provider": {"displayName": "Test", "url": "https://test.com"},
        }
    }


class NewsCacheTests(unittest.TestCase):
    def setUp(self):
        precache.cache_clear()
        self.client = app_module.app.test_client()

    def tearDown(self):
        precache.cache_clear()

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_news_miss_then_hit_with_flag(self, mock_codes, mock_ticker_cls):
        mock_codes.return_value = ["AAPL"]
        mock_ticker = MagicMock()
        mock_ticker.news = [_news_item("t1", "https://example.com/1")]
        mock_ticker_cls.return_value = mock_ticker

        first = self.client.get("/api/news")
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.get_json()["cached"])
        self.assertEqual(first.headers.get("X-Cache"), "MISS")

        # Yahoo now explodes — the second call must be served from cache.
        mock_ticker_cls.side_effect = RuntimeError("yahoo down")
        second = self.client.get("/api/news")
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.get_json()["cached"])
        self.assertEqual(second.headers.get("X-Cache"), "HIT")
        self.assertEqual(second.get_json()["articles"],
                         first.get_json()["articles"])

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_news_refresh_bypass(self, mock_codes, mock_ticker_cls):
        mock_codes.return_value = ["AAPL"]
        first_ticker = MagicMock()
        first_ticker.news = [_news_item("old", "https://example.com/old")]
        mock_ticker_cls.return_value = first_ticker
        self.client.get("/api/news")

        fresh_ticker = MagicMock()
        fresh_ticker.news = [_news_item("new", "https://example.com/new")]
        mock_ticker_cls.return_value = fresh_ticker
        mock_ticker_cls.side_effect = None
        res = self.client.get("/api/news?refresh=1")
        data = res.get_json()
        self.assertFalse(data["cached"])
        self.assertEqual(data["articles"][0]["title"], "new")

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_news_ttl_expiry(self, mock_codes, mock_ticker_cls):
        mock_codes.return_value = ["AAPL"]
        mock_ticker = MagicMock()
        mock_ticker.news = [_news_item("t1", "https://example.com/1")]
        mock_ticker_cls.return_value = mock_ticker
        self.client.get("/api/news")

        # Age the entry out by hand, then confirm a MISS.
        for key in list(precache._caches["news"]._store):
            payload, _exp = precache._caches["news"]._store[key]
            precache._caches["news"]._store[key] = (payload, time.time() - 1)
        res = self.client.get("/api/news")
        self.assertFalse(res.get_json()["cached"])

    @patch("app.yf.Ticker")
    @patch("app.md.list_symbol_codes")
    def test_news_limit_slices_and_validates(self, mock_codes, mock_ticker_cls):
        mock_codes.return_value = ["AAPL"]
        mock_ticker = MagicMock()
        mock_ticker.news = [
            _news_item(f"t{i}", f"https://example.com/{i}",
                       pubdate=f"2026-08-2{i}T10:00:00Z")
            for i in range(1, 4)
        ]
        mock_ticker_cls.return_value = mock_ticker
        res = self.client.get("/api/news?limit=2")
        data = res.get_json()
        self.assertEqual(len(data["articles"]), 2)
        self.assertEqual(data["article_count"], 2)

        bad = self.client.get("/api/news?limit=abc")
        self.assertEqual(bad.status_code, 400)
        self.assertIn("error", bad.get_json())


class ExpensiveEndpointCacheTests(unittest.TestCase):
    def setUp(self):
        precache.cache_clear()
        self.client = app_module.app.test_client()

    def tearDown(self):
        precache.cache_clear()

    def test_knn_k_validation_is_json_400(self):
        res = self.client.get("/api/knn/AAPL?k=banana")
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.get_json())
        res = self.client.get("/api/knn/AAPL?k=500")
        self.assertEqual(res.status_code, 400)

    @patch("app.knn_model.compute_knn_lookalike")
    def test_knn_hit_miss_refresh(self, mock_knn):
        mock_knn.return_value = {"symbol": "AAPL", "k": 5, "neighbors": []}
        first = self.client.get("/api/knn/AAPL?k=5")
        self.assertFalse(first.get_json()["cached"])
        second = self.client.get("/api/knn/AAPL?k=5")
        self.assertTrue(second.get_json()["cached"])
        self.assertEqual(mock_knn.call_count, 1)
        third = self.client.get("/api/knn/AAPL?k=5&refresh=1")
        self.assertFalse(third.get_json()["cached"])
        self.assertEqual(mock_knn.call_count, 2)

    @patch("app.knn_model.compute_knn_lookalike")
    def test_knn_errors_never_cached(self, mock_knn):
        mock_knn.return_value = {"error": "Not enough data for ZZZ"}
        res = self.client.get("/api/knn/ZZZ")
        self.assertEqual(res.status_code, 404)
        self.assertNotIn("cached", res.get_json())
        self.assertEqual(len(precache._caches["knn"]), 0)

    @patch("app.backtester.run_optimization")
    def test_backtest_hit_miss(self, mock_bt):
        mock_bt.return_value = {"symbol": "AAPL", "top10": []}
        first = self.client.get("/api/backtest/AAPL")
        self.assertFalse(first.get_json()["cached"])
        second = self.client.get("/api/backtest/AAPL")
        self.assertTrue(second.get_json()["cached"])
        self.assertEqual(mock_bt.call_count, 1)

    def test_trendscan_param_validation(self):
        res = self.client.get("/api/trend-scan?rsi_period=banana")
        self.assertEqual(res.status_code, 400)
        res = self.client.get("/api/trend-scan?rsi_period=500")
        self.assertEqual(res.status_code, 400)
        res = self.client.get("/api/trend-scan?freq=minutely")
        self.assertEqual(res.status_code, 400)
        res = self.client.get("/api/trend-scan?method=vibes")
        self.assertEqual(res.status_code, 400)

    @patch("app.md.list_symbol_codes")
    @patch("app.adaptive.compute_adaptive_trend")
    @patch("app.md.get_ohlcv_df")
    def test_trendscan_caches_array_body(self, mock_df, mock_trend, mock_codes):
        import pandas as pd
        import numpy as np
        mock_codes.return_value = ["AAPL"]
        idx = pd.date_range("2024-01-01", periods=60, freq="D")
        close = 100 + np.linspace(0, 5, 60)
        mock_df.return_value = pd.DataFrame(
            {"open": close - 0.5, "high": close + 1, "low": close - 1,
             "close": close, "volume": 1e6}, index=idx)
        mock_trend.return_value = {"error": "nope"}
        first = self.client.get("/api/trend-scan")
        self.assertEqual(first.status_code, 200)
        self.assertIsInstance(first.get_json(), list)
        self.assertEqual(first.headers.get("X-Cache"), "MISS")
        second = self.client.get("/api/trend-scan")
        self.assertEqual(second.headers.get("X-Cache"), "HIT")
        self.assertEqual(mock_trend.call_count, 1)

    def test_setups_scan_validation(self):
        res = self.client.get("/api/setups/scan?limit=banana")
        self.assertEqual(res.status_code, 400)
        res = self.client.get("/api/setups/scan?min_score=banana")
        self.assertEqual(res.status_code, 400)
        res = self.client.get("/api/setups/scan?limit=999999")
        self.assertEqual(res.status_code, 400)

    def test_fetch_batch_delay_validation(self):
        res = self.client.post("/api/data-manager/fetch-batch",
                               json={"tickers": ["AAPL"], "delay": "fast"})
        self.assertEqual(res.status_code, 400)
        self.assertIn("error", res.get_json())

    def test_cache_stats_endpoint(self):
        res = self.client.get("/api/cache/stats")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn("ttl_s", data)
        self.assertIn("caps", data)
        self.assertIn("entries", data)

    def test_prewarm_endpoint_kicks_off(self):
        res = self.client.post("/api/cache/prewarm", json={"symbols": 5})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["symbols_cap"], 5)
        bad = self.client.post("/api/cache/prewarm", json={"symbols": "many"})
        self.assertEqual(bad.status_code, 400)


class PrecacheUnitTests(unittest.TestCase):
    def setUp(self):
        precache.cache_clear()

    def tearDown(self):
        precache.cache_clear()

    def test_parse_capped_int(self):
        val, err = precache.parse_capped_int(None, default=7, lo=1, hi=10)
        self.assertEqual((val, err), (7, None))
        val, err = precache.parse_capped_int("3", default=7, lo=1, hi=10)
        self.assertEqual((val, err), (3, None))
        _val, err = precache.parse_capped_int("xx", default=7, lo=1, hi=10)
        self.assertIsNotNone(err)
        _val, err = precache.parse_capped_int("99", default=7, lo=1, hi=10)
        self.assertIsNotNone(err)

    def test_wants_refresh(self):
        self.assertTrue(precache.wants_refresh({"refresh": "1"}))
        self.assertTrue(precache.wants_refresh({"refresh": "yes"}))
        self.assertFalse(precache.wants_refresh({}))
        self.assertFalse(precache.wants_refresh({"refresh": "0"}))

    def test_inflight_dedupe_shares_one_compute(self):
        calls = []
        barrier = threading.Barrier(5)

        def _slow():
            calls.append(1)
            time.sleep(0.2)
            return {"n": 42}

        results = []
        errors = []

        def _worker():
            try:
                barrier.wait(timeout=5)
                results.append(precache.compute_coalesced(("t", "k"), _slow))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 5)
        self.assertTrue(all(r == {"n": 42} for r in results))
        self.assertEqual(len(calls), 1)

    def test_prewarm_failure_tolerance(self):
        with patch("market_data.list_symbols",
                   side_effect=RuntimeError("db gone")):
            summary = precache.prewarm_sync(symbol_cap=5)
        self.assertIn("symbols", summary)
        self.assertTrue(summary["skipped"])

    def test_prewarm_empty_watchlist(self):
        with patch("market_data.list_symbols", return_value=[]), \
             patch("market_data.list_symbols_with_ohlcv", return_value=[]):
            summary = precache.prewarm_sync(symbol_cap=5)
        self.assertIn("empty watchlist", summary["skipped"])

    def test_schedule_background_never_raises(self):
        def _boom():
            raise RuntimeError("boom")

        thread = precache.schedule_background(_boom)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())


class PortfolioCacheTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "p.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        precache.cache_clear()
        self.client = app_module.app.test_client()

    def tearDown(self):
        precache.cache_clear()
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _seed(self, symbol="AAPL", n=80):
        import numpy as np
        import pandas as pd
        db.add_symbol(symbol)
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        close = 100 + np.linspace(0, 10, n)
        df = pd.DataFrame(
            {"open": close - 0.5, "high": close + 1.0, "low": close - 1.0,
             "close": close, "volume": 1_000_000.0}, index=idx)
        db.upsert_ohlcv(symbol, "daily", df)

    def test_portfolio_snapshot_cached_flag(self):
        self._seed()
        first = self.client.get("/api/portfolio/snapshot")
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.get_json()["cached"])
        second = self.client.get("/api/portfolio/snapshot")
        self.assertTrue(second.get_json()["cached"])
        self.assertEqual(second.get_json()["count"],
                         first.get_json()["count"])


if __name__ == "__main__":
    unittest.main()
