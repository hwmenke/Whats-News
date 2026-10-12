"""Exercise clipboard percentage formatting without a browser or network."""

from pathlib import Path
import shutil
import subprocess
import unittest


class CopyOhlcTests(unittest.TestCase):
    def test_malformed_prices_do_not_become_clipboard_quotes(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        source = Path(__file__).resolve().parents[1] / "scripts" / "copy_ohlc.js"
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const ctx = vm.createContext({});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const invalid = [null, undefined, '', '  ', true, false, [], [100], {}, NaN, Infinity, -Infinity, 'bad'];
// Validate before either the fallback or the shared chart formatter can coerce.
for (const formatter of [undefined, v => Number(v).toFixed(2)]) {
    ctx._fmtPx = formatter;
    for (const value of invalid) assert.strictEqual(ctx._copyOhlcPx(value), '—');
    assert.strictEqual(ctx._copyOhlcPx(0), '0.00');
    assert.strictEqual(ctx._copyOhlcPx('125.50'), '125.50');
    assert.strictEqual(ctx._copyOhlcPx(123.45), '123.45');
}
ctx.state = {activeSymbol: 'TEST'};
ctx.rawRows = {daily: [{date: '2026-01-02', open: '', high: true, low: [], close: '100'}]};
ctx.linkedBarFor = () => ({row: {date: '2026-01-02', open: null, high: ' ', low: false, close: 0}});
assert.strictEqual(ctx.formatPaintedOhlcLine(),
    'TEST 2026-01-02 O — H — L — C 100.00 · W 2026-01-02 O — H — L — C 0.00');
"""
        result = subprocess.run(
            [node, "-e", script, str(source)], capture_output=True,
            text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_missing_closes_do_not_fabricate_percentage_changes(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        source = Path(__file__).resolve().parents[1] / "scripts" / "copy_ohlc.js"
        script = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const change = (close, previous) => ctx._copyOhlcChgPct({close}, {close: previous});
for (const invalid of [null, undefined, '', '  ', true, false, [], [100], {}, NaN, Infinity, -Infinity, 'bad']) {
    assert.strictEqual(change(invalid, 100), '', 'invalid current close');
    assert.strictEqual(change(100, invalid), '', 'invalid previous close');
}
assert.strictEqual(change(110, 100), ' +10.00%');
assert.strictEqual(change('90', '100'), ' -10.00%');
assert.strictEqual(change(100, 100), ' +0.00%');
assert.strictEqual(change(0, 100), ' -100.00%');
assert.strictEqual(change(100, 0), '');
assert.strictEqual(change(100, '0'), '');
assert.strictEqual(change(1e308, 1e-308), '');
assert.strictEqual(ctx._copyOhlcChgPct(null, {close: 100}), '');
assert.strictEqual(ctx._copyOhlcChgPct({close: 100}, null), '');
// The user-visible clipboard line must also omit a missing close's percentage.
ctx.rawRows = {daily: [
    {date: '2026-01-01', open: 100, high: 100, low: 100, close: 100},
    {date: '2026-01-02', open: 100, high: 100, low: 100, close: null},
]};
ctx.state = {activeSymbol: 'TEST'};
assert.strictEqual(ctx.formatPaintedOhlcLine(),
    'TEST 2026-01-02 O 100.00 H 100.00 L 100.00 C —');
"""
        result = subprocess.run(
            [node, "-e", script, str(source)], capture_output=True,
            text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
