"""Contract tests: Book drawer heatmap Desk vs Day% sort (localStorage)."""

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
    "scripts/heatmap_sort.js",
    "tests/test_heatmap_sort.py",
)

STORAGE_KEY = "whats-news-heatmap-sort"
OWNED_OFF_LIMITS = (
    "scripts/charts.js",
    "scripts/setup_scanner.js",
    "scripts/vwap.js",
    "scripts/desk_only_persist.js",
)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class HeatmapSortTests(unittest.TestCase):
    """Desk vs Day% pills, wrap renderRegimeHeatmap, persist desk|day, cells still selectSymbol."""

    @classmethod
    def setUpClass(cls):
        cls.sort_js = _read("scripts/heatmap_sort.js")
        cls.app_js = _read("scripts/app.js")
        cls.html = _read("index.html")
        cls.css = _read("styles/main.css")
        cls.charts = _read("scripts/charts.js")
        cls.setup = _read("scripts/setup_scanner.js")
        cls.vwap = _read("scripts/vwap.js")
        cls.desk_only = _read("scripts/desk_only_persist.js")

    def test_storage_key_and_wrap_after_app_js(self):
        js = self.sort_js
        self.assertIn("HEATMAP_SORT_KEY = 'whats-news-heatmap-sort'", js)
        self.assertIn("whats-news-heatmap-sort", js)
        self.assertIn("function normalizeHeatmapSort", js)
        self.assertIn("function readHeatmapSort", js)
        self.assertIn("function writeHeatmapSort", js)
        self.assertIn("function persistHeatmapSort", js)
        self.assertIn("function restoreHeatmapSort", js)
        self.assertIn("function setHeatmapSort", js)
        self.assertIn("function sortHeatmapRows", js)
        self.assertIn("function heatmapChangePct", js)
        self.assertIn("function wrapRenderRegimeHeatmap", js)
        self.assertIn("function bootHeatmapSort", js)
        self.assertIn("localStorage.getItem(HEATMAP_SORT_KEY)", js)
        self.assertIn("localStorage.setItem(HEATMAP_SORT_KEY, normalizeHeatmapSort(mode))", js)
        self.assertNotIn("sessionStorage", js)
        self.assertNotIn("whats-news-heatmap-sort", self.app_js)
        self.assertNotIn("whats-news-tape-sort", js)
        self.assertNotIn("TAPE_SORT_KEY", js)
        self.assertNotIn("setTapeSort", js)

        html = self.html
        self.assertIn("scripts/heatmap_sort.js", html)
        self.assertLess(html.index("scripts/app.js"), html.index("scripts/heatmap_sort.js"))
        self.assertLess(html.index("scripts/desk_only_persist.js"), html.index("scripts/heatmap_sort.js"))

        wrap = js[js.index("function wrapRenderRegimeHeatmap") : js.index("function bootHeatmapSort")]
        self.assertIn("orig.apply(this, [payload].concat(args))", wrap)
        self.assertIn("g.renderRegimeHeatmap = renderRegimeHeatmapSorted", wrap)
        self.assertIn("sortHeatmapRows(src.heatmap || [])", wrap)
        self.assertNotIn("selectSymbol", wrap)
        self.assertLess(wrap.index("lastHeatmapData = src"), wrap.index("sortHeatmapRows"))

        boot = js[js.index("function bootHeatmapSort") :]
        self.assertIn("wrapRenderRegimeHeatmap()", boot)
        self.assertIn("bindHeatmapSortUi()", boot)
        self.assertIn("restoreHeatmapSort()", boot)
        self.assertLess(boot.index("wrapRenderRegimeHeatmap()"), boot.index("restoreHeatmapSort()"))

        restore = js[js.index("function restoreHeatmapSort") : js.index("function rerenderHeatmap")]
        self.assertNotIn("localStorage.setItem", restore)
        self.assertNotIn("persistHeatmapSort", restore)
        self.assertNotIn("writeHeatmapSort", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertNotIn("rerenderHeatmap", restore)
        self.assertIn("readHeatmapSort()", restore)

        set_sort = js[js.index("function setHeatmapSort") : js.index("function bindHeatmapSortUi")]
        self.assertIn("persistHeatmapSort()", set_sort)
        self.assertIn("syncHeatmapSortButtons()", set_sort)
        self.assertIn("rerenderHeatmap()", set_sort)
        self.assertLess(set_sort.index("persistHeatmapSort()"), set_sort.index("rerenderHeatmap()"))
        self.assertNotIn("sessionStorage", set_sort)

        norm = js[js.index("function normalizeHeatmapSort") : js.index("function readHeatmapSort")]
        self.assertIn("=== 'day' ? 'day' : 'desk'", norm)

    def test_control_in_heatmap_header_is_compact(self):
        html = self.html
        drawer = html[html.index('id="book-drawer"') : html.index('id="alert-log"')]
        self.assertIn('id="regime-heatmap"', drawer)
        self.assertIn('class="heatmap-sort"', drawer)
        self.assertIn('aria-label="Heatmap sort"', drawer)
        self.assertIn('data-sort="desk"', drawer)
        self.assertIn('data-sort="day"', drawer)
        self.assertIn(">Desk</button>", drawer)
        self.assertIn(">Day%</button>", drawer)
        self.assertIn("not a published rating", drawer)
        self.assertIn('class="heatmap-sort-btn active"', drawer)
        self.assertLess(drawer.index("heatmap-sort"), drawer.index('id="regime-heatmap"'))
        self.assertLess(drawer.index("Regime map (D / W)"), drawer.index("heatmap-sort-btn"))
        desk_btn = drawer[drawer.index('data-sort="desk"') : drawer.index('data-sort="day"')]
        self.assertIn('aria-pressed="true"', desk_btn)

        css = self.css
        self.assertIn(".heatmap-sort {", css)
        self.assertIn(".heatmap-sort-btn.active", css)
        self.assertIn(".heatmap-sort-head {", css)
        self.assertIn("body.workspace-review .heatmap-sort-btn", css)
        btn = css[css.index(".heatmap-sort-btn {") : css.index(".heatmap-sort-btn:hover")]
        self.assertIn("padding: 1px 6px", btn)
        self.assertIn("font-size: 9.5px", btn)
        review = css[css.index("body.workspace-review .heatmap-sort-btn") :]
        review_block = review.split("}", 1)[0]
        self.assertIn("font-size: 9px", review_block)
        self.assertNotRegex(
            css,
            r"body\.workspace-review .heatmap-sort[^}]*display:\s*none",
        )
        self.assertNotRegex(
            css,
            r"body\.focus-mode\.workspace-review .heatmap-sort[^}]*display:\s*none",
        )

    def test_orig_heatmap_keeps_api_order_and_cell_select(self):
        app = self.app_js
        heat = app[app.index("function renderRegimeHeatmap") : app.index("function renderThemeLeaders")]
        self.assertIn("data.heatmap || []", heat)
        self.assertIn("selectSymbol(r.symbol)", heat)
        self.assertNotIn(".sort(", heat)
        self.assertNotIn("sortHeatmapRows", heat)
        self.assertNotIn("whats-news-heatmap-sort", heat)
        self.assertIn("TAPE_SORT_KEY = 'whats-news-tape-sort'", app)
        self.assertIn("function setTapeSort", app)
        self.assertIn("function restoreTapeSort", app)
        sort_js = self.sort_js.lower()
        self.assertNotIn("fetch(", sort_js)
        self.assertNotIn("/api/", sort_js)
        self.assertNotIn("xmlhttprequest", sort_js)
        self.assertNotIn("yahoo", sort_js)
        self.assertIn("rows.slice()", self.sort_js)
        self.assertIn("change_pct", self.sort_js)
        dist = self.sort_js[self.sort_js.index("function heatmapChangePct") : self.sort_js.index("function sortHeatmapRows")]
        self.assertIn("v == null", dist)
        self.assertIn("Number.isFinite", dist)
        day_sort = self.sort_js[self.sort_js.index("function sortHeatmapRows") : self.sort_js.index("function syncHeatmapSortButtons")]
        self.assertIn("vb - va", day_sort)
        self.assertIn("heatmapSort !== 'day'", day_sort)

    def test_does_not_touch_owned_surfaces(self):
        js = self.sort_js.lower()
        self.assertNotIn("renderportfoliotape", js)
        self.assertNotIn("settapesort", js)
        self.assertNotIn("tapesort", js)
        self.assertNotIn("togglefocusmode", js)
        self.assertNotIn("setworkspace", js)
        self.assertNotIn("charts.js", js)
        self.assertNotIn("setup_scanner", js)
        self.assertNotIn("last_price", js)
        self.assertNotIn("vwap.js", js)
        self.assertNotIn("desk_only_persist", js)
        self.assertNotIn("whats-news-heatmap-sort", self.charts)
        self.assertNotIn("heatmap-sort", self.charts)
        self.assertNotIn("whats-news-heatmap-sort", self.setup)
        self.assertNotIn("heatmap-sort", self.setup)
        self.assertNotIn("whats-news-heatmap-sort", self.vwap)
        self.assertNotIn("heatmap-sort", self.vwap)
        self.assertNotIn("whats-news-heatmap-sort", self.desk_only)
        self.assertNotIn("heatmap-sort", self.desk_only)
        self.assertNotIn("whats-news-heatmap-sort", self.app_js)
        self.assertFalse(os.path.exists(os.path.join(ROOT, "scripts", "last_price.js")))
        for rel in OWNED_OFF_LIMITS:
            text = _read(rel)
            self.assertNotIn("whats-news-heatmap-sort", text)
            self.assertNotIn("heatmap_sort", text)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            text = _read(path)
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        self.assertIn("not a published rating", self.sort_js)
        drawer = self.html[self.html.index("heatmap-sort") : self.html.index('id="regime-heatmap"')]
        self.assertIn("not a published rating", drawer)


class HeatmapSortRoundTripTests(unittest.TestCase):
    """Node: Desk keeps API order; Day% strongest first, missing last; persist; cell click."""

    def test_restore_round_trip_storage_key(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        sort_js = _read("scripts/heatmap_sort.js")
        helpers = sort_js[
            sort_js.index("const HEATMAP_SORT_KEY") : sort_js.index("function bootHeatmapSort")
        ]

        script = r"""
const mem = {};
const writes = [];
const TAPE_SORT = 'whats-news-tape-sort';
const SETUP_SORT = 'whats-news-setup-sort';
mem[TAPE_SORT] = 'sma200';
mem[SETUP_SORT] = 'adr';

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
        className: active ? 'heatmap-sort-btn active' : 'heatmap-sort-btn',
        attrs: { 'aria-pressed': active ? 'true' : 'false' },
        listeners: {},
        _heatmapSortBound: false,
        setAttribute(k, v) { this.attrs[k] = String(v); },
        getAttribute(k) { return this.attrs[k]; },
        addEventListener(ev, fn) { this.listeners[ev] = fn; },
        click() { if (this.listeners.click) this.listeners.click(); },
    };
    el.classList = makeClassList(el);
    return el;
}
const deskBtn = makeBtn('desk', true);
const dayBtn = makeBtn('day', false);
const heatCells = [];
const selected = [];
let origRenderCalls = 0;
let lastOrigOrder = '';
let lastOrigAlerts = null;

global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem: k => { delete mem[k]; writes.push(['del', k]); },
};
global.document = {
    querySelectorAll(sel) {
        if (sel === '.heatmap-sort-btn') return [deskBtn, dayBtn];
        if (sel === '.tape-sort-btn') throw new Error('heatmap sort must not query tape-sort-btn');
        return [];
    },
    getElementById(id) {
        if (id === 'regime-heatmap') {
            return {
                innerHTML: '',
                children: heatCells,
                appendChild(c) { heatCells.push(c); },
            };
        }
        return null;
    },
    addEventListener() {},
};
global.state = { portfolioMeta: null };
global.selectSymbol = function(sym) { selected.push(sym); };
global.renderRegimeHeatmap = function(data) {
    origRenderCalls += 1;
    lastOrigOrder = (data && data.heatmap || []).map(r => r.symbol).join(',');
    lastOrigAlerts = data && data.alerts;
    heatCells.length = 0;
    (data && data.heatmap || []).forEach(r => {
        const cell = {
            listeners: {},
            addEventListener(ev, fn) { this.listeners[ev] = fn; },
            click() { if (this.listeners.click) this.listeners.click(); },
        };
        cell.addEventListener('click', () => global.selectSymbol(r.symbol));
        heatCells.push(cell);
    });
};

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}
""" + helpers + r"""
const rows = [
    { symbol: 'AAPL', change_pct: 2.0 },
    { symbol: 'NVDA', change_pct: 18.5 },
    { symbol: 'MISS', change_pct: null },
    { symbol: 'NVDL', change_pct: -3.2 },
    { symbol: 'MSFT', change_pct: 8.1 },
];
function codes(list) { return list.map(r => r.symbol).join(','); }

assert(HEATMAP_SORT_KEY === 'whats-news-heatmap-sort', 'storage key');
assert(normalizeHeatmapSort(null) === 'desk', 'null → desk');
assert(normalizeHeatmapSort('') === 'desk', 'empty → desk');
assert(normalizeHeatmapSort('junk') === 'desk', 'junk → desk');
assert(normalizeHeatmapSort('sma200') === 'desk', 'tape-sort value is invalid here');
assert(normalizeHeatmapSort(' DAY ') === 'day', 'trim + case');
assert(readHeatmapSort() === 'desk', 'missing key reads desk');
assert(restoreHeatmapSort() === 'desk', 'missing restore → desk');
assert(heatmapSort === 'desk', 'state default desk');
assert(deskBtn.getAttribute('aria-pressed') === 'true', 'Desk pressed when missing');
assert(dayBtn.getAttribute('aria-pressed') === 'false', 'Day% unpressed when missing');
assert(!Object.prototype.hasOwnProperty.call(mem, HEATMAP_SORT_KEY), 'restore must not create the key');
assert(writes.length === 0, 'restore of missing must not write');
assert(codes(sortHeatmapRows(rows)) === 'AAPL,NVDA,MISS,NVDL,MSFT', 'desk keeps API order');
assert(heatmapChangePct(rows[1]) === 18.5, 'numeric pct');
assert(heatmapChangePct(rows[2]) === null, 'null pct');
assert(heatmapChangePct({ change_pct: 'nope' }) === null, 'non-finite pct');
assert(heatmapChangePct({ change_pct: '' }) === null, 'empty pct');

heatmapSort = 'day';
assert(codes(sortHeatmapRows(rows)) === 'NVDA,MSFT,AAPL,NVDL,MISS', 'day desc, missing last');
assert(codes(rows) === 'AAPL,NVDA,MISS,NVDL,MSFT', 'sort must not mutate source');
heatmapSort = 'desk';
assert(codes(sortHeatmapRows(rows)) === 'AAPL,NVDA,MISS,NVDL,MSFT', 'back to desk order');

wrapRenderRegimeHeatmap();
bindHeatmapSortUi();
const payload = { heatmap: rows, alerts: [{ symbol: 'NVDA' }], group_rollup: [{ group: 'mega' }] };
global.state.portfolioMeta = payload;
origRenderCalls = 0;
globalThis.renderRegimeHeatmap(payload);
assert(origRenderCalls === 1, 'wrap calls original');
assert(lastOrigOrder === 'AAPL,NVDA,MISS,NVDL,MSFT', 'desk wrap keeps API heatmap order');
assert(lastOrigAlerts && lastOrigAlerts.length === 1, 'wrap preserves sibling fields');
assert(codes(rows) === 'AAPL,NVDA,MISS,NVDL,MSFT', 'wrap must not mutate heatmap array');
selected.length = 0;
heatCells[0].click();
assert(selected.join(',') === 'AAPL', 'cell click still selectSymbol in desk order');

origRenderCalls = 0;
setHeatmapSort('day');
assert(heatmapSort === 'day', 'click stores day');
assert(mem[HEATMAP_SORT_KEY] === 'day', 'persist day');
assert(dayBtn.getAttribute('aria-pressed') === 'true', 'Day% pressed');
assert(deskBtn.getAttribute('aria-pressed') === 'false', 'Desk unpressed');
assert(origRenderCalls === 1, 'setHeatmapSort re-renders');
assert(lastOrigOrder === 'NVDA,MSFT,AAPL,NVDL,MISS', 'day wrap strongest first, missing last');
selected.length = 0;
heatCells[0].click();
assert(selected.join(',') === 'NVDA', 'cell click still selectSymbol after Day% sort');
assert(mem[TAPE_SORT] === 'sma200', 'must not clobber tape-sort');
assert(mem[SETUP_SORT] === 'adr', 'must not clobber setup-sort');
assert(!writes.some(w => w[1] === TAPE_SORT || w[1] === SETUP_SORT), 'writes stay on heatmap-sort key');

const writesAfterPersist = writes.length;
heatmapSort = 'desk';
origRenderCalls = 0;
const restored = restoreHeatmapSort();
assert(restored === 'day', 'reload restores day');
assert(heatmapSort === 'day', 'mode matches saved');
assert(dayBtn.getAttribute('aria-pressed') === 'true', 'reload presses Day%');
assert(writes.length === writesAfterPersist, 'restore must not write storage');
assert(origRenderCalls === 0, 'restore does not render; wrap applies on next heatmap render');
assert(codes(sortHeatmapRows(rows)) === 'NVDA,MSFT,AAPL,NVDL,MISS', 'restored sort is live before render');

globalThis.renderRegimeHeatmap(payload);
assert(lastOrigOrder === 'NVDA,MSFT,AAPL,NVDL,MISS', 'restored day sort applies on next render');
selected.length = 0;
heatCells[heatCells.length - 1].click();
assert(selected.join(',') === 'MISS', 'last cell is missing-pct name; still selectSymbol');

setHeatmapSort('desk');
assert(heatmapSort === 'desk', 'back to desk');
assert(mem[HEATMAP_SORT_KEY] === 'desk', 'persist desk');
assert(lastOrigOrder === 'AAPL,NVDA,MISS,NVDL,MSFT', 'desk restore API order');
assert(deskBtn.getAttribute('aria-pressed') === 'true', 'Desk pressed again');

localStorage.setItem(HEATMAP_SORT_KEY, 'nope');
const writesAfterNope = writes.length;
restoreHeatmapSort();
assert(heatmapSort === 'desk', 'invalid stored value → desk');
assert(deskBtn.getAttribute('aria-pressed') === 'true', 'invalid restore presses Desk');
assert(writes.length === writesAfterNope, 'invalid restore must not rewrite');

localStorage.setItem(HEATMAP_SORT_KEY, 'DAY');
restoreHeatmapSort();
assert(heatmapSort === 'day', 'stored DAY normalizes');

setHeatmapSort('nope');
assert(heatmapSort === 'desk', 'invalid click → desk');
assert(mem[HEATMAP_SORT_KEY] === 'desk', 'invalid click persists desk');

process.stdout.write(JSON.stringify({
    ok: true,
    key: HEATMAP_SORT_KEY,
    restored: 'day',
    deskOrder: 'AAPL,NVDA,MISS,NVDL,MSFT',
    dayOrder: 'NVDA,MSFT,AAPL,NVDL,MISS',
    tapeSort: mem[TAPE_SORT],
    setupSort: mem[SETUP_SORT],
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
        self.assertEqual(payload["restored"], "day")
        self.assertEqual(payload["deskOrder"], "AAPL,NVDA,MISS,NVDL,MSFT")
        self.assertEqual(payload["dayOrder"], "NVDA,MSFT,AAPL,NVDL,MISS")
        self.assertEqual(payload["tapeSort"], "sma200")
        self.assertEqual(payload["setupSort"], "adr")


if __name__ == "__main__":
    unittest.main()
