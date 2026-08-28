"""Contract tests: Book drawer alert-log filter (ticker + alert text, localStorage)."""

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
    "scripts/alert_log_filter.js",
    "tests/test_alert_log_filter.py",
)

OWNED_OFF_LIMITS = (
    "scripts/charts.js",
    "scripts/volume_rvol.js",
    "scripts/journal_export.js",
    "scripts/setup_scanner.js",
    "scripts/spy_rs.js",
)

STORAGE_KEY = "whats-news-alert-log-filter"
ALERT_HISTORY_KEY = "wn_alert_log"


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class AlertLogFilterTests(unittest.TestCase):
    """Storage key, matching, persist/restore, HTML input, wrap, row click still selectSymbol."""

    @classmethod
    def setUpClass(cls):
        cls.filt_js = _read("scripts/alert_log_filter.js")
        cls.app_js = _read("scripts/app.js")
        cls.html = _read("index.html")
        cls.css = _read("styles/main.css")
        cls.charts = _read("scripts/charts.js")
        cls.setup = _read("scripts/setup_scanner.js")
        cls.volume = _read("scripts/volume_rvol.js")
        cls.export = _read("scripts/journal_export.js")
        cls.spy = _read("scripts/spy_rs.js")

    def test_storage_key_is_not_alert_history_key(self):
        js = self.filt_js
        self.assertIn("ALERT_LOG_FILTER_KEY = 'whats-news-alert-log-filter'", js)
        self.assertIn("whats-news-alert-log-filter", js)
        self.assertNotEqual(STORAGE_KEY, ALERT_HISTORY_KEY)
        self.assertIn("localStorage.getItem(ALERT_LOG_FILTER_KEY)", js)
        self.assertIn("localStorage.setItem(ALERT_LOG_FILTER_KEY, text)", js)
        self.assertIn("localStorage.removeItem(ALERT_LOG_FILTER_KEY)", js)
        self.assertNotIn("localStorage.setItem(key, JSON.stringify(hist))", js)
        self.assertNotIn(f"localStorage.setItem('{ALERT_HISTORY_KEY}'", js)
        self.assertNotIn("whats-news-alert-log-filter", self.app_js)
        self.assertIn("const key = 'wn_alert_log'", self.app_js)

    def test_html_filter_input_exists_in_book_drawer(self):
        html = self.html
        self.assertIn('id="alert-log-filter"', html)
        self.assertIn('id="alert-log" class="alert-log"', html)
        self.assertIn('id="book-drawer"', html)
        drawer = html[html.index('id="book-drawer"') : html.index('id="book-drawer-backdrop"')]
        self.assertIn('id="alert-log-filter"', drawer)
        self.assertIn('id="alert-log" class="alert-log"', drawer)
        panel = html[html.index("Alert log") : html.index('id="theme-leaders"')]
        self.assertIn('id="alert-log-filter"', panel)
        self.assertLess(panel.index('id="alert-log-filter"'), panel.index('id="alert-log" class="alert-log"'))
        filt = html[html.index('id="alert-log-filter"') : html.index('id="alert-log" class="alert-log"')]
        self.assertIn('placeholder="Filter alerts…"', filt)
        self.assertIn("aria-label=", filt)
        self.assertIn("Filter alert log", filt)
        self.assertIn('class="alert-log-filter"', filt)
        self.assertIn("scripts/alert_log_filter.js", html)
        app_at = html.index("scripts/app.js")
        filt_at = html.index("scripts/alert_log_filter.js")
        self.assertLess(app_at, filt_at)
        self.assertLess(html.index("scripts/heatmap_sort.js"), filt_at)
        self.assertIn(".alert-log-filter", self.css)
        self.assertIn(".alert-log-item[hidden]", self.css)
        kbd = html[html.index('id="kbd-help"') :]
        kbd = kbd.split("</dl>", 1)[0]
        self.assertNotIn("alert-log-filter", kbd)
        self.assertNotIn("whats-news-alert-log-filter", kbd)

    def test_filter_matching_and_empty_shows_all(self):
        js = self.filt_js
        self.assertIn("function matchesAlertLogFilter", js)
        self.assertIn("function alertLogFilterQuery", js)
        self.assertIn("function applyAlertLogFilter", js)
        match = js[js.index("function matchesAlertLogFilter") : js.index("function applyAlertLogFilter")]
        self.assertIn("if (!needle) return true", match)
        self.assertIn("code.includes(needle)", match)
        self.assertIn("text.includes(needle)", match)
        self.assertIn("toLowerCase()", match)
        apply = js[js.index("function applyAlertLogFilter") : js.index("function bindAlertLogFilterUi")]
        self.assertIn("item.hidden", apply)
        self.assertIn(".al-flag", apply)
        self.assertIn("dataset", apply)
        wrap = js[js.index("function wrapRenderAlertLog") : js.index("function wrapOpenBookDrawer")]
        self.assertIn("orig.apply(this, arguments)", wrap)
        self.assertIn("applyAlertLogFilter()", wrap)
        self.assertIn("g.renderAlertLog = renderAlertLogWithFilter", wrap)
        self.assertNotIn("selectSymbol", wrap)
        self.assertLess(wrap.index("orig.apply"), wrap.index("applyAlertLogFilter()"))
        open_wrap = js[js.index("function wrapOpenBookDrawer") : js.index("function bootAlertLogFilter")]
        self.assertIn("restoreAlertLogFilter()", open_wrap)
        restore = js[js.index("function restoreAlertLogFilter") : js.index("function alertLogFilterQuery")]
        self.assertNotIn("localStorage.setItem", restore)
        self.assertNotIn("persistAlertLogFilter", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertIn("el.value = readAlertLogFilter()", restore)
        self.assertIn("applyAlertLogFilter()", restore)
        persist = js[js.index("function persistAlertLogFilter") : js.index("function restoreAlertLogFilter")]
        self.assertIn("writeAlertLogFilter", persist)
        handler = js[js.index("function bindAlertLogFilterUi") : js.index("function wrapRenderAlertLog")]
        self.assertIn("persistAlertLogFilter()", handler)
        self.assertIn("applyAlertLogFilter()", handler)
        self.assertLess(handler.index("persistAlertLogFilter()"), handler.index("applyAlertLogFilter()"))
        orig = self.app_js[
            self.app_js.index("function renderAlertLog") : self.app_js.index("function openBookDrawer")
        ]
        self.assertIn("selectSymbol(el.dataset.sym)", orig)
        self.assertIn(".alert-log-item", orig)
        self.assertIn("addEventListener('click'", orig)
        self.assertNotIn("whats-news-alert-log-filter", orig)
        self.assertNotIn("alert-log-filter", orig)
        boot = js[js.index("function bootAlertLogFilter") :]
        self.assertIn("wrapRenderAlertLog()", boot)
        self.assertIn("wrapOpenBookDrawer()", boot)
        self.assertIn("bindAlertLogFilterUi()", boot)
        self.assertIn("restoreAlertLogFilter()", boot)
        self.assertLess(boot.index("wrapRenderAlertLog()"), boot.index("restoreAlertLogFilter()"))

    def test_does_not_fetch_yahoo_or_touch_owned_surfaces(self):
        js = self.filt_js.lower()
        self.assertNotIn("yahoo", js)
        self.assertNotIn("fetch(", js)
        self.assertNotIn("xmlhttprequest", js)
        self.assertNotIn("/api/", js)
        self.assertNotIn("renderportfoliotape", js)
        self.assertNotIn("tapemode", js)
        self.assertNotIn("renderallchips", js)
        self.assertNotIn("charts.js", js)
        self.assertNotIn("setup_scanner", js)
        self.assertNotIn("volume_rvol", js)
        self.assertNotIn("journal_export", js)
        self.assertNotIn("togglefocusmode", js)
        self.assertNotIn("setworkspace", js)
        self.assertNotIn("atr_stop", js)
        self.assertNotIn("gap_fill", js)
        self.assertNotIn("alert-log-filter", self.charts)
        self.assertNotIn("whats-news-alert-log-filter", self.charts)
        self.assertNotIn("alert-log-filter", self.setup)
        self.assertNotIn("whats-news-alert-log-filter", self.setup)
        self.assertNotIn("alert-log-filter", self.volume)
        self.assertNotIn("whats-news-alert-log-filter", self.volume)
        self.assertNotIn("alert-log-filter", self.export)
        self.assertNotIn("whats-news-alert-log-filter", self.export)
        self.assertNotIn("alert_log_filter", self.spy)
        self.assertIn("function renderAlertLog", self.app_js)
        self.assertIn("function selectSymbol", self.app_js)
        for rel in OWNED_OFF_LIMITS:
            text = _read(rel)
            self.assertNotIn("whats-news-alert-log-filter", text)
            self.assertNotIn("alert_log_filter", text)
        for name in ("scripts/atr_stop.js", "scripts/gap_fill.js"):
            path = os.path.join(ROOT, name)
            if os.path.exists(path):
                text = _read(name)
                self.assertNotIn("whats-news-alert-log-filter", text)
                self.assertNotIn("alert_log_filter", text)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            text = _read(path)
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        self.assertIn("not a published rating", self.filt_js)


class AlertLogFilterRoundTripTests(unittest.TestCase):
    """Node round-trip: persist key, restore into the box, empty shows all, click still selectSymbol."""

    def test_restore_round_trip_storage_key(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        filt_js = _read("scripts/alert_log_filter.js")
        helpers = filt_js[
            filt_js.index("const ALERT_LOG_FILTER_KEY") : filt_js.index("function bootAlertLogFilter")
        ]

        script = r"""
const mem = {};
let filterValue = '';
const writes = [];
const items = [];
const selected = [];
let emptyHint = null;
global.ALERT_LOG_FILTER_KEY = 'whats-news-alert-log-filter';
const ALERT_HISTORY_KEY = 'wn_alert_log';
global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem: k => { delete mem[k]; writes.push(['del', k]); },
};
function makeItem(symbol, alert) {
    const clicks = [];
    const item = {
        hidden: false,
        dataset: { sym: symbol },
        querySelector(sel) {
            if (sel === '.al-flag') return { textContent: alert };
            return null;
        },
        addEventListener(type, fn) {
            if (type === 'click') clicks.push(fn);
        },
        click() {
            clicks.forEach(fn => fn({ type: 'click' }));
        },
    };
    return item;
}
items.push(makeItem('AAPL', 'overbought'));
items.push(makeItem('NVDA', 'oversold'));
items.push(makeItem('MSFT', 'overbought'));
let origRenderCalls = 0;
let origOpenCalls = 0;
globalThis.selectSymbol = (sym) => { selected.push(sym); };
function origRenderAlertLog() {
    origRenderCalls += 1;
    items.forEach(el => {
        el.addEventListener('click', () => globalThis.selectSymbol(el.dataset.sym));
    });
}
function origOpenBookDrawer() { origOpenCalls += 1; }
globalThis.renderAlertLog = origRenderAlertLog;
globalThis.openBookDrawer = origOpenBookDrawer;
const logEl = {
    querySelectorAll: sel => sel === '.alert-log-item' ? items : [],
    querySelector: sel => {
        if (sel === '.alert-log-filter-empty') return emptyHint;
        return null;
    },
    appendChild(node) { emptyHint = node; },
};
global.document = {
    createElement: tag => ({ className: '', textContent: '', tagName: tag }),
    getElementById: id => {
        if (id === 'alert-log-filter') {
            return {
                get value() { return filterValue; },
                set value(v) { filterValue = v; },
                addEventListener() {},
            };
        }
        if (id === 'alert-log') return logEl;
        return null;
    },
};
""" + helpers + r"""
function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

assert(ALERT_LOG_FILTER_KEY === 'whats-news-alert-log-filter', 'storage key');
assert(ALERT_LOG_FILTER_KEY !== 'wn_alert_log', 'must not reuse history key');
assert(readAlertLogFilter() === '', 'empty storage reads as empty string');
assert(alertLogFilterQuery() === '', 'empty box is empty query');
assert(matchesAlertLogFilter('AAPL', 'overbought', '') === true, 'empty query matches all');
assert(matchesAlertLogFilter('AAPL', 'overbought', '  ') === true, 'whitespace query matches all');
assert(matchesAlertLogFilter('AAPL', 'overbought', 'aap') === true, 'ticker substring');
assert(matchesAlertLogFilter('AAPL', 'overbought', 'AAP') === true, 'case-insensitive ticker');
assert(matchesAlertLogFilter('NVDA', 'oversold', 'sold') === true, 'alert-text substring');
assert(matchesAlertLogFilter('NVDA', 'Overbought', 'OVER') === true, 'case-insensitive alert text');
assert(matchesAlertLogFilter('AAPL', 'overbought', 'msft') === false, 'non-match');
assert(matchesAlertLogFilter('MSFT', 'overbought', 'msf') === true, 'ticker only');
assert(matchesAlertLogFilter('MSFT', 'overbought', 'sold') === false, 'alert text miss');

filterValue = 'nv';
persistAlertLogFilter();
assert(mem[ALERT_LOG_FILTER_KEY] === 'nv', 'persist writes raw box text');
assert(!Object.prototype.hasOwnProperty.call(mem, ALERT_HISTORY_KEY), 'must not write history key');
assert(alertLogFilterQuery() === 'nv', 'query is trimmed lower');
applyAlertLogFilter();
assert(items[0].hidden === true, 'AAPL hidden');
assert(items[1].hidden === false, 'NVDA visible');
assert(items[2].hidden === true, 'MSFT hidden');

const writesAfterPersist = writes.length;
filterValue = '';
items.forEach(i => { i.hidden = false; });
restoreAlertLogFilter();
assert(filterValue === 'nv', 'reload restores the box');
assert(alertLogFilterQuery() === 'nv', 'restored query is live');
assert(items[1].hidden === false && items[0].hidden === true, 'restore re-applies filter');
assert(writes.length === writesAfterPersist, 'restore must not write storage');
assert(!Object.prototype.hasOwnProperty.call(mem, ALERT_HISTORY_KEY), 'restore must not touch history');

wrapRenderAlertLog();
origRenderCalls = 0;
items.forEach(i => { i.hidden = false; });
globalThis.renderAlertLog();
assert(origRenderCalls === 1, 'wrap calls original render');
assert(items[0].hidden === true && items[1].hidden === false, 're-render keeps filter');

selected.length = 0;
items[1].click();
assert(selected.join(',') === 'NVDA', 'visible row still selectSymbol, got ' + selected.join(','));
items[0].click();
assert(selected.join(',') === 'NVDA,AAPL', 'orig click path still bound on hidden rows too');

wrapOpenBookDrawer();
filterValue = 'stale';
localStorage.setItem(ALERT_LOG_FILTER_KEY, '  nvda  ');
const writesBeforeOpen = writes.length;
globalThis.openBookDrawer();
assert(filterValue === '  nvda  ', 'open restores box as-is');
assert(alertLogFilterQuery() === 'nvda', 'open query trims');
assert(origOpenCalls === 1, 'open wrap calls original');
assert(writes.length === writesBeforeOpen, 'open restore must not persist');
assert(items[1].hidden === false && items[0].hidden === true, 'open restore re-applies');

filterValue = '';
persistAlertLogFilter();
assert(!Object.prototype.hasOwnProperty.call(mem, ALERT_LOG_FILTER_KEY), 'empty filter removes the key');
assert(readAlertLogFilter() === '', 'cleared key reads empty');
assert(matchesAlertLogFilter('AAPL', 'overbought', alertLogFilterQuery()) === true, 'cleared filter shows all');
applyAlertLogFilter();
assert(items.every(i => i.hidden === false), 'empty box unhides every row');

filterValue = '   ';
persistAlertLogFilter();
assert(mem[ALERT_LOG_FILTER_KEY] === '   ', 'whitespace-only still persists the box');
assert(alertLogFilterQuery() === '', 'whitespace-only query is empty = show all');

localStorage.setItem(ALERT_HISTORY_KEY, '[{"symbol":"keep"}]');
persistAlertLogFilter();
assert(mem[ALERT_HISTORY_KEY] === '[{"symbol":"keep"}]', 'filter persist leaves alert history untouched');

filterValue = 'nope';
applyAlertLogFilter();
assert(items.every(i => i.hidden === true), 'non-match hides every row');
assert(emptyHint && emptyHint.textContent === 'No matching alerts', 'empty hint when nothing matches');

wrapRenderAlertLog();
const wrapped = globalThis.renderAlertLog;
globalThis.renderAlertLog();
assert(globalThis.renderAlertLog === wrapped, 'wrap is idempotent');

process.stdout.write(JSON.stringify({
    ok: true,
    key: ALERT_LOG_FILTER_KEY,
    historyKey: ALERT_HISTORY_KEY,
    restoredBox: 'nv',
    selected,
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
        self.assertEqual(payload["key"], STORAGE_KEY)
        self.assertEqual(payload["historyKey"], ALERT_HISTORY_KEY)
        self.assertEqual(payload["restoredBox"], "nv")
        self.assertEqual(payload["selected"], ["NVDA", "AAPL"])


if __name__ == "__main__":
    unittest.main()
