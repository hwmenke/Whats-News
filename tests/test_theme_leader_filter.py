"""Theme leaders in the Book drawer set the watchlist filter (symbol OR group_tag)."""

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
    "scripts/theme_leader_filter.js",
    "tests/test_theme_leader_filter.py",
)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class ThemeLeaderFilterContractTests(unittest.TestCase):
    """Wrap renderThemeLeaders, click writes #watchlist-filter, heatmap still charts."""

    @classmethod
    def setUpClass(cls):
        cls.filt_js = _read("scripts/theme_leader_filter.js")
        cls.app_js = _read("scripts/app.js")
        cls.html = _read("index.html")
        cls.css = _read("styles/main.css")
        cls.charts = _read("scripts/charts.js")
        cls.setup = _read("scripts/setup_scanner.js")
        cls.vwap = _read("scripts/vwap.js")
        cls.desk = _read("scripts/desk_only_persist.js")
        cls.palette = _read("scripts/desk_palette.js")

    def test_wraps_render_theme_leaders_after_app_js(self):
        js = self.filt_js
        self.assertIn("function wrapRenderThemeLeaders", js)
        self.assertIn("function applyThemeLeaderFilter", js)
        self.assertIn("function onThemeLeadersActivate", js)
        self.assertIn("function enhanceThemeLeaderItems", js)
        self.assertIn("function bindThemeLeaderFilterUi", js)
        self.assertIn("function bootThemeLeaderFilter", js)
        wrap = js[js.index("function wrapRenderThemeLeaders") : js.index("function bootThemeLeaderFilter")]
        self.assertIn("orig.apply(this, arguments)", wrap)
        self.assertIn("enhanceThemeLeaderItems()", wrap)
        self.assertIn("g.renderThemeLeaders = renderThemeLeadersWithFilter", wrap)
        self.assertLess(wrap.index("orig.apply"), wrap.index("enhanceThemeLeaderItems()"))
        self.assertIn("_themeLeaderFilterWrapped", wrap)
        html = self.html
        self.assertIn("scripts/theme_leader_filter.js", html)
        self.assertLess(html.index("scripts/app.js"), html.index("scripts/theme_leader_filter.js"))
        self.assertLess(
            html.index("scripts/desk_only_persist.js"),
            html.index("scripts/theme_leader_filter.js"),
        )
        self.assertIn('id="theme-leaders"', html)
        self.assertIn('id="watchlist-filter"', html)
        book = html[html.index('id="book-drawer"') : html.index('id="book-drawer-backdrop"')]
        self.assertIn('id="theme-leaders"', book)
        self.assertIn("function renderThemeLeaders", self.app_js)
        orig = self.app_js[
            self.app_js.index("function renderThemeLeaders") : self.app_js.index("function renderAlertLog")
        ]
        self.assertIn("group_rollup", orig)
        self.assertIn("theme-leader-item", orig)
        self.assertIn("theme-leader-name", orig)
        self.assertNotIn("addEventListener", orig)
        self.assertNotIn("watchlist-filter", orig)
        self.assertNotIn("persistWatchlistFilter", orig)
        self.assertIn("getElementById('theme-leaders')", js)

    def test_click_sets_watchlist_filter_and_rerenders(self):
        js = self.filt_js
        apply = js[js.index("function applyThemeLeaderFilter") : js.index("function onThemeLeadersActivate")]
        self.assertIn("getElementById('watchlist-filter')", apply)
        self.assertIn("el.value = name", apply)
        self.assertIn("typeof persistWatchlistFilter === 'function'", apply)
        self.assertIn("persistWatchlistFilter()", apply)
        self.assertIn("renderSymbolList()", apply)
        self.assertIn("state.portfolioMeta", apply)
        self.assertIn("renderPortfolioTape(state.portfolioMeta)", apply)
        self.assertLess(apply.index("el.value = name"), apply.index("persistWatchlistFilter()"))
        self.assertLess(apply.index("persistWatchlistFilter()"), apply.index("renderSymbolList()"))
        self.assertNotIn("selectSymbol", apply)
        self.assertNotIn("setWorkspace", apply)
        enhance = js[js.index("function enhanceThemeLeaderItems") : js.index("function bindThemeLeaderFilterUi")]
        self.assertIn("setAttribute('role', 'button')", enhance)
        self.assertIn("tabIndex = 0", enhance)
        keys = js[js.index("function onThemeLeadersActivate") : js.index("function enhanceThemeLeaderItems")]
        self.assertIn("Enter", keys)
        self.assertIn("' '", keys)
        self.assertIn("closest('.theme-leader-item')", keys)
        self.assertIn("themeLeaderGroupName", keys)
        self.assertIn("applyThemeLeaderFilter(group)", keys)
        match = self.app_js[
            self.app_js.index("function matchesWatchlistFilter") : self.app_js.index("function filterByWatchlistQuery")
        ]
        self.assertIn("code.includes(q)", match)
        self.assertIn("tag.includes(q)", match)
        hide = self.app_js[
            self.app_js.index("function renderSymbolList") : self.app_js.index("function startTagEdit")
        ]
        self.assertIn("if (!matchesWatchlistFilter(sym.symbol, tag, q))", hide)
        self.assertIn("item.hidden = true", hide)
        self.assertIn("visibleSymbolCodes()", self.app_js)
        self.assertIn(".filter(el => !el.hidden)", self.palette)
        prep = self.app_js[
            self.app_js.index("function prepareTapeRows") : self.app_js.index("function renderPortfolioTape")
        ]
        self.assertIn("filterByWatchlistQuery(rows)", prep)
        self.assertIn("cursor: pointer", self.css)
        item_css = self.css[self.css.index(".theme-leader-item {") :]
        item_css = item_css.split("}", 1)[0]
        self.assertIn("cursor: pointer", item_css)
        self.assertIn(".theme-leader-item:focus-visible", self.css)

    def test_heatmap_click_still_selects_symbol(self):
        heat = self.app_js[
            self.app_js.index("function renderRegimeHeatmap") : self.app_js.index("function renderThemeLeaders")
        ]
        self.assertIn("selectSymbol(r.symbol)", heat)
        self.assertIn("heat-cell", heat)
        self.assertIn("regime-heatmap", heat)
        self.assertNotIn("watchlist-filter", heat)
        self.assertNotIn("renderRegimeHeatmap", self.filt_js)
        self.assertNotIn("heat-cell", self.filt_js)
        self.assertNotIn("selectSymbol", self.filt_js)
        self.assertNotIn("setWorkspace", self.filt_js)
        js = self.filt_js.lower()
        self.assertNotIn("settapemode", js)
        self.assertNotIn("settapesort", js)
        self.assertNotIn("tapesort", js)

    def test_does_not_touch_owned_surfaces(self):
        js = self.filt_js.lower()
        self.assertNotIn("yahoo", js)
        self.assertNotIn("fetch(", js)
        self.assertNotIn("xmlhttprequest", js)
        self.assertNotIn("/api/", js)
        self.assertNotIn("charts.js", js)
        self.assertNotIn("setup_scanner", js)
        self.assertNotIn("desk_only", js)
        self.assertNotIn("whats-news-desk-only", js)
        self.assertNotIn("whats-news-tape-sort", js)
        self.assertNotIn("vwap", js)
        self.assertNotIn("lastprice", js)
        self.assertNotIn("last-price", js)
        self.assertNotIn("sessionstorage", js)
        self.assertIn("function setTapeSort", self.app_js)
        self.assertIn("TAPE_SORT_KEY = 'whats-news-tape-sort'", self.app_js)
        self.assertIn("DESK_ONLY_KEY = 'whats-news-desk-only'", self.desk)
        self.assertNotIn("theme_leader_filter", self.charts)
        self.assertNotIn("theme-leader", self.charts)
        self.assertNotIn("theme_leader_filter", self.setup)
        self.assertNotIn("theme-leader", self.setup)
        self.assertNotIn("theme_leader_filter", self.vwap)
        self.assertNotIn("theme-leader", self.vwap)
        self.assertIn("function persistWatchlistFilter", self.app_js)
        self.assertIn("WATCHLIST_FILTER_KEY = 'whats-news-watchlist-filter'", self.app_js)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            text = _read(path)
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        self.assertIn("not a published rating", self.filt_js)


class ThemeLeaderFilterRoundTripTests(unittest.TestCase):
    """Node: click/keyboard write the box, persist if present, list+tape, no navigation."""

    def test_click_and_keyboard_round_trip(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        filt_js = _read("scripts/theme_leader_filter.js")
        app_js = _read("scripts/app.js")
        helpers = filt_js[
            filt_js.index("function themeLeaderGroupName") : filt_js.index("function bootThemeLeaderFilter")
        ]
        match_helpers = app_js[
            app_js.index("function watchlistFilterQuery") : app_js.index("function renderSymbolList")
        ]

        script = r"""
const mem = {};
let filterValue = '';
let listRenders = 0;
let tapeRenders = 0;
const tapeArgs = [];
let persistCalls = 0;
const selectCalls = [];
const workspaceCalls = [];
let origRenderCalls = 0;
let items = [];
let boundClick = null;
let boundKey = null;
const writes = [];

global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem: k => { delete mem[k]; writes.push(['del', k]); },
};

function makeItem(group) {
    const attrs = {};
    const item = {
        className: 'theme-leader-item',
        tabIndex: -1,
        title: '',
        querySelector(sel) {
            if (sel === '.theme-leader-name') return { textContent: group };
            return null;
        },
        setAttribute(k, v) { attrs[k] = String(v); },
        getAttribute(k) { return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null; },
        closest(sel) { return sel === '.theme-leader-item' ? item : null; },
    };
    return item;
}

const root = {
    _themeLeaderFilterBound: false,
    contains(node) { return items.indexOf(node) !== -1; },
    querySelectorAll(sel) { return sel === '.theme-leader-item' ? items : []; },
    addEventListener(type, fn) {
        if (type === 'click') boundClick = fn;
        if (type === 'keydown') boundKey = fn;
    },
};

global.document = {
    getElementById: id => {
        if (id === 'watchlist-filter') {
            return {
                get value() { return filterValue; },
                set value(v) { filterValue = v; },
            };
        }
        if (id === 'theme-leaders') return root;
        return null;
    },
};

const meta = { tape: [{ symbol: 'NVDA', group_tag: 'AI chips' }, { symbol: 'MSFT', group_tag: 'software' }] };
globalThis.state = { portfolioMeta: meta };
globalThis.renderSymbolList = () => { listRenders += 1; };
globalThis.renderPortfolioTape = (data) => { tapeRenders += 1; tapeArgs.push(data); };
globalThis.selectSymbol = (s) => { selectCalls.push(s); };
globalThis.setWorkspace = (id) => { workspaceCalls.push(id); };
globalThis.persistWatchlistFilter = () => {
    persistCalls += 1;
    if (filterValue) mem['whats-news-watchlist-filter'] = filterValue;
    else delete mem['whats-news-watchlist-filter'];
};

function origRenderThemeLeaders(data) {
    origRenderCalls += 1;
    items = (data && data.group_rollup || []).map(g => makeItem(g.group));
}
globalThis.renderThemeLeaders = origRenderThemeLeaders;
""" + helpers + match_helpers + r"""
function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

wrapRenderThemeLeaders();
globalThis.renderThemeLeaders({
    group_rollup: [
        { group: 'AI chips', n: 4, avg_change_pct: 2.1 },
        { group: 'software', n: 2, avg_change_pct: -0.4 },
    ],
});
assert(origRenderCalls === 1, 'wrap calls original render');
assert(items.length === 2, 'rows from group_rollup');
assert(items[0].getAttribute('role') === 'button', 'row is a button');
assert(items[0].tabIndex === 0, 'row is keyboard focusable');
assert((items[0].getAttribute('aria-label') || '').indexOf('AI chips') !== -1, 'aria names the group');
assert(typeof boundClick === 'function' && typeof boundKey === 'function', 'delegated listeners');

boundClick({
    type: 'click',
    target: { closest: sel => sel === '.theme-leader-item' ? items[0] : null },
    preventDefault() {},
});
assert(filterValue === 'AI chips', 'click writes the group string');
assert(persistCalls === 1, 'persistWatchlistFilter when present');
assert(mem['whats-news-watchlist-filter'] === 'AI chips', 'persist writes the box');
assert(listRenders === 1, 're-render symbol list');
assert(tapeRenders === 1 && tapeArgs[0] === meta, 'tape re-renders with portfolioMeta');
assert(selectCalls.length === 0, 'must not navigate via selectSymbol');
assert(workspaceCalls.length === 0, 'must not leave Review/Book');
assert(watchlistFilterQuery() === 'AI CHIPS', 'query is trimmed upper');
assert(matchesWatchlistFilter('NVDA', 'AI chips', watchlistFilterQuery()) === true, 'group_tag match');
assert(matchesWatchlistFilter('MSFT', 'software', watchlistFilterQuery()) === false, 'other group hidden');
assert(matchesWatchlistFilter('AICH', '', watchlistFilterQuery()) === true, 'symbol OR group_tag');
const taped = filterByWatchlistQuery(meta.tape);
assert(taped.length === 1 && taped[0].symbol === 'NVDA', 'tape follows matchesWatchlistFilter');

filterValue = '';
listRenders = 0;
tapeRenders = 0;
persistCalls = 0;
let prevented = false;
boundKey({
    type: 'keydown',
    key: 'Enter',
    target: { closest: sel => sel === '.theme-leader-item' ? items[1] : null },
    preventDefault() { prevented = true; },
});
assert(filterValue === 'software', 'Enter sets the group');
assert(prevented === true, 'Enter preventDefault');
assert(persistCalls === 1 && listRenders === 1 && tapeRenders === 1, 'keyboard same path as click');

filterValue = 'keep';
boundKey({
    type: 'keydown',
    key: 'Tab',
    target: { closest: sel => sel === '.theme-leader-item' ? items[0] : null },
    preventDefault() { throw new Error('Tab must not activate'); },
});
assert(filterValue === 'keep', 'other keys ignored');

filterValue = '';
persistCalls = 0;
prevented = false;
boundKey({
    type: 'keydown',
    key: ' ',
    target: { closest: sel => sel === '.theme-leader-item' ? items[0] : null },
    preventDefault() { prevented = true; },
});
assert(filterValue === 'AI chips', 'Space activates');
assert(prevented === true, 'Space preventDefault');

delete globalThis.persistWatchlistFilter;
filterValue = 'stale';
listRenders = 0;
tapeRenders = 0;
persistCalls = 0;
applyThemeLeaderFilter('semis');
assert(filterValue === 'semis', 'still writes the box without persist helper');
assert(persistCalls === 0, 'skip persist when missing');
assert(listRenders === 1, 'still re-renders the list');
assert(tapeRenders === 1, 'still re-renders tape when meta exists');

globalThis.state.portfolioMeta = null;
tapeRenders = 0;
listRenders = 0;
applyThemeLeaderFilter('semis');
assert(listRenders === 1, 'list still renders without meta');
assert(tapeRenders === 0, 'no tape render without portfolioMeta');

wrapRenderThemeLeaders();
const wrapped = globalThis.renderThemeLeaders;
globalThis.renderThemeLeaders({ group_rollup: [{ group: 'AI chips', n: 1, avg_change_pct: 1 }] });
assert(globalThis.renderThemeLeaders === wrapped, 'wrap is idempotent');
assert(selectCalls.length === 0 && workspaceCalls.length === 0, 'still no navigation');

process.stdout.write(JSON.stringify({
    ok: true,
    filter: filterValue,
    selectCalls,
    workspaceCalls,
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
        self.assertEqual(payload["filter"], "semis")
        self.assertEqual(payload["selectCalls"], [])
        self.assertEqual(payload["workspaceCalls"], [])


if __name__ == "__main__":
    unittest.main()
