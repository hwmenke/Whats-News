"""
Offline tests for the yahoo_db downloader.

Nothing here touches the network: the Yahoo lookup crawl gets an injected
fetcher, the SEC/Nasdaq parsers get fixture text, and the downloader gets a
stubbed yf.download.
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yahoo_db import db as ydb                                  # noqa: E402
from yahoo_db import downloader as ydl                          # noqa: E402
from yahoo_db.config import Config                              # noqa: E402
from yahoo_db.db import (STATUS_ACTIVE, STATUS_DELISTED,        # noqa: E402
                         STATUS_UNKNOWN, Store, merge_sources,
                         normalize_symbol)
from yahoo_db.sources import nasdaq, sec, seeds, static_symbols, yahoo_lookup  # noqa: E402


def make_bars(dates, close=100.0, with_actions=True) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    frame = pd.DataFrame(
        {
            "Open": [close] * len(index),
            "High": [close + 1] * len(index),
            "Low": [close - 1] * len(index),
            "Close": [close] * len(index),
            "Adj Close": [close * 0.99] * len(index),
            "Volume": [1000.0] * len(index),
        },
        index=index,
    )
    if with_actions:
        frame["Dividends"] = [0.0] * len(index)
        frame["Stock Splits"] = [0.0] * len(index)
    return frame


def grouped(frames: dict) -> pd.DataFrame:
    """Build a yf.download(group_by='ticker') style MultiIndex frame."""
    return pd.concat(frames, axis=1)


class SymbolNormalizationTests(unittest.TestCase):
    def test_class_separators_become_dashes(self):
        self.assertEqual(normalize_symbol("brk.b"), "BRK-B")
        self.assertEqual(normalize_symbol("BF/B"), "BF-B")

    def test_market_suffixes_survive(self):
        self.assertEqual(normalize_symbol("shop.to"), "SHOP.TO")
        self.assertEqual(normalize_symbol("VOD.L"), "VOD.L")

    def test_special_prefixes(self):
        self.assertEqual(normalize_symbol("$SPX"), "^SPX")
        self.assertEqual(normalize_symbol("^gspc"), "^GSPC")
        self.assertEqual(normalize_symbol("btc-usd"), "BTC-USD")
        self.assertEqual(normalize_symbol("es=f"), "ES=F")

    def test_blank_input(self):
        self.assertEqual(normalize_symbol(None), "")
        self.assertEqual(normalize_symbol("   "), "")

    def test_merge_sources_dedupes(self):
        self.assertEqual(merge_sources("sec", "nasdaq"), "nasdaq,sec")
        self.assertEqual(merge_sources("sec,nasdaq", "sec"), "nasdaq,sec")
        self.assertEqual(merge_sources("", "seeds"), "seeds")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(_tmp_db(self))
        self.store.init_schema()

    def tearDown(self):
        self.store.close()

    def test_upsert_tickers_merges_sources_and_keeps_first_seen(self):
        self.store.upsert_tickers([
            {"symbol": "aapl", "name": "Apple Inc.", "source": "sec"},
        ])
        first_seen = self.store.conn.execute(
            "SELECT first_seen FROM tickers WHERE symbol='AAPL'").fetchone()[0]

        result = self.store.upsert_tickers([
            {"symbol": "AAPL", "exchange": "NMS", "status": STATUS_ACTIVE,
             "source": "nasdaq"},
        ])
        self.assertEqual(result, {"inserted": 0, "updated": 1})

        row = self.store.conn.execute(
            "SELECT * FROM tickers WHERE symbol='AAPL'").fetchone()
        self.assertEqual(row["sources"], "nasdaq,sec")
        self.assertEqual(row["name"], "Apple Inc.")   # not clobbered by a blank
        self.assertEqual(row["exchange"], "NMS")
        self.assertEqual(row["status"], STATUS_ACTIVE)
        self.assertEqual(row["first_seen"], first_seen)

    def test_delisted_status_is_sticky(self):
        self.store.upsert_tickers([{"symbol": "OLDCO", "source": "seeds",
                                    "status": STATUS_DELISTED}])
        self.store.upsert_tickers([{"symbol": "OLDCO", "source": "nasdaq",
                                    "status": STATUS_ACTIVE}])
        row = self.store.conn.execute(
            "SELECT status FROM tickers WHERE symbol='OLDCO'").fetchone()
        self.assertEqual(row["status"], STATUS_DELISTED)

    def test_upsert_prices_is_idempotent_and_updates(self):
        frame = make_bars(["2024-01-02", "2024-01-03"])
        self.assertEqual(self.store.upsert_prices("AAPL", "1d", frame), 2)
        self.assertEqual(self.store.upsert_prices("AAPL", "1d", frame), 2)
        self.assertEqual(
            self.store.conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0], 2)

        revised = make_bars(["2024-01-03"], close=250.0)
        self.store.upsert_prices("AAPL", "1d", revised)
        row = self.store.conn.execute(
            "SELECT close FROM prices WHERE symbol='AAPL' AND date='2024-01-03'"
        ).fetchone()
        self.assertEqual(row["close"], 250.0)

    def test_upsert_prices_handles_multiindex_columns(self):
        frame = grouped({"AAPL": make_bars(["2024-01-02"])})["AAPL"]
        wide = pd.concat({"AAPL": frame}, axis=1)   # still 2 column levels
        self.assertEqual(self.store.upsert_prices("AAPL", "1d", wide), 1)
        row = self.store.conn.execute("SELECT * FROM prices").fetchone()
        self.assertEqual(row["open"], 100.0)
        self.assertEqual(row["adj_close"], 99.0)

    def test_upsert_prices_skips_all_nan_rows(self):
        frame = make_bars(["2024-01-02", "2024-01-03"])
        frame.loc[frame.index[1], ["Open", "High", "Low", "Close"]] = float("nan")
        self.assertEqual(self.store.upsert_prices("X", "1d", frame), 1)

    def test_upsert_actions_ignores_zero_rows(self):
        frame = make_bars(["2024-01-02", "2024-01-03"])
        frame["Dividends"] = [0.0, 0.24]
        frame["Stock Splits"] = [4.0, 0.0]
        result = self.store.upsert_actions(
            "AAPL", dividends=frame["Dividends"], splits=frame["Stock Splits"])
        self.assertEqual(result, {"dividends": 1, "splits": 1, "new_splits": 1})
        self.assertEqual(
            self.store.conn.execute("SELECT amount FROM dividends").fetchone()[0], 0.24)

    def test_last_price_dates_bulk(self):
        self.store.upsert_prices("AAPL", "1d", make_bars(["2024-01-02", "2024-01-03"]))
        self.store.upsert_prices("MSFT", "1d", make_bars(["2024-01-02"]))
        dates = self.store.last_price_dates(["AAPL", "MSFT", "NOPE"], "1d")
        self.assertEqual(dates, {"AAPL": "2024-01-03", "MSFT": "2024-01-02"})

    def test_symbols_to_fetch_orders_and_filters(self):
        self.store.upsert_tickers([
            {"symbol": "NEW", "source": "t"},
            {"symbol": "OLD", "source": "t"},
            {"symbol": "DEAD", "source": "t", "status": STATUS_DELISTED},
        ])
        # OLD succeeded long ago, DEAD succeeded long ago but is delisted.
        self.store.conn.execute(
            "INSERT INTO fetch_log (symbol, interval, status, rows, fetched_at) "
            "VALUES ('OLD','1d','ok',10,'2000-01-01T00:00:00+00:00')")
        self.store.conn.execute(
            "INSERT INTO fetch_log (symbol, interval, status, rows, fetched_at) "
            "VALUES ('DEAD','1d','ok',10,'2000-01-01T00:00:00+00:00')")
        self.store.conn.commit()

        # Never-fetched first. DEAD is included too, but only because its last
        # look was 25 years ago — delisted symbols get a slow recheck so one
        # bad day at Yahoo cannot bury a symbol permanently.
        due = self.store.symbols_to_fetch("1d", refresh_after_hours=1)
        self.assertEqual(due, ["NEW", "DEAD", "OLD"])

        due = self.store.symbols_to_fetch("1d", refresh_after_hours=1,
                                          include_delisted=False)
        self.assertEqual(due, ["NEW", "OLD"])

    def test_delisted_symbols_are_not_refetched_daily(self):
        self.store.upsert_tickers([{"symbol": "DEAD", "source": "t",
                                    "status": STATUS_DELISTED}])
        self.store.log_fetch("DEAD", "1d", "ok", rows=10)
        # Fresh success: nothing to do, even though the refresh window is open.
        self.assertEqual(
            self.store.symbols_to_fetch("1d", refresh_after_hours=0), [])
        # …but it is not excluded forever.
        self.store.conn.execute(
            "UPDATE fetch_log SET fetched_at='2000-01-01T00:00:00+00:00'")
        self.store.conn.commit()
        self.assertEqual(
            self.store.symbols_to_fetch("1d", refresh_after_hours=0,
                                        delisted_recheck_days=30), ["DEAD"])

    def test_failed_symbols_back_off_exponentially(self):
        self.store.upsert_tickers([{"symbol": "GHOST", "source": "t"}])
        self.store.log_fetch("GHOST", "1d", "empty", error="no data")
        # One failure just now: not due again today, due again tomorrow.
        self.assertEqual(self.store.symbols_to_fetch("1d"), [])
        self.store.conn.execute(
            "UPDATE fetch_log SET fetched_at='2000-01-01T00:00:00+00:00'")
        self.store.conn.commit()
        self.assertEqual(self.store.symbols_to_fetch("1d"), ["GHOST"])

    def test_force_ignores_every_window(self):
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "t"},
                                   {"symbol": "GHOST", "source": "t"}])
        self.store.log_fetch("AAPL", "1d", "ok", rows=5)
        self.store.log_fetch("GHOST", "1d", "empty")
        self.assertEqual(self.store.symbols_to_fetch("1d"), [])
        self.assertEqual(sorted(self.store.symbols_to_fetch("1d", force=True)),
                         ["AAPL", "GHOST"])

    def test_symbols_to_fetch_skips_recent_success(self):
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "t"}])
        self.store.log_fetch("AAPL", "1d", "ok", rows=5)
        self.assertEqual(self.store.symbols_to_fetch("1d", refresh_after_hours=20), [])

    def test_symbols_to_fetch_filters_quote_types(self):
        self.store.upsert_tickers([
            {"symbol": "AAPL", "source": "t", "quote_type": "EQUITY"},
            {"symbol": "SPY", "source": "t", "quote_type": "ETF"},
        ])
        self.assertEqual(
            self.store.symbols_to_fetch("1d", quote_types=["etf"]), ["SPY"])

    def test_exclude_types_keeps_symbols_of_unknown_type(self):
        # The lookup crawl and seed files leave quote_type blank, and those are
        # exactly the delisted symbols. An inclusive --types filter drops them;
        # an exclusive one must not.
        self.store.upsert_tickers([
            {"symbol": "AAPL", "source": "t", "quote_type": "EQUITY"},
            {"symbol": "SPY", "source": "t", "quote_type": "ETF"},
            {"symbol": "VFINX", "source": "t", "quote_type": "MUTUALFUND"},
            {"symbol": "ENRNQ", "source": "seeds"},
            {"symbol": "OLDCO", "source": "yahoo-lookup", "quote_type": ""},
        ])
        self.assertEqual(
            self.store.symbols_to_fetch("1d", quote_types=["EQUITY"]), ["AAPL"])
        self.assertEqual(
            self.store.symbols_to_fetch("1d",
                                        exclude_types=["ETF", "MUTUALFUND"]),
            ["AAPL", "ENRNQ", "OLDCO"])

    def test_stale_sweep_respects_the_type_filter(self):
        # A stocks-only run must not delist the ETFs it never downloads.
        self.store.upsert_tickers([
            {"symbol": "LIVE", "source": "t", "quote_type": "EQUITY"},
            {"symbol": "SPY", "source": "t", "quote_type": "ETF"},
        ])
        self.store.upsert_prices("LIVE", "1d", make_bars(["2024-06-03"]))
        self.store.upsert_prices("SPY", "1d", make_bars(["2024-01-03"]))
        self.store.mark_has_data("LIVE", "2024-06-03")
        self.store.mark_has_data("SPY", "2024-01-03")

        swept = self.store.mark_stale_as_delisted("1d", stale_days=30,
                                                  exclude_types=["ETF"])
        self.assertEqual(swept, 0)
        row = self.store.conn.execute(
            "SELECT status FROM tickers WHERE symbol='SPY'").fetchone()
        self.assertNotEqual(row["status"], STATUS_DELISTED)

    def test_mark_stale_as_delisted_uses_market_date(self):
        self.store.upsert_tickers([
            {"symbol": "LIVE", "source": "t"}, {"symbol": "GONE", "source": "t"}])
        self.store.upsert_prices("LIVE", "1d", make_bars(["2024-06-03"]))
        self.store.upsert_prices("GONE", "1d", make_bars(["2024-01-03"]))
        self.store.mark_has_data("LIVE", "2024-06-03")
        self.store.mark_has_data("GONE", "2024-01-03")

        changed = self.store.mark_stale_as_delisted("1d", stale_days=30)
        self.assertEqual(changed, 1)
        rows = dict(self.store.conn.execute(
            "SELECT symbol, status FROM tickers").fetchall())
        self.assertEqual(rows["GONE"], STATUS_DELISTED)
        self.assertEqual(rows["LIVE"], STATUS_UNKNOWN)
        gone = self.store.conn.execute(
            "SELECT delisted_at FROM tickers WHERE symbol='GONE'").fetchone()[0]
        self.assertEqual(gone, "2024-01-03")

    def test_stats_counts(self):
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "sec"}])
        self.store.upsert_prices("AAPL", "1d", make_bars(["2024-01-02"]))
        stats = self.store.stats("1d")
        self.assertEqual(stats["tickers_total"], 1)
        self.assertEqual(stats["price_rows"], 1)
        self.assertEqual(stats["date_min"], "2024-01-02")

    def test_profile_first_trade_date_from_epoch(self):
        self.store.upsert_profile("AAPL", {
            "longName": "Apple Inc.", "sector": "Technology",
            "firstTradeDateEpochUtc": 345479400, "marketCap": 3e12})
        row = self.store.conn.execute(
            "SELECT * FROM profiles WHERE symbol='AAPL'").fetchone()
        self.assertEqual(row["long_name"], "Apple Inc.")
        self.assertEqual(row["first_trade_date"], "1980-12-12")
        self.assertEqual(row["market_cap"], 3e12)


class NasdaqSourceTests(unittest.TestCase):
    TRADED = (
        "Nasdaq Traded|Symbol|Security Name|Listing Exchange|Market Category|"
        "ETF|Round Lot Size|Test Issue|Financial Status|CQS Symbol|"
        "NASDAQ Symbol|NextShares\n"
        "Y|AAPL|Apple Inc. - Common Stock|Q|Q|N|100|N|N||AAPL|N\n"
        "Y|SPY|SPDR S&P 500|P||Y|100|N|||SPY|N\n"
        "Y|ZAZZT|Nasdaq TEST Stock|Q|G|N|100|Y|N||ZAZZT|N\n"
        "File Creation Time: 0101202512:00|||||||||||\n"
    )
    OTHER = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|"
        "Test Issue|NASDAQ Symbol\n"
        "BRK.A|Berkshire Hathaway Inc.|N|BRK.A|N|100|N|BRK.A\n"
        "ALL.PRB|Allstate Corp Preferred B|N|ALLpB|N|100|N|ALL.PRB\n"
        "File Creation Time: 0101202512:00|||||||\n"
    )

    def test_pipe_parser_drops_trailer(self):
        rows = nasdaq.parse_pipe_file(self.TRADED)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["Symbol"], "AAPL")

    def test_traded_parser_skips_test_issues_and_maps_exchange(self):
        records = {r["symbol"]: r for r in nasdaq._parse_traded(self.TRADED)}
        self.assertNotIn("ZAZZT", records)
        self.assertEqual(records["AAPL"]["exchange"], "NMS")
        self.assertEqual(records["AAPL"]["quote_type"], "EQUITY")
        self.assertEqual(records["SPY"]["quote_type"], "ETF")
        self.assertEqual(records["SPY"]["exchange"], "PCX")
        self.assertEqual(records["AAPL"]["status"], STATUS_ACTIVE)

    def test_other_listed_translates_share_classes_and_preferreds(self):
        symbols = [r["symbol"] for r in nasdaq._parse_other_listed(self.OTHER)]
        self.assertIn("BRK-A", symbols)
        self.assertIn("ALL-PB", symbols)

    def test_to_yahoo_symbol_suffixes(self):
        self.assertEqual(nasdaq.to_yahoo_symbol("SPAC.WS"), "SPAC-WT")
        self.assertEqual(nasdaq.to_yahoo_symbol("SPAC.WS.A"), "SPAC-WTA")
        self.assertEqual(nasdaq.to_yahoo_symbol("SPAC.U"), "SPAC-UN")
        self.assertEqual(nasdaq.to_yahoo_symbol("SPAC.R"), "SPAC-RT")
        self.assertEqual(nasdaq.to_yahoo_symbol("ALL.PRB"), "ALL-PB")
        self.assertEqual(nasdaq.to_yahoo_symbol("ALL.PR"), "ALL-P")
        self.assertEqual(nasdaq.to_yahoo_symbol("bad symbol!"), "")

    def test_to_yahoo_symbol_does_not_eat_longer_tails(self):
        # The suffix match used to be a substring test, so anything whose tail
        # merely started with U or R was mangled into a symbol that does not
        # exist — and a nonexistent symbol gets written off as delisted.
        self.assertEqual(nasdaq.to_yahoo_symbol("RGC.US"), "RGC.US")
        self.assertEqual(nasdaq.to_yahoo_symbol("ABC.RT"), "ABC.RT")
        self.assertEqual(nasdaq.to_yahoo_symbol("ABC.UN"), "ABC.UN")
        # Ordinary share classes are still translated.
        self.assertEqual(nasdaq.to_yahoo_symbol("BRK.A"), "BRK-A")

    def test_fetch_merges_files(self):
        class FakeHttp:
            def get_text(inner, url):
                if "nasdaqtraded" in url:
                    return NasdaqSourceTests.TRADED
                if "otherlisted" in url:
                    return NasdaqSourceTests.OTHER
                raise RuntimeError("boom")   # nasdaqlisted + mfunds unavailable

        records = {r["symbol"]: r for r in nasdaq.fetch(FakeHttp())}
        self.assertEqual(set(records), {"AAPL", "SPY", "BRK-A", "ALL-PB"})


class SecSourceTests(unittest.TestCase):
    def test_parsers(self):
        exchange_payload = {
            "fields": ["cik", "name", "ticker", "exchange"],
            "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"],
                     [1067983, "Berkshire Hathaway", "BRK-B", "NYSE"]],
        }
        tickers_payload = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
            "1": {"cik_str": 9999, "ticker": "OLDCO", "title": "Old Co"},
        }

        class FakeHttp:
            def get_json(inner, url):
                return exchange_payload if "exchange" in url else tickers_payload

        records = {r["symbol"]: r for r in sec.fetch(FakeHttp())}
        self.assertEqual(set(records), {"AAPL", "BRK-B", "OLDCO"})
        self.assertEqual(records["AAPL"]["exchange"], "NMS")
        self.assertEqual(records["BRK-B"]["exchange_name"], "NYSE")
        self.assertEqual(records["OLDCO"]["status"], STATUS_UNKNOWN)

    def test_fetch_survives_a_dead_endpoint(self):
        class DeadHttp:
            def get_json(inner, url):
                raise RuntimeError("503")

        self.assertEqual(sec.fetch(DeadHttp()), [])


class SeedSourceTests(unittest.TestCase):
    def test_plain_list_file(self):
        path = _tmp_file(self, "watchlist.txt", "AAPL\nmsft\n\n#comment\nBRK.B\n")
        records = seeds.parse_seed_file(path)
        symbols = [r["symbol"] for r in records]
        self.assertEqual(symbols, ["AAPL", "MSFT", "BRK-B"])
        self.assertEqual(records[0]["status"], STATUS_UNKNOWN)

    def test_delisted_filename_sets_status(self):
        path = _tmp_file(self, "delisted_2008.txt", "LEH\nBSC\n")
        records = seeds.parse_seed_file(path)
        self.assertTrue(all(r["status"] == STATUS_DELISTED for r in records))

    def test_csv_with_headers(self):
        path = _tmp_file(self, "list.csv",
                         "ticker,company,status\nENRN,Enron Corp,delisted\n"
                         "AAPL,Apple Inc.,active\n")
        records = {r["symbol"]: r for r in seeds.parse_seed_file(path)}
        self.assertEqual(records["ENRN"]["status"], STATUS_DELISTED)
        self.assertEqual(records["ENRN"]["name"], "Enron Corp")
        self.assertEqual(records["AAPL"]["status"], STATUS_ACTIVE)

    def test_fetch_directory(self):
        directory = _tmp_dir(self)
        (directory / "a.txt").write_text("AAPL\n")
        (directory / "delisted.csv").write_text("symbol\nENRN\n")
        (directory / "notes.md").write_text("ignored\n")
        records = {r["symbol"]: r for r in seeds.fetch(directory)}
        self.assertEqual(set(records), {"AAPL", "ENRN"})
        self.assertEqual(records["ENRN"]["status"], STATUS_DELISTED)

    def test_missing_directory_is_not_an_error(self):
        self.assertEqual(seeds.fetch("/nonexistent/path/x"), [])


class StaticSourceTests(unittest.TestCase):
    def test_covers_every_asset_class(self):
        records = static_symbols.fetch()
        symbols = {r["symbol"] for r in records}
        for expected in ("^GSPC", "CL=F", "EURUSD=X", "BTC-USD"):
            self.assertIn(expected, symbols)
        types = {r["quote_type"] for r in records}
        self.assertEqual(types, {"INDEX", "FUTURE", "CURRENCY", "CRYPTOCURRENCY"})
        self.assertEqual(len(symbols), len(records))   # no duplicates


class YahooLookupTests(unittest.TestCase):
    def test_generate_queries_depth(self):
        depth1 = yahoo_lookup.generate_queries(1)
        self.assertEqual(len(depth1), 36)
        depth2 = yahoo_lookup.generate_queries(2)
        self.assertEqual(len(depth2), 36 + 36 * 36)
        self.assertIn("AA", depth2)

    def test_parse_payload(self):
        payload = {"finance": {"result": [{
            "total": 2,
            "documents": [
                {"symbol": "aapl", "shortName": "Apple Inc.",
                 "quoteType": "equity", "exchange": "NMS", "exchDisp": "Nasdaq"},
                {"symbol": "", "shortName": "junk"},
            ],
        }]}}
        records, total = yahoo_lookup.parse_lookup_payload(payload)
        self.assertEqual(total, 2)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["symbol"], "AAPL")
        self.assertEqual(records[0]["quote_type"], "EQUITY")
        self.assertEqual(records[0]["status"], STATUS_UNKNOWN)

    def test_parse_payload_handles_empty_shapes(self):
        self.assertEqual(yahoo_lookup.parse_lookup_payload({}), ([], 0))
        self.assertEqual(
            yahoo_lookup.parse_lookup_payload({"finance": {"result": []}}), ([], 0))
        self.assertEqual(yahoo_lookup.parse_lookup_payload(None), ([], 0))

    def test_crawl_paginates_and_dedupes(self):
        calls = []

        def fake_fetcher(params):
            calls.append(dict(params))
            start = params["start"]
            if start == 0:
                docs = [{"symbol": f"S{i}", "quoteType": "equity"}
                        for i in range(yahoo_lookup.PAGE_SIZE)]
                return {"finance": {"result": [{"total": 150, "documents": docs}]}}
            docs = [{"symbol": f"T{i}", "quoteType": "equity"} for i in range(50)]
            return {"finance": {"result": [{"total": 150, "documents": docs}]}}

        cfg = Config()
        records = yahoo_lookup.fetch(cfg, quote_types=["equity"], regions=["US"],
                                     depth=1, sleep=0, fetcher=fake_fetcher)
        # 36 prefixes x 2 pages each, all returning the same synthetic symbols.
        self.assertEqual(len(calls), 72)
        self.assertEqual(len(records), yahoo_lookup.PAGE_SIZE + 50)

    def test_crawl_survives_a_failing_prefix(self):
        def flaky_fetcher(params):
            if params["query"] == "A":
                raise RuntimeError("429 Too Many Requests")
            return {"finance": {"result": [{
                "total": 1,
                "documents": [{"symbol": "OK", "quoteType": "equity"}]}]}}

        records = yahoo_lookup.fetch(Config(), quote_types=["equity"],
                                     regions=["US"], depth=1, sleep=0,
                                     fetcher=flaky_fetcher)
        self.assertEqual([r["symbol"] for r in records], ["OK"])


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(_tmp_db(self))
        self.store.init_schema()
        self.cfg = Config(sleep_between_batches=0, retry_backoff=0, batch_size=10)
        self.downloader = ydl.Downloader(self.cfg, self.store)
        self._original_download = ydl.yf.download

    def tearDown(self):
        ydl.yf.download = self._original_download
        self.store.close()

    def _stub_download(self, frames, capture=None):
        def fake_download(**kwargs):
            if capture is not None:
                capture.append(kwargs)
            wanted = {t: frames[t] for t in kwargs["tickers"] if t in frames}
            if not wanted:
                return pd.DataFrame()
            return grouped(wanted)
        ydl.yf.download = fake_download

    def test_run_stores_prices_and_marks_active(self):
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "t"},
                                   {"symbol": "MSFT", "source": "t"}])
        self._stub_download({
            "AAPL": make_bars(["2024-01-02", "2024-01-03"]),
            "MSFT": make_bars(["2024-01-02", "2024-01-03"], close=400.0),
        })
        result = self.downloader.run(interval="1d", single_retry=False)

        self.assertEqual(result["ok"], 2)
        self.assertEqual(result["rows"], 4)
        rows = dict(self.store.conn.execute(
            "SELECT symbol, status FROM tickers").fetchall())
        self.assertEqual(rows["AAPL"], STATUS_ACTIVE)
        logged = self.store.conn.execute(
            "SELECT status, rows, first_date, last_date FROM fetch_log "
            "WHERE symbol='AAPL'").fetchone()
        self.assertEqual(logged["status"], "ok")
        self.assertEqual(logged["rows"], 2)
        self.assertEqual(logged["first_date"], "2024-01-02")
        self.assertEqual(logged["last_date"], "2024-01-03")

    def test_second_run_is_incremental_with_overlap(self):
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "t"}])
        self.store.upsert_prices("AAPL", "1d", make_bars(["2024-01-10"]))

        calls = []
        self._stub_download({"AAPL": make_bars(["2024-01-11"])}, capture=calls)
        self.downloader.run(interval="1d", single_retry=False)

        self.assertEqual(len(calls), 1)
        self.assertNotIn("period", calls[0])
        # last stored bar 2024-01-10, minus the 7-day overlap, snapped back to
        # the Monday so the long tail of symbols still shares a batch
        self.assertEqual(calls[0]["start"], "2024-01-01")

    def test_first_run_asks_for_full_history(self):
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "t"}])
        calls = []
        self._stub_download({"AAPL": make_bars(["1990-01-02"])}, capture=calls)
        self.downloader.run(interval="1d", single_retry=False)
        self.assertEqual(calls[0]["period"], "max")

    def _run_with_ticker(self, ticker_cls, **run_kwargs):
        original = ydl.yf.Ticker
        ydl.yf.Ticker = ticker_cls
        try:
            return self.downloader.run(interval="1d", **run_kwargs)
        finally:
            ydl.yf.Ticker = original

    def test_one_empty_response_does_not_delist(self):
        # The single most costly bug this app can have: a Yahoo outage looks
        # exactly like a delisting, and delisting is close to irreversible.
        self.store.upsert_tickers([{"symbol": "GOODCO", "source": "t"}])
        self._stub_download({})

        class Empty:
            def __init__(self, symbol):
                pass

            def history(self, **kwargs):
                return pd.DataFrame()

        result = self._run_with_ticker(Empty)
        self.assertEqual(result["empty"], 1)
        self.assertEqual(result.get("empty_pending_delist"), 1)
        row = self.store.conn.execute(
            "SELECT status FROM tickers WHERE symbol='GOODCO'").fetchone()
        self.assertNotEqual(row["status"], STATUS_DELISTED)

    def test_repeated_empties_eventually_delist(self):
        self.store.upsert_tickers([{"symbol": "DEADCO", "source": "t"}])
        self._stub_download({})

        class Empty:
            def __init__(self, symbol):
                pass

            def history(self, **kwargs):
                return pd.DataFrame()

        for _ in range(self.cfg.delist_after_empty_fetches):
            self._run_with_ticker(Empty, force=True)

        row = self.store.conn.execute(
            "SELECT status, notes FROM tickers WHERE symbol='DEADCO'").fetchone()
        self.assertEqual(row["status"], STATUS_DELISTED)
        self.assertIn("consecutive empty", row["notes"])

    def test_rate_limit_is_never_evidence_of_delisting(self):
        from yfinance.exceptions import YFRateLimitError
        self.store.upsert_tickers([{"symbol": "GOODCO", "source": "t"}])
        self._stub_download({})

        class Throttled:
            def __init__(self, symbol):
                pass

            def history(self, **kwargs):
                raise YFRateLimitError()

        for _ in range(5):
            result = self._run_with_ticker(Throttled, force=True)

        self.assertTrue(result.get("error_rate_limit"))
        row = self.store.conn.execute(
            "SELECT status FROM tickers WHERE symbol='GOODCO'").fetchone()
        self.assertNotEqual(row["status"], STATUS_DELISTED)

    def test_a_whole_empty_batch_is_treated_as_throttling(self):
        # 50 companies do not die simultaneously; that shape is a rate limit.
        # Single-retrying each would fire 50 more requests into the same wall.
        self.store.upsert_tickers([{"symbol": f"S{i}", "source": "t"}
                                   for i in range(5)])
        self._stub_download({})
        retries = []

        class Counting:
            def __init__(self, symbol):
                retries.append(symbol)

            def history(self, **kwargs):
                return pd.DataFrame()

        result = self._run_with_ticker(Counting)
        self.assertEqual(retries, [])
        self.assertEqual(result["error"], 5)
        self.assertEqual(result.get("batches_throttled"), 1)
        delisted = self.store.conn.execute(
            "SELECT COUNT(*) FROM tickers WHERE status=?", (STATUS_DELISTED,)
        ).fetchone()[0]
        self.assertEqual(delisted, 0)

    def test_bars_revive_a_symbol_we_wrongly_wrote_off(self):
        self.store.upsert_tickers([{"symbol": "BACK", "source": "t",
                                    "status": STATUS_DELISTED}])
        self._stub_download({"BACK": make_bars(["2024-01-02", "2024-01-03"])})
        result = self.downloader.run(interval="1d", single_retry=False,
                                     force=True)
        self.assertEqual(result.get("revived"), 1)
        row = self.store.conn.execute(
            "SELECT status FROM tickers WHERE symbol='BACK'").fetchone()
        self.assertEqual(row["status"], STATUS_ACTIVE)

    def test_subset_run_does_not_sweep_the_universe(self):
        # `download --symbols AAPL` must not delist unrelated tickers.
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "t"},
                                   {"symbol": "THIN", "source": "t"}])
        self.store.upsert_prices("THIN", "1d", make_bars(["2020-01-02"]))
        self.store.mark_has_data("THIN", "2020-01-02")
        self._stub_download({"AAPL": make_bars(["2024-06-03"])})

        self.downloader.run(symbols=["AAPL"], interval="1d", single_retry=False)
        row = self.store.conn.execute(
            "SELECT status FROM tickers WHERE symbol='THIN'").fetchone()
        self.assertNotEqual(row["status"], STATUS_DELISTED)

    def test_single_retry_rescues_a_batch_miss(self):
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "t"}])
        self._stub_download({})

        class LiveTicker:
            def __init__(self, symbol):
                pass

            def history(self, **kwargs):
                return make_bars(["2024-01-02"])

        original_ticker = ydl.yf.Ticker
        ydl.yf.Ticker = LiveTicker
        try:
            result = self.downloader.run(interval="1d")
        finally:
            ydl.yf.Ticker = original_ticker

        self.assertEqual(result["ok"], 1)
        self.assertEqual(result["rows"], 1)

    def test_batch_error_is_logged_for_every_symbol(self):
        self.store.upsert_tickers([{"symbol": "A", "source": "t"},
                                   {"symbol": "B", "source": "t"}])

        def boom(**kwargs):
            raise RuntimeError("429 Too Many Requests")

        ydl.yf.download = boom
        result = self.downloader.run(interval="1d", single_retry=False)
        self.assertEqual(result["error"], 2)
        statuses = [r["status"] for r in self.store.conn.execute(
            "SELECT status FROM fetch_log").fetchall()]
        self.assertEqual(statuses, ["error", "error"])

    def test_actions_are_stored_from_the_price_frame(self):
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "t"}])
        frame = make_bars(["2024-01-02", "2024-01-03"])
        frame["Dividends"] = [0.0, 0.24]
        frame["Stock Splits"] = [4.0, 0.0]
        self._stub_download({"AAPL": frame})
        result = self.downloader.run(interval="1d", single_retry=False)
        self.assertEqual(result["dividends"], 1)
        self.assertEqual(result["splits"], 1)

    def test_group_by_start_splits_new_and_existing(self):
        self.store.upsert_prices("OLD", "1d", make_bars(["2024-01-10"]))
        groups = self.downloader._group_by_start(["NEW", "OLD"], "1d")
        self.assertEqual(groups[None], ["NEW"])
        self.assertEqual(groups["2024-01-01"], ["OLD"])

    def test_group_by_start_buckets_the_long_tail_together(self):
        # Three symbols that each last traded on a different weekday used to
        # get three separate single-symbol downloads.
        for symbol, day in (("A", "2024-01-09"), ("B", "2024-01-10"),
                            ("C", "2024-01-11")):
            self.store.upsert_prices(symbol, "1d", make_bars([day]))
        groups = self.downloader._group_by_start(["A", "B", "C"], "1d")
        self.assertEqual(len(groups), 1)
        self.assertEqual(sorted(next(iter(groups.values()))), ["A", "B", "C"])

    def test_force_and_new_splits_both_demand_full_history(self):
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "t"},
                                   {"symbol": "NVDA", "source": "t"}])
        self.store.upsert_prices("AAPL", "1d", make_bars(["2024-01-10"]))
        self.store.upsert_prices("NVDA", "1d", make_bars(["2024-01-10"]))
        self.assertEqual(self.downloader._group_by_start(["AAPL"], "1d",
                                                         force=True)[None],
                         ["AAPL"])
        # A split Yahoo has just told us about restates the whole series.
        splits = pd.Series([10.0], index=pd.to_datetime(["2024-06-10"]))
        self.assertEqual(self.store.upsert_actions("NVDA", splits=splits)["new_splits"], 1)
        self.assertEqual(self.downloader._group_by_start(["NVDA"], "1d")[None],
                         ["NVDA"])
        # Re-seeing the same split is not new information and must not queue
        # another full re-download of the entire history.
        self.store.clear_full_refetch("NVDA")
        self.assertEqual(self.store.upsert_actions("NVDA", splits=splits)["new_splits"], 0)
        self.assertNotIn(None, self.downloader._group_by_start(["NVDA"], "1d"))

    def test_limit_caps_the_run(self):
        self.store.upsert_tickers([{"symbol": f"S{i}", "source": "t"}
                                   for i in range(10)])
        self._stub_download({f"S{i}": make_bars(["2024-01-02"]) for i in range(10)})
        result = self.downloader.run(interval="1d", limit=3, single_retry=False)
        self.assertEqual(result["symbols"], 3)


class ExportTests(unittest.TestCase):
    def test_csv_export_round_trip(self):
        store = Store(_tmp_db(self))
        store.init_schema()
        store.upsert_tickers([{"symbol": "AAPL", "source": "sec"}])
        store.upsert_prices("AAPL", "1d", make_bars(["2024-01-02", "2024-01-03"]))

        from yahoo_db import export as export_mod
        out_dir = _tmp_dir(self)
        result = export_mod.export_table(store, "prices", out_dir, fmt="csv")
        store.close()

        self.assertEqual(result["rows"], 2)
        frame = pd.read_csv(result["path"])
        self.assertEqual(list(frame["symbol"]), ["AAPL", "AAPL"])
        self.assertEqual(frame["close"].tolist(), [100.0, 100.0])

    def test_unknown_table_rejected(self):
        store = Store(_tmp_db(self))
        store.init_schema()
        from yahoo_db import export as export_mod
        with self.assertRaises(ValueError):
            export_mod.export_table(store, "robert'); DROP TABLE prices;--",
                                    _tmp_dir(self))
        store.close()


class CliTests(unittest.TestCase):
    def test_init_and_status_run_end_to_end(self):
        from yahoo_db import cli
        db_path = _tmp_db(self)
        self.assertEqual(cli.main(["--db", str(db_path), "init"]), 0)
        self.assertEqual(cli.main(["--db", str(db_path), "status"]), 0)
        self.assertEqual(cli.main(["--db", str(db_path), "symbols"]), 0)

    def test_empty_symbol_selector_is_an_error_not_the_whole_universe(self):
        from yahoo_db.cli import _resolve_symbols

        class NoFlags:
            symbols = None
            symbols_file = None

        # No selector at all still means "everything due".
        self.assertIsNone(_resolve_symbols(NoFlags()))

        path = _tmp_file(self, "batch.txt", "\n\n   \n# only a comment\n")

        class EmptyFile:
            symbols = None
            symbols_file = str(path)

        # A file a cron job failed to populate must not silently expand into a
        # run over every ticker in the database.
        with self.assertRaises(SystemExit) as caught:
            _resolve_symbols(EmptyFile())
        self.assertIn("no usable symbols", str(caught.exception))

        class Populated:
            symbols = None
            symbols_file = str(_tmp_file(self, "ok.txt", "aapl\nbrk.b\n"))

        self.assertEqual(_resolve_symbols(Populated()), ["AAPL", "BRK-B"])

    def test_config_overrides_reach_the_config(self):
        from yahoo_db.config import load_config
        cfg = load_config(batch_size=None, workers=4)
        self.assertEqual(cfg.workers, 4)
        self.assertEqual(cfg.batch_size, Config().batch_size)


# ── temp-file helpers ──────────────────────────────────────────────────────────

def _tmp_dir(case) -> Path:
    import tempfile
    directory = tempfile.mkdtemp(prefix="yahoo_db_test_")
    case.addCleanup(_rmtree, directory)
    return Path(directory)


def _tmp_db(case) -> Path:
    return _tmp_dir(case) / "test.db"


def _tmp_file(case, name: str, content: str) -> Path:
    path = _tmp_dir(case) / name
    path.write_text(content, encoding="utf-8")
    return path


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
