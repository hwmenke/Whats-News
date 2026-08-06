"""
Offline tests for the wider universe sources.

Same rule as tests/test_yahoo_db.py: nothing here touches the network. The
Wikipedia and OTC parsers run against fixture text written to match the shapes
those endpoints document, and the HTTP clients are fakes.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from yahoo_db import universe                                    # noqa: E402
from yahoo_db.config import Config                               # noqa: E402
from yahoo_db.db import (STATUS_ACTIVE, STATUS_UNKNOWN,          # noqa: E402
                         Store)
from yahoo_db.sources import (SOURCE_NAMES, otc, sec,            # noqa: E402
                              static_symbols, wikipedia_indices)


# ── fixtures ───────────────────────────────────────────────────────────────────

# A constituents table shaped like the one on "List of S&P 500 companies":
# id="constituents", one header row, share classes spelled with a dot.
CONSTITUENTS_HTML = """
<table class="wikitable sortable" id="constituents">
<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>CIK</th></tr>
<tr><td><a href="/x">MMM</a></td><td>3M</td><td>Industrials</td><td>0000066740</td></tr>
<tr><td>BRK.B</td><td>Berkshire Hathaway<sup class="reference">[1]</sup></td>
    <td>Financials</td><td>0001067983</td></tr>
<tr><td>AAPL</td><td>Apple Inc.</td><td>Information Technology</td><td>0000320193</td></tr>
</table>
"""

# The "Selected changes" table: a two-row header where Date and Reason use
# rowspan=2 and Added/Removed use colspan=2.
CHANGES_HTML = """
<table class="wikitable sortable" id="changes">
<tr>
  <th rowspan="2">Date</th><th colspan="2">Added</th>
  <th colspan="2">Removed</th><th rowspan="2">Reason</th>
</tr>
<tr><th>Ticker</th><th>Security</th><th>Ticker</th><th>Security</th></tr>
<tr>
  <td>September 18, 2023</td><td>BX</td><td>Blackstone Inc.</td>
  <td>LNC</td><td>Lincoln National</td><td>Market cap change.</td>
</tr>
<tr>
  <td>May 2, 2023</td><td>AXON</td><td>Axon Enterprise</td>
  <td>FRC</td><td>First Republic Bank</td><td>FRC was seized by regulators.</td>
</tr>
</table>
"""


class FakeHttp:
    """Serves canned HTML/JSON by URL fragment and records what was asked for."""

    def __init__(self, pages=None, json_pages=None):
        self.pages = pages or {}
        self.json_pages = json_pages or []
        self.urls = []
        self.params = []

    def get_text(self, url, params=None):
        self.urls.append(url)
        for fragment, body in self.pages.items():
            if fragment in url:
                return body
        raise RuntimeError(f"404 {url}")

    def get_json(self, url, params=None):
        self.urls.append(url)
        self.params.append(dict(params or {}))
        if not self.json_pages:
            raise RuntimeError(f"404 {url}")
        return self.json_pages.pop(0)

    def close(self):
        pass


# ── HTML table parsing ─────────────────────────────────────────────────────────

class HtmlTableTests(unittest.TestCase):
    def test_single_row_header_and_cells(self):
        table, = wikipedia_indices.extract_tables(CONSTITUENTS_HTML)
        self.assertEqual(table.headers, ["Symbol", "Security", "GICS Sector", "CIK"])
        self.assertEqual(len(table.rows), 3)
        self.assertEqual(table.rows[0][:2], ["MMM", "3M"])

    def test_reference_markers_are_dropped(self):
        table, = wikipedia_indices.extract_tables(CONSTITUENTS_HTML)
        self.assertEqual(table.rows[1][1], "Berkshire Hathaway")

    def test_two_row_header_flattens_across_colspan_and_rowspan(self):
        table, = wikipedia_indices.extract_tables(CHANGES_HTML)
        self.assertEqual(table.headers,
                         ["Date", "Added Ticker", "Added Security",
                          "Removed Ticker", "Removed Security", "Reason"])
        self.assertEqual(len(table.rows), 2)
        self.assertEqual(table.rows[1][3], "FRC")

    def test_non_wikitables_are_ignored(self):
        html = "<table class='infobox'><tr><th>Symbol</th></tr>" \
               "<tr><td>NOPE</td></tr></table>" + CONSTITUENTS_HTML
        tables = wikipedia_indices.extract_tables(html)
        self.assertEqual(len(tables), 1)
        self.assertNotIn(["NOPE"], tables[0].rows)

    def test_nested_table_does_not_add_rows(self):
        html = """
        <table class="wikitable">
        <tr><th>Symbol</th><th>Security</th></tr>
        <tr><td>AAPL</td><td><table class="wikitable"><tr><td>JUNK</td></tr></table>
            Apple</td></tr>
        </table>
        """
        table, = wikipedia_indices.extract_tables(html)
        self.assertEqual(len(table.rows), 1)
        self.assertEqual(table.rows[0][0], "AAPL")

    def test_empty_input(self):
        self.assertEqual(wikipedia_indices.extract_tables(""), [])

    def test_unclosed_cells_still_produce_rows(self):
        html = ("<table class='wikitable'><tr><th>Symbol<tr><td>AAPL"
                "<tr><td>MSFT</table>")
        table, = wikipedia_indices.extract_tables(html)
        self.assertEqual(table.headers, ["Symbol"])
        self.assertEqual(table.rows, [["AAPL"], ["MSFT"]])

    def test_ragged_rows_do_not_break_column_lookup(self):
        html = ("<table class='wikitable'>"
                "<tr><th>Symbol</th><th>Security</th></tr>"
                "<tr><td>AAPL</td></tr>"          # missing the name cell
                "<tr><td>MSFT</td><td>Microsoft</td></tr></table>")
        records = {r["symbol"]: r
                   for r in wikipedia_indices.parse_page(html, {"index": "X"})}
        self.assertEqual(records["AAPL"]["name"], "")
        self.assertEqual(records["MSFT"]["name"], "Microsoft")


# ── Wikipedia index source ─────────────────────────────────────────────────────

class WikipediaSourceTests(unittest.TestCase):
    def test_constituents_are_active_and_class_shares_normalised(self):
        records = {r["symbol"]: r
                   for r in wikipedia_indices.parse_page(CONSTITUENTS_HTML,
                                                         {"index": "S&P 500"})}
        self.assertEqual(set(records), {"MMM", "BRK-B", "AAPL"})
        self.assertEqual(records["BRK-B"]["status"], STATUS_ACTIVE)
        self.assertEqual(records["MMM"]["name"], "3M")
        self.assertEqual(records["MMM"]["quote_type"], "EQUITY")

    def test_changes_table_yields_both_sides_as_unknown(self):
        records = {r["symbol"]: r
                   for r in wikipedia_indices.parse_page(CHANGES_HTML,
                                                         {"index": "S&P 500"})}
        # Removed tickers are the delisted candidates we are here for.
        self.assertEqual(set(records), {"BX", "AXON", "LNC", "FRC"})
        self.assertEqual(records["FRC"]["name"], "First Republic Bank")
        # Leaving an index is not proof of delisting; the download decides.
        for symbol in ("BX", "FRC"):
            self.assertEqual(records[symbol]["status"], STATUS_UNKNOWN)

    def test_reason_prose_is_never_mistaken_for_a_ticker(self):
        symbols = {r["symbol"]
                   for r in wikipedia_indices.parse_page(CHANGES_HTML,
                                                         {"index": "S&P 500"})}
        self.assertNotIn("MARKET", symbols)
        self.assertNotIn("FRC WAS SEIZED BY REGULATORS.", symbols)

    def test_market_suffix_is_appended_once(self):
        html = """
        <table class="wikitable">
        <tr><th>Ticker</th><th>Company</th></tr>
        <tr><td>VOD</td><td>Vodafone</td></tr>
        <tr><td>BT.A</td><td>BT Group</td></tr>
        <tr><td>SHEL.L</td><td>Shell</td></tr>
        </table>
        """
        spec = {"index": "FTSE 100", "suffix": ".L",
                "exchange": "LSE", "exchange_name": "London"}
        records = {r["symbol"]: r for r in wikipedia_indices.parse_page(html, spec)}
        self.assertEqual(set(records), {"VOD.L", "BT-A.L", "SHEL.L"})
        self.assertEqual(records["VOD.L"]["exchange"], "LSE")

    def test_fetch_skips_dead_pages_and_prefers_active(self):
        http = FakeHttp({"Nasdaq-100": CHANGES_HTML,
                         "List_of_S%26P_500_companies": CONSTITUENTS_HTML})
        pages = [{"page": "List_of_S%26P_500_companies", "index": "S&P 500"},
                 {"page": "Nasdaq-100", "index": "Nasdaq-100"},
                 {"page": "Gone_Page", "index": "Gone"}]
        records = {r["symbol"]: r for r in wikipedia_indices.fetch(http, pages=pages)}

        self.assertEqual(set(records),
                         {"MMM", "BRK-B", "AAPL", "BX", "AXON", "LNC", "FRC"})
        self.assertEqual(len(http.urls), 3)   # the dead page was still attempted

    def test_active_membership_beats_an_older_changes_row(self):
        # AAPL appears as a removal first, then as a current constituent.
        removal = """
        <table class="wikitable">
        <tr><th rowspan="2">Date</th><th colspan="2">Removed</th></tr>
        <tr><th>Ticker</th><th>Security</th></tr>
        <tr><td>1999</td><td>AAPL</td><td>Apple Inc.</td></tr>
        </table>
        """
        http = FakeHttp({"Changes": removal, "Current": CONSTITUENTS_HTML})
        records = {r["symbol"]: r for r in wikipedia_indices.fetch(http, pages=[
            {"page": "Changes", "index": "A"}, {"page": "Current", "index": "B"}])}
        self.assertEqual(records["AAPL"]["status"], STATUS_ACTIVE)

    def test_page_without_a_ticker_column_yields_nothing(self):
        html = ("<table class='wikitable'><tr><th>Year</th><th>Note</th></tr>"
                "<tr><td>2001</td><td>Something happened</td></tr></table>")
        self.assertEqual(wikipedia_indices.parse_page(html, {"index": "X"}), [])

    def test_every_configured_page_is_well_formed(self):
        for spec in wikipedia_indices.PAGES:
            self.assertTrue(spec["page"] and " " not in spec["page"], spec)
            self.assertTrue(spec["index"])
            if spec.get("suffix"):
                self.assertTrue(spec["suffix"].startswith("."), spec)
                self.assertTrue(spec.get("exchange"), spec)


# ── OTC Markets source ─────────────────────────────────────────────────────────

class OtcSourceTests(unittest.TestCase):
    def test_extract_rows_handles_the_shapes_the_endpoint_uses(self):
        rows = [{"symbol": "AAAA"}]
        self.assertEqual(otc.extract_rows({"stocks": rows}), rows)
        self.assertEqual(otc.extract_rows({"records": rows}), rows)
        self.assertEqual(otc.extract_rows({"data": {"records": rows}}), rows)
        self.assertEqual(otc.extract_rows(rows), rows)
        self.assertEqual(otc.extract_rows({"totalRecords": 5}), [])
        self.assertEqual(otc.extract_rows("nope"), [])

    def test_parse_records_picks_fields_by_name(self):
        records = {r["symbol"]: r for r in otc.parse_records([
            {"symbol": "gbtc", "securityName": "Grayscale Bitcoin Trust",
             "tierName": "OTCQX U.S."},
            {"ticker": "RHHBY", "companyName": "Roche Holding AG",
             "tierCode": "PC"},
            {"symbol": "", "securityName": "no symbol"},
            {"symbol": "a whole sentence that is not a ticker"},
        ])}
        self.assertEqual(set(records), {"GBTC", "RHHBY"})
        self.assertEqual(records["GBTC"]["name"], "Grayscale Bitcoin Trust")
        self.assertEqual(records["GBTC"]["exchange_name"], "OTCQX U.S.")
        self.assertEqual(records["GBTC"]["exchange"], "PNK")
        self.assertEqual(records["GBTC"]["status"], STATUS_ACTIVE)
        self.assertEqual(records["RHHBY"]["name"], "Roche Holding AG")

    def test_unknown_tier_still_gets_a_readable_exchange_name(self):
        record, = otc.parse_records([{"symbol": "ABCD"}])
        self.assertEqual(record["exchange_name"], "OTC Markets")

    def test_fetch_pages_until_a_short_page(self):
        page1 = {"stocks": [{"symbol": f"AA{i:03d}"[:5]} for i in range(2)]}
        page2 = {"stocks": [{"symbol": "ZZZZ"}]}
        http = FakeHttp(json_pages=[page1, page2])
        records = otc.fetch(http, page_size=2, max_pages=5)
        self.assertEqual(len(http.params), 2)
        self.assertEqual(http.params[0]["page"], 1)
        self.assertEqual(http.params[1]["page"], 2)
        self.assertIn("ZZZZ", {r["symbol"] for r in records})

    def test_fetch_stops_when_a_page_repeats_itself(self):
        # An endpoint that ignores `page` would otherwise loop MAX_PAGES times.
        same = {"stocks": [{"symbol": "AAAA"}, {"symbol": "BBBB"}]}
        http = FakeHttp(json_pages=[dict(same) for _ in range(10)])
        records = otc.fetch(http, page_size=2, max_pages=10)
        self.assertEqual(len(records), 2)
        self.assertEqual(len(http.params), 2)

    def test_fetch_survives_a_dead_endpoint(self):
        self.assertEqual(otc.fetch(FakeHttp()), [])

    def test_fetch_survives_an_unrecognised_shape(self):
        http = FakeHttp(json_pages=[{"error": "unavailable"}])
        self.assertEqual(otc.fetch(http), [])


# ── SEC mutual fund file ───────────────────────────────────────────────────────

class SecMutualFundTests(unittest.TestCase):
    MF_PAYLOAD = {
        "fields": ["cik", "seriesId", "classId", "symbol"],
        "data": [
            [36405, "S000009184", "C000024944", "VFINX"],
            [36405, "S000009184", "C000024945", "VFIAX"],
            [1000, "S000000001", "C000000001", ""],
        ],
    }

    def test_parses_the_fields_data_shape(self):
        records = {r["symbol"]: r
                   for r in sec._parse_mf_payload(self.MF_PAYLOAD)}
        self.assertEqual(set(records), {"VFINX", "VFIAX"})
        self.assertEqual(records["VFINX"]["quote_type"], "MUTUALFUND")
        self.assertEqual(records["VFINX"]["status"], STATUS_UNKNOWN)
        self.assertEqual(records["VFINX"]["source"], "sec")

    def test_parses_the_object_shape_and_finds_the_ticker_by_name(self):
        payload = {"0": {"cik_str": 36405, "ticker": "vfinx"},
                   "1": {"cik_str": 1, "symbol": "SWPPX"}}
        symbols = {r["symbol"] for r in sec._parse_mf_payload(payload)}
        self.assertEqual(symbols, {"VFINX", "SWPPX"})

    def test_junk_payload_is_not_an_error(self):
        self.assertEqual(sec._parse_mf_payload(None), [])
        self.assertEqual(sec._parse_mf_payload({"fields": [], "data": []}), [])

    def test_fetch_includes_funds_and_can_be_turned_off(self):
        exchange = {"fields": ["cik", "name", "ticker", "exchange"],
                    "data": [[320193, "Apple Inc.", "AAPL", "Nasdaq"]]}

        class Http:
            def get_json(inner, url):
                if "_mf" in url:
                    return SecMutualFundTests.MF_PAYLOAD
                if "exchange" in url:
                    return exchange
                raise RuntimeError("503")

        with_funds = {r["symbol"] for r in sec.fetch(Http())}
        self.assertEqual(with_funds, {"AAPL", "VFINX", "VFIAX"})

        without = {r["symbol"] for r in sec.fetch(Http(), include_funds=False)}
        self.assertEqual(without, {"AAPL"})

    def test_fetch_survives_a_dead_fund_file(self):
        class Http:
            def get_json(inner, url):
                if "_mf" in url:
                    raise RuntimeError("503")
                return {"0": {"cik_str": 1, "ticker": "AAPL", "title": "Apple"}}

        self.assertEqual({r["symbol"] for r in sec.fetch(Http())}, {"AAPL"})


# ── static symbols ─────────────────────────────────────────────────────────────

class StaticSymbolTests(unittest.TestCase):
    def setUp(self):
        self.records = static_symbols.fetch()
        self.symbols = {r["symbol"] for r in self.records}

    def test_no_duplicates_and_every_record_is_typed(self):
        self.assertEqual(len(self.symbols), len(self.records))
        self.assertTrue(all(r["quote_type"] for r in self.records))
        self.assertTrue(all(r["status"] == STATUS_ACTIVE for r in self.records))

    def test_widened_coverage(self):
        for expected in (
            "^RUI",          # Russell 1000
            "^SP500-45",     # a GICS sector sub-index
            "^SOX",          # PHLX semiconductors
            "^FTMC",         # FTSE 250
            "MES=F",         # micro equity future
            "DX=F",          # dollar index future
            "EURPLN=X",      # emerging-market cross
            "XAUUSD=X",      # spot gold
            "TON-USD",       # newer crypto
        ):
            self.assertIn(expected, self.symbols)

    def test_symbols_stay_in_yahoo_shape(self):
        for symbol in self.symbols:
            self.assertEqual(symbol, symbol.strip().upper())
            self.assertNotIn(" ", symbol)

    def test_currency_pairs_are_never_self_crosses(self):
        for record in self.records:
            if record["quote_type"] == "CURRENCY" and record["symbol"].endswith("=X"):
                pair = record["symbol"][:-2]
                if len(pair) == 6:
                    self.assertNotEqual(pair[:3], pair[3:], record["symbol"])


# ── wiring ─────────────────────────────────────────────────────────────────────

class SourceWiringTests(unittest.TestCase):
    def test_new_sources_are_registered(self):
        for name in ("otc", "wikipedia"):
            self.assertIn(name, SOURCE_NAMES)

    def test_run_source_dispatches_every_registered_name(self):
        calls = []

        class Http:
            def get_text(inner, url, params=None):
                calls.append(url)
                raise RuntimeError("offline")

            def get_json(inner, url, params=None):
                calls.append(url)
                raise RuntimeError("offline")

        cfg = Config(seeds_dir=Path("/nonexistent"))
        for name in SOURCE_NAMES:
            if name == "yahoo-lookup":
                continue    # needs a live fetcher; covered in test_yahoo_db.py
            result = universe._run_source(name, cfg, Http(), None)
            self.assertIsInstance(result, list, name)
        self.assertTrue(any("wikipedia.org" in url for url in calls))
        self.assertTrue(any("otcmarkets.com" in url for url in calls))

    def test_unknown_source_still_raises(self):
        with self.assertRaises(ValueError) as caught:
            universe._run_source("nope", Config(), None, None)
        self.assertIn("wikipedia", str(caught.exception))

    def test_refresh_merges_a_new_source_into_the_store(self):
        store = Store(_tmp_dir(self) / "test.db")
        self.addCleanup(store.close)
        store.init_schema()

        http_pages = {"List_of_S%26P_500_companies": CONSTITUENTS_HTML}
        original = universe.HttpClient
        universe.HttpClient = lambda **kwargs: FakeHttp(http_pages)
        self.addCleanup(setattr, universe, "HttpClient", original)

        summary = universe.refresh(Config(), store, sources=["wikipedia"])
        self.assertEqual(summary["wikipedia"]["inserted"], 3)

        row = store.conn.execute(
            "SELECT sources, status FROM tickers WHERE symbol='BRK-B'").fetchone()
        self.assertEqual(row["sources"], "wikipedia")
        self.assertEqual(row["status"], STATUS_ACTIVE)


# ── packaging ──────────────────────────────────────────────────────────────────

class PackagingTests(unittest.TestCase):
    def setUp(self):
        try:
            import tomllib
        except ImportError:                       # Python 3.9/3.10
            self.skipTest("tomllib needs Python 3.11+")
        path = Path(__file__).resolve().parent.parent / "pyproject.toml"
        self.assertTrue(path.is_file(), "pyproject.toml is missing")
        self.data = tomllib.loads(path.read_text(encoding="utf-8"))

    def test_console_script_resolves_to_the_cli_entry_point(self):
        target = self.data["project"]["scripts"]["yahoo-db"]
        self.assertEqual(target, "yahoo_db.cli:main")

        module_name, _, attribute = target.partition(":")
        import importlib
        entry = getattr(importlib.import_module(module_name), attribute)
        self.assertTrue(callable(entry))

    def test_module_invocation_keeps_working(self):
        from yahoo_db import __main__ as module_entry
        from yahoo_db.cli import main
        self.assertIs(module_entry.main, main)

    def test_only_the_downloader_package_is_shipped(self):
        # The Flask dashboard at the repo root must never be packaged.
        packages = self.data["tool"]["setuptools"]["packages"]
        self.assertEqual(sorted(packages), ["yahoo_db", "yahoo_db.sources"])

    def test_declared_dependencies_cover_the_runtime_imports(self):
        names = {dep.split(">")[0].split("=")[0].strip().lower()
                 for dep in self.data["project"]["dependencies"]}
        self.assertEqual(names, {"yfinance", "pandas", "requests"})


# ── helpers ────────────────────────────────────────────────────────────────────

def _tmp_dir(case) -> Path:
    import tempfile
    directory = tempfile.mkdtemp(prefix="yahoo_db_sources_test_")
    case.addCleanup(_rmtree, directory)
    return Path(directory)


def _rmtree(path):
    import shutil
    shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
