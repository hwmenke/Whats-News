"""Contract tests for optional unfilled daily Gap overlay (open vs prior close)."""

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
    "scripts/gap_fill.js",
)


_NODE_GAP_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const root = process.argv[2];
const chartsSrc = fs.readFileSync(path.join(root, 'scripts', 'charts.js'), 'utf8');
const lastSrc = fs.readFileSync(path.join(root, 'scripts', 'last_price.js'), 'utf8');
const vwapSrc = fs.readFileSync(path.join(root, 'scripts', 'vwap.js'), 'utf8');
const spySrc = fs.readFileSync(path.join(root, 'scripts', 'spy_rs.js'), 'utf8');
const newsSrc = fs.readFileSync(path.join(root, 'scripts', 'news_markers.js'), 'utf8');
const gapSrc = fs.readFileSync(path.join(root, 'scripts', 'gap_fill.js'), 'utf8');

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
    vm.runInContext(gapSrc, ctx);
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
        daily: series.daily.candle.created.map(o => ({ price: o.price, title: o.title, color: o.color, lineStyle: o.lineStyle })),
        weekly: series.weekly.candle.created.map(o => ({ price: o.price, title: o.title, color: o.color })),
        dailyRemoved: series.daily.candle.removed.length,
        weeklyRemoved: series.weekly.candle.removed.length,
    })`, ctx);
}

const store = makeStore();
let desk = loadDesk(store);
assert(typeof desk.mostRecentUnfilledGap === 'function', 'mostRecentUnfilledGap missing');
assert(typeof desk.gapZoneFromOpen === 'function', 'gapZoneFromOpen missing');
assert(typeof desk.gapFillIsOn === 'function', 'gapFillIsOn missing');
assert(typeof desk.getGapFillOn === 'function', 'getGapFillOn missing');
assert(typeof desk.setGapFillOn === 'function', 'setGapFillOn missing');
assert(typeof desk.applyGapFillIfOn === 'function', 'applyGapFillIfOn missing');
assert(typeof desk.forgetGapFillLines === 'function', 'forgetGapFillLines missing');
assert(typeof desk.gapFillLineOptions === 'function', 'gapFillLineOptions missing');
assert(desk.gapFillIsOn() === false, 'default off');
assert(desk.getGapFillOn() === false, 'getGapFillOn default');

const upZone = desk.gapZoneFromOpen(12, 10);
assert(upZone.direction === 'up', 'gap up');
almost(upZone.high, 12);
almost(upZone.low, 10);
const downZone = desk.gapZoneFromOpen(8, 10);
assert(downZone.direction === 'down', 'gap down');
almost(downZone.high, 10);
almost(downZone.low, 8);
assert(desk.gapZoneFromOpen(10, 10) == null, 'equal open/close is not a gap');
assert(desk.gapZoneFromOpen(null, 10) == null, 'missing open');
assert(desk.gapZoneFromOpen(12, 'nope') == null, 'invalid prior close');

const unfilledUp = [
    { date: '2024-01-02', open: 10, high: 11, low: 9, close: 10 },
    { date: '2024-01-03', open: 12, high: 13, low: 11.5, close: 12 },
];
const gapUp = desk.mostRecentUnfilledGap(unfilledUp);
assert(gapUp.direction === 'up', 'unfilled gap up');
almost(gapUp.high, 12);
almost(gapUp.low, 10);
assert(gapUp.time === '2024-01-03', 'gap bar date');
assert(gapUp.priorClose === 10, 'prior close is gap low on a gap up');

const filledSameDay = [
    { date: '2024-01-02', open: 10, high: 11, low: 9, close: 10 },
    { date: '2024-01-03', open: 12, high: 13, low: 9.5, close: 11 },
];
assert(desk.mostRecentUnfilledGap(filledSameDay) == null, 'same-day fill is not unfilled');

const unfilledDown = [
    { date: '2024-01-02', open: 10, high: 11, low: 9, close: 10 },
    { date: '2024-01-03', open: 8, high: 9, low: 7.5, close: 8 },
];
const gapDown = desk.mostRecentUnfilledGap(unfilledDown);
assert(gapDown.direction === 'down', 'unfilled gap down');
almost(gapDown.high, 10);
almost(gapDown.low, 8);

const laterFill = [
    { date: 'a', open: 10, high: 11, low: 9, close: 10 },
    { date: 'b', open: 12, high: 13, low: 11.5, close: 12 },
    { date: 'c', open: 12, high: 12.5, low: 9.8, close: 11 },
];
assert(desk.mostRecentUnfilledGap(laterFill) == null, 'later bar filling prior close clears the gap');

const olderUnfilled = [
    { date: 'a', open: 10, high: 11, low: 9, close: 10 },
    { date: 'b', open: 12, high: 13, low: 11.5, close: 12 },
    { date: 'c', open: 12.2, high: 12.4, low: 12.05, close: 12.1 },
];
const older = desk.mostRecentUnfilledGap(olderUnfilled);
assert(older.time === 'c', 'most recent of two unfilled gaps');
almost(older.high, 12.2);
almost(older.low, 12);

const recentNoGapKeepsPrior = [
    { date: 'a', open: 10, high: 11, low: 9, close: 10 },
    { date: 'b', open: 12, high: 13, low: 11.5, close: 12 },
    { date: 'c', open: 12.2, high: 12.4, low: 12.05, close: 12.1 },
    { date: 'd', open: 12.1, high: 12.3, low: 12.08, close: 12.05 },
];
const keepPrior = desk.mostRecentUnfilledGap(recentNoGapKeepsPrior);
assert(keepPrior.time === 'c', 'skip a no-gap last bar; keep prior unfilled');
almost(keepPrior.high, 12.2);

const noGap = [
    { date: 'a', open: 10, high: 11, low: 9, close: 10 },
    { date: 'b', open: 10, high: 11, low: 9, close: 10.5 },
];
assert(desk.mostRecentUnfilledGap(noGap) == null, 'open equals prior close');
assert(desk.mostRecentUnfilledGap([]) == null, 'empty rows');
assert(desk.mostRecentUnfilledGap(null) == null, 'null rows');
assert(desk.mostRecentUnfilledGap([{ open: 10, close: 10 }]) == null, 'single bar');

const skipBad = [
    { date: 'a', open: 10, high: 11, low: 9, close: 10 },
    { date: 'b', open: 'nope', high: 13, low: 11, close: 12 },
    { date: 'c', open: 14, high: 15, low: 13.5, close: 14 },
];
const skipped = desk.mostRecentUnfilledGap(skipBad);
assert(skipped.time === 'c', 'walk left past invalid open; c vs b close 12');
almost(skipped.high, 14);
almost(skipped.low, 12);

const optsH = desk.gapFillLineOptions(12, 'GapH');
assert(optsH.title === 'GapH', 'compact GapH label');
assert(optsH.color === '#2dd4bf', 'distinct gap color');
assert(optsH.color !== '#f5c542', 'not VWAP gold');
assert(optsH.color !== '#c026d3', 'not Last magenta');
assert(optsH.color !== '#f87171', 'not PDH');
assert(optsH.color !== '#4ade80', 'not PDL');
assert(optsH.axisLabelVisible === true, 'axis label');
assert(optsH.lineStyle === 2, 'dashed, not Last solid');

const weeklyGap = [
    { date: '2024-01-05', open: 10, high: 11, low: 9, close: 10 },
    { date: '2024-01-12', open: 15, high: 16, low: 14.5, close: 15 },
];
seedBars(desk, unfilledUp, weeklyGap);
desk.setGapFillOn(true, { persist: false, apply: true });
assert(desk.gapFillIsOn() === true, 'toggled on');
const linesOn = painted(desk);
assert(linesOn.daily.length === 2, 'two daily gap lines');
assert(linesOn.weekly.length === 0, 'weekly pane skipped');
const dailyPrices = linesOn.daily.map(l => l.price).sort((a, b) => a - b);
almost(dailyPrices[0], 10);
almost(dailyPrices[1], 12);
const titles = linesOn.daily.map(l => l.title).sort();
assert(titles[0] === 'GapH' && titles[1] === 'GapL', 'GapH and GapL titles');
assert(linesOn.daily[0].color === '#2dd4bf', 'daily gap color');

desk.setGapFillOn(false, { persist: false, apply: true });
const linesOff = painted(desk);
assert(linesOff.daily.length === 2, 'cleared then not redrawn');
assert(linesOff.dailyRemoved >= 2, 'daily lines removed when off');
assert(linesOff.weeklyRemoved === 0, 'weekly never painted');

seedBars(desk, filledSameDay, weeklyGap);
desk.setGapFillOn(true, { persist: false, apply: true });
const noPaint = painted(desk);
assert(noPaint.daily.length === 0, 'filled gap draws nothing');
assert(noPaint.weekly.length === 0, 'weekly still skipped when daily has no unfilled gap');

desk.setGapFillOn(false, { persist: false, apply: false });

const OVERLAYS = 'whats-news-chart-overlays';
desk.applySavedOverlays();
const fresh = desk.collectOverlayState();
assert(fresh.gap === false, 'collect default off');
assert(fresh.last === false, 'Last independently off');
assert(fresh.vwap === false, 'VWAP independently off');
assert(fresh.spy_rs === false, 'vs-SPY independently off');
assert(fresh.news_markers === false, 'News independently off');
assert(store.getItem(OVERLAYS) === null, 'must not write overlays before a user toggle');

desk.setGapFillOn(true, { persist: true, apply: false });
assert(desk.gapFillIsOn() === true, 'persist toggle on');
const afterToggle = JSON.parse(store.getItem(OVERLAYS));
assert(afterToggle.gap === true, 'gap saved on');
assert(afterToggle.last === false, 'Last stays off');
assert(afterToggle.vwap === false, 'VWAP stays off');
assert(afterToggle.spy_rs === false, 'vs-SPY stays off');
assert(afterToggle.news_markers === false, 'News stays off');
assert(afterToggle.gapFill == null, 'must use key gap not gapFill');

desk = loadDesk(store);
desk.applySavedOverlays();
assert(desk.gapFillIsOn() === true, 'gap restored on');
assert(desk.collectOverlayState().gap === true, 'collect restored on');
assert(desk.lastPriceIsOn() === false, 'Last still off after gap restore');
assert(desk.vwapIsOn() === false, 'VWAP still off after gap restore');
assert(desk.spyRsIsOn() === false, 'vs-SPY still off after gap restore');
assert(desk.newsMarkersIsOn() === false, 'News still off after gap restore');

const legacy = makeStore();
legacy.setItem(OVERLAYS, JSON.stringify({
    bb: false, ep: true, darvas: true, spy_rs: false, news_markers: false, vwap: false, last: false,
}));
desk = loadDesk(legacy);
desk.applySavedOverlays();
assert(desk.gapFillIsOn() === false, 'legacy blob without gap key stays off');
assert(legacy.getItem(OVERLAYS).indexOf('"gap"') === -1, 'applySavedOverlays must not rewrite storage');

const blank = makeStore();
desk = loadDesk(blank);
desk.applySavedOverlays();
assert(desk.gapFillIsOn() === false, 'empty storage keeps Gap off');
assert(blank.getItem(OVERLAYS) === null, 'applySavedOverlays must not create the overlays key');

desk.setGapFillOn(true, { persist: false, apply: false });
assert(blank.getItem(OVERLAYS) === null, 'persist false must not write');

process.stdout.write(JSON.stringify({
    ok: true,
    gapHigh: gapUp.high,
    gapLow: gapUp.low,
    defaultOn: false,
    color: optsH.color,
}));
"""


class DailyGapFillOverlayContractTests(unittest.TestCase):
    """Gap overlay pill — most recent unfilled daily open/prior-close; off by default."""

    @classmethod
    def setUpClass(cls):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            cls.charts = fh.read()
        with open("scripts/gap_fill.js", encoding="utf-8") as fh:
            cls.gap = fh.read()
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
        self.assertIn('id="pill-gap"', html)
        idx = html.index('id="pill-gap"')
        snippet = html[idx : idx + 460]
        self.assertIn('aria-pressed="false"', snippet)
        self.assertNotIn("active-gap", snippet)
        self.assertIn("not a published rating", snippet)
        self.assertIn("open vs prior close", snippet)
        self.assertIn("Daily only", snippet)
        self.assertIn("scripts/gap_fill.js", html)
        self.assertLess(html.index("scripts/charts.js"), html.index("scripts/gap_fill.js"))
        self.assertLess(html.index("scripts/last_price.js"), html.index("scripts/gap_fill.js"))
        last_idx = html.index('id="pill-last"')
        gap_idx = html.index('id="pill-gap"')
        self.assertLess(last_idx, gap_idx)

    def test_module_daily_only_unfilled_gap_and_persist_hooks(self):
        gap = self.gap
        charts = self.charts
        self.assertIn("let gapFillOn = false", gap)
        self.assertIn("function gapFillIsOn", gap)
        self.assertIn("function getGapFillOn", gap)
        self.assertIn("function setGapFillOn", gap)
        self.assertIn("function applyGapFillIfOn", gap)
        self.assertIn("function toggleGapFill", gap)
        self.assertIn("function mostRecentUnfilledGap", gap)
        self.assertIn("function gapZoneFromOpen", gap)
        self.assertIn("function forgetGapFillLines", gap)
        self.assertIn("function gapFillLineOptions", gap)
        self.assertIn("persist: true", gap)
        self.assertIn("not a published rating", gap)
        self.assertIn("weekly skipped in v1", gap)
        self.assertIn("open vs prior close", gap)
        self.assertIn("rawRows.daily", gap)
        self.assertNotIn("rawRows.weekly", gap)
        self.assertNotIn("charts.weekly", gap)
        self.assertIn("GAP_FILL_COLOR = '#2dd4bf'", gap)
        self.assertNotIn("'#f5c542'", gap)
        self.assertNotIn("'#c026d3'", gap)
        self.assertNotIn("'#f87171'", gap)
        self.assertNotIn("'#4ade80'", gap)
        self.assertIn("title: title || 'Gap'", gap)
        self.assertIn("'GapH'", gap)
        self.assertIn("'GapL'", gap)
        self.assertIn("createPriceLine", gap)
        self.assertIn("aria-pressed", gap)
        self.assertIn("active-gap", gap)
        self.assertIn("pill-gap", gap)
        self.assertNotIn("fetch(", gap)
        self.assertNotIn("apiFetch", gap)
        self.assertNotIn("yahoo", gap.lower())

        self.assertIn("gap: false", charts)
        self.assertIn(
            "gap: (typeof gapFillIsOn === 'function') ? !!gapFillIsOn() : false",
            charts,
        )
        self.assertIn("function persistOverlays", charts)
        self.assertIn("function applySavedOverlays", charts)
        apply_start = charts.index("function applySavedOverlays")
        apply_end = charts.index("function setChartPack")
        apply_body = charts[apply_start:apply_end]
        self.assertIn("setGapFillOn(!!merged.gap, { persist: false, apply: false })", apply_body)
        self.assertNotIn("persistOverlays()", apply_body)
        self.assertIn("Gap too", apply_body)
        self.assertIn("Last too", apply_body)
        self.assertIn("VWAP stay off", apply_body)

        self.assertIn("typeof applyGapFillIfOn === 'function') applyGapFillIfOn()", charts)
        self.assertIn("forgetGapFillLines()", charts)
        load_start = charts.index("function loadOHLCV")
        load_end = charts.index("function updateVolBadge")
        load_body = charts[load_start:load_end]
        self.assertIn("if (freq === 'daily' && typeof applyGapFillIfOn === 'function') applyGapFillIfOn();", load_body)
        self.assertIn("Daily only", load_body)
        self.assertNotIn("freq === 'weekly'", load_body)

        self.assertIn(".ind-pill.active-gap", self.css)
        self.assertIn("#2dd4bf", self.css)
        self.assertNotEqual("#2dd4bf", "#f5c542")
        self.assertNotEqual("#2dd4bf", "#c026d3")

        self.assertNotIn("openJournalForDate", gap)
        self.assertNotIn("whats-news-watchlist-filter", gap)
        self.assertNotIn("setup_scanner", gap)
        self.assertNotIn("whats-news-journal-filter", gap)
        self.assertNotIn("volume_rvol", gap)
        self.assertNotIn("journal_export", gap)
        self.assertNotIn("checklist_persist", gap)

        self.assertNotIn("sessionVwapPoints", gap)
        self.assertNotIn("applyVwapIfOn", gap)
        self.assertNotIn("applyLastPriceIfOn", gap)
        self.assertNotIn("lastCloseFromRows", gap)

    def test_forbidden_files_have_no_ibd_substring(self):
        for path in FORBIDDEN:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(
                re.search(r"ibd", text, re.IGNORECASE),
                msg=f"{path} must not contain the IBD substring",
            )
        self.assertIsNone(re.search(r"ibd", self.css, re.IGNORECASE))

    def test_app_scanner_journal_untouched_by_gap_module(self):
        self.assertNotIn("pill-gap", self.app_js)
        self.assertNotIn("mostRecentUnfilledGap", self.app_js)
        self.assertNotIn("applyGapFillIfOn", self.app_js)
        self.assertNotIn("applyGapFillIfOn", self.setup)
        self.assertNotIn("pill-gap", self.setup)
        self.assertNotIn("pill-gap", self.journal)
        self.assertNotIn("mostRecentUnfilledGap", self.journal)
        self.assertNotIn("applyGapFillIfOn", self.journal)
        self.assertNotIn("applyGapFillIfOn", self.last)
        self.assertNotIn("applyGapFillIfOn", self.vwap)

    def test_unfilled_gap_math_and_persist_roundtrip(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_GAP_SCRIPT)
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
        self.assertEqual(payload["gapHigh"], 12)
        self.assertEqual(payload["gapLow"], 10)
        self.assertFalse(payload["defaultOn"])
        self.assertEqual(payload["color"], "#2dd4bf")


if __name__ == "__main__":
    unittest.main()
