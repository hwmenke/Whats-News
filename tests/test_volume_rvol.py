"""Contract tests: color volume histogram bars vs the 20-bar volume SMA."""

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
    "scripts/volume_rvol.js",
)


_NODE_RVOL_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const root = process.argv[2];
const chartsSrc = fs.readFileSync(path.join(root, 'scripts', 'charts.js'), 'utf8');
const rvolSrc = fs.readFileSync(path.join(root, 'scripts', 'volume_rvol.js'), 'utf8');
const vwapSrc = fs.readFileSync(path.join(root, 'scripts', 'vwap.js'), 'utf8');
const lastSrc = fs.readFileSync(path.join(root, 'scripts', 'last_price.js'), 'utf8');
const spySrc = fs.readFileSync(path.join(root, 'scripts', 'spy_rs.js'), 'utf8');
const newsSrc = fs.readFileSync(path.join(root, 'scripts', 'news_markers.js'), 'utf8');

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
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
    vm.runInContext(rvolSrc, ctx);
    vm.runInContext(spySrc, ctx);
    vm.runInContext(newsSrc, ctx);
    vm.runInContext(vwapSrc, ctx);
    vm.runInContext(lastSrc, ctx);
    return ctx;
}

const store = makeStore();
let desk = loadDesk(store);

assert(typeof desk.colorVolumeBarsByRvol === 'function', 'colorVolumeBarsByRvol missing');
assert(typeof desk.volumeBarVsSma === 'function', 'volumeBarVsSma missing');
assert(typeof desk.volumeSmaPoints === 'function', 'volumeSmaPoints missing');
assert(typeof desk.isVolPopColor === 'function', 'isVolPopColor missing');
assert(typeof desk.volumeRvolColors === 'function', 'volumeRvolColors missing');
assert(desk.volumeBarVsSma(300, 110) === 'above', '300 vs 110 is above');
assert(desk.volumeBarVsSma(50, 97.5) === 'below', '50 vs 97.5 is below');
assert(desk.volumeBarVsSma(100, 100) === 'below', 'equal SMA is muted (not above)');
assert(desk.volumeBarVsSma(100, null) == null, 'missing SMA');
assert(desk.volumeBarVsSma(100, 0) == null, 'zero SMA');
assert(desk.volumeBarVsSma(undefined, 100) == null, 'missing volume');

const rows = [];
for (let i = 0; i < 25; i++) {
    rows.push({
        date: '2024-02-' + String(i + 1).padStart(2, '0'),
        open: 10, close: 11, volume: 100,
    });
}
rows[24].volume = 300;
rows[23].open = 12;
rows[23].close = 10;
rows[23].volume = 50;

const smaPts = desk.volumeSmaPoints(rows);
assert(smaPts[19].value === 100, 'SMA20 of flat 100');
assert(smaPts[24].value === (100 * 18 + 50 + 300) / 20, 'last SMA includes 50 and 300');

const palette = desk.volumeRvolColors();
const volUp = '#22c55e33';
const volDown = '#ef444433';
const surgeUp = '#fb923c';
const climaxDown = '#fda4af';

const volData = rows.map((r, i) => ({
    time: r.date,
    value: r.volume || 0,
    color: r.close >= r.open ? volUp : volDown,
}));
volData[24].color = surgeUp;

const painted = desk.colorVolumeBarsByRvol(volData, smaPts, rows);
assert(painted === volData, 'mutates in place and returns same array');
for (let i = 0; i < 19; i++) {
    assert(painted[i].color === volUp, 'no SMA yet keeps direction color at ' + i);
}
assert(painted[19].color === palette.belowUp, 'bar 19 volume==SMA is muted up');
assert(painted[23].color === palette.belowDown, '50 vs SMA is muted down');
assert(painted[24].color === surgeUp, 'surge color is not washed out');
assert(painted[24].value === 300, 'histogram values unchanged');

const weekly = [];
for (let i = 0; i < 20; i++) {
    weekly.push({ date: 'w' + i, open: 5, close: 6, volume: 20 });
}
weekly[19].volume = 80;
const wSma = desk.volumeSmaPoints(weekly);
const wData = weekly.map(r => ({ time: r.date, value: r.volume, color: volUp }));
desk.colorVolumeBarsByRvol(wData, wSma, weekly);
assert(wData[19].color === palette.aboveUp, 'weekly above SMA is brighter up');
assert(wSma[19].value === (20 * 19 + 80) / 20, 'weekly SMA includes current bar');

const climaxRows = [
    { date: 'c0', open: 10, close: 9, volume: 10 },
];
const climaxData = [{ time: 'c0', value: 10, color: climaxDown }];
desk.colorVolumeBarsByRvol(climaxData, [{ time: 'c0', value: 1 }], climaxRows);
assert(climaxData[0].color === climaxDown, 'climax color is not washed out');

assert(desk.isVolPopColor(surgeUp) === true, 'surge is pop');
assert(desk.isVolPopColor(volUp) === false, 'muted up is not pop');

const empty = desk.colorVolumeBarsByRvol([], [], []);
assert(Array.isArray(empty) && empty.length === 0, 'empty volData');
assert(desk.colorVolumeBarsByRvol(null, null, null).length === 0, 'null volData');

const OVERLAYS = 'whats-news-chart-overlays';
desk.applySavedOverlays();
const fresh = desk.collectOverlayState();
assert(fresh.vwap === false, 'VWAP default off');
assert(fresh.last === false, 'Last default off');
assert(fresh.gap === false, 'Gap default off');
assert(fresh.spy_rs === false, 'vs-SPY default off');
assert(fresh.rvol == null, 'always-on coloring must not add an overlay key');
assert(store.getItem(OVERLAYS) === null, 'must not write overlays before a user toggle');

desk.setVwapOn(true, { persist: true, apply: false });
desk.setLastPriceOn(true, { persist: true, apply: false });
const afterToggle = JSON.parse(store.getItem(OVERLAYS));
assert(afterToggle.vwap === true, 'VWAP saved on');
assert(afterToggle.last === true, 'Last saved on');
assert(afterToggle.gap === false, 'Gap stays independently off');
assert(afterToggle.rvol == null, 'toggle persist must not add rvol');

desk = loadDesk(store);
desk.applySavedOverlays();
assert(desk.vwapIsOn() === true, 'VWAP restored on');
assert(desk.lastPriceIsOn() === true, 'Last restored on');
assert(desk.collectOverlayState().vwap === true, 'collect VWAP restored');
assert(desk.collectOverlayState().last === true, 'collect Last restored');
assert(desk.collectOverlayState().gap === false, 'collect Gap stays off');
assert(desk.collectOverlayState().rvol == null, 'reload must not invent rvol');

const blank = makeStore();
desk = loadDesk(blank);
desk.applySavedOverlays();
assert(desk.vwapIsOn() === false, 'empty storage keeps VWAP off');
assert(desk.lastPriceIsOn() === false, 'empty storage keeps Last off');
assert(blank.getItem(OVERLAYS) === null, 'applySavedOverlays must not create the overlays key');

process.stdout.write(JSON.stringify({
    ok: true,
    lastSma: smaPts[24].value,
    lastSurgeKept: painted[24].color === surgeUp,
    weeklyAbove: wData[19].color,
    aboveUp: palette.aboveUp,
    belowDown: palette.belowDown,
    overlayKeys: Object.keys(desk.collectOverlayState()).sort(),
}));
"""


class VolumeRvolColorContractTests(unittest.TestCase):
    """Histogram bars vs SMA20: brighter above, muted below. Always-on, not a rating."""

    @classmethod
    def setUpClass(cls):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            cls.charts = fh.read()
        with open("scripts/volume_rvol.js", encoding="utf-8") as fh:
            cls.rvol = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            cls.html = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            cls.app_js = fh.read()
        with open("scripts/vwap.js", encoding="utf-8") as fh:
            cls.vwap = fh.read()
        with open("scripts/last_price.js", encoding="utf-8") as fh:
            cls.last = fh.read()
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            cls.setup = fh.read()

    def test_module_hook_always_on_no_pill_no_fetch(self):
        charts = self.charts
        rvol = self.rvol
        html = self.html
        self.assertIn("function colorVolumeBarsByRvol", rvol)
        self.assertIn("function volumeBarVsSma", rvol)
        self.assertIn("function isVolPopColor", rvol)
        self.assertIn("function volumeRvolColors", rvol)
        self.assertIn("VOL_RVOL_ABOVE_UP", rvol)
        self.assertIn("VOL_RVOL_BELOW_UP", rvol)
        self.assertIn("not a published rating", rvol)
        self.assertIn("no extra fetch", rvol)
        self.assertIn("Daily and weekly", rvol)
        self.assertIn("Always-on", rvol)
        self.assertNotIn("fetch(", rvol)
        self.assertNotIn("apiFetch", rvol)
        self.assertNotIn("yahoo", rvol.lower())
        self.assertNotIn("localStorage", rvol)
        self.assertNotIn("persistOverlays", rvol)
        self.assertNotIn("pill-rvol", rvol)
        self.assertNotIn("whats-news-chart-overlays", rvol)

        load_start = charts.index("function loadOHLCV")
        load_end = charts.index("function updateVolBadge")
        load_body = charts[load_start:load_end]
        self.assertIn("typeof colorVolumeBarsByRvol === 'function'", load_body)
        self.assertIn("colorVolumeBarsByRvol(volData, volSmaPts, rows)", load_body)
        self.assertIn("series[freq].volume.setData(volData)", load_body)
        self.assertIn("series[freq].volumeSma.setData", load_body)
        self.assertIn("volumeSmaPoints(rows, VOL_SMA_PERIOD)", load_body)
        self.assertIn("not a published rating", load_body)
        self.assertNotIn("freq === 'daily' && typeof colorVolumeBarsByRvol", load_body)
        self.assertIn("typeof applyVwapIfOn === 'function') applyVwapIfOn()", load_body)
        self.assertIn("typeof applyLastPriceIfOn === 'function') applyLastPriceIfOn()", load_body)

        self.assertIn("scripts/volume_rvol.js", html)
        self.assertLess(html.index("scripts/charts.js"), html.index("scripts/volume_rvol.js"))
        self.assertLess(html.index("scripts/volume_rvol.js"), html.index("scripts/vwap.js"))
        self.assertLess(html.index("scripts/volume_rvol.js"), html.index("scripts/last_price.js"))
        self.assertNotIn("pill-rvol", html)
        self.assertNotIn("pill-volume-rvol", html)
        self.assertIn('id="pill-vwap"', html)
        self.assertIn('id="pill-last"', html)
        self.assertIn('id="pill-gap"', html)
        self.assertIn('id="pill-atr-stop"', html)

        self.assertIn("VOL_SMA_PERIOD = 20", charts)
        self.assertIn("series[freq].volumeSma", charts)

    def test_does_not_break_vwap_last_or_overlay_persist_hooks(self):
        charts = self.charts
        self.assertIn("vwap: (typeof vwapIsOn === 'function') ? !!vwapIsOn() : false", charts)
        self.assertIn(
            "last: (typeof lastPriceIsOn === 'function') ? !!lastPriceIsOn() : false",
            charts,
        )
        self.assertIn(
            "gap: (typeof gapFillIsOn === 'function') ? !!gapFillIsOn() : false",
            charts,
        )
        self.assertIn(
            "atrStop: (typeof atrStopIsOn === 'function') ? !!atrStopIsOn() : false",
            charts,
        )
        apply_start = charts.index("function applySavedOverlays")
        apply_end = charts.index("function setChartPack")
        apply_body = charts[apply_start:apply_end]
        self.assertIn("setVwapOn(!!merged.vwap, { persist: false, apply: false })", apply_body)
        self.assertIn("setLastPriceOn(!!merged.last, { persist: false, apply: false })", apply_body)
        self.assertIn("setGapFillOn(!!merged.gap, { persist: false, apply: false })", apply_body)
        self.assertIn("setAtrStopOn(!!merged.atrStop, { persist: false, apply: false })", apply_body)
        self.assertNotIn("persistOverlays()", apply_body)
        self.assertNotIn("colorVolumeBarsByRvol", apply_body)
        self.assertNotIn("rvol", apply_body)
        self.assertIn("function persistOverlays", charts)
        self.assertIn("OVERLAYS_STORAGE_KEY = 'whats-news-chart-overlays'", charts)
        self.assertIn("let vwapOn = false", self.vwap)
        self.assertIn("let lastPriceOn = false", self.last)

    def test_app_and_scanner_untouched_by_volume_rvol_module(self):
        self.assertNotIn("colorVolumeBarsByRvol", self.app_js)
        self.assertNotIn("volume_rvol", self.app_js)
        self.assertNotIn("colorVolumeBarsByRvol", self.setup)
        self.assertNotIn("pill-rvol", self.setup)

    def test_forbidden_files_have_no_ibd_substring(self):
        for path in FORBIDDEN:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(
                re.search(r"ibd", text, re.IGNORECASE),
                msg=f"{path} must not contain the IBD substring",
            )

    def test_volume_vs_sma_colors_and_overlay_persist_roundtrip(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_RVOL_SCRIPT)
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
        self.assertTrue(payload["lastSurgeKept"])
        self.assertEqual(payload["weeklyAbove"], "#22c55e88")
        self.assertEqual(payload["aboveUp"], "#22c55e88")
        self.assertEqual(payload["belowDown"], "#ef444422")
        self.assertAlmostEqual(payload["lastSma"], (100 * 18 + 50 + 300) / 20)
        self.assertEqual(
            payload["overlayKeys"],
            ["atrStop", "bb", "darvas", "ep", "gap", "last", "news_markers", "spy_rs", "vwap"],
        )


if __name__ == "__main__":
    unittest.main()
