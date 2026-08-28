"""Reload contract: last analysis tab persists in localStorage."""

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
    "scripts/last_tab_persist.js",
    "tests/test_last_tab_persist.py",
)

OWNED_OFF_LIMITS = (
    "scripts/charts.js",
    "scripts/atr_stop.js",
    "scripts/watchlist_export.js",
    "scripts/gap_fill.js",
)

STORAGE_KEY = "whats-news-last-tab"
ALLOWED_TABS = ("charts", "stats", "knn", "dist")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class LastTabPersistTests(unittest.TestCase):
    """Storage key, wrap switchTab, restore after symbols, invalid → charts."""

    @classmethod
    def setUpClass(cls):
        cls.persist = _read("scripts/last_tab_persist.js")
        cls.app_js = _read("scripts/app.js")
        cls.html = _read("index.html")
        cls.charts = _read("scripts/charts.js")
        cls.setup = _read("scripts/setup_scanner.js")
        cls.gap = _read("scripts/gap_fill.js")

    def test_storage_key_wraps_switch_tab_and_restore_after_symbols(self):
        js = self.persist
        self.assertIn("LAST_TAB_KEY = 'whats-news-last-tab'", js)
        self.assertIn("whats-news-last-tab", js)
        self.assertIn("LAST_TAB_ALLOWED = ['charts', 'stats', 'knn', 'dist']", js)
        self.assertIn("function lastTabScannerPresent", js)
        self.assertIn("function isAllowedLastTab", js)
        self.assertIn("function normalizeLastTab", js)
        self.assertIn("function readLastTab", js)
        self.assertIn("function writeLastTab", js)
        self.assertIn("function persistLastTab", js)
        self.assertIn("function restoreLastTab", js)
        self.assertIn("function wrapSwitchTab", js)
        self.assertIn("function wrapLoadSymbols", js)
        self.assertIn("function bootLastTabPersist", js)
        self.assertIn("localStorage.getItem(LAST_TAB_KEY)", js)
        self.assertIn("localStorage.setItem(LAST_TAB_KEY, normalizeLastTab(tab))", js)
        self.assertIn("getElementById('tab-scanner')", js)
        self.assertIn("v === 'scanner'", js)
        self.assertNotIn("whats-news-last-tab", self.app_js)
        self.assertNotIn("sessionStorage", js)

        allowed = js[js.index("LAST_TAB_ALLOWED") : js.index("function lastTabScannerPresent")]
        for tab in ALLOWED_TABS:
            self.assertIn(f"'{tab}'", allowed)
        self.assertNotIn("'news'", allowed)
        self.assertNotIn("'backtest'", allowed)
        self.assertNotIn("'trend'", allowed)
        self.assertNotIn("'data-manager'", allowed)
        self.assertNotIn("'review'", allowed)

        read = js[js.index("function readLastTab") : js.index("function writeLastTab")]
        self.assertIn("if (raw == null) return 'charts'", read)
        self.assertIn("return normalizeLastTab(raw)", read)
        self.assertIn("catch", read)
        self.assertNotIn("sessionStorage", read)
        self.assertNotIn("localStorage.setItem", read)

        normalize = js[js.index("function normalizeLastTab") : js.index("function readLastTab")]
        self.assertIn("isAllowedLastTab(v) ? v : 'charts'", normalize)

        persist = js[js.index("function persistLastTab") : js.index("function restoreLastTab")]
        self.assertIn("if (!isAllowedLastTab(tabId)) return", persist)
        self.assertIn("writeLastTab(tabId)", persist)
        self.assertNotIn("'news'", persist)

        restore = js[js.index("function restoreLastTab") : js.index("function wrapSwitchTab")]
        self.assertNotIn("localStorage.setItem", restore)
        self.assertNotIn("writeLastTab", restore)
        self.assertNotIn("persistLastTab", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertIn("keepWorkspace: true", restore)
        self.assertIn("_origSwitchTab", restore)

        wrap_tab = js[js.index("function wrapSwitchTab") : js.index("function wrapLoadSymbols")]
        self.assertIn("orig.apply(this, arguments)", wrap_tab)
        self.assertIn("persistLastTab(tabId)", wrap_tab)
        self.assertIn("g.switchTab = switchTabPersist", wrap_tab)
        self.assertLess(wrap_tab.index("orig.apply"), wrap_tab.index("persistLastTab(tabId)"))
        self.assertIn("_lastTabPersistWrapped", wrap_tab)

        wrap_load = js[js.index("function wrapLoadSymbols") : js.index("function bootLastTabPersist")]
        self.assertIn("orig.apply(this, arguments)", wrap_load)
        self.assertIn("restoreLastTab()", wrap_load)
        self.assertIn("g.loadSymbols = loadSymbolsLastTab", wrap_load)
        self.assertLess(wrap_load.index("orig.apply"), wrap_load.index("restoreLastTab()"))
        self.assertIn("await orig.apply", wrap_load)

        boot = js[js.index("function bootLastTabPersist") :]
        self.assertIn("wrapSwitchTab()", boot)
        self.assertIn("wrapLoadSymbols()", boot)
        self.assertLess(boot.index("wrapSwitchTab()"), boot.index("wrapLoadSymbols()"))
        boot_fn = js[js.index("function bootLastTabPersist") : js.index("if (typeof document")]
        self.assertNotIn("restoreLastTab()", boot_fn)

        html = self.html
        self.assertIn("scripts/last_tab_persist.js", html)
        self.assertLess(html.index("scripts/app.js"), html.index("scripts/last_tab_persist.js"))
        self.assertLess(
            html.index("scripts/alert_log_filter.js"),
            html.index("scripts/last_tab_persist.js"),
        )
        self.assertIn('id="tab-scanner"', html)
        self.assertIn("onclick=\"switchTab('charts')\"", html)
        self.assertIn("onclick=\"switchTab('stats')\"", html)
        self.assertIn("onclick=\"switchTab('knn')\"", html)
        self.assertIn("onclick=\"switchTab('dist')\"", html)
        self.assertIn("onclick=\"switchTab('scanner')\"", html)

    def test_existing_workspace_and_switch_tab_contract_unchanged(self):
        app = self.app_js
        self.assertIn("WORKSPACE_KEY = 'whats-news-workspace'", app)
        self.assertIn("activeTab:    'charts'", app)
        self.assertIn("async function switchTab", app)
        self.assertIn("function setWorkspace", app)

        switch = app[app.index("async function switchTab") : app.index("function showStatsArea")]
        self.assertIn("if (tabId === 'scanner')", switch)
        self.assertIn("setWorkspace('scan')", switch)
        self.assertIn("state.activeTab = tabId", switch)
        self.assertNotIn("localStorage", switch)
        self.assertNotIn("LAST_TAB_KEY", switch)
        self.assertNotIn("whats-news-last-tab", switch)

        workspace = app[app.index("function setWorkspace") : app.index("window.setWorkspace")]
        self.assertIn("localStorage.setItem(WORKSPACE_KEY, next === 'review' ? 'chart' : next)", workspace)
        self.assertIn("switchTab('news', { keepWorkspace: true })", workspace)
        self.assertIn("switchTab('charts', { keepWorkspace: true })", workspace)
        self.assertNotIn("whats-news-last-tab", workspace)
        self.assertNotIn("LAST_TAB_KEY", workspace)

        boot = app[app.index("document.addEventListener('DOMContentLoaded'") :]
        self.assertIn("await loadSymbols()", boot)
        self.assertIn("setWorkspace('scan', { skipChart: true })", boot)
        self.assertLess(boot.index("await loadSymbols()"), boot.index("setWorkspace('scan', { skipChart: true })"))
        self.assertNotIn("whats-news-last-tab", boot)
        self.assertNotIn("restoreLastTab", boot)

        js = self.persist.lower()
        self.assertNotIn("fetch(", js)
        self.assertNotIn("/api/", js)
        self.assertNotIn("xmlhttprequest", js)
        self.assertNotIn("sessionstorage", js)
        self.assertNotIn("settapesort", js)
        self.assertNotIn("whats-news-tape-sort", js)
        self.assertNotIn("whats-news-workspace", js)
        self.assertNotIn("setworkspace", js)
        self.assertNotIn("whats-news-last-tab", self.charts)
        self.assertNotIn("whats-news-last-tab", self.setup)
        self.assertNotIn("whats-news-last-tab", self.gap)
        self.assertNotIn("last_tab_persist", self.charts)
        self.assertNotIn("last_tab_persist", self.setup)
        self.assertNotIn("last_tab_persist", self.gap)

        for rel in OWNED_OFF_LIMITS:
            path = os.path.join(ROOT, rel)
            if not os.path.isfile(path):
                continue
            text = _read(rel)
            self.assertNotIn("whats-news-last-tab", text)
            self.assertNotIn("last_tab_persist", text)

    def test_does_not_persist_review_workspace(self):
        js = self.persist
        persist = js[js.index("function persistLastTab") : js.index("function restoreLastTab")]
        self.assertNotIn("news", persist)
        self.assertNotIn("review", persist)
        allowed = js[js.index("LAST_TAB_ALLOWED") : js.index("function lastTabScannerPresent")]
        self.assertNotIn("review", allowed)
        self.assertNotIn("news", allowed)
        restore = js[js.index("function restoreLastTab") : js.index("function wrapSwitchTab")]
        self.assertIn("keepWorkspace: true", restore)
        self.assertNotIn("setWorkspace", restore)
        self.assertNotIn("'review'", restore)
        self.assertNotIn("'news'", restore)
        wrap = js[js.index("function wrapSwitchTab") : js.index("function wrapLoadSymbols")]
        self.assertIn("persistLastTab(tabId)", wrap)
        self.assertNotIn("WORKSPACE_KEY", wrap)
        header = js[: js.index("const LAST_TAB_KEY")]
        self.assertIn("Does not persist Review", header)
        self.assertIn("Chart/Scan workspaces still override layout separately", header)
        app = self.app_js
        set_ws = app[app.index("function setWorkspace") : app.index("window.setWorkspace")]
        self.assertIn("next === 'review' ? 'chart' : next", set_ws)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            text = _read(path)
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        self.assertIn("not a published rating", self.persist)


class LastTabPersistRoundTripTests(unittest.TestCase):
    """Node round-trip: persist analysis tabs, restore after symbols, invalid → charts."""

    def test_restore_round_trip_storage_key(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        persist = _read("scripts/last_tab_persist.js")
        helpers = persist[
            persist.index("const LAST_TAB_KEY") : persist.index("function bootLastTabPersist")
        ]

        script = r"""
const mem = {};
const writes = [];
const tabCalls = [];
const loadOrder = [];
let scannerEl = { id: 'tab-scanner' };
global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem: k => { delete mem[k]; writes.push(['del', k]); },
};
global.state = { activeTab: 'charts', workspace: 'chart' };
global.document = {
    getElementById: id => (id === 'tab-scanner' ? scannerEl : null),
    addEventListener: () => {},
};
async function origSwitchTab(tabId, opts) {
    const keep = !!(opts && opts.keepWorkspace);
    tabCalls.push({ tabId: String(tabId), keepWorkspace: keep });
    if (tabId === 'scanner') {
        state.workspace = 'scan';
        state.activeTab = 'charts';
        return;
    }
    if (!keep) state.workspace = 'chart';
    state.activeTab = tabId;
}
async function origLoadSymbols() {
    loadOrder.push('load');
    state.symbols = [{ symbol: 'NVDA' }];
}
globalThis.switchTab = origSwitchTab;
globalThis.loadSymbols = origLoadSymbols;
""" + helpers + r"""
function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

(async () => {
assert(LAST_TAB_KEY === 'whats-news-last-tab', 'storage key');
assert(LAST_TAB_ALLOWED.join(',') === 'charts,stats,knn,dist', 'allowed analysis tabs');
assert(readLastTab() === 'charts', 'missing key defaults charts');
assert(writes.length === 0, 'read of missing key must not write');

const restoredMissing = restoreLastTab();
assert(restoredMissing === 'charts', 'restore missing is charts');
assert(tabCalls.length === 1 && tabCalls[0].tabId === 'charts', 'restore missing calls switchTab charts');
assert(tabCalls[0].keepWorkspace === true, 'restore keeps workspace');
assert(writes.length === 0, 'restore of missing key must not write');
assert(!writes.some(w => w[1] === 'whats-news-workspace'), 'must not write workspace key');

wrapSwitchTab();
wrapLoadSymbols();
tabCalls.length = 0;

await globalThis.switchTab('stats');
assert(mem[LAST_TAB_KEY] === 'stats', 'persist stats');
assert(state.activeTab === 'stats', 'switchTab stats');

await globalThis.switchTab('knn');
assert(mem[LAST_TAB_KEY] === 'knn', 'persist knn');

await globalThis.switchTab('dist');
assert(mem[LAST_TAB_KEY] === 'dist', 'persist dist');

await globalThis.switchTab('scanner');
assert(mem[LAST_TAB_KEY] === 'scanner', 'persist scanner when tab present');

await globalThis.switchTab('news');
assert(mem[LAST_TAB_KEY] === 'scanner', 'news / Review must not persist');
assert(state.activeTab === 'news', 'news still switches');

await globalThis.switchTab('backtest');
assert(mem[LAST_TAB_KEY] === 'scanner', 'backtest must not persist');

await globalThis.switchTab('trend');
assert(mem[LAST_TAB_KEY] === 'scanner', 'trend must not persist');

await globalThis.switchTab('data-manager');
assert(mem[LAST_TAB_KEY] === 'scanner', 'data-manager must not persist');

await globalThis.switchTab('charts');
assert(mem[LAST_TAB_KEY] === 'charts', 'persist charts');
assert(!writes.some(w => w[1] !== LAST_TAB_KEY), 'must not write other storage keys');

const writesAfterToggle = writes.length;
state.activeTab = 'charts';
state.workspace = 'chart';
tabCalls.length = 0;
mem[LAST_TAB_KEY] = 'stats';
const restored = restoreLastTab();
assert(restored === 'stats', 'restore returns saved stats');
assert(tabCalls.length === 1 && tabCalls[0].tabId === 'stats', 'restore stats');
assert(tabCalls[0].keepWorkspace === true, 'restore stats keeps workspace');
assert(state.activeTab === 'stats', 'state restored to stats');
assert(state.workspace === 'chart', 'Chart workspace stays put');
assert(writes.length === writesAfterToggle, 'restore must not write');

mem[LAST_TAB_KEY] = 'knn';
state.activeTab = 'charts';
tabCalls.length = 0;
assert(restoreLastTab() === 'knn' && tabCalls[0].tabId === 'knn', 'restore knn');

mem[LAST_TAB_KEY] = 'dist';
tabCalls.length = 0;
assert(restoreLastTab() === 'dist' && tabCalls[0].tabId === 'dist', 'restore dist');

mem[LAST_TAB_KEY] = 'scanner';
state.workspace = 'chart';
tabCalls.length = 0;
assert(restoreLastTab() === 'scanner' && tabCalls[0].tabId === 'scanner', 'restore scanner if present');
assert(tabCalls[0].keepWorkspace === true, 'scanner restore keeps workspace flag');
assert(writes.length === writesAfterToggle, 'scanner restore must not persist');

mem[LAST_TAB_KEY] = 'nope';
state.activeTab = 'knn';
tabCalls.length = 0;
const invalid = restoreLastTab();
assert(invalid === 'charts', 'invalid → charts');
assert(tabCalls[0].tabId === 'charts', 'invalid restore switches charts');
assert(writes.length === writesAfterToggle, 'invalid restore must not write');

mem[LAST_TAB_KEY] = 'review';
tabCalls.length = 0;
assert(restoreLastTab() === 'charts', 'review value is invalid → charts');

mem[LAST_TAB_KEY] = 'news';
tabCalls.length = 0;
assert(restoreLastTab() === 'charts', 'news value is invalid → charts');

mem[LAST_TAB_KEY] = ' STATS ';
assert(readLastTab() === 'stats', 'trim/case normalize stats');

scannerEl = null;
mem[LAST_TAB_KEY] = 'scanner';
assert(readLastTab() === 'charts', 'scanner absent from DOM → charts');
scannerEl = { id: 'tab-scanner' };

mem[LAST_TAB_KEY] = 'knn';
state.activeTab = 'charts';
tabCalls.length = 0;
loadOrder.length = 0;
const writesBeforeLoad = writes.length;
await globalThis.loadSymbols();
assert(loadOrder.join(',') === 'load', 'orig loadSymbols ran');
assert(tabCalls.length === 1 && tabCalls[0].tabId === 'knn', 'restore after symbols');
assert(tabCalls[0].keepWorkspace === true, 'post-symbols restore keeps workspace');
assert(writes.length === writesBeforeLoad, 'wrapped load restore must not persist');
assert(state.symbols[0].symbol === 'NVDA', 'symbols still loaded');

process.stdout.write(JSON.stringify({
    ok: true,
    key: LAST_TAB_KEY,
    allowed: LAST_TAB_ALLOWED,
    lastSaved: mem[LAST_TAB_KEY],
}));
})().catch(err => { console.error(err && err.stack ? err.stack : err); process.exit(1); });
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
        self.assertEqual(payload["allowed"], list(ALLOWED_TABS))


if __name__ == "__main__":
    unittest.main()
