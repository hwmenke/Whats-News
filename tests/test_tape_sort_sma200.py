"""Contract tests: tape chips sort by SMA200 distance, then back to default."""

import json
import os
import re
import shutil
import subprocess
import tempfile
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
    "tests/test_tape_sort_sma200.py",
)


def _chunk(src, header, until):
    return src[src.index(header) : src.index(until)]


_NODE_SORT_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');

function extractFn(name) {
    const header = 'function ' + name;
    const start = src.indexOf(header);
    if (start < 0) throw new Error('missing ' + name);
    const brace = src.indexOf('{', start);
    let depth = 0;
    let inStr = null;
    let escape = false;
    for (let i = brace; i < src.length; i++) {
        const ch = src[i];
        if (inStr) {
            if (escape) { escape = false; continue; }
            if (ch === '\\') { escape = true; continue; }
            if (ch === inStr) { inStr = null; continue; }
            continue;
        }
        if (ch === '"' || ch === "'" || ch === '`') { inStr = ch; continue; }
        if (ch === '{') depth++;
        else if (ch === '}') {
            depth--;
            if (depth === 0) return src.slice(start, i + 1);
        }
    }
    throw new Error('unclosed ' + name);
}

const slice = [
    extractFn('tapeSma200Dist'),
    extractFn('sortTapeRows'),
    extractFn('prepareTapeRows'),
    extractFn('watchlistFilterQuery'),
    extractFn('matchesWatchlistFilter'),
    extractFn('filterByWatchlistQuery'),
    extractFn('setPressed'),
    extractFn('setTapeSort'),
    extractFn('normalizeTapeSort'),
    extractFn('readTapeSort'),
    extractFn('writeTapeSort'),
    extractFn('persistTapeSort'),
    extractFn('restoreTapeSort'),
].join('\n');

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

function makeClassList(el) {
    const classes = new Set((el.className || '').split(/\s+/).filter(Boolean));
    return {
        contains(name) { return classes.has(name); },
        add(name) { classes.add(name); el.className = [...classes].join(' '); },
        remove(name) { classes.delete(name); el.className = [...classes].join(' '); },
        toggle(name, on) {
            if (on === undefined) {
                if (classes.has(name)) classes.delete(name); else classes.add(name);
            } else if (on) classes.add(name); else classes.delete(name);
            el.className = [...classes].join(' ');
            return classes.has(name);
        },
    };
}

function makeBtn(sort, active) {
    const el = {
        dataset: { sort },
        className: active ? 'tape-sort-btn active' : 'tape-sort-btn',
        attrs: { 'aria-pressed': active ? 'true' : 'false' },
        setAttribute(k, v) { this.attrs[k] = String(v); },
        getAttribute(k) { return this.attrs[k]; },
    };
    el.classList = makeClassList(el);
    return el;
}

let filterValue = '';
const defaultBtn = makeBtn('default', true);
const smaBtn = makeBtn('sma200', false);
let tapeRenders = 0;
const storeWrites = [];

const sandbox = {
    TAPE_SORT_KEY: 'whats-news-tape-sort',
    state: { tapeSort: 'default', portfolioMeta: { tape: [{}] } },
    document: {
        getElementById(id) {
            if (id === 'watchlist-filter') {
                return { get value() { return filterValue; } };
            }
            return null;
        },
        querySelectorAll(sel) {
            if (sel === '.tape-sort-btn') return [defaultBtn, smaBtn];
            if (sel === '.tape-mode-btn') throw new Error('setTapeSort must not query tape-mode-btn');
            return [];
        },
    },
    localStorage: {
        getItem() { return null; },
        setItem(k, v) { storeWrites.push(['set', k, String(v)]); },
        removeItem(k) { storeWrites.push(['del', k]); },
    },
    renderPortfolioTape() { tapeRenders += 1; },
};

vm.createContext(sandbox);
vm.runInContext(slice, sandbox);

const rows = [
    { symbol: 'AAPL', dist_sma200_pct: 2.0, group_tag: 'mega' },
    { symbol: 'NVDA', dist_sma200_pct: 18.5, group_tag: 'chips' },
    { symbol: 'MISS', dist_sma200_pct: null, group_tag: '' },
    { symbol: 'NVDL', dist_sma200_pct: -3.2, group_tag: 'chips' },
    { symbol: 'MSFT', dist_sma200_pct: 8.1, group_tag: 'mega' },
];

function codes(list) { return list.map(r => r.symbol).join(','); }

sandbox.state.tapeSort = 'default';
assert(codes(sandbox.sortTapeRows(rows)) === 'AAPL,NVDA,MISS,NVDL,MSFT', 'default keeps API order');
assert(sandbox.tapeSma200Dist(rows[1]) === 18.5, 'numeric dist');
assert(sandbox.tapeSma200Dist(rows[2]) === null, 'null dist');
assert(sandbox.tapeSma200Dist({ dist_sma200_pct: 'nope' }) === null, 'non-finite dist');

sandbox.state.tapeSort = 'sma200';
assert(codes(sandbox.sortTapeRows(rows)) === 'NVDA,MSFT,AAPL,NVDL,MISS', 'sma200 desc, missing last');

sandbox.state.tapeSort = 'default';
assert(codes(sandbox.sortTapeRows(rows)) === 'AAPL,NVDA,MISS,NVDL,MSFT', 'back to default order');

filterValue = '';
assert(sandbox.matchesWatchlistFilter('AAPL', 'mega', '') === true, 'empty query matches all');
assert(codes(sandbox.filterByWatchlistQuery(rows)) === 'AAPL,NVDA,MISS,NVDL,MSFT', 'empty filter keeps tape');

filterValue = 'nv';
assert(sandbox.watchlistFilterQuery() === 'NV', 'query is trimmed upper');
assert(sandbox.matchesWatchlistFilter('NVDA', '', 'NV') === true, 'ticker match');
assert(sandbox.matchesWatchlistFilter('AAPL', '', 'NV') === false, 'non-match');
assert(sandbox.matchesWatchlistFilter('AAPL', 'NVIDIA peers', 'NV') === true, 'group tag match');

sandbox.state.tapeSort = 'default';
assert(codes(sandbox.prepareTapeRows(rows)) === 'NVDA,NVDL', 'filter then default order');

sandbox.state.tapeSort = 'sma200';
assert(codes(sandbox.prepareTapeRows(rows)) === 'NVDA,NVDL', 'filter then sma200 (NVDA above NVDL)');

filterValue = 'mega';
sandbox.state.tapeSort = 'sma200';
assert(codes(sandbox.prepareTapeRows(rows)) === 'MSFT,AAPL', 'filter then sort, not the reverse');

filterValue = '';
sandbox.state.tapeSort = 'sma200';
const filteredOnly = sandbox.filterByWatchlistQuery(rows);
assert(codes(filteredOnly) === 'AAPL,NVDA,MISS,NVDL,MSFT', 'filter does not sort');

tapeRenders = 0;
sandbox.setTapeSort('sma200');
assert(sandbox.state.tapeSort === 'sma200', 'setTapeSort stores sma200');
assert(smaBtn.getAttribute('aria-pressed') === 'true', '200 pressed');
assert(defaultBtn.getAttribute('aria-pressed') === 'false', 'Default unpressed');
assert(smaBtn.classList.contains('active') === true, '200 active class');
assert(defaultBtn.classList.contains('active') === false, 'Default inactive class');
assert(tapeRenders === 1, 'setTapeSort re-renders tape');

sandbox.setTapeSort('default');
assert(sandbox.state.tapeSort === 'default', 'back to default');
assert(defaultBtn.getAttribute('aria-pressed') === 'true', 'Default pressed again');
assert(smaBtn.getAttribute('aria-pressed') === 'false', '200 unpressed again');
assert(tapeRenders === 2, 'default click re-renders');
assert(storeWrites.length === 2, 'setTapeSort persists each click');
assert(storeWrites[0][0] === 'set' && storeWrites[0][1] === 'whats-news-tape-sort' && storeWrites[0][2] === 'sma200', 'persist sma200');
assert(storeWrites[1][0] === 'set' && storeWrites[1][1] === 'whats-news-tape-sort' && storeWrites[1][2] === 'default', 'persist default');
assert(!storeWrites.some(w => w[1] !== 'whats-news-tape-sort'), 'must not write setup-sort or overlay keys');

process.stdout.write(JSON.stringify({
    ok: true,
    defaultOrder: 'AAPL,NVDA,MISS,NVDL,MSFT',
    sma200Order: 'NVDA,MSFT,AAPL,NVDL,MISS',
}));
"""


class TapeSortSma200ContractTests(unittest.TestCase):
    """Tiny Default/200 control; client-side sort; filter still applies; j/k unchanged."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "scripts", "app.js"), encoding="utf-8") as fh:
            cls.app_js = fh.read()
        with open(os.path.join(ROOT, "scripts", "desk_palette.js"), encoding="utf-8") as fh:
            cls.palette = fh.read()
        with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as fh:
            cls.html = fh.read()
        with open(os.path.join(ROOT, "styles", "main.css"), encoding="utf-8") as fh:
            cls.css = fh.read()

    def test_control_near_tape_and_default_state(self):
        html = self.html
        tape = html[html.index('id="portfolio-tape"') : html.index('id="book-drawer"')]
        self.assertIn('class="tape-sort"', tape)
        self.assertIn('aria-label="Tape sort"', tape)
        self.assertIn('data-sort="default"', tape)
        self.assertIn('data-sort="sma200"', tape)
        self.assertIn("not a published rating", tape)
        self.assertLess(tape.index("tape-mode"), tape.index("tape-sort"))
        self.assertIn('class="tape-sort-btn active"', tape)
        self.assertIn('aria-pressed="true"', tape[tape.index("data-sort=\"default\"") :])
        self.assertNotIn("tape-mode-btn", tape[tape.index("tape-sort") :])

        js = self.app_js
        self.assertIn("tapeSort: 'default'", js)
        self.assertIn("function setTapeSort", js)
        self.assertIn("function sortTapeRows", js)
        self.assertIn("function prepareTapeRows", js)
        self.assertIn("function tapeSma200Dist", js)
        self.assertIn("querySelectorAll('.tape-sort-btn')", js)
        self.assertIn("setTapeSort(state.tapeSort)", js)
        set_sort = js[js.index("function setTapeSort") : js.index("function renderRegimeHeatmap")]
        self.assertIn("persistTapeSort()", set_sort)
        self.assertNotIn("sessionStorage", set_sort)
        self.assertIn("mode === 'sma200' ? 'sma200' : 'default'", set_sort)
        self.assertNotIn("whats-news-setup-sort", set_sort)
        self.assertNotIn("whats-news-chart-overlays", set_sort)
        self.assertNotIn("whats-news-chart-packs", set_sort)

        css = self.css
        self.assertIn(".tape-sort {", css)
        self.assertIn(".tape-sort-btn.active", css)

        mode = js[js.index("function setTapeMode") : js.index("function setTapeSort")]
        self.assertIn("querySelectorAll('.tape-mode-btn')", mode)
        self.assertNotIn("tape-sort-btn", mode)

    def test_all_breakout_alerts_use_prepare_then_filter(self):
        js = self.app_js
        all_chips = _chunk(js, "function renderAllChips", "function renderBreakoutChips")
        self.assertIn("prepareTapeRows(tapeAll)", all_chips)
        brk = _chunk(js, "function renderBreakoutChips", "function renderAlertChips")
        self.assertIn("prepareTapeRows(data.breakout_queue || [])", brk)
        alerts = _chunk(js, "function renderAlertChips", "function setPressed")
        self.assertIn("prepareTapeRows((data.tape || data.symbols || []).filter(r => r.alert))", alerts)

        prep = _chunk(js, "function prepareTapeRows", "function renderPortfolioTape")
        self.assertIn("sortTapeRows(filterByWatchlistQuery(rows))", prep)

        sort = _chunk(js, "function sortTapeRows", "function prepareTapeRows")
        self.assertIn("tapeSma200Dist", sort)
        self.assertIn("vb - va", sort)
        self.assertIn("visibleSymbolCodes()", sort)

        dist = _chunk(js, "function tapeSma200Dist", "function sortTapeRows")
        self.assertIn("dist_sma200_pct", dist)
        self.assertIn("v == null", dist)

    def test_filter_then_sort_and_jk_walks_visible_list(self):
        js = self.app_js
        match = _chunk(js, "function matchesWatchlistFilter", "function filterByWatchlistQuery")
        self.assertIn("if (!q) return true;", match)
        self.assertIn("code.includes(q)", match)

        filt = _chunk(js, "function filterByWatchlistQuery", "function renderSymbolList")
        self.assertIn("if (!q) return rows || [];", filt)

        hide = _chunk(js, "function renderSymbolList", "function startTagEdit")
        self.assertIn("if (!matchesWatchlistFilter(sym.symbol, tag, q))", hide)
        self.assertIn("item.hidden = true", hide)

        move = _chunk(js, "function moveSymbolSelection", "function saveWatchlistPreset")
        self.assertIn("visibleSymbolCodes()", move)
        self.assertNotIn("prepareTapeRows", move)
        self.assertNotIn("sortTapeRows", move)
        self.assertIn("function visibleSymbolCodes", self.palette)
        self.assertIn(".filter(el => !el.hidden)", self.palette)

        handler = js[js.index("getElementById('watchlist-filter')?.addEventListener('input'") :]
        handler = handler.split("document.getElementById('new-symbol-input')", 1)[0]
        self.assertIn("renderSymbolList()", handler)
        self.assertIn("renderPortfolioTape(state.portfolioMeta)", handler)
        self.assertLess(handler.index("renderSymbolList()"), handler.index("renderPortfolioTape"))

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        tape = self.html[self.html.index("tape-sort") : self.html.index("id=\"tape-book-news\"")]
        self.assertIn("not a published rating", tape)
        self.assertIn("not a published rating", self.app_js)

    def test_sort_filter_and_default_restore_in_node(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        src = os.path.join(ROOT, "scripts", "app.js")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_SORT_SCRIPT)
            runner = fh.name
        try:
            proc = subprocess.run(
                [node, runner, src],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            os.unlink(runner)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["defaultOrder"], "AAPL,NVDA,MISS,NVDL,MSFT")
        self.assertEqual(payload["sma200Order"], "NVDA,MSFT,AAPL,NVDL,MISS")


class TapeSortPersistTests(unittest.TestCase):
    """Default/200 tape sort survives reload via whats-news-tape-sort."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "scripts", "app.js"), encoding="utf-8") as fh:
            cls.app_js = fh.read()
        with open(os.path.join(ROOT, "scripts", "desk_palette.js"), encoding="utf-8") as fh:
            cls.palette = fh.read()
        with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as fh:
            cls.html = fh.read()
        with open(os.path.join(ROOT, "scripts", "charts.js"), encoding="utf-8") as fh:
            cls.charts = fh.read()
        with open(os.path.join(ROOT, "scripts", "setup_scanner.js"), encoding="utf-8") as fh:
            cls.setup = fh.read()
        with open(os.path.join(ROOT, "scripts", "journal_filter.js"), encoding="utf-8") as fh:
            cls.journal = fh.read()
        with open(os.path.join(ROOT, "scripts", "vwap.js"), encoding="utf-8") as fh:
            cls.vwap = fh.read()

    def test_storage_key_restore_before_first_tape_render(self):
        js = self.app_js
        self.assertIn("TAPE_SORT_KEY = 'whats-news-tape-sort'", js)
        self.assertIn("whats-news-tape-sort", js)
        self.assertIn("function normalizeTapeSort", js)
        self.assertIn("function readTapeSort", js)
        self.assertIn("function writeTapeSort", js)
        self.assertIn("function persistTapeSort", js)
        self.assertIn("function restoreTapeSort", js)
        self.assertIn("localStorage.getItem(TAPE_SORT_KEY)", js)
        self.assertIn("localStorage.setItem(TAPE_SORT_KEY", js)
        self.assertNotIn("whats-news-setup-sort", js)
        self.assertNotIn("whats-news-chart-overlays", js)
        self.assertNotIn("whats-news-chart-packs", js)
        self.assertNotIn("sessionStorage", js[js.index("function normalizeTapeSort") : js.index("function renderRegimeHeatmap")])

        boot = js[js.index("document.addEventListener('DOMContentLoaded'") :]
        self.assertIn("restoreTapeSort()", boot)
        self.assertIn("setTapeSort(state.tapeSort)", boot)
        self.assertIn("await loadSymbols();", boot)
        self.assertLess(boot.index("restoreTapeSort()"), boot.index("setTapeSort(state.tapeSort)"))
        self.assertLess(boot.index("restoreTapeSort()"), boot.index("await loadSymbols();"))

        restore = js[js.index("function restoreTapeSort") : js.index("function renderRegimeHeatmap")]
        self.assertNotIn("localStorage.setItem", restore)
        self.assertNotIn("persistTapeSort", restore)
        self.assertNotIn("writeTapeSort", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertIn("readTapeSort()", restore)
        self.assertIn("saved || 'default'", restore)

        set_sort = js[js.index("function setTapeSort") : js.index("function normalizeTapeSort")]
        self.assertIn("persistTapeSort()", set_sort)
        self.assertNotIn("whats-news-setup-sort", set_sort)

        write = js[js.index("function writeTapeSort") : js.index("function persistTapeSort")]
        self.assertIn("localStorage.setItem(TAPE_SORT_KEY", write)
        self.assertNotIn("SETUP_SORT_STORAGE_KEY", write)
        self.assertNotIn("OVERLAYS_STORAGE_KEY", write)

        prep = js[js.index("function prepareTapeRows") : js.index("function renderPortfolioTape")]
        self.assertIn("sortTapeRows(filterByWatchlistQuery(rows))", prep)
        move = js[js.index("function moveSymbolSelection") : js.index("function saveWatchlistPreset")]
        self.assertIn("visibleSymbolCodes()", move)
        self.assertNotIn("prepareTapeRows", move)
        self.assertNotIn("sortTapeRows", move)
        self.assertIn("function visibleSymbolCodes", self.palette)

        self.assertNotIn("whats-news-tape-sort", self.charts)
        self.assertNotIn("whats-news-tape-sort", self.setup)
        self.assertNotIn("whats-news-tape-sort", self.journal)
        self.assertNotIn("whats-news-tape-sort", self.vwap)
        self.assertIn("whats-news-setup-sort", self.setup)
        self.assertIn("not a published rating", self.app_js)
        tape = self.html[self.html.index("tape-sort") : self.html.index('id="tape-book-news"')]
        self.assertIn("not a published rating", tape)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")

    def test_reload_round_trip_storage_key(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        js = self.app_js
        set_pressed = js[js.index("function setPressed") : js.index("function setTapeMode")]
        persist = js[js.index("function setTapeSort") : js.index("function renderRegimeHeatmap")]
        sort_fns = js[js.index("function tapeSma200Dist") : js.index("function renderPortfolioTape")]
        filter_fns = js[js.index("function watchlistFilterQuery") : js.index("function renderSymbolList")]

        script = r"""
const TAPE_SORT_KEY = 'whats-news-tape-sort';
const SETUP_SORT = 'whats-news-setup-sort';
const OVERLAYS = 'whats-news-chart-overlays';
const PACKS = 'whats-news-chart-packs';
const mem = {};
const writes = [];
mem[SETUP_SORT] = 'adr';
mem[OVERLAYS] = '{}';
mem[PACKS] = '{}';
function makeClassList(el) {
    const classes = new Set((el.className || '').split(/\s+/).filter(Boolean));
    return {
        contains(name) { return classes.has(name); },
        add(name) { classes.add(name); el.className = [...classes].join(' '); },
        remove(name) { classes.delete(name); el.className = [...classes].join(' '); },
        toggle(name, on) {
            if (on === undefined) {
                if (classes.has(name)) classes.delete(name); else classes.add(name);
            } else if (on) classes.add(name); else classes.delete(name);
            el.className = [...classes].join(' ');
            return classes.has(name);
        },
    };
}
function makeBtn(sort, active) {
    const el = {
        dataset: { sort },
        className: active ? 'tape-sort-btn active' : 'tape-sort-btn',
        attrs: { 'aria-pressed': active ? 'true' : 'false' },
        setAttribute(k, v) { this.attrs[k] = String(v); },
        getAttribute(k) { return this.attrs[k]; },
    };
    el.classList = makeClassList(el);
    return el;
}
const defaultBtn = makeBtn('default', true);
const smaBtn = makeBtn('sma200', false);
let filterValue = '';
let tapeRenders = 0;
const localStorage = {
    getItem(k) { return Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null; },
    setItem(k, v) { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem(k) { delete mem[k]; writes.push(['del', k]); },
};
const document = {
    getElementById(id) {
        if (id === 'watchlist-filter') return { get value() { return filterValue; } };
        return null;
    },
    querySelectorAll(sel) {
        if (sel === '.tape-sort-btn') return [defaultBtn, smaBtn];
        if (sel === '.tape-mode-btn') throw new Error('tape sort persist must not query tape-mode-btn');
        return [];
    },
};
const state = { tapeSort: 'default', portfolioMeta: { tape: [{}] } };
function renderPortfolioTape() { tapeRenders += 1; }
function assert(cond, msg) { if (!cond) throw new Error(msg); }
""" + set_pressed + persist + sort_fns + filter_fns + r"""
const rows = [
    { symbol: 'AAPL', dist_sma200_pct: 2.0, group_tag: 'mega' },
    { symbol: 'NVDA', dist_sma200_pct: 18.5, group_tag: 'chips' },
    { symbol: 'MISS', dist_sma200_pct: null, group_tag: '' },
    { symbol: 'NVDL', dist_sma200_pct: -3.2, group_tag: 'chips' },
    { symbol: 'MSFT', dist_sma200_pct: 8.1, group_tag: 'mega' },
];
function codes(list) { return list.map(r => r.symbol).join(','); }

assert(TAPE_SORT_KEY === 'whats-news-tape-sort', 'storage key');
assert(normalizeTapeSort(null) === 'default', 'null → default');
assert(normalizeTapeSort('') === 'default', 'empty → default');
assert(normalizeTapeSort('junk') === 'default', 'junk → default');
assert(normalizeTapeSort('adr') === 'default', 'setup-sort value is invalid here');
assert(normalizeTapeSort(' sma200 ') === 'sma200', 'trim + case');
assert(readTapeSort() === null, 'missing key reads null');
assert(restoreTapeSort() === 'default', 'missing restore → default');
assert(state.tapeSort === 'default', 'state default on missing');
assert(defaultBtn.getAttribute('aria-pressed') === 'true', 'Default pressed when missing');
assert(smaBtn.getAttribute('aria-pressed') === 'false', '200 unpressed when missing');
assert(!Object.prototype.hasOwnProperty.call(mem, TAPE_SORT_KEY), 'restore must not create the key');
assert(writes.length === 0, 'restore of missing must not write');
assert(codes(sortTapeRows(rows)) === 'AAPL,NVDA,MISS,NVDL,MSFT', 'default keeps API order');

tapeRenders = 0;
setTapeSort('sma200');
assert(state.tapeSort === 'sma200', 'click stores sma200');
assert(mem[TAPE_SORT_KEY] === 'sma200', 'persist sma200');
assert(smaBtn.getAttribute('aria-pressed') === 'true', '200 pressed');
assert(defaultBtn.getAttribute('aria-pressed') === 'false', 'Default unpressed');
assert(tapeRenders === 1, 'setTapeSort re-renders');
assert(codes(sortTapeRows(rows)) === 'NVDA,MSFT,AAPL,NVDL,MISS', 'sma200 desc, missing last');
assert(mem[SETUP_SORT] === 'adr', 'must not clobber setup-sort');
assert(mem[OVERLAYS] === '{}', 'must not clobber overlays');
assert(mem[PACKS] === '{}', 'must not clobber packs');
assert(!writes.some(w => w[1] === SETUP_SORT || w[1] === OVERLAYS || w[1] === PACKS), 'writes stay on tape-sort key');

const writesAfterPersist = writes.length;
state.tapeSort = 'default';
tapeRenders = 0;
const restored = restoreTapeSort();
assert(restored === 'sma200', 'reload restores sma200');
assert(state.tapeSort === 'sma200', 'state matches saved');
assert(smaBtn.getAttribute('aria-pressed') === 'true', 'reload presses 200');
assert(writes.length === writesAfterPersist, 'restore must not write storage');
assert(tapeRenders === 0, 'restore does not render; boot restores before first tape render');
assert(codes(sortTapeRows(rows)) === 'NVDA,MSFT,AAPL,NVDL,MISS', 'restored sort is live before tape render');

filterValue = 'mega';
assert(codes(prepareTapeRows(rows)) === 'MSFT,AAPL', 'watchlist filter still applies first');
filterValue = '';
assert(codes(prepareTapeRows(rows)) === 'NVDA,MSFT,AAPL,NVDL,MISS', 'empty filter + restored sma200');

localStorage.setItem(TAPE_SORT_KEY, 'nope');
restoreTapeSort();
assert(state.tapeSort === 'default', 'invalid stored value → default');
assert(defaultBtn.getAttribute('aria-pressed') === 'true', 'invalid restore presses Default');

localStorage.setItem(TAPE_SORT_KEY, 'SMA200');
restoreTapeSort();
assert(state.tapeSort === 'sma200', 'stored SMA200 normalizes');

setTapeSort('nope');
assert(state.tapeSort === 'default', 'invalid click → default');
assert(mem[TAPE_SORT_KEY] === 'default', 'invalid click persists default');

process.stdout.write(JSON.stringify({
    ok: true,
    key: TAPE_SORT_KEY,
    restored: 'sma200',
    sma200Order: 'NVDA,MSFT,AAPL,NVDL,MISS',
    setupSort: mem[SETUP_SORT],
    overlays: mem[OVERLAYS],
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
        self.assertEqual(payload["key"], "whats-news-tape-sort")
        self.assertEqual(payload["restored"], "sma200")
        self.assertEqual(payload["sma200Order"], "NVDA,MSFT,AAPL,NVDL,MISS")
        self.assertEqual(payload["setupSort"], "adr")
        self.assertEqual(payload["overlays"], "{}")


if __name__ == "__main__":
    unittest.main()
