"""Contract tests for optional daily ATR Stop overlay (risk-box 1.5×ATR multiple)."""

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
    "scripts/atr_stop.js",
)

UNTOUCHED = (
    "scripts/volume_rvol.js",
    "scripts/journal_export.js",
    "scripts/checklist_persist.js",
    "scripts/vwap.js",
    "scripts/last_price.js",
)


_NODE_ATR_STOP_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const root = process.argv[2];
const chartsSrc = fs.readFileSync(path.join(root, 'scripts', 'charts.js'), 'utf8');
const lastSrc = fs.readFileSync(path.join(root, 'scripts', 'last_price.js'), 'utf8');
const vwapSrc = fs.readFileSync(path.join(root, 'scripts', 'vwap.js'), 'utf8');
const spySrc = fs.readFileSync(path.join(root, 'scripts', 'spy_rs.js'), 'utf8');
const newsSrc = fs.readFileSync(path.join(root, 'scripts', 'news_markers.js'), 'utf8');
const atrSrc = fs.readFileSync(path.join(root, 'scripts', 'atr_stop.js'), 'utf8');

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

function almost(a, b, eps) {
    if (Math.abs(a - b) > (eps || 1e-9)) throw new Error('expected ' + b + ' got ' + a);
}

function makeStore(seed) {
    const data = Object.assign({}, seed || {});
    return {
        data,
        getItem(key) { return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null; },
        setItem(key, val) { data[key] = String(val); },
        removeItem(key) { delete data[key]; },
    };
}

function makeCandle() {
    const created = [];
    const removed = [];
    return {
        created,
        removed,
        createPriceLine(opts) {
            created.push(opts);
            return { opts };
        },
        removePriceLine(line) { removed.push(line); },
    };
}

function loadDesk(store, extra) {
    extra = extra || {};
    const document = {
        getElementById: () => null,
        querySelector: (sel) => {
            if (sel === 'input[name="stop-mode"]:checked') {
                return extra.stopRadio || null;
            }
            return null;
        },
        querySelectorAll: () => [],
        addEventListener: () => {},
    };
    const ctx = {
        console,
        document,
        localStorage: store,
        LightweightCharts: { LineStyle: { Dashed: 2, Solid: 0, LargeDashed: 3 } },
        fetch: () => Promise.reject(new Error('no network')),
        series: { daily: { candle: makeCandle() }, weekly: { candle: makeCandle() } },
        rawRows: { daily: [], weekly: [] },
        state: { stopMode: extra.stopMode != null ? extra.stopMode : 'atr' },
    };
    ctx.window = ctx;
    ctx.globalThis = ctx;
    ctx.LWC = ctx.LightweightCharts;
    vm.createContext(ctx);
    vm.runInContext(chartsSrc, ctx);
    vm.runInContext(spySrc, ctx);
    vm.runInContext(newsSrc, ctx);
    vm.runInContext(vwapSrc, ctx);
    vm.runInContext(lastSrc, ctx);
    vm.runInContext(atrSrc, ctx);
    return ctx;
}

function constantTrRows(n) {
    const rows = [];
    for (let i = 0; i < n; i++) {
        rows.push({
            date: '2024-01-' + String(i + 1).padStart(2, '0'),
            high: 10 + i,
            low: 8 + i,
            close: 9 + i,
            volume: 100,
        });
    }
    return rows;
}

function seedBars(ctx, dailyRows, weeklyRows) {
    const payload = JSON.stringify({ daily: dailyRows, weekly: weeklyRows || [] });
    vm.runInContext(`
        (function(seed) {
            function makeCandle() {
                const created = [];
                const removed = [];
                return {
                    created,
                    removed,
                    createPriceLine(opts) { created.push(opts); return { opts }; },
                    removePriceLine(line) { removed.push(line); },
                };
            }
            series.daily.candle = makeCandle();
            series.weekly.candle = makeCandle();
            rawRows.daily = seed.daily;
            rawRows.weekly = seed.weekly;
        })(${payload});
    `, ctx);
}

function painted(ctx) {
    return vm.runInContext(`({
        daily: series.daily.candle.created.map(o => ({ price: o.price, title: o.title, color: o.color, lineStyle: o.lineStyle })),
        weekly: series.weekly.candle.created.map(o => ({ price: o.price, title: o.title })),
        dailyRemoved: series.daily.candle.removed.length,
        weeklyRemoved: series.weekly.candle.removed.length,
    })`, ctx);
}

const store = makeStore();
let desk = loadDesk(store);
assert(typeof desk.trueRangeAt === 'function', 'trueRangeAt missing');
assert(typeof desk.wilderAtrLast === 'function', 'wilderAtrLast missing');
assert(typeof desk.atrStopLevels === 'function', 'atrStopLevels missing');
assert(typeof desk.atrStopIsOn === 'function', 'atrStopIsOn missing');
assert(typeof desk.getAtrStopOn === 'function', 'getAtrStopOn missing');
assert(typeof desk.setAtrStopOn === 'function', 'setAtrStopOn missing');
assert(typeof desk.applyAtrStopIfOn === 'function', 'applyAtrStopIfOn missing');
assert(typeof desk.forgetAtrStopLines === 'function', 'forgetAtrStopLines missing');
assert(typeof desk.atrStopLineOptions === 'function', 'atrStopLineOptions missing');
assert(typeof desk.processToolsStopMode === 'function', 'processToolsStopMode missing');
assert(typeof desk.atrStopModeIsActive === 'function', 'atrStopModeIsActive missing');
assert(typeof desk.lastDailyClose === 'function', 'lastDailyClose missing');
assert(desk.atrStopIsOn() === false, 'default off');
assert(desk.getAtrStopOn() === false, 'getAtrStopOn default');
assert(desk.processToolsStopMode() === 'atr', 'default stop mode ATR');
assert(desk.atrStopModeIsActive() === true, 'ATR mode active by default');

const rows = constantTrRows(20);
const last = desk.lastDailyClose(rows);
assert(last.value === 28, 'rightmost close 9+19');
assert(last.time === '2024-01-20', 'rightmost date');
assert(desk.lastDailyClose([]) == null, 'empty rows');
assert(desk.lastDailyClose(null) == null, 'null rows');

const tr0 = desk.trueRangeAt(rows, 0);
almost(tr0, 2);
const tr5 = desk.trueRangeAt(rows, 5);
almost(tr5, 2);
const atr = desk.wilderAtrLast(rows, 14);
almost(atr, 2);
assert(desk.wilderAtrLast(constantTrRows(10), 14) == null, 'need 14 bars');
assert(desk.wilderAtrLast([], 14) == null, 'empty ATR');
assert(desk.wilderAtrLast(null, 14) == null, 'null ATR');

const levels = desk.atrStopLevels(rows);
almost(levels.atr, 2);
almost(levels.last, 28);
almost(levels.long, 28 - 1.5 * 2);
almost(levels.short, 28 + 1.5 * 2);
assert(levels.mult === 1.5, 'levels use risk-box multiple');
assert(desk.atrStopLevels([] ) == null, 'empty levels');
assert(desk.atrStopLevels(null) == null, 'null levels');
assert(desk.atrStopLevels(constantTrRows(5)) == null, 'too few bars');

const skipBad = constantTrRows(20);
skipBad[skipBad.length - 1] = { date: 'bad', close: 'nope' };
const skipped = desk.lastDailyClose(skipBad);
assert(skipped.value === 27, 'walk left past invalid closes');

const opts = desk.atrStopLineOptions(25, 'Stop');
assert(opts.title === 'Stop', 'compact Stop label');
assert(opts.color === '#fb7185', 'distinct stop color');
assert(opts.color !== '#c026d3', 'not Last magenta');
assert(opts.color !== '#f5c542', 'not VWAP gold');
assert(opts.color !== '#f87171', 'not PDH');
assert(opts.color !== '#4ade80', 'not PDL');
assert(opts.axisLabelVisible === true, 'axis label');
assert(opts.lineStyle === 2, 'dashed, not Last solid');

const weeklyRows = [
    { date: '2024-01-05', high: 12, low: 8, close: 11 },
    { date: '2024-01-12', high: 20, low: 10, close: 15 },
];
seedBars(desk, rows, weeklyRows);
desk.setAtrStopOn(true, { persist: false, apply: true });
assert(desk.atrStopIsOn() === true, 'toggled on');
const linesOn = painted(desk);
assert(linesOn.daily.length === 2, 'long + short daily stop lines');
assert(linesOn.weekly.length === 0, 'weekly pane skipped');
almost(linesOn.daily[0].price, 25);
almost(linesOn.daily[1].price, 31);
assert(linesOn.daily[0].title === 'Stop', 'long title');
assert(linesOn.daily[1].title === 'Stop S', 'short title');
assert(linesOn.daily[0].price !== 28, 'must not be last close');

seedBars(desk, rows, weeklyRows);
desk.setAtrStopOn(false, { persist: false, apply: true });
const linesOff = painted(desk);
assert(linesOff.daily.length === 0, 'off draws nothing on a fresh series');

desk.setAtrStopOn(true, { persist: false, apply: false });
desk.state.stopMode = 'box';
seedBars(desk, rows, weeklyRows);
desk.applyAtrStopIfOn();
const hiddenBox = painted(desk);
assert(hiddenBox.daily.length === 0, 'box stop mode hides ATR stop');
assert(desk.atrStopIsOn() === true, 'pill stays on while hidden');

desk.state.stopMode = 'user';
seedBars(desk, rows, weeklyRows);
desk.applyAtrStopIfOn();
const hiddenUser = painted(desk);
assert(hiddenUser.daily.length === 0, 'user stop mode hides ATR stop');

desk.state.stopMode = 'atr';
seedBars(desk, rows, weeklyRows);
desk.applyAtrStopIfOn();
const shownAtr = painted(desk);
assert(shownAtr.daily.length === 2, 'ATR mode redraws');
almost(shownAtr.daily[0].price, 25);

const radioDesk = loadDesk(makeStore(), { stopRadio: { value: 'box', checked: true }, stopMode: 'atr' });
assert(radioDesk.processToolsStopMode() === 'box', 'checked radio wins over state');
assert(radioDesk.atrStopModeIsActive() === false, 'box radio not ATR');

desk.setAtrStopOn(false, { persist: false, apply: false });

const OVERLAYS = 'whats-news-chart-overlays';
desk.applySavedOverlays();
const fresh = desk.collectOverlayState();
assert(fresh.atrStop === false, 'collect default off');
assert(fresh.last === false, 'Last independently off');
assert(fresh.vwap === false, 'VWAP independently off');
assert(fresh.spy_rs === false, 'vs-SPY independently off');
assert(fresh.news_markers === false, 'News independently off');
assert(store.getItem(OVERLAYS) === null, 'must not write overlays before a user toggle');

desk.setAtrStopOn(true, { persist: true, apply: false });
assert(desk.atrStopIsOn() === true, 'persist toggle on');
const afterToggle = JSON.parse(store.getItem(OVERLAYS));
assert(afterToggle.atrStop === true, 'atrStop saved on');
assert(afterToggle.last === false, 'Last stays off');
assert(afterToggle.vwap === false, 'VWAP stays off');
assert(afterToggle.spy_rs === false, 'vs-SPY stays off');
assert(afterToggle.news_markers === false, 'News stays off');
assert(afterToggle.atr_stop == null, 'must use key atrStop not atr_stop');

desk = loadDesk(store);
desk.applySavedOverlays();
assert(desk.atrStopIsOn() === true, 'atrStop restored on');
assert(desk.collectOverlayState().atrStop === true, 'collect restored on');
assert(desk.lastPriceIsOn() === false, 'Last still off after atrStop restore');
assert(desk.vwapIsOn() === false, 'VWAP still off after atrStop restore');
assert(desk.spyRsIsOn() === false, 'vs-SPY still off after atrStop restore');
assert(desk.newsMarkersIsOn() === false, 'News still off after atrStop restore');

const legacy = makeStore();
legacy.setItem(OVERLAYS, JSON.stringify({
    bb: false, ep: true, darvas: true, spy_rs: false, news_markers: false, vwap: false, last: false,
}));
desk = loadDesk(legacy);
desk.applySavedOverlays();
assert(desk.atrStopIsOn() === false, 'legacy blob without atrStop key stays off');
assert(legacy.getItem(OVERLAYS).indexOf('atrStop') === -1, 'applySavedOverlays must not rewrite storage');

const blank = makeStore();
desk = loadDesk(blank);
desk.applySavedOverlays();
assert(desk.atrStopIsOn() === false, 'empty storage keeps Stop off');
assert(blank.getItem(OVERLAYS) === null, 'applySavedOverlays must not create the overlays key');

desk.setAtrStopOn(true, { persist: false, apply: false });
assert(blank.getItem(OVERLAYS) === null, 'persist false must not write');

let fetchCalled = false;
desk.fetch = () => { fetchCalled = true; return Promise.reject(new Error('blocked')); };
desk.setAtrStopOn(true, { persist: false, apply: true });
assert(fetchCalled === false, 'no extra fetch');

process.stdout.write(JSON.stringify({
    ok: true,
    lastClose: last.value,
    longStop: levels.long,
    shortStop: levels.short,
    atr: levels.atr,
    defaultOn: false,
    color: opts.color,
    mult: levels.mult,
}));
"""


class AtrStopOverlayContractTests(unittest.TestCase):
    """Stop overlay pill — last ± 1.5×ATR, daily only, ATR stop-mode, off by default."""

    @classmethod
    def setUpClass(cls):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            cls.charts = fh.read()
        with open("scripts/atr_stop.js", encoding="utf-8") as fh:
            cls.atr = fh.read()
        with open("scripts/last_price.js", encoding="utf-8") as fh:
            cls.last = fh.read()
        with open("scripts/vwap.js", encoding="utf-8") as fh:
            cls.vwap = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            cls.html = fh.read()
        with open("styles/main.css", encoding="utf-8") as fh:
            cls.css = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            cls.app_js = fh.read()
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            cls.setup = fh.read()
        with open("scripts/journal_filter.js", encoding="utf-8") as fh:
            cls.journal = fh.read()

    def test_pill_aria_pressed_default_off(self):
        html = self.html
        self.assertIn('id="pill-atr-stop"', html)
        idx = html.index('id="pill-atr-stop"')
        snippet = html[idx : idx + 480]
        self.assertIn('aria-pressed="false"', snippet)
        self.assertNotIn("active-atr-stop", snippet)
        self.assertIn("not a published rating", snippet)
        self.assertIn("1.5", snippet)
        self.assertIn("ATR", snippet)
        self.assertIn("risk box", snippet)
        self.assertIn("scripts/atr_stop.js", html)
        self.assertLess(html.index("scripts/charts.js"), html.index("scripts/atr_stop.js"))
        self.assertLess(html.index("scripts/last_price.js"), html.index("scripts/atr_stop.js"))
        last_idx = html.index('id="pill-last"')
        stop_idx = html.index('id="pill-atr-stop"')
        self.assertLess(last_idx, stop_idx)
        tools = html[html.index("name=\"stop-mode\"") : html.index("name=\"stop-mode\"") + 400]
        self.assertIn('value="atr"', html)
        self.assertIn("1.5×ATR", html)

    def test_module_daily_atr_mode_and_persist_hooks(self):
        atr = self.atr
        charts = self.charts
        self.assertIn("let atrStopOn = false", atr)
        self.assertIn("function atrStopIsOn", atr)
        self.assertIn("function getAtrStopOn", atr)
        self.assertIn("function setAtrStopOn", atr)
        self.assertIn("function applyAtrStopIfOn", atr)
        self.assertIn("function toggleAtrStop", atr)
        self.assertIn("function atrStopLevels", atr)
        self.assertIn("function wilderAtrLast", atr)
        self.assertIn("function trueRangeAt", atr)
        self.assertIn("function forgetAtrStopLines", atr)
        self.assertIn("function atrStopLineOptions", atr)
        self.assertIn("function processToolsStopMode", atr)
        self.assertIn("function atrStopModeIsActive", atr)
        self.assertIn("persist: true", atr)
        self.assertIn("not a published rating", atr)
        self.assertIn("Weekly pane is skipped in v1", atr)
        self.assertIn("ATR_STOP_MULT = 1.5", atr)
        self.assertIn("ATR_STOP_PERIOD = 14", atr)
        self.assertIn("rawRows.daily", atr)
        self.assertNotIn("rawRows.weekly", atr)
        self.assertNotIn("charts.weekly", atr)
        self.assertIn("series.daily", atr)
        self.assertIn("ATR_STOP_COLOR = '#fb7185'", atr)
        self.assertNotIn("'#c026d3'", atr)
        self.assertNotIn("'#f5c542'", atr)
        self.assertNotIn("'#f87171'", atr)
        self.assertIn("title: title || 'Stop'", atr)
        self.assertIn("'Stop S'", atr)
        self.assertIn("createPriceLine", atr)
        self.assertIn("aria-pressed", atr)
        self.assertIn("active-atr-stop", atr)
        self.assertIn("pill-atr-stop", atr)
        self.assertIn("name=\"stop-mode\"", atr)
        self.assertIn("=== 'atr'", atr)
        self.assertNotIn("fetch(", atr)
        self.assertNotIn("apiFetch", atr)
        self.assertNotIn("yahoo", atr.lower())

        self.assertIn("atrStop: false", charts)
        self.assertIn(
            "atrStop: (typeof atrStopIsOn === 'function') ? !!atrStopIsOn() : false",
            charts,
        )
        self.assertIn("function persistOverlays", charts)
        self.assertIn("function applySavedOverlays", charts)
        apply_start = charts.index("function applySavedOverlays")
        apply_end = charts.index("function setChartPack")
        apply_body = charts[apply_start:apply_end]
        self.assertIn("setAtrStopOn(!!merged.atrStop, { persist: false, apply: false })", apply_body)
        self.assertNotIn("persistOverlays()", apply_body)
        self.assertIn("ATR Stop too", apply_body)
        self.assertIn("Last too", apply_body)
        self.assertIn("VWAP stay off", apply_body)

        self.assertIn("typeof applyAtrStopIfOn === 'function') applyAtrStopIfOn()", charts)
        self.assertIn("forgetAtrStopLines()", charts)
        load_start = charts.index("function loadOHLCV")
        load_end = charts.index("function updateVolBadge")
        load_body = charts[load_start:load_end]
        self.assertIn(
            "if (freq === 'daily' && typeof applyAtrStopIfOn === 'function') applyAtrStopIfOn();",
            load_body,
        )
        self.assertIn("Daily only; ATR stop-mode only", load_body)
        self.assertEqual(load_body.count("applyAtrStopIfOn"), 2)

        self.assertIn(".ind-pill.active-atr-stop", self.css)
        self.assertIn("#fb7185", self.css)
        self.assertNotEqual("#fb7185", "#c026d3")
        self.assertNotEqual("#fb7185", "#f5c542")

        self.assertNotIn("openJournalForDate", atr)
        self.assertNotIn("whats-news-watchlist-filter", atr)
        self.assertNotIn("setup_scanner", atr)
        self.assertNotIn("whats-news-journal-filter", atr)
        self.assertNotIn("sessionVwapPoints", atr)
        self.assertNotIn("applyVwapIfOn", atr)
        self.assertNotIn("applyLastPriceIfOn", atr)
        self.assertNotIn("lastCloseFromRows", atr)

    def test_does_not_edit_owned_modules(self):
        for rel in UNTOUCHED:
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                text = fh.read()
            self.assertNotIn("atrStop", text)
            self.assertNotIn("pill-atr-stop", text)
            self.assertNotIn("applyAtrStopIfOn", text)
            self.assertNotIn("atr_stop.js", text)

    def test_forbidden_files_have_no_ibd_substring(self):
        for path in FORBIDDEN:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(
                re.search(r"ibd", text, re.IGNORECASE),
                msg=f"{path} must not contain the IBD substring",
            )
        self.assertIsNone(re.search(r"ibd", self.css, re.IGNORECASE))

    def test_app_scanner_journal_untouched_by_atr_stop_module(self):
        self.assertNotIn("pill-atr-stop", self.app_js)
        self.assertNotIn("atrStopLevels", self.app_js)
        self.assertNotIn("applyAtrStopIfOn", self.app_js)
        self.assertNotIn("applyAtrStopIfOn", self.setup)
        self.assertNotIn("pill-atr-stop", self.setup)
        self.assertNotIn("pill-atr-stop", self.journal)
        self.assertNotIn("atrStopLevels", self.journal)
        self.assertNotIn("applyAtrStopIfOn", self.journal)

    def test_atr_stop_math_shorts_mode_gate_and_persist_roundtrip(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_ATR_STOP_SCRIPT)
            runner = fh.name
        try:
            proc = subprocess.run(
                [node, runner, ROOT],
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
        self.assertEqual(payload["lastClose"], 28)
        self.assertEqual(payload["longStop"], 25)
        self.assertEqual(payload["shortStop"], 31)
        self.assertEqual(payload["atr"], 2)
        self.assertFalse(payload["defaultOn"])
        self.assertEqual(payload["color"], "#fb7185")
        self.assertEqual(payload["mult"], 1.5)


if __name__ == "__main__":
    unittest.main()
