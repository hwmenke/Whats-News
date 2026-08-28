"""Contract tests for optional daily session VWAP (anchored from loaded series)."""

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
    "scripts/vwap.js",
)


_NODE_VWAP_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const root = process.argv[2];
const chartsSrc = fs.readFileSync(path.join(root, 'scripts', 'charts.js'), 'utf8');
const vwapSrc = fs.readFileSync(path.join(root, 'scripts', 'vwap.js'), 'utf8');

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
    };
    ctx.window = ctx;
    ctx.globalThis = ctx;
    vm.createContext(ctx);
    vm.runInContext(chartsSrc, ctx);
    vm.runInContext(vwapSrc, ctx);
    return ctx;
}

const store = makeStore();
let desk = loadDesk(store);
assert(typeof desk.typicalPrice === 'function', 'typicalPrice missing');
assert(typeof desk.sessionVwapPoints === 'function', 'sessionVwapPoints missing');
assert(typeof desk.vwapIsOn === 'function', 'vwapIsOn missing');
assert(typeof desk.setVwapOn === 'function', 'setVwapOn missing');
assert(typeof desk.applyVwapIfOn === 'function', 'applyVwapIfOn missing');
assert(typeof desk.forgetVwapSeries === 'function', 'forgetVwapSeries missing');
assert(desk.vwapIsOn() === false, 'default off');

const tp = desk.typicalPrice({ high: 12, low: 8, close: 10, volume: 100 });
almost(tp, 10);

assert(desk.typicalPrice({ high: 12, low: 8 }) == null, 'missing close');
assert(desk.typicalPrice(null) == null, 'null row');

const rows = [
    { date: '2024-01-02', high: 12, low: 8, close: 10, volume: 100 },
    { date: '2024-01-03', high: 14, low: 10, close: 12, volume: 100 },
    { date: '2024-01-04', high: 11, low: 9, close: 10, volume: 200 },
];
const pts = desk.sessionVwapPoints(rows);
assert(pts.length === 3, 'point count');
almost(pts[0].value, 10);
almost(pts[1].value, 11);
almost(pts[2].value, 10.5);
assert(pts[0].time === '2024-01-02', 'first time');
assert(pts[2].time === '2024-01-04', 'last time');

const zeroLead = [
    { date: 'z0', high: 10, low: 10, close: 10, volume: 0 },
    { date: 'z1', high: 12, low: 8, close: 10, volume: 50 },
    { date: 'z2', high: 20, low: 10, close: 12, volume: 50 },
];
const zpts = desk.sessionVwapPoints(zeroLead);
assert(zpts[0].value === undefined, 'no VWAP until volume');
almost(zpts[1].value, 10);
almost(zpts[2].value, 12);

const skipVol = [
    { date: 's0', high: 12, low: 8, close: 10, volume: 100 },
    { date: 's1', high: 99, low: 99, close: 99, volume: 0 },
    { date: 's2', high: 14, low: 10, close: 12, volume: 100 },
];
const spts = desk.sessionVwapPoints(skipVol);
almost(spts[1].value, 10, 1e-9);
almost(spts[2].value, 11);

const missingPx = [
    { date: 'm0', high: 12, low: 8, close: 10, volume: 100 },
    { date: 'm1', volume: 999 },
    { date: 'm2', high: 14, low: 10, close: 12, volume: 100 },
];
const mpts = desk.sessionVwapPoints(missingPx);
almost(mpts[1].value, 10);
almost(mpts[2].value, 11);

const empty = desk.sessionVwapPoints([]);
assert(Array.isArray(empty) && empty.length === 0, 'empty rows');
assert(desk.sessionVwapPoints(null).length === 0, 'null rows');

const OVERLAYS = 'whats-news-chart-overlays';
desk.applySavedOverlays();
const fresh = desk.collectOverlayState();
assert(fresh.vwap === false, 'collect default off');
assert(store.getItem(OVERLAYS) === null, 'must not write overlays before a user toggle');

desk.setVwapOn(true, { persist: true, apply: false });
assert(desk.vwapIsOn() === true, 'toggled on');
const afterToggle = JSON.parse(store.getItem(OVERLAYS));
assert(afterToggle.vwap === true, 'vwap saved on');
assert(afterToggle.spy_rs === false, 'vs-SPY stays off');
assert(afterToggle.news_markers === false, 'News stays off');
assert(afterToggle.gap === false, 'Gap stays off');
assert(afterToggle.last === false, 'Last stays off');

desk = loadDesk(store);
desk.applySavedOverlays();
assert(desk.vwapIsOn() === true, 'vwap restored on');
assert(desk.collectOverlayState().vwap === true, 'collect restored on');

const legacy = makeStore();
legacy.setItem(OVERLAYS, JSON.stringify({
    bb: false, ep: true, darvas: true, spy_rs: false, news_markers: false,
}));
desk = loadDesk(legacy);
desk.applySavedOverlays();
assert(desk.vwapIsOn() === false, 'legacy blob without vwap key stays off');
assert(legacy.getItem(OVERLAYS).indexOf('vwap') === -1, 'applySavedOverlays must not rewrite storage');

const blank = makeStore();
desk = loadDesk(blank);
desk.applySavedOverlays();
assert(desk.vwapIsOn() === false, 'empty storage keeps VWAP off');
assert(blank.getItem(OVERLAYS) === null, 'applySavedOverlays must not create the overlays key');

desk.setVwapOn(true, { persist: false, apply: false });
assert(blank.getItem(OVERLAYS) === null, 'persist false must not write');

process.stdout.write(JSON.stringify({
    ok: true,
    last: pts[2].value,
    defaultOn: false,
}));
"""


class DailySessionVwapContractTests(unittest.TestCase):
    """Daily price-pane VWAP pill — EOD anchored from first loaded bar; weekly skip."""

    @classmethod
    def setUpClass(cls):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            cls.charts = fh.read()
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

    def test_pill_aria_pressed_default_off(self):
        html = self.html
        self.assertIn('id="pill-vwap"', html)
        idx = html.index('id="pill-vwap"')
        snippet = html[idx : idx + 360]
        self.assertIn('aria-pressed="false"', snippet)
        self.assertNotIn("active-vwap", snippet)
        self.assertIn("not a published rating", snippet)
        self.assertIn("Daily only", snippet)
        self.assertIn("typical price", snippet)
        self.assertIn("scripts/vwap.js", html)
        self.assertLess(html.index("scripts/charts.js"), html.index("scripts/vwap.js"))
        self.assertLess(html.index("scripts/spy_rs.js"), html.index("scripts/vwap.js"))

    def test_module_daily_only_and_formula_docs(self):
        vwap = self.vwap
        charts = self.charts
        self.assertIn("let vwapOn = false", vwap)
        self.assertIn("function vwapIsOn", vwap)
        self.assertIn("function getVwapOn", vwap)
        self.assertIn("function setVwapOn", vwap)
        self.assertIn("function applyVwapIfOn", vwap)
        self.assertIn("function toggleVwap", vwap)
        self.assertIn("function sessionVwapPoints", vwap)
        self.assertIn("function typicalPrice", vwap)
        self.assertIn("function forgetVwapSeries", vwap)
        self.assertIn("function ensureVwapSeries", vwap)
        self.assertIn("persist: true", vwap)
        self.assertIn("not a published rating", vwap)
        self.assertIn("Weekly pane is skipped in v1", vwap)
        self.assertIn("rolling anchored VWAP from the first loaded daily bar", vwap)
        self.assertIn("(high + low + close) / 3", vwap)
        self.assertIn("cumsum(typical * volume) / cumsum(volume)", vwap)
        self.assertIn("rawRows.daily", vwap)
        self.assertNotIn("rawRows.weekly", vwap)
        self.assertNotIn("charts.weekly", vwap)
        self.assertIn("charts.daily.main", vwap)
        self.assertIn("VWAP_COLOR = '#f5c542'", vwap)
        self.assertIn("title: 'VWAP'", vwap)
        self.assertIn("aria-pressed", vwap)
        self.assertIn("active-vwap", vwap)
        self.assertIn("pill-vwap", vwap)
        self.assertIn("addLineSeries", vwap)

        self.assertIn("vwap: false", charts)
        self.assertIn("vwap: (typeof vwapIsOn === 'function') ? !!vwapIsOn() : false", charts)
        self.assertIn("function persistOverlays", charts)
        self.assertIn("function applySavedOverlays", charts)
        apply_start = charts.index("function applySavedOverlays")
        apply_end = charts.index("function setChartPack")
        apply_body = charts[apply_start:apply_end]
        self.assertIn("setVwapOn(!!merged.vwap, { persist: false, apply: false })", apply_body)
        self.assertNotIn("persistOverlays()", apply_body)
        self.assertIn("VWAP stay off", apply_body)

        self.assertIn("freq === 'daily' && typeof applyVwapIfOn === 'function'", charts)
        self.assertIn("forgetVwapSeries()", charts)
        self.assertIn("weekly skip in v1", charts)
        load_start = charts.index("function loadOHLCV")
        load_end = charts.index("function updateVolBadge")
        load_body = charts[load_start:load_end]
        self.assertEqual(load_body.count("applyVwapIfOn"), 2)
        self.assertIn("if (freq === 'daily' && typeof applyVwapIfOn === 'function') applyVwapIfOn();", load_body)
        self.assertNotIn("freq === 'weekly'", load_body)

        self.assertIn(".ind-pill.active-vwap", self.css)
        self.assertIn("#f5c542", self.css)

        self.assertNotIn("openJournalForDate", vwap)
        self.assertNotIn("whats-news-watchlist-filter", vwap)
        self.assertNotIn("setup_scanner", vwap)

    def test_forbidden_files_have_no_ibd_substring(self):
        for path in FORBIDDEN:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(
                re.search(r"ibd", text, re.IGNORECASE),
                msg=f"{path} must not contain the IBD substring",
            )
        self.assertIsNone(re.search(r"ibd", self.css, re.IGNORECASE))

    def test_app_and_scanner_untouched_by_vwap_module(self):
        self.assertNotIn("pill-vwap", self.app_js)
        self.assertNotIn("sessionVwapPoints", self.app_js)
        self.assertNotIn("applyVwapIfOn", self.setup)
        self.assertNotIn("pill-vwap", self.setup)

    def test_session_vwap_math_and_persist_roundtrip(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_VWAP_SCRIPT)
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
        self.assertEqual(payload["last"], 10.5)
        self.assertFalse(payload["defaultOn"])


if __name__ == "__main__":
    unittest.main()
