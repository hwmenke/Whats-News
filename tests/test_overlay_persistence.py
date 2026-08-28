"""Reload contract for overlay and method-pack pills (localStorage)."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

_NODE_RELOAD_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const root = process.argv[2];
const chartsSrc = fs.readFileSync(path.join(root, 'scripts', 'charts.js'), 'utf8');
const spySrc = fs.readFileSync(path.join(root, 'scripts', 'spy_rs.js'), 'utf8');
const newsSrc = fs.readFileSync(path.join(root, 'scripts', 'news_markers.js'), 'utf8');
const vwapSrc = fs.readFileSync(path.join(root, 'scripts', 'vwap.js'), 'utf8');
const lastSrc = fs.readFileSync(path.join(root, 'scripts', 'last_price.js'), 'utf8');

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

function makeStore(seed) {
    const data = Object.assign({}, seed || {});
    return {
        data,
        getItem(key) { return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null; },
        setItem(key, val) { data[key] = String(val); },
        removeItem(key) { delete data[key]; },
    };
}

function loadDesk(store) {
    const document = {
        getElementById: () => null,
        querySelectorAll: () => [],
        addEventListener: () => {},
    };
    const ctx = {
        console,
        document,
        localStorage: store,
        LightweightCharts: { LineStyle: { Dashed: 2, Solid: 0, LargeDashed: 3 } },
        fetch: () => Promise.reject(new Error('no network')),
    };
    ctx.window = ctx;
    ctx.globalThis = ctx;
    vm.createContext(ctx);
    vm.runInContext(chartsSrc, ctx);
    vm.runInContext(spySrc, ctx);
    vm.runInContext(newsSrc, ctx);
    vm.runInContext(vwapSrc, ctx);
    vm.runInContext(lastSrc, ctx);
    return ctx;
}

const OVERLAYS = 'whats-news-chart-overlays';
const PACKS = 'whats-news-chart-packs';

const store = makeStore();
let desk = loadDesk(store);
desk.applySavedOverlays();
desk.applySavedPacks();

const fresh = desk.collectOverlayState();
assert(fresh.bb === false, 'BB default off');
assert(fresh.ep === true, 'EP default on');
assert(fresh.darvas === true, 'Darvas default on');
assert(fresh.spy_rs === false, 'vs-SPY default off');
assert(fresh.news_markers === false, 'News default off');
assert(fresh.vwap === false, 'VWAP default off');
assert(fresh.last === false, 'Last default off');
assert(desk.spyRsIsOn() === false, 'spyRsIsOn default');
assert(desk.newsMarkersIsOn() === false, 'newsMarkersIsOn default');
assert(desk.vwapIsOn() === false, 'vwapIsOn default');
assert(desk.lastPriceIsOn() === false, 'lastPriceIsOn default');
assert(store.getItem(OVERLAYS) === null, 'must not write overlays before a user toggle');
assert(store.getItem(PACKS) === null, 'must not write packs before a user toggle');

desk.toggleOverlay('bb');
desk.toggleOverlay('ep');
desk.toggleOverlay('darvas');
desk.setSpyRsOn(true, { persist: true, apply: false });
desk.setNewsMarkersOn(false, { persist: true, apply: false });
desk.setVwapOn(true, { persist: true, apply: false });
desk.setLastPriceOn(true, { persist: true, apply: false });
desk.toggleChartPack('minervini');
desk.toggleChartPack('stockbee');
desk.toggleChartPack('weinstein');

const afterToggle = JSON.parse(store.getItem(OVERLAYS));
assert(afterToggle.bb === true, 'BB saved on');
assert(afterToggle.ep === false, 'EP saved off');
assert(afterToggle.darvas === false, 'Darvas saved off');
assert(afterToggle.spy_rs === true, 'vs-SPY saved on after toggle');
assert(afterToggle.news_markers === false, 'News stays off');
assert(afterToggle.vwap === true, 'VWAP saved on after toggle');
assert(afterToggle.last === true, 'Last saved on after toggle');
assert(store.getItem('whats-news-price-alerts') == null, 'overlay persist must not write price-alert lines');

const packsSaved = JSON.parse(store.getItem(PACKS));
assert(packsSaved.minervini === true, '50/150/200 pack saved');
assert(packsSaved.stockbee === true, '9/20 pack saved');
assert(packsSaved.weinstein === true, '10/40w pack saved');

desk = loadDesk(store);
desk.applySavedOverlays();
desk.applySavedPacks();
const restored = desk.collectOverlayState();
assert(restored.bb === true, 'BB restored');
assert(restored.ep === false, 'EP restored off');
assert(restored.darvas === false, 'Darvas restored off');
assert(restored.spy_rs === true, 'vs-SPY restored on');
assert(restored.news_markers === false, 'News restored off');
assert(restored.vwap === true, 'VWAP restored on');
assert(restored.last === true, 'Last restored on');
assert(desk.spyRsIsOn() === true, 'spyRsIsOn restored');
assert(desk.newsMarkersIsOn() === false, 'news still off');
assert(desk.vwapIsOn() === true, 'vwap restored');
assert(desk.lastPriceIsOn() === true, 'last restored');
desk.persistPacks();
const packsRestored = JSON.parse(store.getItem(PACKS));
assert(packsRestored.minervini === true, 'minervini restored');
assert(packsRestored.stockbee === true, 'stockbee restored');
assert(packsRestored.weinstein === true, 'weinstein restored');

const empty = makeStore();
desk = loadDesk(empty);
desk.applySavedOverlays();
desk.applySavedPacks();
const untouched = desk.collectOverlayState();
assert(untouched.spy_rs === false, 'empty storage must not turn vs-SPY on');
assert(untouched.news_markers === false, 'empty storage must not turn News on');
assert(untouched.vwap === false, 'empty storage must not turn VWAP on');
assert(untouched.last === false, 'empty storage must not turn Last on');
assert(untouched.bb === false, 'empty storage keeps BB off');
assert(untouched.ep === true, 'empty storage keeps EP on');
assert(untouched.darvas === true, 'empty storage keeps Darvas on');
assert(empty.getItem(OVERLAYS) === null, 'applySavedOverlays must not create the overlays key');
assert(empty.getItem(PACKS) === null, 'applySavedPacks must not create the packs key');

process.stdout.write(JSON.stringify({
    ok: true,
    keys: { overlays: OVERLAYS, packs: PACKS },
    restored: restored,
}));
"""


class OverlayPackReloadTests(unittest.TestCase):
    def test_reload_restores_toggles_and_empty_storage_keeps_spy_news_off(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_RELOAD_SCRIPT)
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
        self.assertEqual(payload["keys"]["overlays"], "whats-news-chart-overlays")
        self.assertEqual(payload["keys"]["packs"], "whats-news-chart-packs")
        self.assertTrue(payload["restored"]["spy_rs"])
        self.assertFalse(payload["restored"]["news_markers"])
        self.assertTrue(payload["restored"]["vwap"])
        self.assertTrue(payload["restored"]["last"])
