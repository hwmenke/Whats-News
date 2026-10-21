"""Fresh / empty finance.db — the Simulator failure mode.

A leftover empty SQLite file (connect without init_db) used to make
health 200 while /api/symbols and /api/news blew up with
``no such table: symbols``. These checks lock the startup contract:
init_db + first connection create tables; watchlist/news/chart stay 2xx.
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ["DATA_SERVICE_MODE"] = "embedded"

import database as db
import data_client
import app as app_module


def _make_empty_sqlite(path):
    """Create a real SQLite file with zero user tables (the Mac worktree case)."""
    conn = sqlite3.connect(path)
    conn.close()
    with sqlite3.connect(path) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    assert tables == [], tables


class FreshDbStartupTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "finance.db")
        _make_empty_sqlite(self.db_path)
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_init_db_creates_symbols_on_empty_file(self):
        self.assertNotIn("symbols", self._raw_tables())
        db.init_db()
        tables = db.schema_tables()
        self.assertIn("symbols", tables)
        self.assertIn("ohlcv", tables)
        db.init_db()  # idempotent
        self.assertEqual(db.list_symbols(), [])

    def test_get_connection_recovers_empty_file_without_explicit_init(self):
        self.assertNotIn("symbols", self._raw_tables())
        self.assertEqual(db.list_symbol_codes(), [])
        self.assertIn("symbols", db.schema_tables())

    @patch("yahoo_news.yf.Ticker")
    def test_health_symbols_news_ohlcv_on_empty_file(self, mock_ticker_class):
        mock_ticker = MagicMock()
        mock_ticker.news = []
        mock_ticker_class.return_value = mock_ticker
        app_module.ensure_local_schema()

        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        body = health.get_json()
        self.assertTrue(body["ok"])
        self.assertTrue(body.get("schema_ok"))
        self.assertEqual(body.get("symbol_count"), 0)
        self.assertIn("symbols", db.schema_tables())

        listed = self.client.get("/api/symbols")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.get_json(), [])

        empty_news = self.client.get("/api/news")
        self.assertEqual(empty_news.status_code, 200)
        self.assertEqual(empty_news.get_json().get("articles"), [])
        self.assertEqual(empty_news.get_json().get("message"), "No symbols in watchlist")

        added = self.client.post("/api/symbols", json={"symbol": "AAPL"})
        self.assertIn(added.status_code, (200, 201))
        self.assertTrue(added.get_json().get("added"))

        again = self.client.get("/api/symbols")
        self.assertEqual(again.status_code, 200)
        self.assertEqual([s["symbol"] for s in again.get_json()], ["AAPL"])

        news = self.client.get("/api/news")
        self.assertEqual(news.status_code, 200)
        payload = news.get_json()
        self.assertIsInstance(payload.get("articles"), list)
        # Live Yahoo may return headlines; empty feed is also honest. Never 500.

        bars = self.client.get("/api/ohlcv/AAPL")
        self.assertEqual(bars.status_code, 404)
        self.assertIn("Fetch", bars.get_json().get("error", ""))

    @patch("data_fetcher.fetch_and_store")
    def test_chart_fetch_does_not_500_on_fresh_schema(self, mock_fetch):
        db.init_db()
        db.add_symbol("AAPL")
        mock_fetch.return_value = {
            "symbol": "AAPL",
            "daily_rows": 10,
            "weekly_rows": 2,
        }
        res = self.client.post("/api/fetch/AAPL")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["daily_rows"], 10)
        mock_fetch.assert_called_once()

    def _raw_tables(self):
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        return [r[0] for r in rows]


if __name__ == "__main__":
    unittest.main()
