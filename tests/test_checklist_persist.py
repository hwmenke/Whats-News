"""Reload contract: process-tools checklist persists in localStorage."""

import json
import os
import re
import shutil
import subprocess
import unittest

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

FORBIDDEN = (
    "scripts/app.js",
    "scripts/charts.js",
    "index.html",
    "portfolio.py",
    "scripts/spy_rs.js",
    "scripts/setup_scanner.js",
    "scripts/checklist_persist.js",
    "tests/test_checklist_persist.py",
)

OWNED_OFF_LIMITS = (
    "scripts/charts.js",
    "scripts/heatmap_sort.js",
    "scripts/last_price.js",
    "scripts/theme_leader_filter.js",
)

STORAGE_KEY = "whats-news-checklist"
CHECKLIST_KEYS = ("regime", "stop", "size", "plan")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class ChecklistPersistTests(unittest.TestCase):
    """Storage key, wrap syncChecklist, restore on boot, no risk-box prices, no tape-sort."""

    @classmethod
    def setUpClass(cls):
        cls.persist = _read("scripts/checklist_persist.js")
        cls.app_js = _read("scripts/app.js")
        cls.html = _read("index.html")
        cls.charts = _read("scripts/charts.js")
        cls.setup = _read("scripts/setup_scanner.js")
        cls.heatmap = _read("scripts/heatmap_sort.js")
        cls.last_price = _read("scripts/last_price.js")
        cls.theme = _read("scripts/theme_leader_filter.js")

    def test_storage_key_wraps_sync_and_boot_restore(self):
        js = self.persist
        self.assertIn("CHECKLIST_KEY = 'whats-news-checklist'", js)
        self.assertIn("whats-news-checklist", js)
        self.assertIn("function emptyChecklist", js)
        self.assertIn("function normalizeChecklist", js)
        self.assertIn("function readChecklist", js)
        self.assertIn("function writeChecklist", js)
        self.assertIn("function persistChecklist", js)
        self.assertIn("function restoreChecklist", js)
        self.assertIn("function wrapSyncChecklist", js)
        self.assertIn("function bootChecklistPersist", js)
        self.assertIn("localStorage.getItem(CHECKLIST_KEY)", js)
        self.assertIn(
            "localStorage.setItem(CHECKLIST_KEY, JSON.stringify(normalizeChecklist(flags)))",
            js,
        )
        self.assertNotIn("whats-news-checklist", self.app_js)
        self.assertNotIn("sessionStorage", js)

        empty = js[js.index("function emptyChecklist") : js.index("function normalizeChecklist")]
        self.assertIn("regime: false", empty)
        self.assertIn("stop: false", empty)
        self.assertIn("size: false", empty)
        self.assertIn("plan: false", empty)

        read = js[js.index("function readChecklist") : js.index("function writeChecklist")]
        self.assertIn("JSON.parse(raw)", read)
        self.assertIn("if (raw == null) return emptyChecklist()", read)
        self.assertIn("catch", read)
        self.assertIn("return emptyChecklist()", read)
        self.assertNotIn("sessionStorage", read)
        self.assertNotIn("localStorage.setItem", read)

        restore = js[js.index("function restoreChecklist") : js.index("function wrapSyncChecklist")]
        self.assertNotIn("localStorage.setItem", restore)
        self.assertNotIn("writeChecklist", restore)
        self.assertNotIn("persistChecklist", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertIn("querySelectorAll('#pm-checklist input[type=\"checkbox\"]')", restore)
        self.assertIn("box.checked = !!flags[key]", restore)
        self.assertIn("state.checklist =", restore)

        wrap = js[js.index("function wrapSyncChecklist") : js.index("function bootChecklistPersist")]
        self.assertIn("orig.apply(this, arguments)", wrap)
        self.assertIn("persistChecklist()", wrap)
        self.assertIn("g.syncChecklist = syncChecklistPersist", wrap)
        self.assertLess(wrap.index("orig.apply"), wrap.index("persistChecklist()"))
        self.assertIn("_checklistPersistWrapped", wrap)

        boot = js[js.index("function bootChecklistPersist") :]
        self.assertIn("wrapSyncChecklist()", boot)
        self.assertIn("restoreChecklist()", boot)
        self.assertLess(boot.index("wrapSyncChecklist()"), boot.index("restoreChecklist()"))

        html = self.html
        self.assertIn("scripts/checklist_persist.js", html)
        self.assertLess(html.index("scripts/app.js"), html.index("scripts/checklist_persist.js"))
        self.assertLess(
            html.index("scripts/desk_only_persist.js"),
            html.index("scripts/checklist_persist.js"),
        )
        self.assertLess(
            html.index("scripts/checklist_persist.js"),
            html.index("scripts/theme_leader_filter.js"),
        )
        self.assertIn('id="pm-checklist"', html)
        for key in CHECKLIST_KEYS:
            self.assertIn(f'data-check="{key}"', html)

    def test_existing_checklist_contract_unchanged(self):
        app = self.app_js
        self.assertIn(
            "checklist: { regime: false, stop: false, size: false, plan: false }",
            app,
        )
        sync = app[app.index("function syncChecklist") : app.index("function computeRMultiple")]
        self.assertIn("querySelectorAll('#pm-checklist input[type=\"checkbox\"]')", sync)
        self.assertIn("state.checklist[box.dataset.check] = box.checked", sync)
        self.assertIn("pm-copy-setup", sync)
        self.assertIn("pm-save-journal", sync)
        self.assertNotIn("localStorage", sync)
        self.assertNotIn("CHECKLIST_KEY", sync)
        self.assertNotIn("whats-news-checklist", sync)

        boot = app[app.index("document.addEventListener('DOMContentLoaded'") :]
        handler = boot[boot.index("querySelectorAll('#pm-checklist input[type=\"checkbox\"]'") :]
        handler = handler.split("document.getElementById('pm-copy-setup')", 1)[0]
        self.assertIn("box.addEventListener('change', syncChecklist)", handler)
        self.assertIn("syncChecklist()", handler)
        self.assertNotIn("whats-news-checklist", handler)
        self.assertNotIn("localStorage", handler)

        self.assertIn("function setTapeSort", app)
        self.assertIn("TAPE_SORT_KEY = 'whats-news-tape-sort'", app)
        self.assertIn("function restoreTapeSort", app)

        js = self.persist.lower()
        self.assertNotIn("fetch(", js)
        self.assertNotIn("/api/", js)
        self.assertNotIn("xmlhttprequest", js)
        self.assertNotIn("sessionstorage", js)
        self.assertNotIn("settapesort", js)
        self.assertNotIn("tapesort", js)
        self.assertNotIn("whats-news-tape-sort", js)
        self.assertNotIn("heatmap_sort", js)
        self.assertNotIn("last_price", js)
        self.assertNotIn("theme_leader", js)
        self.assertNotIn("whats-news-checklist", self.charts)
        self.assertNotIn("whats-news-checklist", self.setup)
        self.assertNotIn("whats-news-checklist", self.heatmap)
        self.assertNotIn("whats-news-checklist", self.last_price)
        self.assertNotIn("whats-news-checklist", self.theme)
        self.assertNotIn("checklist_persist", self.heatmap)
        self.assertNotIn("checklist_persist", self.last_price)
        self.assertNotIn("checklist_persist", self.theme)
        self.assertNotIn("checklist_persist", self.charts)

    def test_does_not_persist_risk_box_prices(self):
        js = self.persist
        self.assertNotIn("pm-entry-input", js)
        self.assertNotIn("pm-stop-input", js)
        self.assertNotIn("pm-target-input", js)
        self.assertNotIn("pm-apply-risk-box", js)
        self.assertNotIn("applyRiskBoxFromInputs", js)
        self.assertNotIn("riskBox", js)
        self.assertNotIn("risk_box", js)
        write = js[js.index("function writeChecklist") : js.index("function persistChecklist")]
        self.assertIn("normalizeChecklist(flags)", write)
        self.assertNotIn("entry", write)
        self.assertNotIn("target", write)
        persist = js[js.index("function persistChecklist") : js.index("function restoreChecklist")]
        self.assertIn("state.checklist", persist)
        self.assertNotIn("state.riskBox", persist)
        restore = js[js.index("function restoreChecklist") : js.index("function wrapSyncChecklist")]
        self.assertNotIn("pm-entry-input", restore)
        self.assertNotIn("pm-stop-input", restore)
        self.assertNotIn("pm-target-input", restore)
        self.assertNotIn("riskBox", restore)
        apply_box = self.app_js[
            self.app_js.index("function applyRiskBoxFromInputs") : self.app_js.index("async function openBookNews")
        ]
        self.assertNotIn("whats-news-checklist", apply_box)
        self.assertNotIn("CHECKLIST_KEY", apply_box)
        self.assertNotIn("localStorage", apply_box)
        for rel in OWNED_OFF_LIMITS:
            text = _read(rel)
            self.assertNotIn("whats-news-checklist", text)
            self.assertNotIn("checklist_persist", text)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            text = _read(path)
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        self.assertIn("not a published rating", self.persist)


class ChecklistPersistRoundTripTests(unittest.TestCase):
    """Node round-trip: persist four flags, restore boxes/state, invalid JSON → all false."""

    def test_restore_round_trip_storage_key(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        persist = _read("scripts/checklist_persist.js")
        helpers = persist[
            persist.index("const CHECKLIST_KEY") : persist.index("function bootChecklistPersist")
        ]

        script = r"""
const mem = {};
const writes = [];
const boxes = {
    regime: { dataset: { check: 'regime' }, checked: false },
    stop: { dataset: { check: 'stop' }, checked: false },
    size: { dataset: { check: 'size' }, checked: false },
    plan: { dataset: { check: 'plan' }, checked: false },
};
const copyBtn = { disabled: true, title: 'Complete checklist first' };
const saveBtn = { disabled: true, title: 'Complete checklist first' };
let entryValue = '101.25';
let stopValue = '95.5';
let targetValue = '120';
global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem: k => { delete mem[k]; writes.push(['del', k]); },
};
global.state = {
    checklist: { regime: false, stop: false, size: false, plan: false },
    riskBox: { entry: 101.25, stop: 95.5, target: 120 },
};
global.document = {
    querySelectorAll: sel => {
        if (sel === '#pm-checklist input[type="checkbox"]') {
            return [boxes.regime, boxes.stop, boxes.size, boxes.plan];
        }
        return [];
    },
    getElementById: id => {
        if (id === 'pm-copy-setup') return copyBtn;
        if (id === 'pm-save-journal') return saveBtn;
        if (id === 'pm-entry-input') return { get value() { return entryValue; }, set value(v) { entryValue = String(v); } };
        if (id === 'pm-stop-input') return { get value() { return stopValue; }, set value(v) { stopValue = String(v); } };
        if (id === 'pm-target-input') return { get value() { return targetValue; }, set value(v) { targetValue = String(v); } };
        return null;
    },
};
function origSyncChecklist() {
    const list = document.querySelectorAll('#pm-checklist input[type="checkbox"]');
    list.forEach(box => { state.checklist[box.dataset.check] = box.checked; });
    const allChecked = Object.values(state.checklist).every(Boolean);
    copyBtn.disabled = !allChecked;
    saveBtn.disabled = !allChecked;
    copyBtn.title = allChecked ? 'Copy setup card' : 'Complete checklist first';
    saveBtn.title = allChecked ? 'Save to journal' : 'Complete checklist first';
}
globalThis.syncChecklist = origSyncChecklist;
""" + helpers + r"""
function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}
function flagsEq(a, b) {
    return !!(a && b) && a.regime === b.regime && a.stop === b.stop && a.size === b.size && a.plan === b.plan;
}

(async () => {
assert(CHECKLIST_KEY === 'whats-news-checklist', 'storage key');
const missing = readChecklist();
assert(flagsEq(missing, { regime: false, stop: false, size: false, plan: false }), 'missing key is all false');
assert(writes.length === 0, 'read of missing key must not write');

const restoredMissing = restoreChecklist();
assert(flagsEq(restoredMissing, { regime: false, stop: false, size: false, plan: false }), 'restore missing is all false');
assert(!boxes.regime.checked && !boxes.stop.checked && !boxes.size.checked && !boxes.plan.checked, 'boxes stay unchecked');
assert(writes.length === 0, 'restore of missing key must not write');
assert(entryValue === '101.25' && stopValue === '95.5' && targetValue === '120', 'restore must not touch risk box prices');
assert(state.riskBox.entry === 101.25, 'restore must not rewrite state.riskBox');

wrapSyncChecklist();
boxes.regime.checked = true;
boxes.stop.checked = true;
boxes.size.checked = false;
boxes.plan.checked = true;
globalThis.syncChecklist();
assert(mem[CHECKLIST_KEY], 'toggle persists JSON');
const saved = JSON.parse(mem[CHECKLIST_KEY]);
assert(saved.regime === true && saved.stop === true && saved.size === false && saved.plan === true, 'persisted flags');
assert(!Object.prototype.hasOwnProperty.call(saved, 'entry'), 'must not persist entry price');
assert(!Object.prototype.hasOwnProperty.call(saved, 'target'), 'must not persist target price');
assert(Object.keys(saved).sort().join(',') === 'plan,regime,size,stop', 'only four checklist keys');
assert(!writes.some(w => w[1] !== CHECKLIST_KEY), 'must not write other storage keys');
assert(copyBtn.disabled === true, 'size still unchecked so copy stays gated');

boxes.regime.checked = false;
boxes.stop.checked = false;
boxes.size.checked = false;
boxes.plan.checked = false;
state.checklist = { regime: false, stop: false, size: false, plan: false };
copyBtn.disabled = true;
saveBtn.disabled = true;
const writesAfterToggle = writes.length;
const restored = restoreChecklist();
assert(flagsEq(restored, { regime: true, stop: true, size: false, plan: true }), 'restore returns saved flags');
assert(boxes.regime.checked === true && boxes.stop.checked === true, 'reload restores checked boxes');
assert(boxes.size.checked === false && boxes.plan.checked === true, 'unchecked size stays false; plan restored');
assert(state.checklist.regime === true && state.checklist.plan === true && state.checklist.size === false, 'state restored');
assert(writes.length === writesAfterToggle, 'restore must not write');
assert(entryValue === '101.25' && stopValue === '95.5' && targetValue === '120', 'reload must not change risk box inputs');

mem[CHECKLIST_KEY] = '{not-json';
boxes.regime.checked = true;
boxes.stop.checked = true;
boxes.size.checked = true;
boxes.plan.checked = true;
state.checklist = { regime: true, stop: true, size: true, plan: true };
const writesBeforeInvalid = writes.length;
const invalid = restoreChecklist();
assert(flagsEq(invalid, { regime: false, stop: false, size: false, plan: false }), 'invalid JSON is all false');
assert(!boxes.regime.checked && !boxes.stop.checked && !boxes.size.checked && !boxes.plan.checked, 'invalid JSON unchecks all');
assert(state.checklist.regime === false && state.checklist.plan === false, 'invalid JSON clears state');
assert(writes.length === writesBeforeInvalid, 'invalid JSON restore must not write');
assert(copyBtn.disabled === true, 'invalid JSON keeps copy gated');

mem[CHECKLIST_KEY] = JSON.stringify({ regime: true, stop: false, size: true, plan: false, entry: 99.5, target: 130, riskBox: { entry: 1 } });
const extra = restoreChecklist();
assert(flagsEq(extra, { regime: true, stop: false, size: true, plan: false }), 'extra price keys ignored');
assert(entryValue === '101.25', 'extra stored prices must not fill entry input');

boxes.regime.checked = true;
boxes.stop.checked = true;
boxes.size.checked = true;
boxes.plan.checked = true;
globalThis.syncChecklist();
const afterAll = JSON.parse(mem[CHECKLIST_KEY]);
assert(afterAll.regime && afterAll.stop && afterAll.size && afterAll.plan, 'all four persist true');
assert(copyBtn.disabled === false && saveBtn.disabled === false, 'complete checklist unlocks copy/save');
assert(!Object.prototype.hasOwnProperty.call(afterAll, 'entry'), 'complete persist still omits prices');

process.stdout.write(JSON.stringify({
    ok: true,
    key: CHECKLIST_KEY,
    savedKeys: Object.keys(saved).sort(),
    invalidAllFalse: true,
}));
})().catch(err => { console.error(err && err.stack ? err.stack : err); process.exit(1); });
"""
        proc = subprocess.run(
            [node, "-e", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["key"], STORAGE_KEY)
        self.assertEqual(payload["savedKeys"], ["plan", "regime", "size", "stop"])


if __name__ == "__main__":
    unittest.main()
