"""Contract tests for optional Last overlay (rightmost bar close, not PDC)."""

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
    "scripts/last_price.js",
)


_NODE_LAST_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const root = process.argv[2];
const chartsSrc = fs.readFileSync(path.join(root, 'scripts', 'charts.js'), 'utf8');
const lastSrc = fs.readFileSync(path.join(root, 'scripts', 'last_price.js'), 'utf8');
const vwapSrc = fs.readFileSync(path.join(root, 'scripts', 'vwap.js'), 'utf8');
const spySrc = fs.readFileSync(path.join(root, 'scripts', 'spy_rs.js'), 'utf8');
const newsSrc = fs.readFileSync(path.join(root, 'scripts', 'news_markers.js'), 'utf8');

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

function loadDesk(store) {
    const document = {
        getElementById: () => null,
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
    return ctx;
}

function seedBars(ctx, dailyRows, weeklyRows) {
    const payload = JSON.stringify({ daily: dailyRows, weekly: weeklyRows });
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
        daily: series.daily.candle.created.map(o => ({ price: o.price, title: o.title, color: o.color })),
        weekly: series.weekly.candle.created.map(o => ({ price: o.price, title: o.title, color: o.color })),
        dailyRemoved: series.daily.candle.removed.length,
        weeklyRemoved: series.weekly.candle.removed.length,
    })`, ctx);
}

const store = makeStore();
let desk = loadDesk(store);
assert(typeof desk.lastCloseFromRows === 'function', 'lastCloseFromRows missing');
assert(typeof desk.lastPriceIsOn === 'function', 'lastPriceIsOn missing');
assert(typeof desk.getLastPriceOn === 'function', 'getLastPriceOn missing');
assert(typeof desk.setLastPriceOn === 'function', 'setLastPriceOn missing');
assert(typeof desk.applyLastPriceIfOn === 'function', 'applyLastPriceIfOn missing');
assert(typeof desk.forgetLastPriceLines === 'function', 'forgetLastPriceLines missing');
assert(typeof desk.lastPriceLineOptions === 'function', 'lastPriceLineOptions missing');
assert(desk.lastPriceIsOn() === false, 'default off');
assert(desk.getLastPriceOn() === false, 'getLastPriceOn default');

const rows = [
    { date: '2024-01-02', close: 10, high: 11, low: 9 },
    { date: '2024-01-03', close: 12, high: 13, low: 11 },
];
const last = desk.lastCloseFromRows(rows);
assert(last.value === 12, 'rightmost close, not prior-session PDC (10)');
assert(last.time === '2024-01-03', 'rightmost date');
assert(desk.lastCloseFromRows([] ) == null, 'empty rows');
assert(desk.lastCloseFromRows(null) == null, 'null rows');

const skipBad = [
    { date: 'a', close: 8 },
    { date: 'b', close: 'nope' },
    { date: 'c' },
];
const skipped = desk.lastCloseFromRows(skipBad);
assert(skipped.value === 8, 'walk left past invalid closes');

const weeklyRows = [
    { date: '2024-01-05', close: 11 },
    { date: '2024-01-12', close: 15 },
];
assert(desk.lastCloseFromRows(weeklyRows).value === 15, 'weekly rightmost close');

const opts = desk.lastPriceLineOptions(12);
assert(opts.title === 'Last', 'compact Last label');
assert(opts.color === '#c026d3', 'distinct last color');
assert(opts.color !== '#f5c542', 'not VWAP gold');
assert(opts.color !== '#f87171', 'not PDH');
assert(opts.color !== '#4ade80', 'not PDL');
assert(opts.axisLabelVisible === true, 'axis label');
assert(opts.lineStyle === 0, 'solid, not PDC dashed');

seedBars(desk, rows, weeklyRows);
desk.setLastPriceOn(true, { persist: false, apply: true });
assert(desk.lastPriceIsOn() === true, 'toggled on');
const linesOn = painted(desk);
assert(linesOn.daily.length === 1, 'one daily last line');
assert(linesOn.weekly.length === 1, 'one weekly last line');
almost(linesOn.daily[0].price, 12);
almost(linesOn.weekly[0].price, 15);
assert(linesOn.daily[0].title === 'Last', 'daily title');
assert(linesOn.weekly[0].title === 'Last', 'weekly title');
assert(linesOn.daily[0].price !== 10, 'daily must not be PDC prior close');
assert(linesOn.weekly[0].price !== 11, 'weekly must not be prior week close');

desk.setLastPriceOn(false, { persist: false, apply: true });
const linesOff = painted(desk);
assert(linesOff.daily.length === 1, 'cleared then not redrawn');
assert(linesOff.dailyRemoved >= 1, 'daily line removed when off');
assert(linesOff.weeklyRemoved >= 1, 'weekly line removed when off');

const OVERLAYS = 'whats-news-chart-overlays';
desk.applySavedOverlays();
const fresh = desk.collectOverlayState();
assert(fresh.last === false, 'collect default off');
assert(fresh.vwap === false, 'VWAP independently off');
assert(fresh.spy_rs === false, 'vs-SPY independently off');
assert(fresh.news_markers === false, 'News independently off');
assert(store.getItem(OVERLAYS) === null, 'must not write overlays before a user toggle');

desk.setLastPriceOn(true, { persist: true, apply: false });
assert(desk.lastPriceIsOn() === true, 'persist toggle on');
const afterToggle = JSON.parse(store.getItem(OVERLAYS));
assert(afterToggle.last === true, 'last saved on');
assert(afterToggle.vwap === false, 'VWAP stays off');
assert(afterToggle.spy_rs === false, 'vs-SPY stays off');
assert(afterToggle.news_markers === false, 'News stays off');
assert(afterToggle.lastPrice == null, 'must use key last not lastPrice');

desk = loadDesk(store);
desk.applySavedOverlays();
assert(desk.lastPriceIsOn() === true, 'last restored on');
assert(desk.collectOverlayState().last === true, 'collect restored on');
assert(desk.vwapIsOn() === false, 'VWAP still off after last restore');
assert(desk.spyRsIsOn() === false, 'vs-SPY still off after last restore');
assert(desk.newsMarkersIsOn() === false, 'News still off after last restore');

const legacy = makeStore();
legacy.setItem(OVERLAYS, JSON.stringify({
    bb: false, ep: true, darvas: true, spy_rs: false, news_markers: false, vwap: false,
}));
desk = loadDesk(legacy);
desk.applySavedOverlays();
assert(desk.lastPriceIsOn() === false, 'legacy blob without last key stays off');
assert(legacy.getItem(OVERLAYS).indexOf('"last"') === -1, 'applySavedOverlays must not rewrite storage');

const blank = makeStore();
desk = loadDesk(blank);
desk.applySavedOverlays();
assert(desk.lastPriceIsOn() === false, 'empty storage keeps Last off');
assert(blank.getItem(OVERLAYS) === null, 'applySavedOverlays must not create the overlays key');

desk.setLastPriceOn(true, { persist: false, apply: false });
assert(blank.getItem(OVERLAYS) === null, 'persist false must not write');

process.stdout.write(JSON.stringify({
    ok: true,
    lastDaily: last.value,
    defaultOn: false,
    color: opts.color,
}));
"""


class LastPriceOverlayContractTests(unittest.TestCase):
    """Last overlay pill — rightmost close, not PDC; daily + weekly; off by default."""

    @classmethod
    def setUpClass(cls):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            cls.charts = fh.read()
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
        self.assertIn('id="pill-last"', html)
        idx = html.index('id="pill-last"')
        snippet = html[idx : idx + 420]
        self.assertIn('aria-pressed="false"', snippet)
        self.assertNotIn("active-last", snippet)
        self.assertIn("not a published rating", snippet)
        self.assertIn("not prior-session PDC", snippet)
        self.assertIn("scripts/last_price.js", html)
        self.assertLess(html.index("scripts/charts.js"), html.index("scripts/last_price.js"))
        self.assertLess(html.index("scripts/vwap.js"), html.index("scripts/last_price.js"))
        vwap_idx = html.index('id="pill-vwap"')
        last_idx = html.index('id="pill-last"')
        self.assertLess(vwap_idx, last_idx)

    def test_module_daily_weekly_not_pdc_and_persist_hooks(self):
        last = self.last
        charts = self.charts
        self.assertIn("let lastPriceOn = false", last)
        self.assertIn("function lastPriceIsOn", last)
        self.assertIn("function getLastPriceOn", last)
        self.assertIn("function setLastPriceOn", last)
        self.assertIn("function applyLastPriceIfOn", last)
        self.assertIn("function toggleLastPrice", last)
        self.assertIn("function lastCloseFromRows", last)
        self.assertIn("function forgetLastPriceLines", last)
        self.assertIn("function lastPriceLineOptions", last)
        self.assertIn("persist: true", last)
        self.assertIn("not a published rating", last)
        self.assertIn("Not PDC", last)
        self.assertIn("current last print", last)
        self.assertIn("rawRows", last)
        self.assertIn("rawRows[freq]", last)
        self.assertIn("_drawLastPriceFreq('daily')", last)
        self.assertIn("_drawLastPriceFreq('weekly')", last)
        self.assertIn("LAST_PRICE_COLOR = '#c026d3'", last)
        self.assertNotIn("'#f5c542'", last)
        self.assertNotIn("'#f87171'", last)
        self.assertNotIn("'#4ade80'", last)
        self.assertIn("title: 'Last'", last)
        self.assertIn("createPriceLine", last)
        self.assertIn("aria-pressed", last)
        self.assertIn("active-last", last)
        self.assertIn("pill-last", last)
        self.assertNotIn("fetch(", last)
        self.assertNotIn("apiFetch", last)
        self.assertNotIn("yahoo", last.lower())

        self.assertIn("last: false", charts)
        self.assertIn(
            "last: (typeof lastPriceIsOn === 'function') ? !!lastPriceIsOn() : false",
            charts,
        )
        self.assertIn("function persistOverlays", charts)
        self.assertIn("function applySavedOverlays", charts)
        apply_start = charts.index("function applySavedOverlays")
        apply_end = charts.index("function setChartPack")
        apply_body = charts[apply_start:apply_end]
        self.assertIn("setLastPriceOn(!!merged.last, { persist: false, apply: false })", apply_body)
        self.assertNotIn("persistOverlays()", apply_body)
        self.assertIn("Last too", apply_body)

        self.assertIn("typeof applyLastPriceIfOn === 'function') applyLastPriceIfOn()", charts)
        self.assertIn("forgetLastPriceLines()", charts)
        load_start = charts.index("function loadOHLCV")
        load_end = charts.index("function updateVolBadge")
        load_body = charts[load_start:load_end]
        self.assertIn("if (typeof applyLastPriceIfOn === 'function') applyLastPriceIfOn();", load_body)
        self.assertIn("Daily + weekly; not PDC", load_body)

        self.assertIn(".ind-pill.active-last", self.css)
        self.assertIn("#c026d3", self.css)
        self.assertNotEqual("#c026d3", "#f5c542")

        self.assertNotIn("openJournalForDate", last)
        self.assertNotIn("whats-news-watchlist-filter", last)
        self.assertNotIn("setup_scanner", last)
        self.assertNotIn("whats-news-journal-filter", last)

        self.assertNotIn("sessionVwapPoints", last)
        self.assertNotIn("applyVwapIfOn", last)

    def test_forbidden_files_have_no_ibd_substring(self):
        for path in FORBIDDEN:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(
                re.search(r"ibd", text, re.IGNORECASE),
                msg=f"{path} must not contain the IBD substring",
            )
        self.assertIsNone(re.search(r"ibd", self.css, re.IGNORECASE))

    def test_app_scanner_journal_untouched_by_last_module(self):
        self.assertNotIn("pill-last", self.app_js)
        self.assertNotIn("lastCloseFromRows", self.app_js)
        self.assertNotIn("applyLastPriceIfOn", self.app_js)
        self.assertNotIn("applyLastPriceIfOn", self.setup)
        self.assertNotIn("pill-last", self.setup)
        self.assertNotIn("pill-last", self.journal)
        self.assertNotIn("lastCloseFromRows", self.journal)
        self.assertNotIn("applyLastPriceIfOn", self.journal)

    def test_last_close_is_not_pdc_and_persist_roundtrip(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_LAST_SCRIPT)
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
        self.assertEqual(payload["lastDaily"], 12)
        self.assertFalse(payload["defaultOn"])
        self.assertEqual(payload["color"], "#c026d3")


if __name__ == "__main__":
    unittest.main()
