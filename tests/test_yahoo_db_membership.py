"""
Point-in-time index membership: parsing the dates out of Wikipedia's changes
tables, storing them, and rewinding today's members back to a past date.

Offline — the pages are fixture HTML.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yahoo_db import universe                                   # noqa: E402
from yahoo_db.db import Store                                   # noqa: E402
from yahoo_db.sources import wikipedia_indices as wiki          # noqa: E402


CONSTITUENTS_PAGE = """
<table class="wikitable" id="constituents">
  <tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr>
  <tr><td>AAPL</td><td>Apple Inc.</td><td>Tech</td></tr>
  <tr><td>MSFT</td><td>Microsoft</td><td>Tech</td></tr>
  <tr><td>NVDA</td><td>Nvidia</td><td>Tech</td></tr>
  <tr><td>BRK.B</td><td>Berkshire Hathaway</td><td>Financials</td></tr>
</table>
<table class="wikitable">
  <tr>
    <th rowspan="2">Date</th>
    <th colspan="2">Added</th>
    <th colspan="2">Removed</th>
    <th rowspan="2">Reason</th>
  </tr>
  <tr><th>Ticker</th><th>Security</th><th>Ticker</th><th>Security</th></tr>
  <tr>
    <td>March 2, 2015</td>
    <td>NVDA</td><td>Nvidia</td>
    <td>ENRNQ</td><td>Enron Corp</td>
    <td>Market cap change</td>
  </tr>
  <tr>
    <td>2019-11-21</td>
    <td>MSFT</td><td>Microsoft</td>
    <td>LEHMQ</td><td>Lehman Brothers</td>
    <td>Acquisition</td>
  </tr>
</table>
"""

SPEC = {"page": "Test_index", "index": "Test 500"}


class DateParsingTests(unittest.TestCase):
    def test_the_formats_wikipedia_actually_mixes(self):
        self.assertEqual(wiki.parse_date("March 2, 2015"), "2015-03-02")
        self.assertEqual(wiki.parse_date("2 March 2015"), "2015-03-02")
        self.assertEqual(wiki.parse_date("2015-03-02"), "2015-03-02")
        self.assertEqual(wiki.parse_date("March 2, 2015[1]"), "2015-03-02")
        self.assertEqual(wiki.parse_date("Mar 2, 2015"), "2015-03-02")

    def test_a_month_with_no_day_falls_back_to_the_first(self):
        self.assertEqual(wiki.parse_date("June 2020"), "2020-06-01")

    def test_non_dates_are_rejected_rather_than_guessed(self):
        for junk in ("", "   ", "n/a", "see note", "Market cap change", "[1]"):
            self.assertEqual(wiki.parse_date(junk), "", junk)

    def test_impossible_dates_are_rejected(self):
        self.assertEqual(wiki.parse_date("February 31, 2015"), "")


class MembershipParsingTests(unittest.TestCase):
    def test_splits_current_members_from_dated_events(self):
        members, changes = wiki.parse_membership(CONSTITUENTS_PAGE, SPEC)
        self.assertEqual(members, ["AAPL", "BRK-B", "MSFT", "NVDA"])
        self.assertEqual(sorted(changes), [
            ("ENRNQ", "removed", "2015-03-02"),
            ("LEHMQ", "removed", "2019-11-21"),
            ("MSFT", "added", "2019-11-21"),
            ("NVDA", "added", "2015-03-02"),
        ])

    def test_changes_without_a_usable_date_are_dropped(self):
        html = CONSTITUENTS_PAGE.replace("March 2, 2015", "unknown")
        _, changes = wiki.parse_membership(html, SPEC)
        self.assertNotIn("NVDA", [c[0] for c in changes])
        self.assertIn("MSFT", [c[0] for c in changes])

    def test_a_page_with_no_changes_table_still_yields_members(self):
        html = CONSTITUENTS_PAGE.split("<table class=\"wikitable\">")[0]
        members, changes = wiki.parse_membership(html, SPEC)
        self.assertEqual(members, ["AAPL", "BRK-B", "MSFT", "NVDA"])
        self.assertEqual(changes, [])

    def test_fetch_all_still_returns_the_universe_records(self):
        class Http:
            def get_text(inner, url, params=None):
                return CONSTITUENTS_PAGE

        records, membership = wiki.fetch_all(Http(), pages=[SPEC])
        self.assertIn("AAPL", [r["symbol"] for r in records])
        # The dead names only ever appear in the changes table.
        self.assertIn("ENRNQ", [r["symbol"] for r in records])
        self.assertEqual(len(membership), 1)
        self.assertEqual(membership[0]["index"], "Test 500")

    def test_fetch_is_unchanged_for_callers_that_only_want_symbols(self):
        class Http:
            def get_text(inner, url, params=None):
                return CONSTITUENTS_PAGE

        self.assertEqual(
            sorted(r["symbol"] for r in wiki.fetch(Http(), pages=[SPEC])),
            ["AAPL", "BRK-B", "ENRNQ", "LEHMQ", "MSFT", "NVDA"])


class StoreMembershipTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.mkdtemp(prefix="ydb_idx_")
        self.addCleanup(self._cleanup, directory)
        self.store = Store(Path(directory) / "m.db")
        self.store.init_schema()
        self.store.replace_index_constituents(
            "Test 500", ["AAPL", "MSFT", "NVDA", "BRK-B"])
        self.store.add_index_changes([
            ("Test 500", "NVDA", "added", "2015-03-02"),
            ("Test 500", "ENRNQ", "removed", "2015-03-02"),
            ("Test 500", "MSFT", "added", "2019-11-21"),
            ("Test 500", "LEHMQ", "removed", "2019-11-21"),
        ])

    def _cleanup(self, directory):
        import shutil
        self.store.close()
        shutil.rmtree(directory, ignore_errors=True)

    def test_today_is_the_stored_snapshot(self):
        result = self.store.constituents_on("Test 500")
        self.assertEqual(result["symbols"], ["AAPL", "BRK-B", "MSFT", "NVDA"])
        self.assertEqual(result["rewound"], 0)

    def test_rewind_undoes_later_changes(self):
        # Before the 2019 change: MSFT had not joined, LEHMQ had not left.
        result = self.store.constituents_on("Test 500", "2016-01-01")
        self.assertEqual(result["symbols"],
                         ["AAPL", "BRK-B", "LEHMQ", "NVDA"])
        self.assertEqual(result["rewound"], 2)

        # Before 2015 too: NVDA had not joined, ENRNQ had not left.
        result = self.store.constituents_on("Test 500", "2015-03-01")
        self.assertEqual(result["symbols"],
                         ["AAPL", "BRK-B", "ENRNQ", "LEHMQ"])

    def test_a_change_takes_effect_on_its_own_date(self):
        # Index changes are effective at that day's open, so a symbol added on
        # 2015-03-02 is a member on 2015-03-02.
        on_day = self.store.constituents_on("Test 500", "2015-03-02")["symbols"]
        day_before = self.store.constituents_on("Test 500", "2015-03-01")["symbols"]
        self.assertIn("NVDA", on_day)
        self.assertNotIn("NVDA", day_before)
        self.assertNotIn("ENRNQ", on_day)
        self.assertIn("ENRNQ", day_before)

    def test_dates_before_the_history_are_flagged_unreliable(self):
        # Rewinding past the oldest change just returns membership as of that
        # change. Reporting that honestly matters more than returning a list.
        early = self.store.constituents_on("Test 500", "2005-01-01")
        self.assertFalse(early["reliable"])
        self.assertEqual(early["earliest_change"], "2015-03-02")

        fine = self.store.constituents_on("Test 500", "2016-01-01")
        self.assertTrue(fine["reliable"])

    def test_changes_are_idempotent(self):
        before = self.store.conn.execute(
            "SELECT COUNT(*) FROM index_changes").fetchone()[0]
        self.store.add_index_changes([
            ("Test 500", "NVDA", "added", "2015-03-02")])   # already known
        after = self.store.conn.execute(
            "SELECT COUNT(*) FROM index_changes").fetchone()[0]
        self.assertEqual(before, after)

    def test_malformed_changes_are_ignored(self):
        added = self.store.add_index_changes([
            ("Test 500", "", "added", "2020-01-01"),        # no symbol
            ("Test 500", "X", "joined", "2020-01-01"),      # unknown action
            ("Test 500", "X", "added", ""),                 # no date
        ])
        self.assertEqual(added, 0)

    def test_constituents_replace_rather_than_accumulate(self):
        self.store.replace_index_constituents("Test 500", ["AAPL"])
        self.assertEqual(self.store.constituents_on("Test 500")["symbols"],
                         ["AAPL"])

    def test_unknown_index_is_empty_not_an_error(self):
        result = self.store.constituents_on("Nope", "2016-01-01")
        self.assertEqual(result["symbols"], [])
        self.assertFalse(result["reliable"])

    def test_list_indices_reports_coverage(self):
        rows = self.store.list_indices()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["index_name"], "Test 500")
        self.assertEqual(rows[0]["members"], 4)
        self.assertEqual(rows[0]["changes"], 4)
        self.assertEqual(rows[0]["first_change"], "2015-03-02")
        self.assertEqual(rows[0]["last_change"], "2019-11-21")


class UniverseWiringTests(unittest.TestCase):
    def test_refresh_stores_membership_as_a_side_effect(self):
        directory = tempfile.mkdtemp(prefix="ydb_idx2_")
        self.addCleanup(lambda: __import__("shutil").rmtree(directory,
                                                            ignore_errors=True))
        store = Store(Path(directory) / "m.db")
        store.init_schema()

        original = wiki.PAGES
        wiki.PAGES = [SPEC]

        class Http:
            def get_text(inner, url, params=None):
                return CONSTITUENTS_PAGE

            def close(inner):
                pass

        try:
            records = universe._run_wikipedia(Http(), store)
        finally:
            wiki.PAGES = original

        self.assertIn("AAPL", [r["symbol"] for r in records])
        result = store.constituents_on("Test 500", "2016-01-01")
        self.assertIn("LEHMQ", result["symbols"])
        self.assertNotIn("MSFT", result["symbols"])
        store.close()


class CliTests(unittest.TestCase):
    def test_constituents_command(self):
        from yahoo_db import cli
        directory = tempfile.mkdtemp(prefix="ydb_idx3_")
        self.addCleanup(lambda: __import__("shutil").rmtree(directory,
                                                            ignore_errors=True))
        db_path = str(Path(directory) / "m.db")

        store = Store(db_path)
        store.init_schema()
        store.replace_index_constituents("Test 500", ["AAPL", "MSFT"])
        store.add_index_changes([("Test 500", "MSFT", "added", "2019-11-21")])
        store.close()

        # Listing, today's members, and a past date all succeed.
        self.assertEqual(cli.main(["--db", db_path, "constituents"]), 0)
        self.assertEqual(cli.main(["--db", db_path, "constituents",
                                   "--index", "Test 500"]), 0)
        self.assertEqual(cli.main(["--db", db_path, "constituents",
                                   "--index", "Test 500",
                                   "--on", "2016-01-01", "--json"]), 0)
        # An index we hold nothing for is a non-zero exit, not a traceback.
        self.assertEqual(cli.main(["--db", db_path, "constituents",
                                   "--index", "Nope"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
