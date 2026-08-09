"""
Tests for the What's News adapter — the drop-in that points the dashboard at
the archive. Offline: the downloader is stubbed, as everywhere else.
"""

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yahoo_db import downloader as ydl                       # noqa: E402
from yahoo_db import whats_news as wn                        # noqa: E402
from yahoo_db.db import STATUS_DELISTED                      # noqa: E402


def make_bars(dates, close=100.0):
    index = pd.to_datetime(dates)
    return pd.DataFrame(
        {
            "Open": [close] * len(index),
            "High": [close + 1] * len(index),
            "Low": [close - 1] * len(index),
            "Close": [close] * len(index),
            "Adj Close": [close * 0.99] * len(index),
            "Volume": [1000.0] * len(index),
            "Dividends": [0.0] * len(index),
            "Stock Splits": [0.0] * len(index),
        },
        index=index,
    )


class AdapterTestCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.mkdtemp(prefix="wn_test_")
        self.addCleanup(self._cleanup, directory)
        wn.configure(db_path=Path(directory) / "market.db")
        self.store = wn.store()

    def _cleanup(self, directory):
        import shutil
        if wn._store is not None:
            wn._store.close()
        wn._store = None
        wn._cfg = None
        shutil.rmtree(directory, ignore_errors=True)


class WatchlistTests(AdapterTestCase):
    def test_add_list_and_group(self):
        self.assertTrue(wn.add_symbol("aapl", name="Apple Inc."))
        self.assertFalse(wn.add_symbol("AAPL"))     # already watched

        wn.set_symbol_group("AAPL", " tech ")
        rows = wn.list_symbols()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # Exactly the shape the dashboard's own database.py returned.
        for key in ("id", "symbol", "name", "sector", "added_at",
                    "last_fetch", "group_tag", "sort_order"):
            self.assertIn(key, row)
        self.assertEqual(row["symbol"], "AAPL")
        self.assertEqual(row["name"], "Apple Inc.")
        self.assertEqual(row["group_tag"], "tech")

    def test_added_symbol_joins_the_universe(self):
        wn.add_symbol("NVDA")
        row = self.store.conn.execute(
            "SELECT sources FROM tickers WHERE symbol='NVDA'").fetchone()
        self.assertIsNotNone(row)
        self.assertIn("watchlist", row["sources"])

    def test_remove_keeps_the_price_history(self):
        # The dashboard's own remove_symbol deleted bars. Here they may be the
        # only copy of a dead company's history, so removal must not touch them.
        wn.add_symbol("ENRNQ")
        self.store.upsert_prices("ENRNQ", "1d", make_bars(["2001-11-28"]))
        wn.remove_symbol("ENRNQ")

        self.assertEqual(wn.list_symbols(), [])
        kept = self.store.conn.execute(
            "SELECT COUNT(*) FROM prices WHERE symbol='ENRNQ'").fetchone()[0]
        self.assertEqual(kept, 1)

    def test_list_symbols_shows_only_the_watchlist(self):
        # The archive holds far more than the sidebar can render.
        self.store.upsert_tickers([{"symbol": f"S{i}", "source": "nasdaq"}
                                   for i in range(500)])
        wn.add_symbol("S1")
        self.assertEqual([r["symbol"] for r in wn.list_symbols()], ["S1"])

    def test_last_fetch_comes_from_the_archive_log(self):
        wn.add_symbol("AAPL")
        self.assertIsNone(wn.list_symbols()[0]["last_fetch"])
        self.store.log_fetch("AAPL", "1d", "ok", rows=10)
        self.assertIsNotNone(wn.list_symbols()[0]["last_fetch"])

    def test_sector_prefers_the_profile(self):
        wn.add_symbol("AAPL")
        self.store.upsert_profile("AAPL", {"sector": "Technology",
                                           "quoteType": "EQUITY"})
        self.assertEqual(wn.list_symbols()[0]["sector"], "Technology")


class SearchTests(AdapterTestCase):
    def setUp(self):
        super().setUp()
        self.store.upsert_tickers([
            {"symbol": "AAPL", "name": "Apple Inc.", "source": "s"},
            {"symbol": "AAPU", "name": "Leveraged Apple", "source": "s"},
            {"symbol": "GOOG", "name": "Alphabet", "source": "s"},
            {"symbol": "ENRNQ", "name": "Enron Corp", "source": "s",
             "status": STATUS_DELISTED},
        ])

    def test_exact_match_ranks_first(self):
        found = [r["symbol"] for r in wn.search_symbols("AAPL")]
        self.assertEqual(found[0], "AAPL")

    def test_matches_on_name_too(self):
        self.assertIn("GOOG", [r["symbol"] for r in wn.search_symbols("alphabet")])

    def test_delisted_can_be_included_or_excluded(self):
        self.assertIn("ENRNQ", [r["symbol"] for r in wn.search_symbols("enron")])
        self.assertEqual(
            wn.search_symbols("enron", include_delisted=False), [])

    def test_blank_query_returns_nothing(self):
        self.assertEqual(wn.search_symbols("  "), [])


class BarsTests(AdapterTestCase):
    def setUp(self):
        super().setUp()
        # Six weeks of weekdays.
        self.dates = pd.bdate_range("2024-01-01", periods=30)
        self.store.upsert_prices("AAPL", "1d", make_bars(self.dates))

    def test_get_ohlcv_shape_matches_the_dashboard_contract(self):
        rows = wn.get_ohlcv("AAPL", "daily", limit=5)
        self.assertEqual(len(rows), 5)
        for key in ("date", "open", "high", "low", "close", "volume"):
            self.assertIn(key, rows[0])
        # Newest `limit` bars, returned oldest-first.
        self.assertEqual(rows[-1]["date"], self.dates[-1].strftime("%Y-%m-%d"))
        self.assertLess(rows[0]["date"], rows[-1]["date"])

    def test_weekly_is_resampled_from_daily(self):
        # The archive stores only 1d, but the dashboard's weekly toggle must
        # still work without a second download pass.
        stored = self.store.conn.execute(
            "SELECT COUNT(*) FROM prices WHERE interval='1wk'").fetchone()[0]
        self.assertEqual(stored, 0)

        weekly = wn.get_ohlcv("AAPL", "weekly", limit=10)
        self.assertTrue(0 < len(weekly) < 30)
        first = weekly[0]
        self.assertEqual(first["high"], 101.0)
        self.assertEqual(first["low"], 99.0)
        # A week aggregates several days of volume.
        self.assertGreater(max(w["volume"] for w in weekly), 1000.0)

    def test_stored_weekly_bars_win_over_resampling(self):
        self.store.upsert_prices("AAPL", "1wk", make_bars(["2024-02-02"], 500.0))
        weekly = wn.get_ohlcv("AAPL", "weekly", limit=10)
        self.assertEqual(len(weekly), 1)
        self.assertEqual(weekly[0]["close"], 500.0)

    def test_unknown_symbol_is_empty_not_an_error(self):
        self.assertEqual(wn.get_ohlcv("NOPE", "daily"), [])
        self.assertTrue(wn.get_ohlcv_df("NOPE", "daily").empty)

    def test_latest_date_and_recency(self):
        self.assertEqual(wn.get_latest_ohlcv_date("AAPL", "daily"),
                         self.dates[-1].strftime("%Y-%m-%d"))
        self.assertFalse(wn.is_recently_fetched("AAPL"))
        self.store.log_fetch("AAPL", "1d", "ok", rows=30)
        self.assertTrue(wn.is_recently_fetched("AAPL"))

    def test_get_ohlcv_df_is_datetime_indexed(self):
        df = wn.get_ohlcv_df("AAPL", "daily", limit=10)
        self.assertIsInstance(df.index, pd.DatetimeIndex)
        self.assertTrue(df.index.is_monotonic_increasing)
        for col in ("open", "high", "low", "close", "volume"):
            self.assertIn(col, df.columns)


class FetchTests(AdapterTestCase):
    def setUp(self):
        super().setUp()
        self._original = ydl.yf.download

        def fake_download(**kwargs):
            wanted = [t for t in kwargs["tickers"] if t == "AAPL"]
            if not wanted:
                return pd.DataFrame()
            frame = make_bars(pd.bdate_range("2024-01-01", periods=20))
            return pd.concat({"AAPL": frame}, axis=1)

        ydl.yf.download = fake_download

        class NoTicker:
            def __init__(self, symbol):
                pass

            def history(self, **kwargs):
                return pd.DataFrame()

        self._original_ticker = ydl.yf.Ticker
        ydl.yf.Ticker = NoTicker
        self.addCleanup(self._restore)

    def _restore(self):
        ydl.yf.download = self._original
        ydl.yf.Ticker = self._original_ticker

    def test_fetch_and_store_returns_the_expected_keys(self):
        result = wn.fetch_and_store("AAPL")
        for key in ("symbol", "name", "sector", "daily_rows", "weekly_rows"):
            self.assertIn(key, result)
        self.assertNotIn("error", result)
        self.assertEqual(result["symbol"], "AAPL")
        self.assertEqual(result["daily_rows"], 20)
        self.assertTrue(0 < result["weekly_rows"] < 20)
        self.assertEqual(len(wn.get_ohlcv("AAPL", "daily", limit=100)), 20)

    def test_failure_reports_an_error_key(self):
        result = wn.fetch_and_store("NOSUCH")
        self.assertIn("error", result)
        self.assertEqual(result["symbol"], "NOSUCH")

    def test_fetch_registers_the_symbol_in_the_universe(self):
        wn.fetch_and_store("AAPL")
        row = self.store.conn.execute(
            "SELECT symbol FROM tickers WHERE symbol='AAPL'").fetchone()
        self.assertIsNotNone(row)

    def test_full_history_accepts_a_start_date(self):
        result = wn.fetch_full_history("AAPL", start="2010-01-01")
        self.assertEqual(result["symbol"], "AAPL")
        self.assertNotIn("error", result)


class DropInCompatibilityTests(AdapterTestCase):
    def test_exposes_every_name_the_dashboard_calls(self):
        # app.py calls these on the database module and the fetcher module; a
        # missing one is an AttributeError at runtime, in a route, in prod.
        for name in ("init_db", "list_symbols", "add_symbol", "remove_symbol",
                     "set_symbol_group", "get_ohlcv", "get_ohlcv_df",
                     "update_last_fetch", "update_symbol_info",
                     "get_latest_ohlcv_date", "is_recently_fetched",
                     "upsert_ohlcv", "fetch_and_store", "fetch_full_history"):
            self.assertTrue(callable(getattr(wn, name, None)), name)

    def test_signatures_match_the_modules_it_replaces(self):
        import inspect
        import database
        import data_fetcher

        for module, names in ((database, ("list_symbols", "add_symbol",
                                          "remove_symbol", "set_symbol_group",
                                          "get_ohlcv", "get_ohlcv_df",
                                          "get_latest_ohlcv_date",
                                          "is_recently_fetched")),
                              (data_fetcher, ("fetch_and_store",
                                              "fetch_full_history"))):
            for name in names:
                original = inspect.signature(getattr(module, name))
                replacement = inspect.signature(getattr(wn, name))
                self.assertEqual(
                    list(original.parameters), list(replacement.parameters),
                    f"{module.__name__}.{name} parameters drifted")

    def test_update_last_fetch_is_a_harmless_no_op(self):
        wn.add_symbol("AAPL")
        wn.update_last_fetch("AAPL")        # must not raise


# The real proof of "plug and play": boot the actual Flask app with the two
# module aliases in place and hit its routes. It runs in a subprocess because
# importing app.py has import-time side effects and swaps entries in
# sys.modules — neither belongs in this process. Skipped when the dashboard's
# own dependencies are not installed, since they are not yahoo_db's.
FLASK_SMOKE = r"""
import sys, tempfile, pathlib, json
sys.path.insert(0, %(repo)r)
import pandas as pd
from yahoo_db import whats_news as wn

tmp = pathlib.Path(tempfile.mkdtemp())
wn.configure(db_path=tmp / "market.db")
st = wn.store()
idx = pd.bdate_range("2010-01-04", periods=400)
st.upsert_prices("AAPL", "1d", pd.DataFrame({
    "Open": [100.0] * len(idx), "High": [101.0] * len(idx),
    "Low": [99.0] * len(idx), "Close": [100.0] * len(idx),
    "Adj Close": [99.0] * len(idx), "Volume": [1e6] * len(idx)}, index=idx))
st.upsert_tickers([{"symbol": "AAPL", "name": "Apple Inc.", "source": "s"}])
wn.add_symbol("AAPL")

sys.modules["database"] = wn
sys.modules["data_fetcher"] = wn
import app as flask_app

client = flask_app.app.test_client()
out = {}
for key, route in (("symbols", "/api/symbols"),
                   ("daily", "/api/ohlcv/AAPL?freq=daily&limit=3"),
                   ("weekly", "/api/ohlcv/AAPL?freq=weekly&limit=3")):
    r = client.get(route)
    out[key] = (r.status_code, len(r.get_json() or []))
print(json.dumps(out))
"""


def _dashboard_importable() -> bool:
    import importlib.util
    return all(importlib.util.find_spec(m) is not None
               for m in ("flask", "flask_cors", "ta", "sklearn"))


class FlaskIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(_dashboard_importable(),
                         "dashboard dependencies not installed")
    def test_dashboard_routes_serve_from_the_archive(self):
        import subprocess
        repo = str(Path(__file__).resolve().parent.parent)
        proc = subprocess.run(
            [sys.executable, "-c", FLASK_SMOKE % {"repo": repo}],
            capture_output=True, text=True, timeout=180, cwd=repo)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])

        import json
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        self.assertEqual(result["symbols"][0], 200)
        self.assertEqual(result["symbols"][1], 1)
        self.assertEqual(result["daily"], [200, 3])
        # Weekly is derived from the daily bars, with nothing stored at 1wk.
        self.assertEqual(result["weekly"], [200, 3])


if __name__ == "__main__":
    unittest.main(verbosity=2)
