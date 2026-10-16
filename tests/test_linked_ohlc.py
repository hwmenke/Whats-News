"""Linked readouts must stay within the hovered bar's week."""
import pathlib
import shutil
import subprocess
import unittest

import portfolio

ROOT = pathlib.Path(__file__).resolve().parents[1]


class LinkedOhlcTests(unittest.TestCase):
    def test_missing_weeks_do_not_use_unrelated_bars(self):
        daily = [{"date": "2024-01-12"}]
        weekly = [{"date": "2024-01-12"}, {"date": "2024-01-26"}]
        for day in ("2024-01-01", "2024-01-15", "2024-01-29"):
            self.assertIsNone(portfolio.linked_ohlc_bar("daily", day, daily, weekly))
        self.assertIsNone(portfolio.linked_ohlc_bar("weekly", "2024-01-19", daily, weekly))
        self.assertEqual(portfolio.linked_ohlc_bar("daily", "2024-01-08", daily, weekly), weekly[0])
        self.assertEqual(portfolio.linked_ohlc_bar("weekly", "2024-01-12", daily, weekly), daily[0])
        # A holiday-shortened week still matches its final trading day.
        self.assertEqual(portfolio.linked_ohlc_bar("weekly", "2024-01-12", [{"date": "2024-01-11"}], weekly), {"date": "2024-01-11"})

    def test_browser_missing_week_mapping(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const ctx = {rawRows: {
    daily: [{date: '2024-01-12'}],
    weekly: [{date: '2024-01-12'}, {date: '2024-01-26'}]
}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('scripts/linked_ohlc.js', 'utf8'), ctx);
for (const day of ['2024-01-01', '2024-01-15', '2024-01-29']) {
    assert.strictEqual(ctx.linkedBarFor('daily', day), null);
}
assert.strictEqual(ctx.linkedBarFor('weekly', '2024-01-19'), null);
assert.strictEqual(ctx.linkedBarFor('daily', '2024-01-08').row.date, '2024-01-12');
assert.strictEqual(ctx.linkedBarFor('weekly', '2024-01-12').row.date, '2024-01-12');
ctx.rawRows.daily = [{date: '2024-01-11'}];
assert.strictEqual(ctx.linkedBarFor('weekly', '2024-01-12').row.date, '2024-01-11');
"""
        result = subprocess.run([node, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
