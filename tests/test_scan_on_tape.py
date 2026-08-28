"""Contract tests: Scan hits already on the desk get a tape chip; optional Hide tape."""

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
    "scripts/scan_on_tape.js",
    "tests/test_scan_on_tape.py",
)

STORAGE_KEY = "whats-news-scan-hide-tape"
OWNED_OFF_LIMITS = (
    "scripts/volume_rvol.js",
    "scripts/journal_export.js",
    "scripts/checklist_persist.js",
    "scripts/vwap.js",
    "scripts/last_price.js",
    "scripts/gap_fill.js",
    "scripts/atr_stop.js",
    "scripts/charts.js",
    "scripts/app.js",
)


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class ScanOnTapeTests(unittest.TestCase):
    """Tape chip on desk tickers, Hide tape off by default, wrap after setup_scanner.js."""

    @classmethod
    def setUpClass(cls):
        cls.js = _read("scripts/scan_on_tape.js")
        cls.app_js = _read("scripts/app.js")
        cls.html = _read("index.html")
        cls.css = _read("styles/main.css")
        cls.charts = _read("scripts/charts.js")
        cls.setup = _read("scripts/setup_scanner.js")

    def test_storage_key_wrap_and_default_off(self):
        js = self.js
        self.assertIn("SCAN_HIDE_TAPE_KEY = 'whats-news-scan-hide-tape'", js)
        self.assertIn("whats-news-scan-hide-tape", js)
        self.assertIn("function normalizeHideTape", js)
        self.assertIn("function readHideTape", js)
        self.assertIn("function writeHideTape", js)
        self.assertIn("function persistHideTape", js)
        self.assertIn("function restoreHideTape", js)
        self.assertIn("function deskTickerSet", js)
        self.assertIn("function markSetupRowsOnTape", js)
        self.assertIn("function setHideTape", js)
        self.assertIn("function wrapRenderSetupScanTable", js)
        self.assertIn("function wrapLoadSymbols", js)
        self.assertIn("function bootScanOnTape", js)
        self.assertIn("localStorage.getItem(SCAN_HIDE_TAPE_KEY)", js)
        self.assertIn("localStorage.setItem(SCAN_HIDE_TAPE_KEY, on ? '1' : '0')", js)
        self.assertNotIn("sessionStorage", js)
        self.assertNotIn("whats-news-scan-hide-tape", self.app_js)
        self.assertNotIn("whats-news-scan-hide-tape", self.setup)

        read = js[js.index("function readHideTape") : js.index("function writeHideTape")]
        self.assertIn("if (raw == null || raw === '') return false", read)
        self.assertIn("normalizeHideTape(raw)", read)
        self.assertNotIn("sessionStorage", read)

        restore = js[js.index("function restoreHideTape") : js.index("function deskTickerSet")]
        self.assertNotIn("localStorage.setItem", restore)
        self.assertNotIn("persistHideTape", restore)
        self.assertNotIn("writeHideTape", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertIn("readHideTape()", restore)
        self.assertIn("syncHideTapeControl()", restore)
        self.assertIn("markSetupRowsOnTape()", restore)

        set_hide = js[js.index("function setHideTape") : js.index("function bindHideTapeUi")]
        self.assertIn("persistHideTape()", set_hide)
        self.assertIn("syncHideTapeControl()", set_hide)
        self.assertIn("markSetupRowsOnTape()", set_hide)
        self.assertLess(set_hide.index("persistHideTape()"), set_hide.index("markSetupRowsOnTape()"))
        self.assertNotIn("sessionStorage", set_hide)

        wrap = js[js.index("function wrapRenderSetupScanTable") : js.index("function wrapLoadSymbols")]
        self.assertIn("orig.apply(this, arguments)", wrap)
        self.assertIn("markSetupRowsOnTape()", wrap)
        self.assertIn("g.renderSetupScanTable = renderSetupScanTableMarked", wrap)
        self.assertLess(wrap.index("orig.apply"), wrap.index("markSetupRowsOnTape()"))
        self.assertNotIn("selectSymbol", wrap)
        self.assertNotIn("setWorkspace", wrap)
        self.assertNotIn("switchTab", wrap)

        wrap_load = js[js.index("function wrapLoadSymbols") : js.index("function bootScanOnTape")]
        self.assertIn("orig.apply(this, arguments)", wrap_load)
        self.assertIn("markSetupRowsOnTape()", wrap_load)
        self.assertIn("g.loadSymbols = loadSymbolsThenMark", wrap_load)
        self.assertLess(wrap_load.index("orig.apply"), wrap_load.index("markSetupRowsOnTape()"))

        boot = js[js.index("function bootScanOnTape") :]
        self.assertIn("wrapRenderSetupScanTable()", boot)
        self.assertIn("wrapLoadSymbols()", boot)
        self.assertIn("bindHideTapeUi()", boot)
        self.assertIn("restoreHideTape()", boot)
        self.assertLess(boot.index("wrapRenderSetupScanTable()"), boot.index("restoreHideTape()"))
        self.assertLess(boot.index("wrapLoadSymbols()"), boot.index("restoreHideTape()"))

        html = self.html
        self.assertIn("scripts/scan_on_tape.js", html)
        self.assertLess(
            html.index("scripts/setup_scanner.js"),
            html.index("scripts/scan_on_tape.js"),
        )
        self.assertLess(
            html.index("scripts/scan_on_tape.js"),
            html.index("scripts/app.js"),
        )
        self.assertLess(
            html.index("scripts/scan_on_tape.js"),
            html.index("scripts/journal_filter.js"),
        )
        self.assertLess(
            html.index("scripts/scan_on_tape.js"),
            html.index("scripts/heatmap_sort.js"),
        )

    def test_hide_tape_control_default_off_near_sort_pills(self):
        html = self.html
        self.assertIn('id="btn-setup-hide-tape"', html)
        self.assertIn(">Hide tape</button>", html)
        header = html[html.index('id="setup-sort-pills"') : html.index('id="setup-filter-pills"')]
        self.assertIn('id="btn-setup-hide-tape"', header)
        self.assertIn("Hide tape", header)
        self.assertIn("not a published rating", header)
        btn = html[html.index('id="btn-setup-hide-tape"') : html.index('id="btn-setup-hide-tape"') + 280]
        self.assertIn('aria-pressed="false"', btn)
        self.assertNotIn('aria-pressed="true"', btn)
        self.assertIn("setup-hide-tape-pill", btn)
        self.assertNotIn("checked", btn.lower())

        css = self.css
        self.assertIn(".setup-on-tape", css)
        self.assertIn(".setup-tape-chip", css)
        self.assertIn(".setup-hide-tape-pill", css)
        self.assertIn("body.setup-hide-tape .setup-scan-row.setup-on-tape", css)
        hide = css[css.index("body.setup-hide-tape .setup-scan-row.setup-on-tape") :]
        hide_block = hide.split("}", 1)[0]
        self.assertIn("display: none", hide_block)
        self.assertIn(".setup-scan-row.setup-scan-selected", css)
        self.assertIn(".setup-scan-row.setup-scan-active", css)
        selected = css[css.index(".setup-scan-row.setup-scan-selected") : css.index(".setup-tape-chip")]
        self.assertIn("box-shadow: inset 2px 0 0 var(--accent)", selected)
        self.assertNotIn("display: none", selected)

    def test_marks_dataset_symbol_vs_desk_set(self):
        js = self.js
        desk = js[js.index("function deskTickerSet") : js.index("function rowSymbolCode")]
        self.assertIn("state.symbols", desk)
        self.assertIn("toUpperCase()", desk)
        self.assertIn("univ:", desk)
        row = js[js.index("function rowSymbolCode") : js.index("function ensureTapeChip")]
        self.assertIn("dataset.symbol", row)
        self.assertIn("toUpperCase()", row)
        mark = js[js.index("function markSetupRowsOnTape") : js.index("function syncHideTapeControl")]
        self.assertIn("deskTickerSet()", mark)
        self.assertIn("rowSymbolCode(tr)", mark)
        self.assertIn("setup-on-tape", mark)
        self.assertIn("ensureTapeChip(tr, onDesk)", mark)
        self.assertIn("tr.hidden = hide && onDesk", mark)
        chip = js[js.index("function ensureTapeChip") : js.index("function setupScanOnTapeRows")]
        self.assertIn("setup-tape-chip", chip)
        self.assertIn("Already on the desk", chip)
        self.assertIn("'tape'", chip)

        self.assertIn("function renderSetupScanTable", self.setup)
        self.assertIn("tr.className = 'setup-scan-row'", self.setup)
        self.assertIn("tr.dataset.symbol = row.symbol", self.setup)
        self.assertIn("setup-open", self.setup)
        self.assertIn("setup-promote", self.setup)
        self.assertIn("+ Desk", self.setup)
        self.assertIn("Stay in Scan workspace", self.setup)
        orig = self.setup[
            self.setup.index("function renderSetupScanTable") : self.setup.index("function normalizeSetupSort")
        ]
        self.assertNotIn("setup-on-tape", orig)
        self.assertNotIn("whats-news-scan-hide-tape", orig)
        self.assertIn("syncSetupHitHighlight(currentActiveSymbol())", orig)

    def test_does_not_touch_owned_surfaces(self):
        js = self.js.lower()
        self.assertNotIn("yahoo", js)
        self.assertNotIn("fetch(", js)
        self.assertNotIn("xmlhttprequest", js)
        self.assertNotIn("/api/", js)
        self.assertNotIn("charts.js", js)
        self.assertNotIn("volume_rvol", js)
        self.assertNotIn("journal_export", js)
        self.assertNotIn("checklist_persist", js)
        self.assertNotIn("last_price", js)
        self.assertNotIn("gap_fill", js)
        self.assertNotIn("atr_stop", js)
        self.assertNotIn("settapesort", js)
        self.assertNotIn("tapesort", js)
        self.assertNotIn("setworkspace", js)
        self.assertNotIn("switchtab", js)
        self.assertNotIn("selectsymbol", js)
        self.assertNotIn("sessionstorage", js)
        self.assertNotIn("whats-news-scan-hide-tape", self.charts)
        self.assertNotIn("scan_on_tape", self.charts)
        self.assertNotIn("whats-news-scan-hide-tape", self.setup)
        self.assertNotIn("scan_on_tape", self.setup)
        self.assertNotIn("whats-news-scan-hide-tape", self.app_js)
        self.assertIn("function setTapeSort", self.app_js)
        self.assertIn("TAPE_SORT_KEY = 'whats-news-tape-sort'", self.app_js)
        for rel in OWNED_OFF_LIMITS:
            text = _read(rel)
            self.assertNotIn("whats-news-scan-hide-tape", text)
            self.assertNotIn("scan_on_tape", text)
            self.assertNotIn("setup-hide-tape", text)
            self.assertNotIn("setup-on-tape", text)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            text = _read(path)
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        self.assertIn("not a published rating", self.js)
        self.assertIn("on the desk", self.js)
        self.assertNotIn("published rating", self.js.lower().replace("not a published rating", ""))
        btn = self.html[self.html.index("btn-setup-hide-tape") : self.html.index("setup-scan-meta")]
        self.assertIn("not a published rating", btn)
        self.assertIsNone(needle.search(self.css), msg="styles/main.css must not contain that rating brand")


class ScanOnTapeRoundTripTests(unittest.TestCase):
    """Node: default off, persist, restore, empty storage does not hide, dataset vs desk set."""

    def test_restore_round_trip_storage_key(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        js = _read("scripts/scan_on_tape.js")
        helpers = js[
            js.index("const SCAN_HIDE_TAPE_KEY") : js.index("function bootScanOnTape")
        ]

        script = r"""
const mem = {};
const writes = [];
const bodyClasses = new Set();

function makeClassList(el) {
    const classes = new Set((el.className || '').split(/\s+/).filter(Boolean));
    const sync = () => { el.className = [...classes].join(' '); };
    return {
        contains(name) { return classes.has(name); },
        add(name) { classes.add(name); sync(); },
        remove(name) { classes.delete(name); sync(); },
        toggle(name, on) {
            if (on === undefined) {
                if (classes.has(name)) classes.delete(name); else classes.add(name);
            } else if (on) classes.add(name); else classes.delete(name);
            sync();
            return classes.has(name);
        },
    };
}

function makeEl(className) {
    const el = {
        className: className || '',
        textContent: '',
        title: '',
        hidden: false,
        dataset: {},
        parentNode: null,
        children: [],
        querySelector(sel) {
            const cls = String(sel || '').replace(/^\./, '');
            const walk = (node) => {
                const names = (node.className || '').split(/\s+/).filter(Boolean);
                if (names.includes(cls)) return node;
                for (const c of node.children || []) {
                    const hit = walk(c);
                    if (hit) return hit;
                }
                return null;
            };
            return walk(el);
        },
        appendChild(child) {
            child.parentNode = el;
            el.children.push(child);
            return child;
        },
        insertBefore(child, ref) {
            child.parentNode = el;
            const i = el.children.indexOf(ref);
            if (i >= 0) el.children.splice(i, 0, child);
            else el.children.push(child);
            return child;
        },
        removeChild(child) {
            const i = el.children.indexOf(child);
            if (i >= 0) el.children.splice(i, 1);
            child.parentNode = null;
            return child;
        },
        setAttribute(k, v) { el.attrs[k] = String(v); },
        getAttribute(k) { return Object.prototype.hasOwnProperty.call(el.attrs, k) ? el.attrs[k] : null; },
        addEventListener(ev, fn) { el.listeners[ev] = el.listeners[ev] || []; el.listeners[ev].push(fn); },
        click() { (el.listeners.click || []).forEach(fn => fn({ type: 'click' })); },
        attrs: {},
        listeners: {},
    };
    el.classList = makeClassList(el);
    return el;
}

const rows = [];
function makeRow(symbol) {
    const tr = makeEl('setup-scan-row');
    tr.dataset.symbol = symbol;
    const cell = makeEl('setup-sym');
    cell.textContent = symbol;
    const open = makeEl('btn btn-ghost btn-sm setup-open');
    open.dataset = { symbol };
    const promote = makeEl('btn btn-ghost btn-sm setup-promote');
    promote.dataset = { symbol };
    tr.appendChild(cell);
    tr.appendChild(open);
    tr.appendChild(promote);
    const origQS = tr.querySelector.bind(tr);
    tr.querySelector = (sel) => {
        if (sel === '.setup-open') return open;
        if (sel === '.setup-promote') return promote;
        if (sel === '.setup-sym') return cell;
        return origQS(sel);
    };
    return tr;
}
rows.push(makeRow('NVDA'));
rows.push(makeRow('tsla'));
rows.push(makeRow('aapl'));

const hideBtn = makeEl('ind-pill setup-hide-tape-pill');
hideBtn.setAttribute('aria-pressed', 'false');
const body = {
    classList: {
        contains(name) { return bodyClasses.has(name); },
        toggle(name, on) {
            if (on) bodyClasses.add(name); else bodyClasses.delete(name);
            return bodyClasses.has(name);
        },
        add(name) { bodyClasses.add(name); },
        remove(name) { bodyClasses.delete(name); },
    },
};

global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem: k => { delete mem[k]; writes.push(['del', k]); },
};
global.state = { symbols: [{ symbol: 'NVDA' }, { symbol: 'AAPL', group_tag: 'mega' }, { symbol: 'SPY', group_tag: 'univ:sp500' }] };
global.document = {
    body,
    createElement: tag => makeEl(tag),
    getElementById: id => (id === 'btn-setup-hide-tape' ? hideBtn : null),
    querySelectorAll: sel => {
        if (String(sel).includes('setup-scan-row')) return rows;
        if (String(sel).includes('symbol-item')) return [];
        return [];
    },
};

let origRenderCalls = 0;
let origLoadCalls = 0;
const openClicks = [];
const promoteClicks = [];
rows.forEach(tr => {
    const open = tr.querySelector('.setup-open');
    const promote = tr.querySelector('.setup-promote');
    open.addEventListener('click', () => openClicks.push(tr.dataset.symbol));
    promote.addEventListener('click', () => promoteClicks.push(tr.dataset.symbol));
});
function origRenderSetupScanTable() { origRenderCalls += 1; }
async function origLoadSymbols() { origLoadCalls += 1; }
globalThis.renderSetupScanTable = origRenderSetupScanTable;
globalThis.loadSymbols = origLoadSymbols;
""" + helpers + r"""
function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

(async () => {
assert(SCAN_HIDE_TAPE_KEY === 'whats-news-scan-hide-tape', 'storage key');
assert(readHideTape() === false, 'empty storage defaults off');
assert(restoreHideTape() === false, 'restore default off');
assert(hideBtn.getAttribute('aria-pressed') === 'false', 'control default off');
assert(!hideBtn.classList.contains('setup-hide-tape-on'), 'pill default off');
assert(writes.length === 0, 'restore of missing key must not write');
assert(!bodyClasses.has('setup-hide-tape'), 'body hide class off by default');

markSetupRowsOnTape();
assert(rows[0].classList.contains('setup-on-tape'), 'NVDA on desk is marked');
assert(!rows[1].classList.contains('setup-on-tape'), 'TSLA not on desk');
assert(rows[2].classList.contains('setup-on-tape'), 'aapl matches AAPL case-insensitive');
assert(!rows[0].hidden && !rows[1].hidden && !rows[2].hidden, 'default does not hide rows');
assert(rows[0].querySelector('.setup-tape-chip'), 'NVDA has tape chip');
assert(rows[0].querySelector('.setup-tape-chip').textContent === 'tape', 'chip label is tape');
assert(!rows[1].querySelector('.setup-tape-chip'), 'TSLA has no chip');
assert(rows[0].querySelector('.setup-open'), 'Chart button still on NVDA');
assert(rows[0].querySelector('.setup-promote'), '+ Desk button still on NVDA');
assert(!deskTickerSet().has('SPY'), 'univ: archive is not the desk');

const desk = deskTickerSet();
assert(desk.has('NVDA') && desk.has('AAPL'), 'desk set from state.symbols');
assert(rowSymbolCode(rows[1]) === 'TSLA', 'dataset.symbol uppercased');

setHideTape(true);
assert(mem[SCAN_HIDE_TAPE_KEY] === '1', 'persist writes 1');
assert(hideBtn.getAttribute('aria-pressed') === 'true', 'control on');
assert(hideBtn.classList.contains('setup-hide-tape-on'), 'pill on class');
assert(bodyClasses.has('setup-hide-tape'), 'body hide class on');
assert(rows[0].hidden === true, 'on-desk NVDA hidden');
assert(rows[1].hidden === false, 'off-desk TSLA stays visible');
assert(rows[2].hidden === true, 'on-desk AAPL hidden');
assert(rows[0].classList.contains('setup-on-tape'), 'hidden row stays marked');

setHideTape(false);
assert(mem[SCAN_HIDE_TAPE_KEY] === '0', 'persist writes 0');
assert(!rows[0].hidden && !rows[2].hidden, 'turning hide off shows desk rows');
assert(rows[0].classList.contains('setup-on-tape'), 'marks remain when unhidden');

const writesAfterToggle = writes.length;
hideTape = true;
rows[0].hidden = true;
restoreHideTape();
assert(hideTape === false, 'restore 0 is off');
assert(!rows[0].hidden, 'restore 0 does not hide');
assert(writes.length === writesAfterToggle, 'restore must not write');

delete mem[SCAN_HIDE_TAPE_KEY];
hideTape = true;
rows[0].hidden = true;
assert(readHideTape() === false, 'cleared key reads as default off');
restoreHideTape();
assert(hideTape === false, 'cleared key restores off');
assert(!rows[0].hidden, 'empty storage must not hide rows');

mem[SCAN_HIDE_TAPE_KEY] = '';
assert(readHideTape() === false, 'empty string does not hide');
mem[SCAN_HIDE_TAPE_KEY] = 'false';
assert(readHideTape() === false, 'false string does not hide');
mem[SCAN_HIDE_TAPE_KEY] = '0';
assert(readHideTape() === false, '0 does not hide');
mem[SCAN_HIDE_TAPE_KEY] = '1';
assert(readHideTape() === true, '1 hides');
mem[SCAN_HIDE_TAPE_KEY] = 'true';
assert(readHideTape() === true, 'true hides');

wrapRenderSetupScanTable();
origRenderCalls = 0;
globalThis.renderSetupScanTable([{ symbol: 'NVDA' }]);
assert(origRenderCalls === 1, 'wrap calls original render');
assert(rows[0].classList.contains('setup-on-tape'), 're-render re-marks');
const wrapped = globalThis.renderSetupScanTable;
globalThis.renderSetupScanTable();
assert(globalThis.renderSetupScanTable === wrapped, 'wrap is idempotent');
assert(origRenderCalls === 2, 'second render still calls orig');

wrapLoadSymbols();
origLoadCalls = 0;
state.symbols.push({ symbol: 'TSLA' });
await globalThis.loadSymbols();
assert(origLoadCalls === 1, 'wrap calls original loadSymbols');
assert(rows[1].classList.contains('setup-on-tape'), 'watchlist reload re-marks TSLA');

bindHideTapeUi();
hideBtn.click();
assert(mem[SCAN_HIDE_TAPE_KEY] === '1', 'pill click persists on');
assert(rows[0].hidden && rows[1].hidden, 'pill click hides on-desk rows');
hideBtn.click();
assert(mem[SCAN_HIDE_TAPE_KEY] === '0', 'pill click persists off');
assert(!rows[0].hidden && !rows[1].hidden, 'second click shows rows');

rows[0].querySelector('.setup-open').click();
rows[0].querySelector('.setup-promote').click();
assert(openClicks.join(',') === 'NVDA', 'Chart button still fires');
assert(promoteClicks.join(',') === 'NVDA', '+ Desk button still fires');

process.stdout.write(JSON.stringify({
    ok: true,
    key: SCAN_HIDE_TAPE_KEY,
    marked: rows.filter(r => r.classList.contains('setup-on-tape')).map(r => r.dataset.symbol),
    openClicks,
    promoteClicks,
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
        self.assertEqual(payload["openClicks"], ["NVDA"])
        self.assertEqual(payload["promoteClicks"], ["NVDA"])


if __name__ == "__main__":
    unittest.main()
