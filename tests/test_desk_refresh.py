"""Browser refresh preferences must never create overflowing timers."""

import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeskRefreshTests(unittest.TestCase):
    def test_invalid_intervals_disable_refresh_and_clear_existing_timer(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
let saved = '{}';
let delays = [];
let cleared = [];
let callback;
let loads = 0;
const ctx = {
    localStorage: {
        getItem() {return saved;},
        setItem(key, value) {saved = value;}
    },
    setInterval(fn, delay) {callback = fn; delays.push(delay); return 42;},
    clearInterval(id) {cleared.push(id);},
    window: {},
    loadSymbols() {loads++;}
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('scripts/desk_prefs.js', 'utf8'), ctx);
for (const invalid of [Infinity, -Infinity, NaN, 'Infinity', 'bad',
                       2147483648 / 1000, -30, 14, 0, null, '', true, [30], {}]) {
    ctx.applyDeskRefreshInterval('30');
    assert.strictEqual(delays.pop(), 30000);
    callback();
    assert.strictEqual(loads > 0, true);
    ctx.applyDeskRefreshInterval(invalid);
    assert.strictEqual(delays.length, 0);
    assert.strictEqual(cleared.pop(), 42);
    assert.strictEqual(JSON.parse(saved).refreshSec, 0);
}
for (const valid of [15, '60', 2147483647 / 1000]) {
    ctx.applyDeskRefreshInterval(valid);
    assert.strictEqual(delays.pop(), Number(valid) * 1000);
    assert.strictEqual(JSON.parse(saved).refreshSec, Number(valid));
}
"""
        result = subprocess.run(
            [node, "-e", script], cwd=ROOT, capture_output=True,
            text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
