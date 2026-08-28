"""Contract tests: Trade journal CSV export (filter-aware, no persist-key changes)."""

import json
import os
import re
import shutil
import subprocess
import unittest

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

FORBIDDEN = (
    "scripts/app.js",
    "scripts/charts.js",
    "index.html",
    "portfolio.py",
    "scripts/spy_rs.js",
    "scripts/setup_scanner.js",
    "scripts/journal_export.js",
    "tests/test_journal_export.py",
)

JOURNAL_ENTRIES_KEY = "whats-news-journal"
JOURNAL_FILTER_KEY = "whats-news-journal-filter"
EXPORT_FILENAME = "whats-news-journal.csv"


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class JournalExportTests(unittest.TestCase):
    """Button, script order, columns, filename, no Yahoo, persist keys untouched."""

    @classmethod
    def setUpClass(cls):
        cls.export_js = _read("scripts/journal_export.js")
        cls.filt_js = _read("scripts/journal_filter.js")
        cls.app_js = _read("scripts/app.js")
        cls.html = _read("index.html")
        cls.css = _read("styles/main.css")
        cls.charts = _read("scripts/charts.js")
        cls.setup = _read("scripts/setup_scanner.js")
        cls.stamp_tests = _read("tests/test_journal_date_stamp.py")
        cls.filter_tests = _read("tests/test_journal_filter.py")

    def test_html_export_button_in_journal_drawer_header(self):
        html = self.html
        self.assertIn('id="journal-drawer"', html)
        self.assertIn('id="btn-journal-export"', html)
        self.assertIn("scripts/journal_export.js", html)
        drawer = html[html.index('id="journal-drawer"') : html.index('id="journal-list"')]
        self.assertIn('id="btn-journal-export"', drawer)
        self.assertIn('id="journal-filter"', drawer)
        head = html[html.index('id="journal-drawer"') : html.index('id="journal-compose"')]
        self.assertIn('id="btn-journal-export"', head)
        self.assertIn('id="btn-journal-close"', head)
        self.assertIn("Export", head)
        self.assertIn("aria-label=", head[head.index("btn-journal-export") :])
        self.assertIn("Export journal as CSV", head)
        self.assertIn("journal-export-btn", head)
        self.assertIn('class="btn btn-ghost btn-sm journal-export-btn"', head.replace("\n", " "))
        self.assertLess(head.index("btn-journal-export"), head.index("btn-journal-close"))
        app_at = html.index("scripts/app.js")
        filt_at = html.index("scripts/journal_filter.js")
        exp_at = html.index("scripts/journal_export.js")
        desk_at = html.index("scripts/desk_only_persist.js")
        self.assertLess(app_at, filt_at)
        self.assertLess(filt_at, exp_at)
        self.assertLess(exp_at, desk_at)
        self.assertIn(".journal-export-btn", self.css)
        self.assertIn(".journal-filter", self.css)

    def test_export_module_columns_filename_and_filter_aware(self):
        js = self.export_js
        self.assertIn("JOURNAL_EXPORT_FILENAME = 'whats-news-journal.csv'", js)
        self.assertIn("whats-news-journal.csv", js)
        self.assertIn("JOURNAL_EXPORT_CORE_COLS = ['date', 'symbol', 'note', 'closed']", js)
        self.assertIn("function journalExportLoadEntries", js)
        self.assertIn("function journalExportVisibleEntries", js)
        self.assertIn("function journalExportColumns", js)
        self.assertIn("function journalCsvEscape", js)
        self.assertIn("function journalExportCell", js)
        self.assertIn("function journalEntriesToCsv", js)
        self.assertIn("function journalExportDownload", js)
        self.assertIn("function exportJournalCsv", js)
        self.assertIn("function bindJournalExportUi", js)
        self.assertIn("function bootJournalExport", js)
        self.assertIn("loadJournalEntries()", js)
        self.assertIn("getElementById('journal-filter')", js)
        self.assertIn("getElementById('btn-journal-export')", js)
        self.assertIn("matchesJournalFilter", js)
        self.assertIn("journalFilterQuery", js)
        self.assertIn("a.download", js)
        self.assertIn("text/csv", js)
        self.assertIn("createObjectURL", js)
        load = js[js.index("function journalExportLoadEntries") : js.index("function journalExportVisibleEntries")]
        self.assertIn("loadJournalEntries()", load)
        self.assertNotIn("localStorage", load)
        vis = js[js.index("function journalExportVisibleEntries") : js.index("function journalExportColumns")]
        self.assertIn("getElementById('journal-filter')", vis)
        self.assertIn("if (!filterEl) return list.slice()", vis)
        self.assertIn("if (!q) return list.slice()", vis)
        self.assertIn("matchesJournalFilter", vis)
        cell = js[js.index("function journalExportCell") : js.index("function journalEntriesToCsv")]
        self.assertIn("slice(0, 10)", cell)
        self.assertIn("true", cell)
        self.assertIn("false", cell)
        dl = js[js.index("function journalExportDownload") : js.index("function exportJournalCsv")]
        self.assertIn("whats-news-journal.csv", js)
        self.assertIn("createElement('a')", dl)
        self.assertIn("a.download", dl)
        self.assertIn("a.click()", dl)
        bind = js[js.index("function bindJournalExportUi") : js.index("function bootJournalExport")]
        self.assertIn("exportJournalCsv", bind)
        self.assertIn("addEventListener('click'", bind)
        self.assertIn("JOURNAL_KEY = 'whats-news-journal'", self.app_js)
        self.assertIn("JOURNAL_FILTER_KEY = 'whats-news-journal-filter'", self.filt_js)
        self.assertNotIn("localStorage.setItem", js)
        self.assertNotIn("localStorage.removeItem", js)
        self.assertNotIn("JOURNAL_FILTER_KEY", js)
        self.assertNotIn("whats-news-journal-filter", js)
        self.assertNotIn("JOURNAL_KEY", js)

    def test_does_not_fetch_yahoo_or_touch_owned_surfaces(self):
        js = self.export_js.lower()
        self.assertNotIn("yahoo", js)
        self.assertNotIn("fetch(", js)
        self.assertNotIn("xmlhttprequest", js)
        self.assertNotIn("/api/", js)
        self.assertNotIn("renderportfoliotape", js)
        self.assertNotIn("tapemode", js)
        self.assertNotIn("renderallchips", js)
        self.assertNotIn("charts.js", js)
        self.assertNotIn("setup_scanner", js)
        self.assertNotIn("togglefocusmode", js)
        self.assertNotIn("setworkspace", js)
        self.assertNotIn("movesymbolselection", js)
        self.assertNotIn("journal-item-head", self.export_js)
        self.assertNotIn("journal-export", self.charts)
        self.assertNotIn("whats-news-journal.csv", self.charts)
        self.assertNotIn("journal-export", self.setup)
        self.assertNotIn("whats-news-journal.csv", self.setup)
        self.assertNotIn("btn-journal-export", self.app_js)
        self.assertNotIn("journalEntriesToCsv", self.app_js)
        self.assertNotIn("exportJournalCsv", self.filt_js)
        self.assertIn("function setupBarClickJournal", self.charts)
        self.assertIn("onChartBarClick({ freq, date })", self.charts)
        self.assertIn("class JournalDateStampTests", self.stamp_tests)
        self.assertIn("class JournalFilterTests", self.filter_tests)
        self.assertIn("function journalNoteStamp", self.app_js)
        self.assertIn("function openJournalForDate", self.app_js)
        self.assertIn("function onChartBarClick", self.app_js)
        self.assertIn("function renderPortfolioTape", self.app_js)
        self.assertIn("function renderAllChips", self.app_js)
        self.assertIn("function loadJournalEntries", self.app_js)
        self.assertIn("function matchesJournalFilter", self.filt_js)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            text = _read(path)
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        self.assertIn("not a published rating", self.export_js)


class JournalExportRoundTripTests(unittest.TestCase):
    """Node round-trip: CSV columns, filter-aware rows, filename, no persist writes."""

    def test_csv_round_trip_filter_and_filename(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        export_js = _read("scripts/journal_export.js")
        helpers = export_js[
            export_js.index("const JOURNAL_EXPORT_FILENAME") : export_js.index("function bootJournalExport")
        ]

        script = r"""
const mem = {};
const writes = [];
let filterValue = '';
let filterPresent = true;
const clicks = [];
let lastCsv = '';
let lastAnchor = null;
global.JOURNAL_EXPORT_FILENAME = 'whats-news-journal.csv';
const JOURNAL_KEY = 'whats-news-journal';
const JOURNAL_FILTER_KEY = 'whats-news-journal-filter';
const ENTRIES = [
    { id: 'AAPL-1', symbol: 'AAPL', date: '2026-08-21', note: 'held the 20 EMA', closed: false, result_r: null },
    { id: 'NVDA-1', symbol: 'NVDA', date: '2026-08-22T15:30:00.000Z', note: 'breakout, then hold', closed: true, result_r: 2.5 },
    { id: 'MSFT-1', symbol: 'MSFT', date: '2026-08-20', entry: 100, stop: 95, target: 110, r_multiple: 2, book_rs: 'A', darvas_state: 'box', closed: false, result_r: null },
    { id: 'Q-1', symbol: 'QQQ', date: '2026-08-19', note: 'he said "hold"', closed: false, result_r: null },
];
mem[JOURNAL_KEY] = JSON.stringify(ENTRIES);
mem[JOURNAL_FILTER_KEY] = 'nv';
global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem: k => { delete mem[k]; writes.push(['del', k]); },
};
function loadJournalEntries() {
    try {
        const raw = JSON.parse(localStorage.getItem(JOURNAL_KEY) || '[]');
        return Array.isArray(raw) ? raw : [];
    } catch { return []; }
}
function journalFilterQuery() {
    return (document.getElementById('journal-filter')?.value || '').trim().toLowerCase();
}
function matchesJournalFilter(symbol, note, q) {
    const needle = String(q == null ? journalFilterQuery() : q).trim().toLowerCase();
    if (!needle) return true;
    const code = String(symbol || '').toLowerCase();
    const text = String(note || '').toLowerCase();
    return code.includes(needle) || text.includes(needle);
}
global.loadJournalEntries = loadJournalEntries;
global.journalFilterQuery = journalFilterQuery;
global.matchesJournalFilter = matchesJournalFilter;
global.Blob = function Blob(parts, opts) {
    this.parts = parts;
    this.type = (opts && opts.type) || '';
};
global.URL = {
    createObjectURL(blob) { lastCsv = blob && blob.parts ? String(blob.parts[0]) : ''; return 'blob:journal-csv'; },
    revokeObjectURL() {},
};
const exportBtn = { _journalExportBound: false, handler: null, addEventListener(type, fn) { if (type === 'click') this.handler = fn; } };
global.document = {
    getElementById: id => {
        if (id === 'journal-filter') {
            if (!filterPresent) return null;
            return { get value() { return filterValue; }, set value(v) { filterValue = v; } };
        }
        if (id === 'btn-journal-export') return exportBtn;
        return null;
    },
    createElement(tag) {
        if (tag !== 'a') return {};
        lastAnchor = {
            href: '',
            download: '',
            click() { clicks.push({ href: this.href, download: this.download, csv: lastCsv }); },
            setAttribute(k, v) { this[k] = v; },
            remove() {},
        };
        return lastAnchor;
    },
    body: { appendChild() {}, removeChild() {} },
    documentElement: { appendChild() {}, removeChild() {} },
};
""" + helpers + r"""
function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

assert(JOURNAL_EXPORT_FILENAME === 'whats-news-journal.csv', 'filename constant');
assert(JOURNAL_EXPORT_CORE_COLS.join(',') === 'date,symbol,note,closed', 'core columns');

filterPresent = true;
filterValue = '';
const allCsv = journalEntriesToCsv(loadJournalEntries());
const allLines = allCsv.split('\n');
assert(allLines[0].startsWith('date,symbol,note,closed'), 'header starts with core cols: ' + allLines[0]);
assert(allLines[0].indexOf('id') >= 0, 'id extra field');
assert(allLines[0].indexOf('entry') >= 0, 'entry extra field');
assert(allLines[0].indexOf('stop') >= 0, 'stop extra field');
assert(allLines[0].indexOf('target') >= 0, 'target extra field');
assert(allLines[0].indexOf('r_multiple') >= 0, 'r_multiple extra field');
assert(allLines[0].indexOf('book_rs') >= 0, 'book_rs extra field');
assert(allLines[0].indexOf('darvas_state') >= 0, 'darvas_state extra field');
assert(allLines[0].indexOf('result_r') >= 0, 'result_r extra field');
assert(allLines.length === 5, 'header + 4 rows, got ' + allLines.length);
assert(allCsv.indexOf('AAPL') >= 0 && allCsv.indexOf('held the 20 EMA') >= 0, 'AAPL note row');
assert(allCsv.indexOf('"breakout, then hold"') >= 0, 'comma in note is quoted');
assert(allCsv.indexOf('""hold""') >= 0, 'quotes in note are escaped');
assert(allCsv.indexOf('2026-08-22') >= 0, 'ISO date sliced to calendar day');
assert(allCsv.indexOf('T15:30') < 0, 'time suffix not exported on date col');
const nvdaLine = allLines.find(l => l.indexOf('NVDA') >= 0);
assert(nvdaLine && nvdaLine.indexOf('true') >= 0, 'closed true for NVDA');
const aaplLine = allLines.find(l => l.indexOf('AAPL') >= 0);
assert(aaplLine && aaplLine.indexOf('false') >= 0, 'closed false for AAPL');
assert(allCsv.indexOf(',100,') >= 0 || allCsv.indexOf(',100') >= 0, 'setup entry price');

filterValue = 'nv';
const filtered = journalEntriesToCsv(loadJournalEntries());
const filtLines = filtered.split('\n').filter(Boolean);
assert(filtLines.length === 2, 'header + NVDA only, got ' + filtLines.length + ' ' + filtered);
assert(filtered.indexOf('NVDA') >= 0, 'NVDA kept');
assert(filtered.indexOf('AAPL') < 0, 'AAPL filtered out');
assert(filtered.indexOf('MSFT') < 0, 'MSFT filtered out');
assert(filtered.indexOf('QQQ') < 0, 'QQQ filtered out');
assert(filtered.startsWith('date,symbol,note,closed'), 'filtered header still core-first');

filterValue = '  ';
const wsCsv = journalEntriesToCsv(loadJournalEntries());
assert(wsCsv.split('\n').length === 5, 'whitespace filter exports all');

filterValue = 'no-such-ticker';
const emptyCsv = journalEntriesToCsv(loadJournalEntries());
assert(emptyCsv.split('\n').filter(Boolean).length === 1, 'no matches → header only');
assert(emptyCsv.startsWith('date,symbol,note,closed'), 'empty export still has core header');

filterPresent = false;
filterValue = 'nv';
const noBox = journalEntriesToCsv(loadJournalEntries());
assert(noBox.indexOf('AAPL') >= 0 && noBox.indexOf('NVDA') >= 0, 'missing #journal-filter exports all');

filterPresent = true;
filterValue = 'nv';
const writesBefore = writes.length;
exportJournalCsv();
assert(clicks.length === 1, 'download clicked once');
assert(clicks[0].download === 'whats-news-journal.csv', 'download filename');
assert(clicks[0].csv.indexOf('NVDA') >= 0 && clicks[0].csv.indexOf('AAPL') < 0, 'click uses live filter');
assert(writes.length === writesBefore, 'export must not write storage');
assert(mem[JOURNAL_KEY] === JSON.stringify(ENTRIES), 'entries key unchanged');
assert(mem[JOURNAL_FILTER_KEY] === 'nv', 'filter key unchanged');

bindJournalExportUi();
assert(typeof exportBtn.handler === 'function', 'click bound');
filterValue = '';
clicks.length = 0;
exportBtn.handler();
assert(clicks.length === 1, 'bound click downloads');
assert(clicks[0].download === 'whats-news-journal.csv', 'bound click filename');
assert(clicks[0].csv.indexOf('AAPL') >= 0 && clicks[0].csv.indexOf('QQQ') >= 0, 'empty box exports all');
assert(writes.length === writesBefore, 'bound click must not persist');

process.stdout.write(JSON.stringify({
    ok: true,
    filename: JOURNAL_EXPORT_FILENAME,
    entriesKey: JOURNAL_KEY,
    filterKey: JOURNAL_FILTER_KEY,
    header: allLines[0],
    filteredCount: filtLines.length - 1,
    writes: writes.length,
}));
"""
        proc = subprocess.run(
            [node, "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["filename"], EXPORT_FILENAME)
        self.assertEqual(payload["entriesKey"], JOURNAL_ENTRIES_KEY)
        self.assertEqual(payload["filterKey"], JOURNAL_FILTER_KEY)
        self.assertTrue(payload["header"].startswith("date,symbol,note,closed"))
        self.assertEqual(payload["filteredCount"], 1)
        self.assertEqual(payload["writes"], 0)


if __name__ == "__main__":
    unittest.main()
