import os
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import numpy as np
import pandas as pd

import database as db
import portfolio
import setup_scanner


class SetupScannerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "setup_scan.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()

        idx = pd.date_range("2024-01-01", periods=60, freq="D")
        self.frame = pd.DataFrame(
            {
                "open": np.linspace(100, 130, 60),
                "high": np.linspace(101, 135, 60),
                "low": np.linspace(99, 128, 60),
                "close": np.linspace(100.5, 132, 60),
                "volume": np.full(60, 2_000_000.0),
            },
            index=idx,
        )
        db.add_symbol("TEST1")
        db.upsert_ohlcv("TEST1", "daily", self.frame)

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_scan_setups_returns_catalog(self):
        with patch("setup_scanner.md.list_symbols_with_ohlcv", return_value=["TEST1"]):
            out = setup_scanner.scan_setups(limit=10)
        self.assertIn("setup_catalog", out)
        self.assertIn("EP", out["setup_catalog"])
        self.assertEqual(out["scanned"], 1)
        self.assertGreaterEqual(out["count"], 0)

    def test_scan_filters_by_setup_tag(self):
        fake_row = {
            "symbol": "TEST1",
            "ready": True,
            "setups": ["EP", "NEAR_HIGH"],
            "setup_score": 2,
            "change_pct": 1.0,
        }
        with patch("setup_scanner._scan_one_setup", return_value=fake_row):
            out = setup_scanner.scan_setups(symbols=["TEST1"], setup_filter="EP")
        self.assertEqual(out["count"], 1)
        with patch("setup_scanner._scan_one_setup", return_value=fake_row):
            out2 = setup_scanner.scan_setups(symbols=["TEST1"], setup_filter="DARVAS_BOX")
        self.assertEqual(out2["count"], 0)

    def test_scan_payload_includes_adr_pct(self):
        with patch("setup_scanner.md.list_symbols_with_ohlcv", return_value=["TEST1"]):
            out = setup_scanner.scan_setups(limit=10)
        ready = [r for r in out["results"] if r.get("ready")]
        self.assertTrue(ready)
        row = ready[0]
        self.assertIn("adr_pct", row)
        daily = db.get_ohlcv("TEST1", "daily", limit=setup_scanner.SCAN_ADR_BARS)
        expected = setup_scanner.scan_adr_pct(daily)
        self.assertIsNotNone(expected)
        self.assertAlmostEqual(row["adr_pct"], expected)
        self.assertAlmostEqual(expected, round(portfolio.legend_adr_pct(daily), 2))
        self.assertIn("vol_ratio_5_20", row)
        self.assertIsNotNone(row["vol_ratio_5_20"])

    def test_scan_adr_pct_matches_legend_math(self):
        rows = [{"high": 102.41, "low": 100.0, "close": 100.0}] * 20
        self.assertAlmostEqual(setup_scanner.scan_adr_pct(rows), 2.41)
        self.assertEqual(portfolio.format_legend_adr(portfolio.legend_adr_pct(rows)), "ADR 2.41%")
        self.assertIsNone(setup_scanner.scan_adr_pct([{"high": 102.0, "low": 100.0, "close": 100.0}] * 4))
        self.assertIsNone(setup_scanner.scan_adr_pct(None))
        self.assertIsNone(setup_scanner.scan_adr_pct([]))


class SetupScanRowMetricChipTests(unittest.TestCase):
    """Glanceable ADR / RVOL chips on Scan hit rows — omit when missing, not N/A."""

    def test_chip_class_and_adr_field_contract(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        with open("setup_scanner.py", encoding="utf-8") as fh:
            py = fh.read()
        with open("styles/main.css", encoding="utf-8") as fh:
            css = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()

        self.assertIn("function formatSetupAdrChip", setup)
        self.assertIn("function formatSetupRvolChip", setup)
        self.assertIn("function setupMetricChipsHtml", setup)
        self.assertIn("setup-metric-chip", setup)
        self.assertIn("setup-metric-chips", setup)
        self.assertIn("row.adr_pct", setup)
        self.assertIn("row.vol_ratio_5_20", setup)
        self.assertIn("ADR ${", setup)
        self.assertIn("RVOL ${", setup)
        self.assertIn("toFixed(1)", setup)
        self.assertIn("setupMetricChipsHtml(row)", setup)
        self.assertIn("${row.symbol}${metricChips}", setup)
        self.assertNotIn("N/A", setup)
        self.assertNotIn("share float", setup.lower())
        self.assertNotIn("share_float", setup)

        self.assertIn("def scan_adr_pct", py)
        self.assertIn("legend_adr_pct", py)
        self.assertIn('"adr_pct": scan_adr_pct(daily_rows)', py)
        self.assertIn("SCAN_ADR_BARS", py)
        self.assertNotIn("share_float", py)
        self.assertNotIn("share float", py.lower())

        self.assertIn(".setup-metric-chip", css)
        self.assertIn(".setup-metric-chips", css)
        self.assertIn("color: var(--text-muted)", css)

        # Enter still opens the chart without leaving Scan.
        self.assertIn("Stay in Scan workspace", setup)
        self.assertNotIn("switchTab('charts')", setup)
        self.assertIn('data-workspace="chart"', html)
        self.assertIn('data-workspace="scan"', html)
        self.assertIn('data-workspace="review"', html)

        for blob in (setup, py, css):
            self.assertIsNone(re.search(r"ibd", blob, re.IGNORECASE))

    def test_chip_html_omits_missing_and_formats_compact(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        start = setup.index("function formatSetupAdrChip")
        end = setup.index("function renderSetupScanTable")
        fns = setup[start:end]
        script = fns + r"""
const both = setupMetricChipsHtml({adr_pct: 2.41, vol_ratio_5_20: 1.84});
const none = setupMetricChipsHtml({});
const adrOnly = setupMetricChipsHtml({adr_pct: 2.4});
const rvolOnly = setupMetricChipsHtml({vol_ratio_5_20: 1.8});
const missing = setupMetricChipsHtml({adr_pct: null, vol_ratio_5_20: null});
console.log(JSON.stringify({both, none, adrOnly, rvolOnly, missing}));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        import json
        out = json.loads(proc.stdout)
        self.assertIn('class="setup-metric-chip"', out["both"])
        self.assertIn("ADR 2.4%", out["both"])
        self.assertIn("RVOL 1.8\u00d7", out["both"])
        self.assertEqual(out["none"], "")
        self.assertEqual(out["missing"], "")
        self.assertIn("ADR 2.4%", out["adrOnly"])
        self.assertNotIn("RVOL", out["adrOnly"])
        self.assertIn("RVOL 1.8\u00d7", out["rvolOnly"])
        self.assertNotIn("ADR", out["rvolOnly"])
        for html in out.values():
            self.assertNotIn("N/A", html)


class SetupScanFilterPersistenceTests(unittest.TestCase):
    """Reload restores last Scan filter + universe; hit rows stay on the 60s cache."""

    def test_storage_key_and_restore_on_load_contract(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()

        self.assertIn("SETUP_FILTERS_STORAGE_KEY = 'whats-news-setup-filters'", setup)
        self.assertIn("whats-news-setup-filters", setup)
        self.assertIn("function readSetupFilters", setup)
        self.assertIn("function writeSetupFilters", setup)
        self.assertIn("function persistSetupFilters", setup)
        self.assertIn("function restoreSetupFilters", setup)
        self.assertIn("localStorage.getItem(SETUP_FILTERS_STORAGE_KEY)", setup)
        self.assertIn("localStorage.setItem(SETUP_FILTERS_STORAGE_KEY", setup)
        self.assertIn("restoreSetupFilters()", setup)
        self.assertIn("bindSetupUniverseToggle()", setup)
        self.assertIn("persistSetupFilters()", setup)

        init = setup[setup.index("async function initSetupScanner") : setup.index("function renderSetupFilterPills")]
        self.assertLess(init.index("restoreSetupFilters()"), init.index("apiFetch"))
        self.assertNotIn("loadSetupScan", init)

        restore = setup[setup.index("function restoreSetupFilters") : setup.index("function bindSetupUniverseToggle")]
        self.assertNotIn("loadSetupScan", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertIn("_setupFilter = saved.filter", restore)
        self.assertIn("el.checked = !!saved.universe", restore)

        self.assertIn("whats-news-setup-scan", setup)
        self.assertIn("sessionStorage.getItem(SETUP_SCAN_CACHE_KEY)", setup)
        self.assertIn("SETUP_SCAN_CACHE_TTL_MS = 60 * 1000", setup)

        self.assertIn("function setupMetricChipsHtml", setup)
        self.assertIn("setup-metric-chip", setup)
        self.assertIn("setupMetricChipsHtml(row)", setup)

        self.assertIn('id="chk-setup-universe"', html)
        self.assertIn('id="setup-filter-pills"', html)
        self.assertIn("loadSetupScan({ allowStaleRows: true })", app_js)
        self.assertNotIn("whats-news-setup-filters", app_js)

        self.assertIsNone(re.search(r"ibd", setup, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", html, re.IGNORECASE))

    def test_restore_round_trip_without_scan(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        start = setup.index("function currentSetupUniverse")
        end = setup.index("async function initSetupScanner")
        fns = setup[start:end]
        script = r"""
const mem = {};
const session = {};
let checkbox = { checked: true, addEventListener() {} };
global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); },
};
global.sessionStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(session, k) ? session[k] : null),
    setItem: (k, v) => { session[k] = String(v); },
};
global.document = {
    getElementById: id => (id === 'chk-setup-universe' ? checkbox : null),
};
let loadSetupScanCalls = 0;
global.loadSetupScan = () => { loadSetupScanCalls += 1; };
const SETUP_FILTERS_STORAGE_KEY = 'whats-news-setup-filters';
let _setupFilter = null;
""" + fns + r"""
writeSetupFilters('EP', false);
const saved = readSetupFilters();
_setupFilter = null;
checkbox.checked = true;
const applied = restoreSetupFilters();
persistSetupFilters();
const round = JSON.parse(localStorage.getItem(SETUP_FILTERS_STORAGE_KEY));
const empty = readSetupFilters();
localStorage.setItem(SETUP_FILTERS_STORAGE_KEY, 'not-json');
const bad = readSetupFilters();
localStorage.setItem(SETUP_FILTERS_STORAGE_KEY, JSON.stringify({ filter: 'ALL', universe: true }));
const all = readSetupFilters();
console.log(JSON.stringify({
    saved,
    applied,
    checkbox: checkbox.checked,
    filterAfter: _setupFilter,
    round,
    scanCalls: loadSetupScanCalls,
    sessionKeys: Object.keys(session),
    allFilter: all && all.filter,
    bad,
    key: SETUP_FILTERS_STORAGE_KEY,
}));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        import json
        out = json.loads(proc.stdout)
        self.assertEqual(out["key"], "whats-news-setup-filters")
        self.assertEqual(out["saved"], {"filter": "EP", "universe": False})
        self.assertEqual(out["applied"], {"filter": "EP", "universe": False})
        self.assertFalse(out["checkbox"])
        self.assertEqual(out["filterAfter"], "EP")
        self.assertEqual(out["round"], {"filter": "EP", "universe": False})
        self.assertEqual(out["scanCalls"], 0)
        self.assertEqual(out["sessionKeys"], [])
        self.assertIsNone(out["allFilter"])
        self.assertIsNone(out["bad"])


class SetupScanActiveHighlightTests(unittest.TestCase):
    """Hit-row highlight follows state.activeSymbol; missing names get no fake row."""

    def test_active_class_and_helper_contract(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        with open("styles/main.css", encoding="utf-8") as fh:
            css = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()

        self.assertIn("SETUP_SCAN_ACTIVE_CLASS = 'setup-scan-active'", setup)
        self.assertIn("function syncSetupHitHighlight", setup)
        self.assertIn("function bindSetupHitHighlight", setup)
        self.assertIn("function currentActiveSymbol", setup)
        self.assertIn("function highlightSetupRow", setup)
        self.assertIn("setup-scan-active", setup)
        self.assertIn("setup-scan-selected", setup)
        self.assertIn("syncSetupHitHighlight(currentActiveSymbol())", setup)
        self.assertIn("root.selectSymbol", setup)
        self.assertIn("_setupHitBound", setup)
        self.assertIn("Object.defineProperty(state, 'activeSymbol'", setup)
        self.assertIn("bindSetupHitHighlight()", setup)
        self.assertIn("DOMContentLoaded", setup)
        self.assertNotIn("highlightSetupRow(first.dataset.symbol)", setup)
        self.assertNotIn("highlightSetupRow(first", setup)

        init = setup[
            setup.index("async function initSetupScanner") : setup.index("function renderSetupFilterPills")
        ]
        self.assertIn("bindSetupHitHighlight()", init)
        self.assertNotIn("loadSetupScan", init)

        sync_fn = setup[
            setup.index("function syncSetupHitHighlight") : setup.index("function bindSetupHitHighlight")
        ]
        self.assertNotIn("loadSetupScan", sync_fn)
        self.assertIn("SETUP_SCAN_ACTIVE_CLASS", sync_fn)
        self.assertIn("highlightSetupRow", sync_fn)

        bind_fn = setup[
            setup.index("function bindSetupHitHighlight") : setup.index("function moveSetupScanSelection")
        ]
        self.assertNotIn("loadSetupScan", bind_fn)
        self.assertIn("syncSetupHitHighlight", bind_fn)
        self.assertIn("selectSymbol", bind_fn)

        load_fn = setup[setup.index("async function loadSetupScan") :]
        self.assertIn("syncSetupHitHighlight(currentActiveSymbol())", load_fn)
        self.assertIn("allowStaleRows", load_fn)

        self.assertIn(".setup-scan-row.setup-scan-active", css)
        self.assertIn("box-shadow: inset 2px 0 0 var(--accent)", css)

        self.assertNotIn("syncSetupHitHighlight", app_js)
        self.assertNotIn("setup-scan-active", app_js)
        self.assertIn("function moveSymbolSelection", app_js)
        self.assertIn("openDeskPalette('jump')", app_js)

        self.assertIsNone(re.search(r"ibd", setup, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", css, re.IGNORECASE))

    def test_highlight_helper_matches_active_or_nothing(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        start = setup.index("const SETUP_SCAN_ACTIVE_CLASS")
        end = setup.index("function moveSetupScanSelection")
        fns = setup[start:end]
        script = r"""
function makeRow(symbol) {
    const classes = new Set(['setup-scan-row']);
    return {
        dataset: { symbol },
        classList: {
            toggle(name, on) {
                if (on) classes.add(name);
                else classes.delete(name);
            },
            add(name) { classes.add(name); },
            remove(...names) { names.forEach(n => classes.delete(n)); },
            contains(name) { return classes.has(name); },
        },
        scrollIntoView() {},
        classes,
    };
}
const rows = [makeRow('AAPL'), makeRow('NVDA'), makeRow('MSFT')];
global.window = global;
global.document = {
    querySelectorAll: sel => (String(sel).includes('setup-scan-row') ? rows : []),
    addEventListener() {},
};
let scanCalls = 0;
global.loadSetupScan = () => { scanCalls += 1; };
global.state = { activeSymbol: 'AAPL' };
const origCalls = [];
function origSelect(symbol) {
    origCalls.push(symbol);
    state.activeSymbol = symbol;
}
global.selectSymbol = origSelect;
let _setupScanCursor = 0;
""" + fns + r"""
const hit = syncSetupHitHighlight('NVDA');
const nvdaOn = {
    active: rows[1].classList.contains('setup-scan-active'),
    selected: rows[1].classList.contains('setup-scan-selected'),
};
const aaplAfterNvda = {
    active: rows[0].classList.contains('setup-scan-active'),
    selected: rows[0].classList.contains('setup-scan-selected'),
};
highlightSetupRow('AAPL');
const afterJk = {
    aaplSelected: rows[0].classList.contains('setup-scan-selected'),
    aaplActive: rows[0].classList.contains('setup-scan-active'),
    nvdaActive: rows[1].classList.contains('setup-scan-active'),
    nvdaSelected: rows[1].classList.contains('setup-scan-selected'),
};
bindSetupHitHighlight();
selectSymbol('MSFT');
const afterTape = {
    msftActive: rows[2].classList.contains('setup-scan-active'),
    msftSelected: rows[2].classList.contains('setup-scan-selected'),
    aaplActive: rows[0].classList.contains('setup-scan-active'),
    orig: origCalls.slice(),
    wrapped: selectSymbol._setupHitBound === true,
};
selectSymbol('ZZZZ');
const missing = rows.map(r => ({
    sym: r.dataset.symbol,
    active: r.classList.contains('setup-scan-active'),
    selected: r.classList.contains('setup-scan-selected'),
}));
const caseHit = syncSetupHitHighlight('nvda');
console.log(JSON.stringify({
    hit,
    nvdaOn,
    aaplAfterNvda,
    afterJk,
    afterTape,
    missing,
    caseHit,
    nvdaAfterCase: {
        active: rows[1].classList.contains('setup-scan-active'),
        selected: rows[1].classList.contains('setup-scan-selected'),
    },
    scanCalls,
    cursor: _setupScanCursor,
    origAll: origCalls,
}));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        import json
        out = json.loads(proc.stdout)
        self.assertTrue(out["hit"])
        self.assertTrue(out["nvdaOn"]["active"])
        self.assertTrue(out["nvdaOn"]["selected"])
        self.assertFalse(out["aaplAfterNvda"]["active"])
        self.assertFalse(out["aaplAfterNvda"]["selected"])
        self.assertTrue(out["afterJk"]["aaplSelected"])
        self.assertFalse(out["afterJk"]["aaplActive"])
        self.assertTrue(out["afterJk"]["nvdaActive"])
        self.assertFalse(out["afterJk"]["nvdaSelected"])
        self.assertTrue(out["afterTape"]["msftActive"])
        self.assertTrue(out["afterTape"]["msftSelected"])
        self.assertFalse(out["afterTape"]["aaplActive"])
        self.assertEqual(out["afterTape"]["orig"], ["MSFT"])
        self.assertTrue(out["afterTape"]["wrapped"])
        self.assertTrue(all(not row["active"] and not row["selected"] for row in out["missing"]))
        self.assertTrue(out["caseHit"])
        self.assertTrue(out["nvdaAfterCase"]["active"])
        self.assertEqual(out["scanCalls"], 0)
        self.assertEqual(out["cursor"], 1)
        self.assertEqual(out["origAll"], ["MSFT", "ZZZZ"])


class SetupScanSortTests(unittest.TestCase):
    """Sort already-fetched Scan hits by ADR% / RVOL or default ranking — no extra fetch."""

    def test_sort_control_and_storage_key_contract(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("styles/main.css", encoding="utf-8") as fh:
            css = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()

        self.assertIn("SETUP_SORT_STORAGE_KEY = 'whats-news-setup-sort'", setup)
        self.assertIn("whats-news-setup-sort", setup)
        self.assertIn("SETUP_FILTERS_STORAGE_KEY = 'whats-news-setup-filters'", setup)
        self.assertNotEqual(
            "whats-news-setup-sort",
            "whats-news-setup-filters",
        )
        self.assertIn("function normalizeSetupSort", setup)
        self.assertIn("function readSetupSort", setup)
        self.assertIn("function writeSetupSort", setup)
        self.assertIn("function persistSetupSort", setup)
        self.assertIn("function restoreSetupSort", setup)
        self.assertIn("function sortedSetupScanRows", setup)
        self.assertIn("function setupScanSortValue", setup)
        self.assertIn("function applySetupScanSort", setup)
        self.assertIn("function setSetupSort", setup)
        self.assertIn("function bindSetupSortControl", setup)
        self.assertIn("function syncSetupSortPills", setup)
        self.assertIn("localStorage.getItem(SETUP_SORT_STORAGE_KEY)", setup)
        self.assertIn("localStorage.setItem(SETUP_SORT_STORAGE_KEY", setup)
        self.assertIn("row.adr_pct", setup)
        self.assertIn("row.vol_ratio_5_20", setup)
        self.assertIn("sortedSetupScanRows(_setupScanRows, _setupSort)", setup)
        self.assertNotIn("whats-news-setup-sort", app_js)
        self.assertNotIn("setSetupSort", app_js)
        self.assertNotIn("sortedSetupScanRows", app_js)

        init = setup[
            setup.index("async function initSetupScanner") : setup.index("function renderSetupFilterPills")
        ]
        self.assertIn("restoreSetupSort()", init)
        self.assertIn("bindSetupSortControl()", init)
        self.assertLess(init.index("restoreSetupSort()"), init.index("apiFetch"))
        self.assertNotIn("loadSetupScan", init)

        restore = setup[
            setup.index("function restoreSetupSort") : setup.index("function setupScanSortValue")
        ]
        self.assertNotIn("loadSetupScan", restore)
        self.assertNotIn("apiFetch", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertNotIn("SETUP_FILTERS_STORAGE_KEY", restore)

        set_fn = setup[setup.index("function setSetupSort") : setup.index("function bindSetupSortControl")]
        self.assertNotIn("loadSetupScan", set_fn)
        self.assertNotIn("apiFetch", set_fn)
        self.assertNotIn("yahoo", set_fn.lower())

        apply_sort = setup[
            setup.index("function applySetupScanSort") : setup.index("function syncSetupSortPills")
        ]
        self.assertNotIn("loadSetupScan", apply_sort)
        self.assertNotIn("apiFetch", apply_sort)
        self.assertNotIn("yahoo", apply_sort.lower())
        self.assertIn("renderSetupScanTable(sortedSetupScanRows(_setupScanRows, _setupSort))", apply_sort)

        payload = setup[
            setup.index("function applySetupScanPayload") : setup.index("function readSetupScanCache")
        ]
        self.assertIn("_setupScanRows", payload)
        self.assertIn("data.results.slice()", payload)
        self.assertIn("sortedSetupScanRows(_setupScanRows, _setupSort)", payload)
        self.assertNotIn("yahoo", payload.lower())

        self.assertIn('id="setup-sort-pills"', html)
        self.assertIn('data-setup-sort="scan"', html)
        self.assertIn('data-setup-sort="adr"', html)
        self.assertIn('data-setup-sort="rvol"', html)
        self.assertIn("not a published rating", html)
        self.assertIn('aria-label="Sort scan hits"', html)
        self.assertIn("Highest ADR% first", html)
        self.assertIn("Highest RVOL first", html)
        self.assertIn("Default scanner ranking", html)
        sort_html = html[html.index('id="setup-sort-pills"') : html.index('id="setup-filter-pills"')]
        self.assertNotIn("yahoo", sort_html.lower())

        self.assertIn(".setup-sort-control", css)
        self.assertIn(".setup-sort-pills", css)
        self.assertIn(".setup-sort-pill", css)
        self.assertIn(".setup-sort-pill.setup-sort-on", css)
        self.assertIn("font-size: 10px", css)

        self.assertIn("not a published rating", setup)
        self.assertIsNone(re.search(r"ibd", setup, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", html, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", css, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", app_js, re.IGNORECASE))

    def test_sort_rows_persist_and_re_render_without_fetch(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        sort_fns = setup[
            setup.index("function normalizeSetupSort") : setup.index("const SETUP_SCAN_ACTIVE_CLASS")
        ]
        payload_fn = setup[
            setup.index("function applySetupScanPayload") : setup.index("function readSetupScanCache")
        ]
        script = r"""
const mem = {};
function makeBtn(id, on) {
    const attrs = {
        'data-setup-sort': id,
        'aria-pressed': on ? 'true' : 'false',
    };
    const classes = new Set(['setup-sort-pill']);
    if (on) classes.add('setup-sort-on');
    return {
        getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
        setAttribute(k, v) { attrs[k] = String(v); },
        classList: {
            toggle(name, flag) { if (flag) classes.add(name); else classes.delete(name); },
            contains(name) { return classes.has(name); },
        },
        classes,
        attrs,
    };
}
const pills = [makeBtn('scan', true), makeBtn('adr', false), makeBtn('rvol', false)];
const wrap = {
    querySelectorAll(sel) { return String(sel).includes('data-setup-sort') ? pills : []; },
    addEventListener(ev, fn) { wrap.handler = fn; },
    contains(el) { return pills.includes(el); },
};
const meta = { textContent: '' };
global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); },
};
global.document = {
    getElementById: id => {
        if (id === 'setup-sort-pills') return wrap;
        if (id === 'setup-scan-meta') return meta;
        return null;
    },
};
let loadSetupScanCalls = 0;
let apiFetchCalls = 0;
global.loadSetupScan = () => { loadSetupScanCalls += 1; };
global.apiFetch = () => { apiFetchCalls += 1; };
const renderCalls = [];
function renderSetupScanTable(rows) {
    renderCalls.push((rows || []).map(r => r.symbol));
}
const SETUP_SORT_STORAGE_KEY = 'whats-news-setup-sort';
const SETUP_FILTERS_STORAGE_KEY = 'whats-news-setup-filters';
let _setupSort = 'scan';
let _setupScanRows = [];
""" + sort_fns + payload_fn + r"""
const rows = [
    {symbol: 'AAA', adr_pct: 1.0, vol_ratio_5_20: 3.0},
    {symbol: 'BBB', adr_pct: 5.0, vol_ratio_5_20: 1.0},
    {symbol: 'CCC', adr_pct: null, vol_ratio_5_20: 2.0},
    {symbol: 'DDD', adr_pct: 5.0, vol_ratio_5_20: null},
];
const scanOrder = sortedSetupScanRows(rows, 'scan').map(r => r.symbol);
const adrOrder = sortedSetupScanRows(rows, 'adr').map(r => r.symbol);
const rvolOrder = sortedSetupScanRows(rows, 'rvol').map(r => r.symbol);
const origAfter = rows.map(r => r.symbol);
const bad = normalizeSetupSort('rating');
const empty = sortedSetupScanRows(null, 'adr');

applySetupScanPayload({ results: rows, count: 4, scanned: 4 });
const storedAfterPayload = _setupScanRows.map(r => r.symbol);
const firstRender = renderCalls.slice();

setSetupSort('adr');
const afterAdr = {
    sort: _setupSort,
    stored: localStorage.getItem(SETUP_SORT_STORAGE_KEY),
    filters: localStorage.getItem(SETUP_FILTERS_STORAGE_KEY),
    render: renderCalls[renderCalls.length - 1],
    pills: pills.map(p => ({
        id: p.getAttribute('data-setup-sort'),
        on: p.classList.contains('setup-sort-on'),
        pressed: p.getAttribute('aria-pressed'),
    })),
};

setSetupSort('rvol');
const afterRvol = {
    sort: _setupSort,
    stored: localStorage.getItem(SETUP_SORT_STORAGE_KEY),
    render: renderCalls[renderCalls.length - 1],
};

setSetupSort('scan');
const afterScan = {
    sort: _setupSort,
    stored: localStorage.getItem(SETUP_SORT_STORAGE_KEY),
    render: renderCalls[renderCalls.length - 1],
};

const saved = Object.assign({}, mem);
_setupSort = 'scan';
mem['whats-news-setup-sort'] = saved['whats-news-setup-sort'];
localStorage.setItem(SETUP_SORT_STORAGE_KEY, 'rvol');
const restored = restoreSetupSort();

bindSetupSortControl();
wrap.handler({ target: pills[1] });
const afterClick = {
    sort: _setupSort,
    stored: localStorage.getItem(SETUP_SORT_STORAGE_KEY),
    render: renderCalls[renderCalls.length - 1],
    boundTwice: (bindSetupSortControl(), wrap._setupSortBound),
};

console.log(JSON.stringify({
    scanOrder,
    adrOrder,
    rvolOrder,
    origAfter,
    bad,
    empty,
    storedAfterPayload,
    firstRender,
    afterAdr,
    afterRvol,
    afterScan,
    restored,
    afterClick,
    loadSetupScanCalls,
    apiFetchCalls,
    key: SETUP_SORT_STORAGE_KEY,
    meta: meta.textContent,
}));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        import json
        out = json.loads(proc.stdout)
        self.assertEqual(out["key"], "whats-news-setup-sort")
        self.assertEqual(out["scanOrder"], ["AAA", "BBB", "CCC", "DDD"])
        self.assertEqual(out["adrOrder"], ["BBB", "DDD", "AAA", "CCC"])
        self.assertEqual(out["rvolOrder"], ["AAA", "CCC", "BBB", "DDD"])
        self.assertEqual(out["origAfter"], ["AAA", "BBB", "CCC", "DDD"])
        self.assertEqual(out["bad"], "scan")
        self.assertEqual(out["empty"], [])
        self.assertEqual(out["storedAfterPayload"], ["AAA", "BBB", "CCC", "DDD"])
        self.assertEqual(out["firstRender"], [["AAA", "BBB", "CCC", "DDD"]])
        self.assertEqual(out["afterAdr"]["sort"], "adr")
        self.assertEqual(out["afterAdr"]["stored"], "adr")
        self.assertIsNone(out["afterAdr"]["filters"])
        self.assertEqual(out["afterAdr"]["render"], ["BBB", "DDD", "AAA", "CCC"])
        self.assertEqual(
            out["afterAdr"]["pills"],
            [
                {"id": "scan", "on": False, "pressed": "false"},
                {"id": "adr", "on": True, "pressed": "true"},
                {"id": "rvol", "on": False, "pressed": "false"},
            ],
        )
        self.assertEqual(out["afterRvol"]["sort"], "rvol")
        self.assertEqual(out["afterRvol"]["stored"], "rvol")
        self.assertEqual(out["afterRvol"]["render"], ["AAA", "CCC", "BBB", "DDD"])
        self.assertEqual(out["afterScan"]["sort"], "scan")
        self.assertEqual(out["afterScan"]["stored"], "scan")
        self.assertEqual(out["afterScan"]["render"], ["AAA", "BBB", "CCC", "DDD"])
        self.assertEqual(out["restored"], "rvol")
        self.assertEqual(out["afterClick"]["sort"], "adr")
        self.assertEqual(out["afterClick"]["stored"], "adr")
        self.assertEqual(out["afterClick"]["render"], ["BBB", "DDD", "AAA", "CCC"])
        self.assertTrue(out["afterClick"]["boundTwice"])
        self.assertEqual(out["loadSetupScanCalls"], 0)
        self.assertEqual(out["apiFetchCalls"], 0)
        self.assertEqual(out["meta"], "4 hits · scanned 4 symbols")


if __name__ == "__main__":
    unittest.main()

