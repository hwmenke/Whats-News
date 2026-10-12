"""Regression coverage for persisted user price alerts."""

import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class PriceAlertTests(unittest.TestCase):
    def test_removing_one_chip_preserves_nearby_alerts(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let saved = JSON.stringify({AAPL: [100, 100.10, 100.123], MSFT: [200]});
const ctx = {
    document: {addEventListener() {}, getElementById() {return null;}},
    localStorage: {
        getItem() {return saved;},
        setItem(key, value) {saved = value;}
    },
    state: {activeSymbol: 'AAPL'}
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('scripts/price_alerts.js', 'utf8'), ctx);
ctx.removePriceAlert(100.10);
assert.deepStrictEqual(JSON.parse(saved), {AAPL: [100, 100.123], MSFT: [200]});
// Chips display two decimals, including for legacy saved prices.
ctx.removePriceAlert(100.12);
assert.deepStrictEqual(JSON.parse(saved), {AAPL: [100], MSFT: [200]});
ctx.removePriceAlert(100.01);
assert.deepStrictEqual(JSON.parse(saved), {AAPL: [100], MSFT: [200]});
ctx.removePriceAlert(100);
assert.deepStrictEqual(JSON.parse(saved), {MSFT: [200]});
"""
        proc = subprocess.run(
            [node, "-e", script], cwd=ROOT, capture_output=True,
            text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_click_prices_reject_malformed_values_and_keep_valid_fallbacks(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let coordinatePrice = null;
let barClose = null;
let storedClose = null;
const candle = {coordinateToPrice() {return coordinatePrice;}};
const ctx = {
    document: {addEventListener() {}},
    series: {daily: {candle}},
    rawRows: {daily: []},
    _legendTimeKey(time) {return time;}
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('scripts/price_alerts.js', 'utf8'), ctx);
const param = {
    point: {y: 10}, time: '2026-10-12',
    seriesData: {get() {return {close: barClose};}}
};
for (const value of [null, undefined, '', '   ', false, true, [], {}, NaN, Infinity, 'bad']) {
    coordinatePrice = barClose = storedClose = value;
    ctx.rawRows.daily = [{date: param.time, close: storedClose}];
    assert.strictEqual(ctx._priceFromClickParam(param), null);
}
for (const value of [0, 123.45, '125.50']) {
    coordinatePrice = value;
    assert.strictEqual(ctx._priceFromClickParam(param), Number(value));
    coordinatePrice = '';
    barClose = value;
    assert.strictEqual(ctx._priceFromClickParam(param), Number(value));
    barClose = false;
    ctx.rawRows.daily = [{date: param.time, close: value}];
    assert.strictEqual(ctx._priceFromClickParam(param), Number(value));
}
"""
        proc = subprocess.run(
            [node, "-e", script], cwd=ROOT, capture_output=True,
            text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

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
