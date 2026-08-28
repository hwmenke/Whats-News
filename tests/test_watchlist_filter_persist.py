"""Reload contract: watchlist filter text persists in localStorage."""

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
    "tests/test_watchlist_filter_persist.py",
)

STORAGE_KEY = "whats-news-watchlist-filter"


class WatchlistFilterPersistContractTests(unittest.TestCase):
    """Storage key, input persist, restore after symbols load, empty = all, j/k visible."""

    @classmethod
    def setUpClass(cls):
        with open("scripts/app.js", encoding="utf-8") as fh:
            cls.app_js = fh.read()
        with open("scripts/desk_palette.js", encoding="utf-8") as fh:
            cls.palette = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            cls.html = fh.read()

    def test_storage_key_and_restore_after_symbols_load(self):
        js = self.app_js
        self.assertIn("WATCHLIST_FILTER_KEY = 'whats-news-watchlist-filter'", js)
        self.assertIn("whats-news-watchlist-filter", js)
        self.assertIn("function readWatchlistFilter", js)
        self.assertIn("function writeWatchlistFilter", js)
        self.assertIn("function persistWatchlistFilter", js)
        self.assertIn("function restoreWatchlistFilter", js)
        self.assertIn("localStorage.getItem(WATCHLIST_FILTER_KEY)", js)
        self.assertIn("localStorage.setItem(WATCHLIST_FILTER_KEY, text)", js)
        self.assertIn("localStorage.removeItem(WATCHLIST_FILTER_KEY)", js)

        boot = js[js.index("document.addEventListener('DOMContentLoaded'") :]
        self.assertIn("await loadSymbols();", boot)
        self.assertIn("restoreWatchlistFilter();", boot)
        self.assertLess(boot.index("await loadSymbols();"), boot.index("restoreWatchlistFilter();"))

        restore = js[js.index("function restoreWatchlistFilter") : js.index("function watchlistFilterQuery")]
        self.assertNotIn("localStorage.setItem", restore)
        self.assertNotIn("persistWatchlistFilter", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertIn("el.value = readWatchlistFilter()", restore)
        self.assertIn("renderSymbolList()", restore)

        handler = js[js.index("getElementById('watchlist-filter')?.addEventListener('input'") :]
        handler = handler.split("document.getElementById('new-symbol-input')", 1)[0]
        self.assertIn("persistWatchlistFilter()", handler)
        self.assertIn("renderSymbolList()", handler)
        persist_at = handler.index("persistWatchlistFilter()")
        render_at = handler.index("renderSymbolList()")
        self.assertLess(persist_at, render_at)

        self.assertIn('id="watchlist-filter"', self.html)
        self.assertNotIn("sessionStorage", js[js.index("function readWatchlistFilter") : js.index("function renderSymbolList")])

    def test_empty_filter_shows_all_and_jk_walks_visible(self):
        js = self.app_js
        match = js[js.index("function matchesWatchlistFilter") : js.index("function filterByWatchlistQuery")]
        self.assertIn("if (!q) return true;", match)
        self.assertIn("code.includes(q)", match)

        filt = js[js.index("function filterByWatchlistQuery") : js.index("function renderSymbolList")]
        self.assertIn("if (!q) return rows || [];", filt)

        hide = js[js.index("function renderSymbolList") : js.index("function startTagEdit")]
        self.assertIn("if (!matchesWatchlistFilter(sym.symbol, tag, q))", hide)
        self.assertIn("item.hidden = true", hide)

        move = js[js.index("function moveSymbolSelection") : js.index("function saveWatchlistPreset")]
        self.assertIn("visibleSymbolCodes()", move)
        self.assertIn("function visibleSymbolCodes", self.palette)
        self.assertIn(".filter(el => !el.hidden)", self.palette)

        tape_all = js[js.index("function renderAllChips") : js.index("function renderBreakoutChips")]
        self.assertIn("prepareTapeRows(tapeAll)", tape_all)
        self.assertIn("prepareTapeRows(data.breakout_queue || [])", js)
        self.assertIn("prepareTapeRows((data.tape || data.symbols || []).filter(r => r.alert))", js)
        prep = js[js.index("function prepareTapeRows") : js.index("function renderPortfolioTape")]
        self.assertIn("filterByWatchlistQuery(rows)", prep)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        self.assertIn("not a published rating", self.app_js)


class WatchlistFilterPersistRoundTripTests(unittest.TestCase):
    """Node round-trip: persist key, restore into the box, empty shows all, j/k visible only."""

    def test_restore_round_trip_storage_key(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("scripts/desk_palette.js", encoding="utf-8") as fh:
            palette = fh.read()

        helpers = app_js[
            app_js.index("function readWatchlistFilter") : app_js.index("function renderSymbolList")
        ]
        visible = palette[
            palette.index("function visibleSymbolCodes") : palette.index("function allWatchlistCodes")
        ]

        script = r"""
const mem = {};
let filterValue = '';
let listRenders = 0;
let tapeRenders = 0;
const writes = [];
global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem: k => { delete mem[k]; writes.push(['del', k]); },
};
global.document = {
    getElementById: id => {
        if (id === 'watchlist-filter') {
            return {
                get value() { return filterValue; },
                set value(v) { filterValue = v; },
            };
        }
        if (id === 'symbol-list') {
            return {
                querySelectorAll: sel => {
                    if (sel !== '.symbol-item[data-symbol]') return [];
                    return global._items || [];
                },
            };
        }
        return null;
    },
};
global.state = { portfolioMeta: { tape: [{ symbol: 'NVDA' }, { symbol: 'AAPL' }] } };
global.renderSymbolList = () => { listRenders += 1; };
global.renderPortfolioTape = () => { tapeRenders += 1; };
const WATCHLIST_FILTER_KEY = 'whats-news-watchlist-filter';
""" + helpers + visible + r"""
function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

assert(WATCHLIST_FILTER_KEY === 'whats-news-watchlist-filter', 'storage key');
assert(readWatchlistFilter() === '', 'empty storage reads as empty string');
assert(watchlistFilterQuery() === '', 'empty box is empty query');
assert(matchesWatchlistFilter('AAPL', 'tech', '') === true, 'empty query matches all');
assert(filterByWatchlistQuery([{ symbol: 'AAPL' }, { symbol: 'NVDA' }]).map(r => r.symbol).join(',') === 'AAPL,NVDA', 'empty filter keeps tape');

filterValue = 'nv';
persistWatchlistFilter();
assert(mem[WATCHLIST_FILTER_KEY] === 'nv', 'persist writes raw box text');
assert(watchlistFilterQuery() === 'NV', 'query is trimmed upper');
assert(matchesWatchlistFilter('NVDA', '', 'NV') === true, 'ticker match');
assert(matchesWatchlistFilter('AAPL', '', 'NV') === false, 'non-match hidden');
assert(matchesWatchlistFilter('AAPL', 'NVIDIA peers', 'NV') === true, 'group tag match');
const taped = filterByWatchlistQuery([{ symbol: 'NVDA' }, { symbol: 'AAPL', group_tag: 'chips' }]);
assert(taped.length === 1 && taped[0].symbol === 'NVDA', 'tape follows the same query');

const writesAfterPersist = writes.length;
filterValue = '';
listRenders = 0;
tapeRenders = 0;
const restored = restoreWatchlistFilter();
assert(filterValue === 'nv', 'reload restores the box');
assert(watchlistFilterQuery() === 'NV', 'restored query is live');
assert(listRenders === 1, 'restore re-renders the list');
assert(tapeRenders === 1, 'restore re-renders the tape when meta exists');
assert(writes.length === writesAfterPersist, 'restore must not write storage');

global._items = [
    { hidden: false, dataset: { symbol: 'NVDA' } },
    { hidden: true, dataset: { symbol: 'AAPL' } },
    { hidden: false, dataset: { symbol: 'NVDL' } },
];
const visible = visibleSymbolCodes();
assert(visible.join(',') === 'NVDA,NVDL', 'j/k walk only visible filtered rows, got ' + visible.join(','));

filterValue = '';
persistWatchlistFilter();
assert(!Object.prototype.hasOwnProperty.call(mem, WATCHLIST_FILTER_KEY), 'empty filter removes the key');
assert(readWatchlistFilter() === '', 'cleared key reads empty');
assert(matchesWatchlistFilter('AAPL', '', watchlistFilterQuery()) === true, 'cleared filter shows all');

localStorage.setItem(WATCHLIST_FILTER_KEY, '  msft  ');
filterValue = 'stale';
restoreWatchlistFilter();
assert(filterValue === '  msft  ', 'whitespace in the box is restored as-is');
assert(watchlistFilterQuery() === 'MSFT', 'query still trims so a whitespace-only box shows all names');

filterValue = '   ';
persistWatchlistFilter();
assert(mem[WATCHLIST_FILTER_KEY] === '   ', 'whitespace-only still persists the box');
assert(watchlistFilterQuery() === '', 'whitespace-only query is empty = show all');

process.stdout.write(JSON.stringify({
    ok: true,
    key: WATCHLIST_FILTER_KEY,
    visible,
    restoredBox: 'nv',
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
        self.assertEqual(payload["visible"], ["NVDA", "NVDL"])
        self.assertEqual(payload["restoredBox"], "nv")


if __name__ == "__main__":
    unittest.main()
