"""Contract tests: Trade journal list filter (ticker + note, localStorage)."""

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
    "scripts/journal_filter.js",
    "tests/test_journal_filter.py",
)

STORAGE_KEY = "whats-news-journal-filter"
JOURNAL_ENTRIES_KEY = "whats-news-journal"


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class JournalFilterTests(unittest.TestCase):
    """Storage key, matching, persist/restore, HTML input, no Yahoo fetch."""

    @classmethod
    def setUpClass(cls):
        cls.filt_js = _read("scripts/journal_filter.js")
        cls.app_js = _read("scripts/app.js")
        cls.html = _read("index.html")
        cls.css = _read("styles/main.css")
        cls.charts = _read("scripts/charts.js")
        cls.setup = _read("scripts/setup_scanner.js")
        cls.stamp_tests = _read("tests/test_journal_date_stamp.py")

    def test_storage_key_is_not_journal_entries_key(self):
        js = self.filt_js
        self.assertIn("JOURNAL_FILTER_KEY = 'whats-news-journal-filter'", js)
        self.assertIn("whats-news-journal-filter", js)
        self.assertNotEqual(STORAGE_KEY, JOURNAL_ENTRIES_KEY)
        self.assertIn("localStorage.getItem(JOURNAL_FILTER_KEY)", js)
        self.assertIn("localStorage.setItem(JOURNAL_FILTER_KEY, text)", js)
        self.assertIn("localStorage.removeItem(JOURNAL_FILTER_KEY)", js)
        self.assertNotIn("localStorage.setItem(JOURNAL_KEY", js)
        self.assertNotIn(f"localStorage.setItem('{JOURNAL_ENTRIES_KEY}'", js)
        self.assertNotIn("whats-news-journal-filter", self.app_js)
        self.assertIn("JOURNAL_KEY = 'whats-news-journal'", self.app_js)

    def test_html_filter_input_exists_in_journal_drawer(self):
        html = self.html
        self.assertIn('id="journal-filter"', html)
        self.assertIn('id="journal-drawer"', html)
        drawer = html[html.index('id="journal-drawer"') : html.index('id="journal-list"')]
        self.assertIn('id="journal-filter"', drawer)
        filt = html[html.index('id="journal-filter"') : html.index('id="journal-list"')]
        self.assertIn('placeholder="Filter notes…"', filt)
        self.assertIn("aria-label=", filt)
        self.assertIn("Filter journal notes", filt)
        self.assertIn('class="journal-filter"', filt)
        self.assertIn("scripts/journal_filter.js", html)
        app_at = html.index("scripts/app.js")
        filt_at = html.index("scripts/journal_filter.js")
        self.assertLess(app_at, filt_at)
        self.assertIn(".journal-filter", self.css)
        self.assertIn(".journal-item[hidden]", self.css)

    def test_filter_matching_and_empty_shows_all(self):
        js = self.filt_js
        self.assertIn("function matchesJournalFilter", js)
        self.assertIn("function journalFilterQuery", js)
        self.assertIn("function applyJournalFilter", js)
        match = js[js.index("function matchesJournalFilter") : js.index("function applyJournalFilter")]
        self.assertIn("if (!needle) return true", match)
        self.assertIn("code.includes(needle)", match)
        self.assertIn("text.includes(needle)", match)
        self.assertIn("toLowerCase()", match)
        apply = js[js.index("function applyJournalFilter") : js.index("function journalSymbolOnWatchlist")]
        self.assertIn("item.hidden", apply)
        self.assertIn(".journal-sym", apply)
        self.assertIn(".journal-note-text", apply)
        wrap = js[js.index("function wrapJournalRender") : js.index("function wrapOpenJournal")]
        self.assertIn("orig.apply(this, arguments)", wrap)
        self.assertIn("applyJournalFilter()", wrap)
        self.assertIn("g.renderJournal = renderJournalWithFilter", wrap)
        open_wrap = js[js.index("function wrapOpenJournal") : js.index("function bootJournalFilter")]
        self.assertIn("restoreJournalFilter()", open_wrap)
        restore = js[js.index("function restoreJournalFilter") : js.index("function journalFilterQuery")]
        self.assertNotIn("localStorage.setItem", restore)
        self.assertNotIn("persistJournalFilter", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertIn("el.value = readJournalFilter()", restore)
        self.assertIn("applyJournalFilter()", restore)
        persist = js[js.index("function persistJournalFilter") : js.index("function restoreJournalFilter")]
        self.assertIn("writeJournalFilter", persist)
        handler = js[js.index("function bindJournalFilterUi") : js.index("function wrapJournalRender")]
        self.assertIn("persistJournalFilter()", handler)
        self.assertIn("applyJournalFilter()", handler)
        self.assertLess(handler.index("persistJournalFilter()"), handler.index("applyJournalFilter()"))
        # Closing / deleting / saving still go through renderJournal in app.js.
        self.assertIn("function closeJournalEntry", self.app_js)
        close_fn = self.app_js[
            self.app_js.index("function closeJournalEntry") : self.app_js.index("function deleteJournalEntry")
        ]
        del_fn = self.app_js[
            self.app_js.index("function deleteJournalEntry") : self.app_js.index("function saveJournalNote")
        ]
        save_fn = self.app_js[
            self.app_js.index("function saveJournalNote") : self.app_js.index("function renderJournal")
        ]
        self.assertIn("renderJournal()", close_fn)
        self.assertIn("renderJournal()", del_fn)
        self.assertIn("renderJournal()", save_fn)
        self.assertIn("renderJournal()", self.app_js[self.app_js.index("function openJournal()") : self.app_js.index("function journalNoteStamp")])

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
        self.assertNotIn("togglefocusmode", js)
        self.assertNotIn("setworkspace", js)
        self.assertNotIn("movesymbolselection", js)
        self.assertNotIn("journal-item-head", self.filt_js)
        self.assertNotIn("journal-filter", self.charts)
        self.assertNotIn("whats-news-journal-filter", self.charts)
        self.assertNotIn("journal-filter", self.setup)
        self.assertNotIn("whats-news-journal-filter", self.setup)
        self.assertIn("function setupBarClickJournal", self.charts)
        self.assertIn("onChartBarClick({ freq, date })", self.charts)
        self.assertIn("class JournalDateStampTests", self.stamp_tests)
        self.assertIn("function journalNoteStamp", self.app_js)
        self.assertIn("function openJournalForDate", self.app_js)
        self.assertIn("function onChartBarClick", self.app_js)
        self.assertIn("function renderPortfolioTape", self.app_js)
        self.assertIn("function renderAllChips", self.app_js)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            text = _read(path)
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        self.assertIn("not a published rating", self.filt_js)


class JournalFilterRoundTripTests(unittest.TestCase):
    """Node round-trip: persist key, restore into the box, empty shows all."""

    def test_restore_round_trip_storage_key(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        filt_js = _read("scripts/journal_filter.js")
        helpers = filt_js[
            filt_js.index("const JOURNAL_FILTER_KEY") : filt_js.index("function bootJournalFilter")
        ]

        script = r"""
const mem = {};
let filterValue = '';
const writes = [];
const items = [];
global.JOURNAL_FILTER_KEY = 'whats-news-journal-filter';
const JOURNAL_KEY = 'whats-news-journal';
global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem: k => { delete mem[k]; writes.push(['del', k]); },
};
function makeItem(symbol, note, date) {
    return {
        hidden: false,
        dataset: { date: date || '' },
        className: 'journal-item',
        querySelector(sel) {
            if (sel === '.journal-sym') return { textContent: symbol };
            if (sel === '.journal-note-text') return note ? { textContent: note } : null;
            return null;
        },
    };
}
items.push(makeItem('AAPL', 'held the 20 EMA', '2026-08-21'));
items.push(makeItem('NVDA', 'breakout note', '2026-08-22'));
items.push(makeItem('MSFT', '', '2026-08-20'));
let origRenderCalls = 0;
let origOpenCalls = 0;
globalThis.state = { symbols: [{ symbol: 'AAPL' }, { symbol: 'NVDA' }] };
globalThis.journalFocusDate = null;
globalThis.selectSymbol = () => {};
function origRenderJournal() { origRenderCalls += 1; }
function origOpenJournal() { origOpenCalls += 1; globalThis.renderJournal(); }
globalThis.renderJournal = origRenderJournal;
globalThis.openJournal = origOpenJournal;
global.document = {
    getElementById: id => {
        if (id === 'journal-filter') {
            return {
                get value() { return filterValue; },
                set value(v) { filterValue = v; },
                addEventListener() {},
            };
        }
        if (id === 'journal-list') {
            return {
                querySelectorAll: sel => sel === '.journal-item' ? items : [],
                querySelector: sel => {
                    if (sel === '.journal-filter-empty') return null;
                    if (sel === '.journal-item-focus:not([hidden])') return items.find(i => !i.hidden) || null;
                    return null;
                },
                appendChild() {},
                addEventListener() {},
            };
        }
        if (id === 'journal-date') return { value: '' };
        return null;
    },
};
global.renderJournal = function() { origRenderCalls += 1; };
global.openJournal = function() { origOpenCalls += 1; global.renderJournal(); };
""" + helpers + r"""
function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

assert(JOURNAL_FILTER_KEY === 'whats-news-journal-filter', 'storage key');
assert(JOURNAL_FILTER_KEY !== 'whats-news-journal', 'must not reuse entries key');
assert(readJournalFilter() === '', 'empty storage reads as empty string');
assert(journalFilterQuery() === '', 'empty box is empty query');
assert(matchesJournalFilter('AAPL', 'held the 20 EMA', '') === true, 'empty query matches all');
assert(matchesJournalFilter('AAPL', 'held the 20 EMA', '  ') === true, 'whitespace query matches all');
assert(matchesJournalFilter('AAPL', 'held the 20 EMA', 'aap') === true, 'ticker substring');
assert(matchesJournalFilter('AAPL', 'held the 20 EMA', 'AAP') === true, 'case-insensitive ticker');
assert(matchesJournalFilter('NVDA', 'held the 20 EMA', 'held') === true, 'note substring');
assert(matchesJournalFilter('NVDA', 'Breakout Note', 'BREAK') === true, 'case-insensitive note');
assert(matchesJournalFilter('AAPL', 'held the 20 EMA', 'msft') === false, 'non-match');
assert(matchesJournalFilter('MSFT', '', 'msf') === true, 'setup card matches ticker only');
assert(matchesJournalFilter('MSFT', '', 'held') === false, 'setup card without note text');

filterValue = 'nv';
persistJournalFilter();
assert(mem[JOURNAL_FILTER_KEY] === 'nv', 'persist writes raw box text');
assert(!Object.prototype.hasOwnProperty.call(mem, JOURNAL_KEY), 'must not write journal entries key');
assert(journalFilterQuery() === 'nv', 'query is trimmed lower');
applyJournalFilter();
assert(items[0].hidden === true, 'AAPL hidden');
assert(items[1].hidden === false, 'NVDA visible');
assert(items[2].hidden === true, 'MSFT hidden');

const writesAfterPersist = writes.length;
filterValue = '';
items.forEach(i => { i.hidden = false; });
restoreJournalFilter();
assert(filterValue === 'nv', 'reload restores the box');
assert(journalFilterQuery() === 'nv', 'restored query is live');
assert(items[1].hidden === false && items[0].hidden === true, 'restore re-applies filter');
assert(writes.length === writesAfterPersist, 'restore must not write storage');
assert(!Object.prototype.hasOwnProperty.call(mem, JOURNAL_KEY), 'restore must not touch entries');

wrapJournalRender();
origRenderCalls = 0;
items.forEach(i => { i.hidden = false; });
globalThis.renderJournal();
assert(origRenderCalls === 1, 'wrap calls original render');
assert(items[0].hidden === true && items[1].hidden === false, 're-render keeps filter');

wrapOpenJournal();
filterValue = 'stale';
localStorage.setItem(JOURNAL_FILTER_KEY, '  nvda  ');
const writesBeforeOpen = writes.length;
globalThis.openJournal();
assert(filterValue === '  nvda  ', 'open restores box as-is');
assert(journalFilterQuery() === 'nvda', 'open query trims');
assert(origOpenCalls === 1, 'open wrap calls original');
assert(writes.length === writesBeforeOpen, 'open restore must not persist');

filterValue = '';
persistJournalFilter();
assert(!Object.prototype.hasOwnProperty.call(mem, JOURNAL_FILTER_KEY), 'empty filter removes the key');
assert(readJournalFilter() === '', 'cleared key reads empty');
assert(matchesJournalFilter('AAPL', 'held', journalFilterQuery()) === true, 'cleared filter shows all');
applyJournalFilter();
assert(items.every(i => i.hidden === false), 'empty box unhides every row');

filterValue = '   ';
persistJournalFilter();
assert(mem[JOURNAL_FILTER_KEY] === '   ', 'whitespace-only still persists the box');
assert(journalFilterQuery() === '', 'whitespace-only query is empty = show all');

localStorage.setItem(JOURNAL_KEY, '[{"id":"keep"}]');
persistJournalFilter();
assert(mem[JOURNAL_KEY] === '[{"id":"keep"}]', 'filter persist leaves journal entries untouched');

process.stdout.write(JSON.stringify({
    ok: true,
    key: JOURNAL_FILTER_KEY,
    entriesKey: JOURNAL_KEY,
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
        self.assertEqual(payload["entriesKey"], JOURNAL_ENTRIES_KEY)
        self.assertEqual(payload["restoredBox"], "nv")


if __name__ == "__main__":
    unittest.main()
