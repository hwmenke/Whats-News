"""Contract tests for the 20-bar volume SMA on daily + weekly volume panes."""

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
)


_NODE_SMA_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const root = process.argv[2];
const chartsSrc = fs.readFileSync(path.join(root, 'scripts', 'charts.js'), 'utf8');

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

const ctx = {
    console,
    document: {
        getElementById: () => null,
        querySelectorAll: () => [],
        addEventListener: () => {},
    },
    localStorage: { getItem: () => null, setItem: () => {} },
    ResizeObserver: class { observe() {} disconnect() {} },
    LightweightCharts: {
        LineStyle: { Solid: 0, Dashed: 1, LargeDashed: 2 },
        ColorType: { Solid: 0 },
        createChart: () => null,
    },
    fetch: () => Promise.reject(new Error('no network')),
};
ctx.window = ctx;
ctx.globalThis = ctx;
vm.createContext(ctx);
vm.runInContext(chartsSrc, ctx);

assert(typeof ctx.computeSma === 'function', 'computeSma missing');
assert(typeof ctx.volumeSmaPoints === 'function', 'volumeSmaPoints missing');
assert(typeof ctx._avg20Vol === 'function', '_avg20Vol missing');

const rows = [];
for (let i = 0; i < 25; i++) {
    rows.push({ date: '2024-02-' + String(i + 1).padStart(2, '0'), volume: 100 });
}
rows[24].volume = 300;

const pts = ctx.volumeSmaPoints(rows);
assert(Array.isArray(pts) && pts.length === 25, 'point count');
for (let i = 0; i < 19; i++) {
    assert(pts[i].time === rows[i].date, 'whitespace time ' + i);
    assert(pts[i].value === undefined, 'no SMA until 20 bars at ' + i);
}
assert(pts[19].value === 100, 'SMA20 of flat 100, got ' + pts[19].value);
assert(pts[24].value === 110, 'last SMA (19*100+300)/20, got ' + pts[24].value);

const p5 = ctx.volumeSmaPoints(rows, 5);
assert(p5[3].value === undefined, 'period 5 still needs 5 bars');
assert(p5[4].value === 100, 'period 5 SMA');
assert(p5[24].value === (100 * 4 + 300) / 5, 'period 5 last, got ' + p5[24].value);

const missing = [];
for (let i = 0; i < 20; i++) {
    missing.push({ date: 'm' + i, volume: i === 19 ? undefined : 10 });
}
const mpts = ctx.volumeSmaPoints(missing);
assert(mpts[19].value === (10 * 19) / 20, 'missing volume counts as 0');

const closes = rows.map(r => r.volume || 0);
const sma = ctx.computeSma(closes, 20);
assert(sma[18] == null, 'computeSma waits for period');
assert(sma[19] === 100, 'computeSma period 20');
assert(sma[24] === 110, 'computeSma last');

const avgAtLast = ctx._avg20Vol(rows, 24);
assert(avgAtLast === 100, '_avg20Vol prior-20 excludes current, got ' + avgAtLast);

process.stdout.write(JSON.stringify({
    ok: true,
    lastSma: pts[24].value,
    seriesName: 'volumeSma',
    period: 20,
}));
"""


class VolumeSma20ContractTests(unittest.TestCase):
    """Daily + weekly volume panes draw a 20-bar SMA without hiding the histogram."""

    @classmethod
    def setUpClass(cls):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            cls.charts = fh.read()
        with open("styles/main.css", encoding="utf-8") as fh:
            cls.css = fh.read()

    def test_series_name_and_period_20(self):
        charts = self.charts
        self.assertIn("VOL_SMA_PERIOD = 20", charts)
        self.assertIn("series[freq].volumeSma", charts)
        self.assertIn("function volumeSmaPoints", charts)
        self.assertIn("volumeSmaPoints(rows, VOL_SMA_PERIOD)", charts)
        self.assertIn("computeSma(vols, p)", charts)
        self.assertIn("addHistogramSeries", charts)
        self.assertIn("charts[freq].volume.addLineSeries", charts)
        self.assertIn("C.vol_sma", charts)
        self.assertIn("vol_sma:", charts)
        self.assertIn("#7d93b0", charts)
        vol_block_start = charts.index("series[freq].volume = charts[freq].volume.addHistogramSeries")
        vol_block = charts[vol_block_start : vol_block_start + 900]
        self.assertIn("addHistogramSeries", vol_block)
        self.assertIn("series[freq].volumeSma", vol_block)
        self.assertIn("lastValueVisible: true", vol_block)
        self.assertIn("priceFormat: { type: 'volume' }", vol_block)
        self.assertIn("not a published rating", vol_block)
        self.assertIn("_avg20Vol", vol_block)
        self.assertIn("buildPanel('daily')", charts)
        self.assertIn("buildPanel('weekly')", charts)
        self.assertIn("volumeSma: null", charts)
        self.assertIsNone(re.search(r"ibd", charts, re.IGNORECASE))

    def test_histogram_stays_and_css_hint_is_muted(self):
        charts = self.charts
        css = self.css
        self.assertIn("series[freq].volume.setData(volData)", charts)
        self.assertIn("series[freq].volumeSma.setData", charts)
        self.assertIn(".chart-wrapper-volume .chart-label::after", css)
        self.assertIn('content: "SMA20"', css)
        self.assertIn("#7d93b0", css)
        self.assertIn(".chart-wrapper-volume { height: 84px;", css)
        self.assertIsNone(re.search(r"ibd", css, re.IGNORECASE))

    def test_forbidden_files_have_no_ibd_substring(self):
        for path in FORBIDDEN:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(
                re.search(r"ibd", text, re.IGNORECASE),
                msg=f"{path} must not contain the IBD substring",
            )

    def test_volume_sma_points_use_period_20(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_SMA_SCRIPT)
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
        self.assertEqual(payload["seriesName"], "volumeSma")
        self.assertEqual(payload["period"], 20)
        self.assertEqual(payload["lastSma"], 110)


if __name__ == "__main__":
    unittest.main()
