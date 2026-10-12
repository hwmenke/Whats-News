"""Execute the browser legend calculations without chart or network services."""

import pathlib
import shutil
import subprocess
import unittest

import portfolio


class LegendStatsTests(unittest.TestCase):
    def test_52h_gap_omits_non_finite_highs_and_overflow(self):
        rows = [{"high": value} for value in (100, float("inf"), float("nan"), float("-inf"))]
        self.assertEqual(portfolio.legend_high52(rows, 3), 100)
        self.assertIsNone(portfolio.legend_high52(rows[1:], 2))
        for invalid in (None, "bad", float("nan"), float("inf"), float("-inf"), 0, -1):
            with self.subTest(invalid=invalid):
                self.assertIsNone(portfolio.legend_gap_from_52h_pct(invalid, 100))
                self.assertIsNone(portfolio.legend_gap_from_52h_pct(100, invalid))
        for close, high in ((1e308, 1e-308), (1e308, 1)):
            self.assertIsNone(portfolio.legend_gap_from_52h_pct(close, high))
        for invalid in (float("nan"), float("inf"), float("-inf")):
            self.assertEqual(portfolio.format_legend_52h_gap(invalid), "")
        self.assertAlmostEqual(portfolio.legend_gap_from_52h_pct("90", "100"), -10)
        self.assertEqual(portfolio.format_legend_52h_gap(0), "52H 0.0%")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_browser_52h_gap_omits_overflow(self):
        script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync('scripts/legend_stats.js', 'utf8'), ctx);
assert.strictEqual(ctx.high52AsOfBar([
    {high: 100}, {high: Infinity}, {high: NaN}, {high: -Infinity}
], 3), 100);
for (const invalid of [null, undefined, 'bad', NaN, Infinity, -Infinity, 0, -1]) {
    assert.strictEqual(ctx.gapFrom52hPct(invalid, 100), null);
    assert.strictEqual(ctx.gapFrom52hPct(100, invalid), null);
}
for (const [close, high] of [[1e308, 1e-308], [1e308, 1]]) {
    assert.strictEqual(ctx.gapFrom52hPct(close, high), null);
    assert.strictEqual(ctx.legendStatHtmlBits('daily', 0, {
        rows: [{close, high}], dailyRows: [], sma200Series: []
    }), '');
}
assert.ok(Math.abs(ctx.gapFrom52hPct('90', '100') + 10) < 1e-12);
assert.strictEqual(ctx.format52hGapLegend(0), '52H 0.0%');
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", script],
            cwd=pathlib.Path(__file__).resolve().parents[1],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_sma200_distance_omits_non_finite_inputs_and_overflow(self):
        for invalid in (None, "bad", float("nan"), float("inf"), float("-inf"), 0, -1):
            with self.subTest(invalid=invalid):
                self.assertIsNone(portfolio.legend_sma200_dist_pct(invalid, 100))
                self.assertIsNone(portfolio.legend_sma200_dist_pct(100, invalid))
        for close, sma in ((1e308, 1e-308), (1e308, 1)):
            self.assertIsNone(portfolio.legend_sma200_dist_pct(close, sma))
        for invalid in (float("nan"), float("inf"), float("-inf")):
            self.assertEqual(portfolio.format_legend_sma200_dist(invalid), "")
        for close, expected in ((110, 10), (90, -10), (100, 0)):
            self.assertAlmostEqual(portfolio.legend_sma200_dist_pct(close, 100), expected)
        self.assertAlmostEqual(portfolio.legend_sma200_dist_pct("110", "100"), 10)
        self.assertEqual(portfolio.format_legend_sma200_dist(0), "200 +0.0%")

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_browser_sma200_distance_omits_non_finite_inputs_and_overflow(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync('scripts/legend_stats.js', 'utf8'), ctx);
for (const invalid of [null, undefined, 'bad', NaN, Infinity, -Infinity, 0, -1]) {
    assert.strictEqual(ctx.distToSma200Pct(invalid, 100), null);
    assert.strictEqual(ctx.distToSma200Pct(100, invalid), null);
}
for (const [close, sma] of [[1e308, 1e-308], [1e308, 1]]) {
    assert.strictEqual(ctx.distToSma200Pct(close, sma), null);
    assert.strictEqual(ctx.legendStatHtmlBits('weekly', 0, {
        rows: [{close}], sma200Series: [sma]
    }), '');
}
for (const invalid of [NaN, Infinity, -Infinity]) {
    assert.strictEqual(ctx.formatSma200DistLegend(invalid), '');
}
for (const [close, expected] of [[110, 10], [90, -10], [100, 0], ['110', 10]]) {
    assert.ok(Math.abs(ctx.distToSma200Pct(close, '100') - expected) < 1e-12);
}
assert.strictEqual(ctx.formatSma200DistLegend(0), '200 +0.0%');
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", script], cwd=root,
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_rvol_numeric_string_volumes_and_prior_bar_window(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync('scripts/legend_stats.js', 'utf8'), ctx);
const valid = {high: 102, low: 100, close: 100};
const invalid = [];
for (const column of ['high', 'low', 'close']) {
    for (const value of [NaN, Infinity, -Infinity]) {
        invalid.push({...valid, [column]: value});
    }
}
invalid.push({high: 1e308, low: 1, close: 1e-308});
assert.strictEqual(ctx.computeAdrPct([...Array(5).fill(valid), ...invalid]), 2);
assert.strictEqual(ctx.computeAdrPct([...Array(4).fill(valid), ...invalid]), null);
assert.strictEqual(ctx.computeAdrPct(Array(5).fill({high: 1e306, low: 1, close: 1})), null);
for (const volume of [100, '100']) {
    const rows = [{volume: 9000}, ...Array.from({length: 20}, () => ({volume}))];
    rows.push({volume: '200'});
    assert.strictEqual(ctx._legendAvg20Vol(rows, 21), 100);
    assert.strictEqual(ctx.computeRvol(rows, 21), 2);
    assert.strictEqual(ctx.formatRvolLegend(ctx.computeRvol(rows, 21)), 'RVOL 2.0×');
}
const rows = [{volume: '100'}, {volume: null}, {volume: 'bad'},
              {volume: Infinity}, {volume: 0}, {volume: '100'}];
assert.strictEqual(ctx._legendAvg20Vol(rows, 5), 20);
assert.strictEqual(ctx.computeRvol(rows, 5), 5);
assert.strictEqual(ctx.computeRvol([{volume: 0}, {volume: 100}], 1), null);
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", script], cwd=root,
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
