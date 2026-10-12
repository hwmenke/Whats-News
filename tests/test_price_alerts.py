"""Regression coverage for persisted user price alerts."""

import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class PriceAlertTests(unittest.TestCase):
    def test_malformed_saved_prices_do_not_draw_alert_lines(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const drawn = [];
const saved = JSON.stringify({AAPL: [
    null, '', '   ', false, true, [], {}, 'bad', 'Infinity',
    0, 123.45, '125.50'
]});
const ctx = {
    document: {addEventListener() {}, getElementById() {return null;}},
    localStorage: {getItem() {return saved;}},
    state: {activeSymbol: 'AAPL'},
    series: {daily: {candle: {
        createPriceLine(options) {drawn.push(options.price); return {};},
        removePriceLine() {}
    }}}
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('scripts/price_alerts.js', 'utf8'), ctx);
assert.deepStrictEqual(Array.from(ctx.getPriceAlertPrices()), [0, 123.45, 125.5]);
ctx.applyPriceAlerts();
assert.deepStrictEqual(drawn, [0, 123.45, 125.5]);
assert.strictEqual(ctx.getPriceAlertsOn(), true);
ctx.state.activeSymbol = 'MSFT';
assert.strictEqual(ctx.getPriceAlertsOn(), false);
"""
        proc = subprocess.run(
            [node, "-e", script], cwd=ROOT, capture_output=True,
            text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
