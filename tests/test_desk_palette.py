"""Keyboard regression coverage for the desk command palette."""

import pathlib
import shutil
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeskPaletteTests(unittest.TestCase):
    def test_opening_resets_selection_for_reopen_and_mode_switch(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const handlers = {};
const input = {
    value: '', focus() {},
    addEventListener(event, handler) {handlers[event] = handler;}
};
const overlay = {hidden: true, addEventListener() {}};
const results = {innerHTML: '', querySelectorAll() {return [];}};
const elements = {
    'desk-palette': overlay, 'desk-palette-input': input,
    'desk-palette-results': results
};
const selected = [], workspaces = [];
const ctx = {
    document: {addEventListener() {}, getElementById(id) {return elements[id];}},
    requestAnimationFrame(fn) {fn();},
    state: {symbols: [{symbol: 'AAPL'}, {symbol: 'MSFT'}, {symbol: 'GOOG'}]},
    selectSymbol(code) {selected.push(code);},
    setWorkspace(name) {workspaces.push(name);}
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('scripts/desk_palette.js', 'utf8'), ctx);
ctx.initDeskPalette();
const press = key => handlers.keydown({key, preventDefault() {}});
ctx.openDeskPalette();
press('ArrowDown');
press('ArrowDown');
press('Escape');
ctx.openDeskPalette();
press('Enter');
assert.deepStrictEqual(selected, ['AAPL']);
assert.strictEqual(overlay.hidden, true);
ctx.openDeskPalette();
press('ArrowDown');
ctx.openDeskPalette('command');
assert.ok(/desk-palette-row active[\s\S]*?data-idx="0"/.test(results.innerHTML));
press('Enter');
assert.deepStrictEqual(workspaces, ['chart']);
assert.strictEqual(overlay.hidden, true);
"""
        proc = subprocess.run(
            [node, "-e", script], cwd=ROOT, capture_output=True,
            text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

    def test_closing_restores_focus_to_opener(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        script = r"""
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const inputHandlers = {}, overlayHandlers = {}, documentHandlers = {};
const document = {
    activeElement: null,
    addEventListener(event, handler) {documentHandlers[event] = handler;},
    getElementById(id) {return elements[id];}
};
let restored = 0;
const opener = {
    isConnected: true,
    focus() {restored++; document.activeElement = this;}
};
const input = {
    value: '', isConnected: true,
    focus() {document.activeElement = this;},
    addEventListener(event, handler) {inputHandlers[event] = handler;}
};
const overlay = {
    hidden: true,
    addEventListener(event, handler) {overlayHandlers[event] = handler;}
};
const elements = {
    'desk-palette': overlay, 'desk-palette-input': input,
    'desk-palette-results': {innerHTML: '', querySelectorAll() {return [];}}
};
const ctx = {document, state: {symbols: []}, requestAnimationFrame(fn) {fn();}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('scripts/desk_palette.js', 'utf8'), ctx);
ctx.initDeskPalette();
document.activeElement = opener;
ctx.openDeskPalette();
assert.strictEqual(document.activeElement, input);
// Switching modes while open must preserve the original opener.
ctx.openDeskPalette('command');
inputHandlers.keydown({key: 'Escape', preventDefault() {}});
assert.strictEqual(overlay.hidden, true);
assert.strictEqual(document.activeElement, opener);
assert.strictEqual(restored, 1);
ctx.closeDeskPalette();
assert.strictEqual(restored, 1);
ctx.openDeskPalette();
overlayHandlers.click({target: overlay});
assert.strictEqual(document.activeElement, opener);
ctx.openDeskPalette('command');
documentHandlers.keydown({key: 'k', ctrlKey: true, target: input, preventDefault() {}});
assert.strictEqual(document.activeElement, opener);
assert.strictEqual(restored, 3);
// Escape must also work after Tab moves focus from the input to a result.
ctx.openDeskPalette('command');
const result = {tagName: 'BUTTON'};
document.activeElement = result;
let prevented = false;
documentHandlers.keydown({key: 'Escape', target: result, preventDefault() {prevented = true;}});
assert.strictEqual(prevented, true);
assert.strictEqual(overlay.hidden, true);
assert.strictEqual(document.activeElement, opener);
assert.strictEqual(restored, 4);
// Escape outside the palette remains available to other keyboard handlers.
prevented = false;
documentHandlers.keydown({key: 'Escape', target: opener, preventDefault() {prevented = true;}});
assert.strictEqual(prevented, false);
// A removed opener cannot receive focus.
ctx.openDeskPalette();
opener.isConnected = false;
ctx.closeDeskPalette();
assert.strictEqual(restored, 4);
"""
        proc = subprocess.run(
            [node, "-e", script], cwd=ROOT, capture_output=True,
            text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)

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
