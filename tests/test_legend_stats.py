"""Execute the browser legend calculations without chart or network services."""

import pathlib
import shutil
import subprocess
import unittest


class LegendStatsTests(unittest.TestCase):
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
