"""
Offline tests for the resumable universe crawl and the `verify` audit.

Same rules as the rest of the suite: nothing here touches the network. The
lookup crawl gets an injected fetcher (including one that raises KeyboardInterrupt
where a real Ctrl-C would land), and every quality check runs against bars
written straight into a temporary SQLite file.
"""

import json
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yahoo_db import universe, verify                            # noqa: E402
from yahoo_db.config import Config                               # noqa: E402
from yahoo_db.db import (SCHEMA_VERSION, STATUS_ACTIVE,          # noqa: E402
                         STATUS_DELISTED, STATUS_UNKNOWN, Store)
from yahoo_db.sources import yahoo_lookup                        # noqa: E402


def make_bars(dates, close=100.0, volume=1000.0) -> pd.DataFrame:
    index = pd.to_datetime(dates)
    closes = close if isinstance(close, list) else [close] * len(index)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 1 for c in closes],
            "Low": [c - 1 for c in closes],
            "Close": closes,
            "Adj Close": [c * 0.99 for c in closes],
            "Volume": [volume] * len(index),
        },
        index=index,
    )


def payload(symbols) -> dict:
    """A one-page lookup response for the given symbols."""
    return {"finance": {"result": [{
        "total": len(symbols),
        "documents": [{"symbol": s, "quoteType": "equity"} for s in symbols],
    }]}}


class LookupProgressStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(_tmp_db(self))
        self.store.init_schema()

    def tearDown(self):
        self.store.close()

    def test_schema_creates_the_progress_table(self):
        tables = {r[0] for r in self.store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertIn("lookup_progress", tables)
        # Against the constant, not a literal: the point is that init_schema
        # stamps the version it actually wrote, and hardcoding a number here
        # breaks every time the schema legitimately grows.
        self.assertEqual(self.store.get_meta("schema_version"),
                         str(SCHEMA_VERSION))

    def test_mark_and_read_back(self):
        self.store.mark_lookup_prefix("US", "equity", "AA", symbols=7)
        self.store.mark_lookup_prefix("US", "equity", "AB")
        self.assertEqual(self.store.lookup_prefixes_done("US", "equity"),
                         {"AA", "AB"})
        self.assertEqual(self.store.lookup_prefixes_done("US", "etf"), set())
        self.assertEqual(self.store.lookup_prefixes_done("GB", "equity"), set())
        row = self.store.conn.execute(
            "SELECT symbols FROM lookup_progress WHERE prefix='AA'").fetchone()
        self.assertEqual(row["symbols"], 7)

    def test_region_and_type_spelling_do_not_split_the_state(self):
        self.store.mark_lookup_prefix("us", "EQUITY", "AA")
        self.assertEqual(self.store.lookup_prefixes_done("US", "equity"), {"AA"})
        # Re-marking the same triple updates rather than duplicating.
        self.store.mark_lookup_prefix("US", "equity", "AA", symbols=3)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM lookup_progress").fetchone()[0], 1)

    def test_stale_completion_expires(self):
        self.store.mark_lookup_prefix("US", "equity", "AA")
        self.store.mark_lookup_prefix("US", "equity", "AB")
        _backdate(self.store, "AB", days=20)

        self.assertEqual(self.store.lookup_prefixes_done("US", "equity",
                                                         max_age_days=14),
                         {"AA"})
        self.assertEqual(self.store.lookup_prefixes_done("US", "equity",
                                                         max_age_days=30),
                         {"AA", "AB"})
        self.assertEqual(self.store.count_lookup_prefixes_done(
            ["US"], ["equity"], max_age_days=14), 1)

    def test_count_only_covers_the_requested_pairs(self):
        for quote_type in ("equity", "etf"):
            self.store.mark_lookup_prefix("US", quote_type, "AA")
        self.store.mark_lookup_prefix("GB", "equity", "AA")

        self.assertEqual(
            self.store.count_lookup_prefixes_done(["US"], ["equity", "etf"]), 2)
        self.assertEqual(
            self.store.count_lookup_prefixes_done(["US", "GB"], ["equity"]), 2)
        self.assertEqual(self.store.count_lookup_prefixes_done([], ["equity"]), 0)

    def test_clear_is_narrowed_to_the_given_regions_and_types(self):
        for region in ("US", "GB"):
            for quote_type in ("equity", "etf"):
                self.store.mark_lookup_prefix(region, quote_type, "AA")

        self.assertEqual(self.store.clear_lookup_progress(regions=["us"],
                                                          quote_types=["EQUITY"]), 1)
        left = {(r["region"], r["quote_type"]) for r in self.store.conn.execute(
            "SELECT region, quote_type FROM lookup_progress").fetchall()}
        self.assertEqual(left, {("US", "etf"), ("GB", "equity"), ("GB", "etf")})

        self.assertEqual(self.store.clear_lookup_progress(), 3)
        self.assertEqual(self.store.conn.execute(
            "SELECT COUNT(*) FROM lookup_progress").fetchone()[0], 0)


class LookupCrawlResumeTests(unittest.TestCase):
    """The crawl itself, driven through its `completed` / `checkpoint` hooks."""

    def setUp(self):
        _quiet(self)
        self.cfg = Config()
        self.asked = []
        self.marked = []
        self.stored = []

    def _fetcher(self, failing=(), interrupt_at=None):
        def fetch_params(params):
            key = (params["region"], params["type"], params["query"])
            self.asked.append(key)
            if params["query"] == interrupt_at:
                raise KeyboardInterrupt
            if params["query"] in failing:
                raise RuntimeError("500 Server Error")
            return payload([f"{params['query']}X"])
        return fetch_params

    def _checkpoint(self, records, region, quote_type, prefix):
        self.stored.extend(r["symbol"] for r in records)
        self.marked.append((region, quote_type, prefix))

    def _crawl(self, fetcher, done=(), depth=1):
        completed = (lambda region, quote_type: set(done)) if done else None
        return yahoo_lookup.fetch(
            self.cfg, quote_types=["equity"], regions=["US"], depth=depth,
            sleep=0, fetcher=fetcher, completed=completed,
            checkpoint=self._checkpoint)

    def test_completed_prefixes_are_never_requested(self):
        self._crawl(self._fetcher(), done={"A", "B", "C"})
        queries = {q for _, _, q in self.asked}
        self.assertEqual(queries & {"A", "B", "C"}, set())
        self.assertEqual(len(self.marked), 36 - 3)
        self.assertIn(("US", "equity", "D"), self.marked)

    def test_every_finished_triple_is_checkpointed_with_its_symbols(self):
        self._crawl(self._fetcher())
        self.assertEqual(len(self.marked), 36)
        self.assertIn("AX", self.stored)
        self.assertEqual(len(self.stored), 36)

    def test_a_failed_triple_is_not_recorded_as_done(self):
        self._crawl(self._fetcher(failing={"A", "B"}))
        prefixes = {q for _, _, q in self.marked}
        self.assertNotIn("A", prefixes)
        self.assertNotIn("B", prefixes)
        self.assertEqual(len(self.marked), 34)
        self.assertNotIn("AX", self.stored)

    def test_a_partially_paginated_triple_is_not_recorded_as_done(self):
        """Page one arrives, page two blows up: nothing about that prefix may
        be claimed, or its later pages would never be fetched again."""
        def fetch_params(params):
            self.asked.append(params["query"])
            if params["start"] > 0:
                raise RuntimeError("timeout on page 2")
            return {"finance": {"result": [{
                "total": 500,
                "documents": [{"symbol": f"{params['query']}{i}",
                               "quoteType": "equity"}
                              for i in range(yahoo_lookup.PAGE_SIZE)],
            }]}}

        self._crawl(fetch_params)
        self.assertEqual(self.marked, [])
        self.assertEqual(self.stored, [])

    def test_interrupt_keeps_finished_triples_and_drops_the_one_in_flight(self):
        self._crawl(self._fetcher(interrupt_at="C"))
        self.assertEqual(self.marked, [("US", "equity", "A"),
                                       ("US", "equity", "B")])
        self.assertEqual(self.stored, ["AX", "BX"])

    def test_symbols_are_only_emitted_once_across_prefixes(self):
        def same_symbol_everywhere(params):
            return payload(["DUPE"])

        self._crawl(same_symbol_everywhere)
        self.assertEqual(self.stored, ["DUPE"])
        self.assertEqual(len(self.marked), 36)   # every triple still finishes

    def test_progress_reports_the_resumed_count(self):
        seen = []
        yahoo_lookup.fetch(self.cfg, quote_types=["equity"], regions=["US"],
                           depth=1, sleep=0, fetcher=self._fetcher(),
                           completed=lambda r, q: {"A", "B"},
                           checkpoint=self._checkpoint,
                           progress=lambda *a: seen.append(a))
        self.assertTrue(seen)
        done, total, found, skipped = seen[-1]
        self.assertEqual(total, 36)
        self.assertEqual(skipped, 2)
        self.assertEqual(done, 36)
        self.assertEqual(found, 34)

    def test_without_hooks_the_crawl_still_returns_everything(self):
        records = yahoo_lookup.fetch(self.cfg, quote_types=["equity"],
                                     regions=["US"], depth=1, sleep=0,
                                     fetcher=self._fetcher())
        self.assertEqual(len(records), 36)
        self.assertEqual(self.marked, [])


class UniverseResumeTests(unittest.TestCase):
    """End to end through universe.refresh, with only the HTTP layer replaced."""

    def setUp(self):
        _quiet(self)
        self.store = Store(_tmp_db(self))
        self.store.init_schema()
        self.cfg = Config(sources=["yahoo-lookup"], lookup_types=["equity"],
                          lookup_regions=["US"], lookup_depth=1, lookup_sleep=0)
        self.calls = []
        self._original_fetcher = yahoo_lookup._default_fetcher
        yahoo_lookup._default_fetcher = self._make_default_fetcher
        self.addCleanup(self._restore)

    def _restore(self):
        yahoo_lookup._default_fetcher = self._original_fetcher
        self.store.close()

    def _make_default_fetcher(self, cfg):
        def fetch_params(params):
            self.calls.append(params["query"])
            if params["query"] in getattr(self, "failing", ()):
                raise RuntimeError("503")
            return payload([f"{params['query']}CO"])
        return fetch_params

    def test_second_run_skips_everything_the_first_one_finished(self):
        first = universe.refresh(self.cfg, self.store)
        self.assertEqual(first["yahoo-lookup"]["found"], 36)
        self.assertEqual(first["yahoo-lookup"]["inserted"], 36)
        self.assertEqual(len(self.calls), 36)
        self.assertEqual(self.store.count_tickers(), 36)

        self.calls.clear()
        second = universe.refresh(self.cfg, self.store)
        self.assertEqual(self.calls, [])
        self.assertEqual(second["yahoo-lookup"], {"found": 0, "inserted": 0,
                                                  "updated": 0})
        self.assertEqual(self.store.count_tickers(), 36)

    def test_a_failed_prefix_is_retried_on_the_next_run(self):
        self.failing = {"A", "7"}
        universe.refresh(self.cfg, self.store)
        self.assertEqual(self.store.count_tickers(), 34)

        self.failing = set()
        self.calls.clear()
        universe.refresh(self.cfg, self.store)
        self.assertEqual(sorted(self.calls), ["7", "A"])
        self.assertEqual(self.store.count_tickers(), 36)

    def test_restart_throws_the_checkpoints_away(self):
        universe.refresh(self.cfg, self.store)
        self.calls.clear()

        restart = Config(sources=["yahoo-lookup"], lookup_types=["equity"],
                         lookup_regions=["US"], lookup_depth=1, lookup_sleep=0,
                         lookup_restart=True)
        summary = universe.refresh(restart, self.store)
        self.assertEqual(len(self.calls), 36)
        # Nothing new, but every prefix was crawled again.
        self.assertEqual(summary["yahoo-lookup"]["inserted"], 0)
        self.assertEqual(summary["yahoo-lookup"]["updated"], 36)

    def test_stale_checkpoints_are_crawled_again(self):
        universe.refresh(self.cfg, self.store)
        self.calls.clear()
        self.store.conn.execute(
            "UPDATE lookup_progress SET completed_at=?",
            ((datetime.now(timezone.utc) - timedelta(days=40)).isoformat(
                timespec="seconds"),))
        self.store.conn.commit()

        universe.refresh(self.cfg, self.store)
        self.assertEqual(len(self.calls), 36)

    def test_an_interrupted_crawl_saves_what_it_had(self):
        interrupted = []

        def make_fetcher(cfg):
            def fetch_params(params):
                if len(interrupted) >= 3:
                    raise KeyboardInterrupt
                interrupted.append(params["query"])
                return payload([f"{params['query']}CO"])
            return fetch_params

        yahoo_lookup._default_fetcher = make_fetcher
        summary = universe.refresh(self.cfg, self.store)

        self.assertEqual(summary["yahoo-lookup"]["found"], 3)
        self.assertEqual(self.store.count_tickers(), 3)
        self.assertEqual(self.store.count_lookup_prefixes_done(["US"], ["equity"]), 3)

        # Resuming picks up at the fourth prefix, and the interrupted one is
        # crawled again rather than skipped.
        yahoo_lookup._default_fetcher = self._make_default_fetcher
        universe.refresh(self.cfg, self.store)
        self.assertNotIn(interrupted[0], self.calls)
        self.assertIn("D", self.calls)
        self.assertEqual(self.store.count_tickers(), 36)

    def test_a_non_streaming_source_still_reports_its_totals(self):
        cfg = Config(sources=["static"])
        summary = universe.refresh(cfg, self.store)
        self.assertGreater(summary["static"]["found"], 100)
        self.assertEqual(summary["static"]["found"],
                         summary["static"]["inserted"])
        self.assertEqual(self.store.count_tickers(),
                         summary["static"]["inserted"])

    def test_an_unknown_source_is_reported_not_raised(self):
        cfg = Config(sources=["nope"])
        summary = universe.refresh(cfg, self.store)
        self.assertIn("unknown source", summary["nope"]["error"])
        self.assertEqual(summary["nope"]["found"], 0)


class VerifyCheckTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(_tmp_db(self))
        self.store.init_schema()

    def tearDown(self):
        self.store.close()

    # ── coverage ───────────────────────────────────────────────────────────────

    def test_no_prices_is_split_by_status_and_sampled(self):
        self.store.upsert_tickers(
            [{"symbol": "HAS", "source": "t", "status": STATUS_ACTIVE}]
            + [{"symbol": f"D{i}", "source": "t", "status": STATUS_DELISTED}
               for i in range(4)]
            + [{"symbol": "U1", "source": "t"}])
        self.store.upsert_prices("HAS", "1d", make_bars(["2024-06-03"]))

        check = verify.check_no_prices(self.store, "1d", limit=2)
        self.assertEqual(check["count"], 5)
        self.assertEqual(check["by_status"][STATUS_DELISTED]["count"], 4)
        self.assertEqual(check["by_status"][STATUS_DELISTED]["sample"],
                         ["D0", "D1"])
        self.assertEqual(check["by_status"][STATUS_UNKNOWN]["count"], 1)
        self.assertNotIn(STATUS_ACTIVE, check["by_status"])

    # ── gaps ───────────────────────────────────────────────────────────────────

    def test_weekdays_between_ignores_weekends(self):
        self.assertEqual(verify._weekdays_between("2024-06-03", "2024-06-05"), 1)
        self.assertEqual(verify._weekdays_between("2024-06-07", "2024-06-10"), 0)
        self.assertEqual(verify._weekdays_between("2024-06-03", "2024-06-10"), 4)
        self.assertEqual(verify._weekdays_between("2024-06-03", "2024-06-11"), 5)
        self.assertEqual(verify._weekdays_between("2024-06-03", "2024-06-03"), 0)
        self.assertEqual(verify._weekdays_between("2024-06-05", "2024-06-03"), 0)

    def test_holiday_shaped_holes_are_not_gaps(self):
        # Christmas week: Tue 24th then Mon 30th, three weekdays missing.
        self.store.upsert_prices("XMAS", "1d",
                                 make_bars(["2024-12-24", "2024-12-30"]))
        # A long weekend either side of a Friday holiday.
        self.store.upsert_prices("HOL", "1d",
                                 make_bars(["2024-03-28", "2024-04-01"]))
        check = verify.check_price_gaps(self.store, "1d", limit=10,
                                        gap_weekdays=5)
        self.assertEqual(check["count"], 0)

    def test_real_holes_are_reported_with_their_size(self):
        self.store.upsert_prices("GAPPY", "1d",
                                 make_bars(["2024-05-01", "2024-06-05"]))
        self.store.upsert_prices("EDGE", "1d",
                                 make_bars(["2024-06-03", "2024-06-11"]))
        check = verify.check_price_gaps(self.store, "1d", limit=10,
                                        gap_weekdays=5)
        self.assertEqual(check["count"], 2)
        self.assertEqual(check["symbols"], 2)
        worst = check["sample"][0]
        self.assertEqual(worst["symbol"], "GAPPY")
        self.assertEqual(worst["from"], "2024-05-01")
        self.assertEqual(worst["to"], "2024-06-05")
        self.assertEqual(worst["missing_weekdays"], 24)
        self.assertEqual(check["sample"][1]["missing_weekdays"], 5)

    def test_gap_sample_respects_the_limit(self):
        for i in range(5):
            self.store.upsert_prices(f"S{i}", "1d",
                                     make_bars(["2024-05-01", "2024-06-05"]))
        check = verify.check_price_gaps(self.store, "1d", limit=2,
                                        gap_weekdays=5)
        self.assertEqual(check["count"], 5)
        self.assertEqual(len(check["sample"]), 2)

    def test_gaps_are_skipped_for_non_daily_intervals(self):
        self.store.upsert_prices("X", "1wk",
                                 make_bars(["2024-01-01", "2024-06-05"]))
        check = verify.check_price_gaps(self.store, "1wk", limit=10,
                                        gap_weekdays=5)
        self.assertEqual(check["count"], 0)
        self.assertIn("1d", check["skipped"])

    # ── bar arithmetic ─────────────────────────────────────────────────────────

    def test_suspicious_bars_by_kind(self):
        self.store.upsert_prices("GOOD", "1d", make_bars(["2024-06-03"]))
        _raw_bar(self.store, "INVERTED", "2024-06-03", 5, 1, 9, 5, 5, 100)
        _raw_bar(self.store, "OUTSIDE", "2024-06-03", 5, 10, 1, 20, 20, 100)
        _raw_bar(self.store, "ZEROPRICE", "2024-06-03", 0, 0, 0, 0, 0, 100)
        _raw_bar(self.store, "NEGVOL", "2024-06-03", 5, 6, 4, 5, 5, -1)

        checks = verify.check_suspicious_bars(self.store, "1d", limit=10)
        self.assertEqual(checks["high_below_low"]["count"], 1)
        self.assertEqual(checks["high_below_low"]["sample"][0]["symbol"],
                         "INVERTED")
        self.assertEqual(checks["close_outside_range"]["count"], 2)
        self.assertEqual(
            {r["symbol"] for r in checks["close_outside_range"]["sample"]},
            {"INVERTED", "OUTSIDE"})
        self.assertEqual(checks["non_positive_price"]["count"], 1)
        self.assertEqual(checks["negative_volume"]["count"], 1)

    def test_clean_bars_raise_nothing(self):
        self.store.upsert_prices("GOOD", "1d",
                                 make_bars(["2024-06-03", "2024-06-04"]))
        checks = verify.check_suspicious_bars(self.store, "1d", limit=10)
        self.assertEqual([c["count"] for c in checks.values()], [0, 0, 0, 0])
        self.assertEqual(checks["high_below_low"]["sample"], [])

    def test_zero_volume_runs_ignore_symbols_that_never_trade_volume(self):
        days = ["2024-06-03", "2024-06-04", "2024-06-05", "2024-06-06",
                "2024-06-07"]
        # An FX-style symbol: volume 0 on every bar, by convention.
        self.store.upsert_prices("EURUSD=X", "1d", make_bars(days, volume=0.0))
        # A real symbol that stopped printing volume for a week.
        self.store.upsert_prices("HALTED", "1d", make_bars(days, volume=0.0))
        self.store.upsert_prices("HALTED", "1d",
                                 make_bars(["2024-06-10"], volume=500.0))
        # A short zero stretch, under the threshold.
        self.store.upsert_prices("BLIP", "1d",
                                 make_bars(["2024-06-03", "2024-06-04"],
                                           volume=0.0))
        self.store.upsert_prices("BLIP", "1d",
                                 make_bars(["2024-06-05"], volume=10.0))

        check = verify.check_zero_volume_runs(self.store, "1d", limit=10,
                                              run_length=5)
        self.assertEqual(check["count"], 1)
        self.assertEqual(check["sample"][0]["symbol"], "HALTED")
        self.assertEqual(check["sample"][0]["bars"], 5)
        self.assertEqual(check["sample"][0]["first_date"], "2024-06-03")

    # ── dates ──────────────────────────────────────────────────────────────────

    def test_date_integrity_catches_what_the_primary_key_cannot(self):
        self.store.upsert_prices("OK", "1d", make_bars(["2024-06-03"]))
        # The same trading day under two spellings — distinct to the PK.
        _raw_bar(self.store, "DUPE", "2024-06-03", 1, 1, 1, 1, 1, 1)
        _raw_bar(self.store, "DUPE", "2024-06-03 00:00:00", 1, 1, 1, 1, 1, 1)
        future = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()
        _raw_bar(self.store, "AHEAD", future, 1, 1, 1, 1, 1, 1)

        checks = verify.check_date_integrity(self.store, "1d", limit=10)
        self.assertEqual(checks["malformed_dates"]["count"], 1)
        self.assertEqual(checks["malformed_dates"]["sample"][0]["date"],
                         "2024-06-03 00:00:00")
        self.assertEqual(checks["duplicate_dates"]["count"], 1)
        self.assertEqual(checks["duplicate_dates"]["sample"][0],
                         {"symbol": "DUPE", "day": "2024-06-03", "rows": 2})
        self.assertEqual(checks["future_dates"]["count"], 1)
        self.assertEqual(checks["future_dates"]["sample"][0]["symbol"], "AHEAD")

    def test_a_clean_series_has_no_date_problems(self):
        self.store.upsert_prices("OK", "1d",
                                 make_bars(["2024-06-03", "2024-06-04"]))
        checks = verify.check_date_integrity(self.store, "1d", limit=10)
        self.assertEqual([c["count"] for c in checks.values()], [0, 0, 0])

    # ── splits ─────────────────────────────────────────────────────────────────

    def test_unrecorded_split_is_flagged_and_a_recorded_one_is_not(self):
        days = ["2024-06-03", "2024-06-04", "2024-06-05"]
        self.store.upsert_prices("HIDDEN", "1d",
                                 make_bars(days, close=[200.0, 100.0, 101.0]))
        self.store.upsert_prices("KNOWN", "1d",
                                 make_bars(days, close=[200.0, 100.0, 101.0]))
        self.store.conn.execute(
            "INSERT INTO splits (symbol, date, ratio) VALUES ('KNOWN','2024-06-04',2)")
        self.store.conn.commit()

        check = verify.check_split_suspects(self.store, "1d", limit=10,
                                            tolerance=0.04)
        self.assertEqual(check["checked_candidates"], 2)
        self.assertEqual(check["count"], 1)
        suspect = check["sample"][0]
        self.assertEqual(suspect["symbol"], "HIDDEN")
        self.assertEqual(suspect["date"], "2024-06-04")
        self.assertEqual(suspect["looks_like"], 2.0)
        self.assertEqual(suspect["ratio"], 2.0)

    def test_reverse_splits_and_ordinary_moves(self):
        days = ["2024-06-03", "2024-06-04"]
        self.store.upsert_prices("REVERSE", "1d",
                                 make_bars(days, close=[10.0, 100.0]))
        self.store.upsert_prices("BIGMOVE", "1d",
                                 make_bars(days, close=[170.0, 100.0]))
        self.store.upsert_prices("QUIET", "1d",
                                 make_bars(days, close=[100.0, 103.0]))

        check = verify.check_split_suspects(self.store, "1d", limit=10,
                                            tolerance=0.04)
        self.assertEqual(check["count"], 1)
        self.assertEqual(check["sample"][0]["symbol"], "REVERSE")
        self.assertEqual(check["sample"][0]["looks_like"], 0.1)

    def test_nearest_split_factor(self):
        self.assertEqual(verify._nearest_split_factor(2.02, 0.04), 2.0)
        self.assertEqual(verify._nearest_split_factor(0.51, 0.04), 0.5)
        self.assertEqual(verify._nearest_split_factor(3.0, 0.04), 3.0)
        self.assertIsNone(verify._nearest_split_factor(1.7, 0.04))
        self.assertIsNone(verify._nearest_split_factor(1.0, 0.04))

    def test_a_split_a_few_days_off_still_counts_as_recorded(self):
        self.store.upsert_prices("SLACK", "1d",
                                 make_bars(["2024-06-03", "2024-06-04"],
                                           close=[200.0, 100.0]))
        self.store.conn.execute(
            "INSERT INTO splits (symbol, date, ratio) VALUES ('SLACK','2024-06-06',2)")
        self.store.conn.commit()
        check = verify.check_split_suspects(self.store, "1d", limit=10,
                                            tolerance=0.04)
        self.assertEqual(check["count"], 0)

    # ── staleness and the fetch log ────────────────────────────────────────────

    def test_stale_active_measures_against_the_markets_newest_bar(self):
        self.store.upsert_tickers([
            {"symbol": "LIVE", "source": "t", "status": STATUS_ACTIVE},
            {"symbol": "STALE", "source": "t", "status": STATUS_ACTIVE},
            {"symbol": "DEAD", "source": "t", "status": STATUS_DELISTED},
        ])
        self.store.upsert_prices("LIVE", "1d", make_bars(["2024-06-03"]))
        self.store.upsert_prices("STALE", "1d", make_bars(["2024-01-03"]))
        self.store.upsert_prices("DEAD", "1d", make_bars(["2024-01-03"]))

        check = verify.check_stale_active(self.store, "1d", limit=10,
                                          stale_days=30,
                                          market_last="2024-06-03")
        self.assertEqual(check["count"], 1)
        self.assertEqual(check["sample"][0]["symbol"], "STALE")
        self.assertEqual(check["sample"][0]["last_date"], "2024-01-03")

    def test_stale_active_is_skipped_on_an_empty_database(self):
        check = verify.check_stale_active(self.store, "1d", limit=10,
                                          stale_days=30, market_last=None)
        self.assertEqual(check["count"], 0)
        self.assertIn("no price rows", check["skipped"])

    def test_fetch_log_health_counts_only_the_latest_attempt(self):
        self.store.log_fetch("RECOVERED", "1d", "error", error="429 rate limit")
        self.store.log_fetch("STILLBAD", "1d", "error", error="429 rate limit")
        self.store.log_fetch("EMPTY", "1d", "empty", error="no data returned")
        self.store.conn.execute(
            "INSERT INTO fetch_log (symbol, interval, status, rows, fetched_at) "
            "VALUES ('RECOVERED','1d','ok',5,'2099-01-01T00:00:00+00:00')")
        self.store.conn.commit()

        check = verify.check_fetch_log(self.store, "1d", limit=10)
        self.assertEqual(check["count"], 2)
        self.assertEqual({r["symbol"] for r in check["sample"]},
                         {"STILLBAD", "EMPTY"})
        self.assertEqual(check["error_attempts"], 2)
        self.assertEqual(check["empty_attempts"], 1)
        self.assertEqual(check["by_status"]["error"]["symbols"], 2)
        self.assertEqual(check["top_errors"][0],
                         {"error": "429 rate limit", "n": 2})


class VerifyReportTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(_tmp_db(self))
        self.store.init_schema()

    def tearDown(self):
        self.store.close()

    def test_report_is_json_serialisable_and_totals_the_problems(self):
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "t"},
                                   {"symbol": "NOPE", "source": "t"}])
        self.store.upsert_prices("AAPL", "1d", make_bars(["2024-06-03"]))

        report = verify.run(self.store, interval="1d", limit=5)
        self.assertEqual(report["interval"], "1d")
        self.assertEqual(report["market_last_date"], "2024-06-03")
        self.assertEqual(report["totals"]["price_rows"], 1)
        self.assertEqual(report["checks"]["no_prices"]["count"], 1)
        self.assertEqual(report["problem_count"],
                         sum(c["count"] for c in report["checks"].values()))
        json.loads(json.dumps(report, default=str))

    def test_run_touches_nothing(self):
        self.store.upsert_tickers([{"symbol": "AAPL", "source": "t"}])
        self.store.upsert_prices("AAPL", "1d", make_bars(["2024-01-03"]))
        before = _snapshot(self.store)
        verify.run(self.store, interval="1d", limit=5)
        self.assertEqual(_snapshot(self.store), before)


class VerifyFixTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(_tmp_db(self))
        self.store.init_schema()

    def tearDown(self):
        self.store.close()

    def test_has_data_and_delisted_at_are_re_derived_from_prices(self):
        self.store.upsert_tickers([{"symbol": "REAL", "source": "t"},
                                   {"symbol": "CLAIMED", "source": "t"}])
        self.store.upsert_prices("REAL", "1d",
                                 make_bars(["2024-06-03", "2024-06-04"]))
        self.store.conn.execute(
            "UPDATE tickers SET has_data=1, delisted_at='1999-01-01' "
            "WHERE symbol='CLAIMED'")
        self.store.conn.commit()

        fixed = verify.apply_fixes(self.store, "1d", stale_days=30)
        self.assertEqual(fixed["has_data_set"], 1)
        self.assertEqual(fixed["has_data_cleared"], 1)

        rows = {r["symbol"]: r for r in self.store.conn.execute(
            "SELECT symbol, has_data, delisted_at FROM tickers").fetchall()}
        self.assertEqual(rows["REAL"]["has_data"], 1)
        self.assertEqual(rows["REAL"]["delisted_at"], "2024-06-04")
        self.assertEqual(rows["CLAIMED"]["has_data"], 0)
        # A flag we cannot verify is left alone rather than guessed at.
        self.assertEqual(rows["CLAIMED"]["delisted_at"], "1999-01-01")

    def test_fixing_is_idempotent(self):
        self.store.upsert_tickers([{"symbol": "REAL", "source": "t"}])
        self.store.upsert_prices("REAL", "1d", make_bars(["2024-06-03"]))
        verify.apply_fixes(self.store, "1d", stale_days=30)
        again = verify.apply_fixes(self.store, "1d", stale_days=30)
        self.assertEqual(again, {"has_data_set": 0, "has_data_cleared": 0,
                                 "marked_delisted_stale": 0})

    def test_fix_sweeps_stale_symbols_and_verify_then_reports_none(self):
        self.store.upsert_tickers([
            {"symbol": "LIVE", "source": "t", "status": STATUS_ACTIVE},
            {"symbol": "STALE", "source": "t", "status": STATUS_ACTIVE}])
        self.store.upsert_prices("LIVE", "1d", make_bars(["2024-06-03"]))
        self.store.upsert_prices("STALE", "1d", make_bars(["2024-01-03"]))

        before = verify.run(self.store, interval="1d", limit=5, stale_days=30)
        self.assertEqual(before["checks"]["stale_active"]["count"], 1)

        fixed = verify.apply_fixes(self.store, "1d", stale_days=30)
        self.assertEqual(fixed["marked_delisted_stale"], 1)
        after = verify.run(self.store, interval="1d", limit=5, stale_days=30)
        self.assertEqual(after["checks"]["stale_active"]["count"], 0)
        self.assertEqual(self.store.conn.execute(
            "SELECT status FROM tickers WHERE symbol='STALE'").fetchone()[0],
            STATUS_DELISTED)

    def test_fixes_never_touch_price_rows(self):
        self.store.upsert_tickers([{"symbol": "BROKEN", "source": "t"}])
        _raw_bar(self.store, "BROKEN", "2024-06-03", 5, 1, 9, 20, 20, -5)
        before = _snapshot(self.store)["prices"]
        verify.apply_fixes(self.store, "1d", stale_days=30)
        self.assertEqual(_snapshot(self.store)["prices"], before)


class VerifyCliTests(unittest.TestCase):
    def setUp(self):
        from yahoo_db import cli
        self.cli = cli
        self.db_path = _tmp_db(self)
        store = Store(self.db_path)
        store.init_schema()
        store.upsert_tickers([{"symbol": "AAPL", "source": "t"},
                              {"symbol": "NOPE", "source": "t"}])
        store.upsert_prices("AAPL", "1d",
                            make_bars(["2024-05-01", "2024-06-05"]))
        store.log_fetch("NOPE", "1d", "error", error="429 Too Many Requests")
        store.close()

    def test_text_report_names_the_failing_checks(self):
        out = _capture(self.cli.main, ["--db", str(self.db_path), "verify"])
        self.assertIn("no_prices", out)
        self.assertIn("NOPE", out)                      # the symbol with no bars
        self.assertIn("missing_weekdays=24", out)       # the gap in AAPL
        self.assertIn("429 Too Many Requests", out)
        self.assertIn("ok non_positive_price", out)     # a clean check, marked ok
        self.assertNotIn("fixes applied", out)          # --fix was not asked for

    def test_json_report_parses(self):
        out = _capture(self.cli.main,
                       ["--db", str(self.db_path), "verify", "--json"])
        report = json.loads(out)
        self.assertEqual(report["checks"]["no_prices"]["count"], 1)
        self.assertEqual(report["checks"]["price_gaps"]["count"], 1)

    def test_limit_caps_every_sample(self):
        out = _capture(self.cli.main,
                       ["--db", str(self.db_path), "verify", "--json",
                        "--limit", "1"])
        report = json.loads(out)
        self.assertEqual(report["limit"], 1)
        for check in report["checks"].values():
            self.assertLessEqual(len(check.get("sample") or []), 1)

    def test_gap_days_flag_changes_the_threshold(self):
        out = _capture(self.cli.main,
                       ["--db", str(self.db_path), "verify", "--json",
                        "--gap-days", "40"])
        self.assertEqual(json.loads(out)["checks"]["price_gaps"]["count"], 0)

    def test_fix_flag_reports_what_it_changed(self):
        out = _capture(self.cli.main,
                       ["--db", str(self.db_path), "verify", "--fix"])
        self.assertIn("fixes applied", out)
        self.assertIn("has_data_set", out)
        store = Store(self.db_path)
        self.addCleanup(store.close)
        self.assertEqual(store.conn.execute(
            "SELECT has_data FROM tickers WHERE symbol='AAPL'").fetchone()[0], 1)

    def test_every_verify_form_exits_clean(self):
        for argv in (["verify"], ["verify", "--json"], ["verify", "--fix"],
                     ["verify", "--interval", "1wk"], ["status"]):
            with self.subTest(argv=argv):
                code = _capture_code(self.cli.main,
                                     ["--db", str(self.db_path)] + argv)
                self.assertEqual(code, 0)


# ── helpers ────────────────────────────────────────────────────────────────────

def _quiet(case):
    """Several tests drive failing prefixes on purpose; their warnings are the
    expected behaviour, not test output worth reading."""
    import logging
    logger = logging.getLogger("yahoo_db")
    previous = logger.level
    logger.setLevel(logging.CRITICAL)
    case.addCleanup(logger.setLevel, previous)


def _raw_bar(store, symbol, date, open_, high, low, close, adj, volume):
    """Write a bar straight in, bypassing the frame plumbing, so a test can
    store values no sane download would produce."""
    store.conn.execute(
        "INSERT INTO prices (symbol, interval, date, open, high, low, close, "
        "adj_close, volume) VALUES (?,?,?,?,?,?,?,?,?)",
        (symbol, "1d", date, open_, high, low, close, adj, volume))
    store.conn.commit()


def _backdate(store, prefix, days):
    stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(
        timespec="seconds")
    store.conn.execute("UPDATE lookup_progress SET completed_at=? WHERE prefix=?",
                       (stamp, prefix))
    store.conn.commit()


def _snapshot(store) -> dict:
    return {
        table: store.conn.execute(f"SELECT * FROM {table} ORDER BY 1,2").fetchall()
        for table in ("tickers", "prices", "splits", "fetch_log")
    }


def _capture(func, *args) -> str:
    import contextlib
    import io
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        func(*args)
    return buffer.getvalue()


def _capture_code(func, *args) -> int:
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        return func(*args)


def _tmp_dir(case) -> Path:
    import tempfile
    directory = tempfile.mkdtemp(prefix="yahoo_db_quality_test_")
    case.addCleanup(_rmtree, directory)
    return Path(directory)


def _tmp_db(case) -> Path:
    return _tmp_dir(case) / "test.db"


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
