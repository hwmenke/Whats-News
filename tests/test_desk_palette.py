"""Keyboard regression coverage for the desk command palette."""

import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeskPaletteTests(unittest.TestCase):
    def test_arrow_down_with_no_matches_recovers_selection(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const handlers = {};
const input = {
    value: 'ZZZ',
    addEventListener(event, handler) {handlers[event] = handler;}
};
const overlay = {hidden: false, addEventListener() {}};
const results = {innerHTML: '', querySelectorAll() {return [];}};
const list = {querySelectorAll() {return [];}};
const elements = {
    'desk-palette': overlay, 'desk-palette-input': input,
    'desk-palette-results': results, 'symbol-list': list
};
const selected = [];
const ctx = {
    document: {addEventListener() {}, getElementById(id) {return elements[id];}},
    state: {symbols: [{symbol: 'AAPL'}]},
    selectSymbol(code) {selected.push(code);}
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('scripts/desk_palette.js', 'utf8'), ctx);
ctx.initDeskPalette();
// This query has no results (and cannot generate an Add row).
input.value = 'NO MATCH!';
handlers.input();
assert.ok(results.innerHTML.includes('No matches'));
handlers.keydown({key: 'ArrowDown', preventDefault() {}});
// Results can change after a watchlist refresh without another input event.
input.value = 'AAPL';
ctx.renderPaletteResults(input.value);
assert.ok(results.innerHTML.includes('desk-palette-row active'));
handlers.keydown({key: 'Enter', preventDefault() {}});
assert.deepStrictEqual(selected, ['AAPL']);
assert.strictEqual(overlay.hidden, true);
"""
        proc = subprocess.run(
            [node, "-e", script], cwd=ROOT, capture_output=True,
            text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
