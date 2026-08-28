"""Contract tests: watchlist CSV export (Desk only + filter-aware, no persist-key changes)."""

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
    "scripts/watchlist_export.js",
    "tests/test_watchlist_export.py",
)

OWNED_UNTOUCHED = (
    "scripts/charts.js",
    "scripts/gap_fill.js",
    "scripts/atr_stop.js",
    "scripts/alert_log_filter.js",
)

WATCHLIST_FILTER_KEY = "whats-news-watchlist-filter"
DESK_ONLY_KEY = "whats-news-desk-only"
EXPORT_FILENAME = "whats-news-watchlist.csv"


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class WatchlistExportTests(unittest.TestCase):
    """Button, script order, columns, filename, no Yahoo, persist keys untouched."""

    @classmethod
    def setUpClass(cls):
        cls.export_js = _read("scripts/watchlist_export.js")
        cls.app_js = _read("scripts/app.js")
        cls.html = _read("index.html")
        cls.css = _read("styles/main.css")
        cls.charts = _read("scripts/charts.js")
        cls.setup = _read("scripts/setup_scanner.js")
        cls.gap = _read("scripts/gap_fill.js")
        cls.palette = _read("scripts/desk_palette.js")
        cls.filter_tests = _read("tests/test_watchlist_filter_persist.py")
        cls.desk_tests = _read("tests/test_desk_only_persist.py")

    def test_html_export_button_near_presets(self):
        html = self.html
        self.assertIn('id="btn-watchlist-export"', html)
        self.assertIn("scripts/watchlist_export.js", html)
        self.assertIn('id="btn-preset-save"', html)
        self.assertIn('id="btn-preset-load"', html)
        self.assertIn('id="chk-desk-only"', html)
        self.assertIn('id="watchlist-filter"', html)
        preset = html[html.index('class="preset-row"') : html.index('id="btn-refresh-all"')]
        self.assertIn('id="btn-preset-save"', preset)
        self.assertIn('id="btn-preset-load"', preset)
        self.assertIn('id="btn-watchlist-export"', preset)
        self.assertIn("Export", preset)
        self.assertIn("aria-label=", preset[preset.index("btn-watchlist-export") :])
        self.assertIn("Export visible watchlist as CSV", preset)
        self.assertIn("watchlist-export-btn", preset)
        self.assertIn(
            'class="btn btn-ghost btn-sm watchlist-export-btn"',
            preset.replace("\n", " "),
        )
        self.assertLess(preset.index("btn-preset-save"), preset.index("btn-preset-load"))
        self.assertLess(preset.index("btn-preset-load"), preset.index("btn-watchlist-export"))
        app_at = html.index("scripts/app.js")
        exp_at = html.index("scripts/watchlist_export.js")
        filt_at = html.index("scripts/journal_filter.js")
        jour_at = html.index("scripts/journal_export.js")
        desk_at = html.index("scripts/desk_only_persist.js")
        self.assertLess(app_at, exp_at)
        self.assertLess(exp_at, filt_at)
        self.assertLess(filt_at, jour_at)
        self.assertLess(jour_at, desk_at)
        self.assertIn(".watchlist-export-btn", self.css)
        self.assertIn(".preset-row", self.css)

    def test_export_module_columns_filename_desk_and_filter(self):
        js = self.export_js
        self.assertIn("WATCHLIST_EXPORT_FILENAME = 'whats-news-watchlist.csv'", js)
        self.assertIn("whats-news-watchlist.csv", js)
        self.assertIn("WATCHLIST_EXPORT_CORE_COLS = ['symbol', 'group_tag']", js)
        self.assertIn("function watchlistExportLoadRows", js)
        self.assertIn("function watchlistExportDeskOnlyOn", js)
        self.assertIn("function watchlistExportIsUniverseRow", js)
        self.assertIn("function watchlistExportQuery", js)
        self.assertIn("function watchlistExportRowMatches", js)
        self.assertIn("function watchlistExportVisibleRows", js)
        self.assertIn("function watchlistExportColumns", js)
        self.assertIn("function watchlistCsvEscape", js)
        self.assertIn("function watchlistExportCell", js)
        self.assertIn("function watchlistRowsToCsv", js)
        self.assertIn("function watchlistExportDownload", js)
        self.assertIn("function exportWatchlistCsv", js)
        self.assertIn("function bindWatchlistExportUi", js)
        self.assertIn("function bootWatchlistExport", js)
        self.assertIn("state.symbols", js)
        self.assertIn("getElementById('chk-desk-only')", js)
        self.assertIn("getElementById('watchlist-filter')", js)
        self.assertIn("getElementById('btn-watchlist-export')", js)
        self.assertIn("matchesWatchlistFilter", js)
        self.assertIn("watchlistFilterQuery", js)
        self.assertIn("univ:", js)
        self.assertIn("a.download", js)
        self.assertIn("text/csv", js)
        self.assertIn("createObjectURL", js)
        load = js[js.index("function watchlistExportLoadRows") : js.index("function watchlistExportDeskOnlyOn")]
        self.assertIn("state.symbols", load)
        self.assertNotIn("localStorage", load)
        self.assertNotIn("fetch(", load)
        vis = js[js.index("function watchlistExportVisibleRows") : js.index("function watchlistExportColumns")]
        self.assertIn("watchlistExportDeskOnlyOn()", vis)
        self.assertIn("watchlistExportIsUniverseRow", vis)
        self.assertIn("getElementById('watchlist-filter')", vis)
        self.assertIn("if (!filterEl) return list", vis)
        self.assertIn("if (!q) return list", vis)
        self.assertIn("watchlistExportRowMatches", vis)
        desk = js[js.index("function watchlistExportDeskOnlyOn") : js.index("function watchlistExportIsUniverseRow")]
        self.assertIn("getElementById('chk-desk-only')", desk)
        self.assertIn("state.deskOnly", desk)
        univ = js[js.index("function watchlistExportIsUniverseRow") : js.index("function watchlistExportQuery")]
        self.assertIn("univ:", univ)
        dl = js[js.index("function watchlistExportDownload") : js.index("function exportWatchlistCsv")]
        self.assertIn("createElement('a')", dl)
        self.assertIn("a.download", dl)
        self.assertIn("a.click()", dl)
        bind = js[js.index("function bindWatchlistExportUi") : js.index("function bootWatchlistExport")]
        self.assertIn("exportWatchlistCsv", bind)
        self.assertIn("addEventListener('click'", bind)
        self.assertIn("WATCHLIST_FILTER_KEY = 'whats-news-watchlist-filter'", self.app_js)
        self.assertIn("DESK_ONLY_KEY = 'whats-news-desk-only'", _read("scripts/desk_only_persist.js"))
        self.assertNotIn("localStorage.setItem", js)
        self.assertNotIn("localStorage.removeItem", js)
        self.assertNotIn("WATCHLIST_FILTER_KEY", js)
        self.assertNotIn("whats-news-watchlist-filter", js)
        self.assertNotIn("DESK_ONLY_KEY", js)
        self.assertNotIn("whats-news-desk-only", js)

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
        self.assertNotIn("gap_fill", js)
        self.assertNotIn("btn-watchlist-export", self.app_js)
        self.assertNotIn("watchlistRowsToCsv", self.app_js)
        self.assertNotIn("exportWatchlistCsv", self.app_js)
        self.assertNotIn("whats-news-watchlist.csv", self.app_js)
        self.assertNotIn("watchlist-export", self.charts)
        self.assertNotIn("whats-news-watchlist.csv", self.charts)
        self.assertNotIn("watchlist-export", self.setup)
        self.assertNotIn("whats-news-watchlist.csv", self.setup)
        self.assertNotIn("watchlist-export", self.gap)
        self.assertNotIn("whats-news-watchlist.csv", self.gap)
        for rel in OWNED_UNTOUCHED:
            path = os.path.join(ROOT, rel)
            if not os.path.isfile(path):
                continue
            text = _read(rel)
            self.assertNotIn("watchlist_export", text)
            self.assertNotIn("whats-news-watchlist.csv", text)
            self.assertNotIn("btn-watchlist-export", text)
        self.assertIn("function renderSymbolList", self.app_js)
        self.assertIn("function matchesWatchlistFilter", self.app_js)
        self.assertIn("function watchlistFilterQuery", self.app_js)
        self.assertIn("function visibleSymbolCodes", self.palette)
        self.assertIn("function loadSymbols", self.app_js)
        self.assertIn("state.deskOnly", self.app_js)
        self.assertIn("class WatchlistFilterPersistContractTests", self.filter_tests)
        self.assertIn("class DeskOnlyPersistTests", self.desk_tests)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            text = _read(path)
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        self.assertIn("not a published rating", self.export_js)


class WatchlistExportRoundTripTests(unittest.TestCase):
    """Node round-trip: CSV columns, Desk only, filter-aware rows, filename, no persist writes."""

    def test_csv_round_trip_desk_filter_and_filename(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        export_js = _read("scripts/watchlist_export.js")
        helpers = export_js[
            export_js.index("const WATCHLIST_EXPORT_FILENAME") : export_js.index("function bootWatchlistExport")
        ]

        script = r"""
const mem = {};
const writes = [];
let filterValue = '';
let filterPresent = true;
let deskChecked = true;
let deskPresent = true;
const clicks = [];
let lastCsv = '';
let lastAnchor = null;
global.WATCHLIST_EXPORT_FILENAME = 'whats-news-watchlist.csv';
const WATCHLIST_FILTER_KEY = 'whats-news-watchlist-filter';
const DESK_ONLY_KEY = 'whats-news-desk-only';
const ROWS = [
    { id: 1, symbol: 'AAPL', name: 'Apple', sector: 'Tech', group_tag: '', added_at: '2026-01-01', last_fetch: '2026-08-20', sort_order: 0 },
    { id: 2, symbol: 'NVDA', name: 'NVIDIA', sector: 'Tech', group_tag: 'AI chips', added_at: '2026-01-02', last_fetch: null, sort_order: 1 },
    { id: 3, symbol: 'MSFT', name: 'Microsoft', sector: 'Tech', group_tag: 'software', added_at: '2026-01-03', last_fetch: '2026-08-21', sort_order: 2 },
    { id: 4, symbol: 'SPY', name: 'SPDR S&P 500', sector: 'ETF', group_tag: 'univ:sp500', added_at: '2026-02-01', last_fetch: null, sort_order: 3 },
    { id: 5, symbol: 'IWM', name: 'iShares Russell', sector: 'ETF', group_tag: 'univ:r2000', added_at: '2026-02-02', last_fetch: null, sort_order: 4 },
    { id: 6, symbol: 'QQQ', name: 'Invesco "QQQ"', sector: 'ETF', group_tag: 'AI chips, mega', added_at: '2026-03-01', last_fetch: null, sort_order: 5 },
];
mem[WATCHLIST_FILTER_KEY] = 'nv';
mem[DESK_ONLY_KEY] = '1';
global.state = { symbols: ROWS.slice(), deskOnly: true };
global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem: k => { delete mem[k]; writes.push(['del', k]); },
};
function watchlistFilterQuery() {
    return (document.getElementById('watchlist-filter')?.value || '').trim().toUpperCase();
}
function matchesWatchlistFilter(symbol, groupTag, q) {
    if (!q) return true;
    const code = String(symbol || '').toUpperCase();
    const tag = String(groupTag || '').toUpperCase();
    return code.includes(q) || tag.includes(q);
}
global.watchlistFilterQuery = watchlistFilterQuery;
global.matchesWatchlistFilter = matchesWatchlistFilter;
global.Blob = function Blob(parts, opts) {
    this.parts = parts;
    this.type = (opts && opts.type) || '';
};
global.URL = {
    createObjectURL(blob) { lastCsv = blob && blob.parts ? String(blob.parts[0]) : ''; return 'blob:watchlist-csv'; },
    revokeObjectURL() {},
};
const exportBtn = { _watchlistExportBound: false, handler: null, addEventListener(type, fn) { if (type === 'click') this.handler = fn; } };
global.document = {
    getElementById: id => {
        if (id === 'watchlist-filter') {
            if (!filterPresent) return null;
            return { get value() { return filterValue; }, set value(v) { filterValue = v; } };
        }
        if (id === 'chk-desk-only') {
            if (!deskPresent) return null;
            return { get checked() { return deskChecked; }, set checked(v) { deskChecked = !!v; } };
        }
        if (id === 'btn-watchlist-export') return exportBtn;
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

assert(WATCHLIST_EXPORT_FILENAME === 'whats-news-watchlist.csv', 'filename constant');
assert(WATCHLIST_EXPORT_CORE_COLS.join(',') === 'symbol,group_tag', 'core columns');

deskPresent = true;
deskChecked = true;
filterPresent = true;
filterValue = '';
const deskCsv = watchlistRowsToCsv(state.symbols);
const deskLines = deskCsv.split('\n').filter(Boolean);
assert(deskLines[0].startsWith('symbol,group_tag'), 'header starts with core cols: ' + deskLines[0]);
assert(deskLines[0].indexOf('name') >= 0, 'name extra field');
assert(deskLines[0].indexOf('sector') >= 0, 'sector extra field');
assert(deskLines[0].indexOf('added_at') >= 0, 'added_at extra field');
assert(deskLines[0].indexOf('last_fetch') >= 0, 'last_fetch extra field');
assert(deskLines[0].indexOf('sort_order') >= 0, 'sort_order extra field');
assert(deskLines[0].indexOf('id') >= 0, 'id extra field');
assert(deskCsv.indexOf('AAPL') >= 0 && deskCsv.indexOf('NVDA') >= 0 && deskCsv.indexOf('MSFT') >= 0, 'desk names kept');
assert(deskCsv.indexOf('QQQ') >= 0, 'non-univ QQQ kept');
assert(deskCsv.indexOf('SPY') < 0 && deskCsv.indexOf('IWM') < 0, 'univ:* hidden when Desk only');
assert(deskCsv.indexOf('"AI chips, mega"') >= 0, 'comma in group_tag is quoted');
assert(deskCsv.indexOf('""QQQ""') >= 0, 'quotes in name are escaped');
assert(deskLines.length === 5, 'header + 4 desk rows, got ' + deskLines.length + ' ' + deskCsv);

deskChecked = false;
const allCsv = watchlistRowsToCsv(state.symbols);
assert(allCsv.indexOf('SPY') >= 0 && allCsv.indexOf('IWM') >= 0, 'Desk only off includes univ:*');
assert(allCsv.indexOf('univ:sp500') >= 0, 'univ tag exported when visible');
const allLines = allCsv.split('\n').filter(Boolean);
assert(allLines.length === 7, 'header + 6 rows when desk off, got ' + allLines.length);

deskChecked = true;
filterValue = 'nv';
const filtered = watchlistRowsToCsv(state.symbols);
const filtLines = filtered.split('\n').filter(Boolean);
assert(filtLines.length === 2, 'header + NVDA only, got ' + filtLines.length + ' ' + filtered);
assert(filtered.indexOf('NVDA') >= 0, 'NVDA kept');
assert(filtered.indexOf('AAPL') < 0, 'AAPL filtered out');
assert(filtered.indexOf('MSFT') < 0, 'MSFT filtered out');
assert(filtered.indexOf('SPY') < 0, 'SPY still hidden');
assert(filtered.startsWith('symbol,group_tag'), 'filtered header still core-first');

filterValue = 'AI';
const tagCsv = watchlistRowsToCsv(state.symbols);
assert(tagCsv.indexOf('NVDA') >= 0 && tagCsv.indexOf('QQQ') >= 0, 'group_tag match');
assert(tagCsv.indexOf('AAPL') < 0, 'untagged ticker hidden by group query');

filterValue = '  ';
const wsCsv = watchlistRowsToCsv(state.symbols);
assert(wsCsv.split('\n').filter(Boolean).length === 5, 'whitespace filter exports desk list');

filterValue = 'no-such-ticker';
const emptyCsv = watchlistRowsToCsv(state.symbols);
assert(emptyCsv.split('\n').filter(Boolean).length === 1, 'no matches → header only');
assert(emptyCsv.startsWith('symbol,group_tag'), 'empty export still has core header');

filterPresent = false;
filterValue = 'nv';
deskChecked = true;
const noBox = watchlistRowsToCsv(state.symbols);
assert(noBox.indexOf('AAPL') >= 0 && noBox.indexOf('NVDA') >= 0, 'missing #watchlist-filter exports desk list');
assert(noBox.indexOf('SPY') < 0, 'missing filter still respects Desk only');

filterPresent = true;
filterValue = '';
deskPresent = false;
state.deskOnly = true;
const noChkDesk = watchlistRowsToCsv(state.symbols);
assert(noChkDesk.indexOf('SPY') < 0, 'missing checkbox uses state.deskOnly true');
state.deskOnly = false;
const noChkAll = watchlistRowsToCsv(state.symbols);
assert(noChkAll.indexOf('SPY') >= 0, 'missing checkbox uses state.deskOnly false');

deskPresent = true;
deskChecked = true;
filterPresent = true;
filterValue = 'nv';
state.deskOnly = true;
const writesBefore = writes.length;
exportWatchlistCsv();
assert(clicks.length === 1, 'download clicked once');
assert(clicks[0].download === 'whats-news-watchlist.csv', 'download filename');
assert(clicks[0].csv.indexOf('NVDA') >= 0 && clicks[0].csv.indexOf('AAPL') < 0, 'click uses live filter');
assert(clicks[0].csv.indexOf('SPY') < 0, 'click respects Desk only');
assert(writes.length === writesBefore, 'export must not write storage');
assert(mem[WATCHLIST_FILTER_KEY] === 'nv', 'filter key unchanged');
assert(mem[DESK_ONLY_KEY] === '1', 'desk key unchanged');

bindWatchlistExportUi();
assert(typeof exportBtn.handler === 'function', 'click bound');
filterValue = '';
clicks.length = 0;
exportBtn.handler();
assert(clicks.length === 1, 'bound click downloads');
assert(clicks[0].download === 'whats-news-watchlist.csv', 'bound click filename');
assert(clicks[0].csv.indexOf('AAPL') >= 0 && clicks[0].csv.indexOf('QQQ') >= 0, 'empty box exports desk names');
assert(clicks[0].csv.indexOf('SPY') < 0, 'bound click still desk-only');
assert(writes.length === writesBefore, 'bound click must not persist');

const headerOnly = watchlistRowsToCsv([]);
assert(headerOnly.split('\n').filter(Boolean).length === 1, 'empty watchlist is header only');
assert(headerOnly.startsWith('symbol,group_tag'), 'empty list still has core header');

process.stdout.write(JSON.stringify({
    ok: true,
    filename: WATCHLIST_EXPORT_FILENAME,
    filterKey: WATCHLIST_FILTER_KEY,
    deskKey: DESK_ONLY_KEY,
    header: deskLines[0],
    filteredCount: filtLines.length - 1,
    deskCount: deskLines.length - 1,
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
        self.assertEqual(payload["filterKey"], WATCHLIST_FILTER_KEY)
        self.assertEqual(payload["deskKey"], DESK_ONLY_KEY)
        self.assertTrue(payload["header"].startswith("symbol,group_tag"))
        self.assertEqual(payload["filteredCount"], 1)
        self.assertEqual(payload["deskCount"], 4)
        self.assertEqual(payload["writes"], 0)


if __name__ == "__main__":
    unittest.main()
