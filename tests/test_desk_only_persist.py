"""Reload contract: sidebar Desk only checkbox persists in localStorage."""

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
    "scripts/desk_only_persist.js",
    "tests/test_desk_only_persist.py",
)

STORAGE_KEY = "whats-news-desk-only"


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


class DeskOnlyPersistTests(unittest.TestCase):
    """Storage key, wrap toggle/boot, default true, existing desk load, no tape-sort edit."""

    @classmethod
    def setUpClass(cls):
        cls.persist = _read("scripts/desk_only_persist.js")
        cls.app_js = _read("scripts/app.js")
        cls.html = _read("index.html")
        cls.charts = _read("scripts/charts.js")
        cls.setup = _read("scripts/setup_scanner.js")

    def test_storage_key_wraps_toggle_and_boot_restore(self):
        js = self.persist
        self.assertIn("DESK_ONLY_KEY = 'whats-news-desk-only'", js)
        self.assertIn("whats-news-desk-only", js)
        self.assertIn("function readDeskOnly", js)
        self.assertIn("function writeDeskOnly", js)
        self.assertIn("function restoreDeskOnly", js)
        self.assertIn("function wrapToggleDeskOnly", js)
        self.assertIn("function wrapLoadSymbols", js)
        self.assertIn("function bootDeskOnlyPersist", js)
        self.assertIn("localStorage.getItem(DESK_ONLY_KEY)", js)
        self.assertIn("localStorage.setItem(DESK_ONLY_KEY, checked ? '1' : '0')", js)
        self.assertNotIn("whats-news-desk-only", self.app_js)

        read = js[js.index("function readDeskOnly") : js.index("function writeDeskOnly")]
        self.assertIn("if (raw == null) return true", read)
        self.assertIn("raw !== '0'", read)
        self.assertNotIn("sessionStorage", read)

        restore = js[js.index("function restoreDeskOnly") : js.index("function wrapToggleDeskOnly")]
        self.assertNotIn("localStorage.setItem", restore)
        self.assertNotIn("writeDeskOnly", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertIn("el.checked = !!on", restore)
        self.assertIn("state.deskOnly = !!on", restore)
        self.assertIn("getElementById('chk-desk-only')", restore)

        wrap_toggle = js[js.index("function wrapToggleDeskOnly") : js.index("function wrapLoadSymbols")]
        self.assertIn("writeDeskOnly(!!checked)", wrap_toggle)
        self.assertIn("orig.apply(this, arguments)", wrap_toggle)
        self.assertIn("g.toggleDeskOnly = toggleDeskOnlyPersist", wrap_toggle)
        self.assertLess(wrap_toggle.index("writeDeskOnly(!!checked)"), wrap_toggle.index("orig.apply"))

        wrap_load = js[js.index("function wrapLoadSymbols") : js.index("function bootDeskOnlyPersist")]
        self.assertIn("restoreDeskOnly()", wrap_load)
        self.assertIn("orig.apply(this, arguments)", wrap_load)
        self.assertIn("g.loadSymbols = loadSymbolsDeskOnly", wrap_load)
        self.assertLess(wrap_load.index("restoreDeskOnly()"), wrap_load.index("orig.apply"))

        boot = js[js.index("function bootDeskOnlyPersist") :]
        self.assertIn("wrapToggleDeskOnly()", boot)
        self.assertIn("wrapLoadSymbols()", boot)
        self.assertIn("restoreDeskOnly()", boot)
        self.assertLess(boot.index("wrapToggleDeskOnly()"), boot.index("restoreDeskOnly()"))
        self.assertLess(boot.index("wrapLoadSymbols()"), boot.index("restoreDeskOnly()"))

        html = self.html
        self.assertIn('id="chk-desk-only"', html)
        self.assertIn("scripts/desk_only_persist.js", html)
        self.assertLess(html.index("scripts/app.js"), html.index("scripts/desk_only_persist.js"))
        self.assertLess(html.index("scripts/journal_filter.js"), html.index("scripts/desk_only_persist.js"))
        chk = html[html.index('id="chk-desk-only"') : html.index('id="chk-desk-only"') + 80]
        self.assertIn("checked", chk)

    def test_existing_desk_load_contract_unchanged(self):
        app = self.app_js
        load = app[app.index("async function loadSymbols") : app.index("function updateSidebarCount")]
        self.assertIn("${API}/symbols?desk=1", load)
        self.assertIn("${API}/symbols", load)
        self.assertIn("state.deskOnly", load)
        toggle = app[app.index("async function toggleDeskOnly") : app.index("async function refreshPortfolioTape")]
        self.assertIn("state.deskOnly = checked", toggle)
        self.assertIn("await loadSymbols()", toggle)
        self.assertNotIn("localStorage", toggle)
        self.assertNotIn("DESK_ONLY_KEY", toggle)
        handler = app[app.index("getElementById('chk-desk-only')") :]
        handler = handler.split("document.getElementById('watchlist-filter')", 1)[0]
        self.assertIn("toggleDeskOnly(e.target.checked)", handler)
        self.assertNotIn("whats-news-desk-only", handler)

        js = self.persist.lower()
        self.assertNotIn("fetch(", js)
        self.assertNotIn("/api/", js)
        self.assertNotIn("symbols?desk", js)
        self.assertNotIn("tapesort", js)
        self.assertNotIn("settapesort", js)
        self.assertNotIn("xmlhttprequest", js)
        self.assertNotIn("sessionstorage", js)
        self.assertNotIn("whats-news-desk-only", self.charts)
        self.assertNotIn("whats-news-desk-only", self.setup)
        self.assertIn("deskOnly: true", app)
        self.assertIn("function setTapeSort", app)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            text = _read(path)
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")
        self.assertIn("not a published rating", self.persist)


class DeskOnlyPersistRoundTripTests(unittest.TestCase):
    """Node round-trip: default true, persist 0/1, restore checkbox, load uses saved deskOnly."""

    def test_restore_round_trip_storage_key(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")

        persist = _read("scripts/desk_only_persist.js")
        helpers = persist[
            persist.index("const DESK_ONLY_KEY") : persist.index("function bootDeskOnlyPersist")
        ]

        script = r"""
const mem = {};
const writes = [];
let boxChecked = true;
const urls = [];
global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); writes.push(['set', k, String(v)]); },
    removeItem: k => { delete mem[k]; writes.push(['del', k]); },
};
global.state = { deskOnly: true };
global.document = {
    getElementById: id => {
        if (id === 'chk-desk-only') {
            return {
                get checked() { return boxChecked; },
                set checked(v) { boxChecked = !!v; },
            };
        }
        return null;
    },
};
async function origLoadSymbols() {
    urls.push(state.deskOnly ? '/api/symbols?desk=1' : '/api/symbols');
}
async function origToggleDeskOnly(checked) {
    state.deskOnly = checked;
    await globalThis.loadSymbols();
}
globalThis.loadSymbols = origLoadSymbols;
globalThis.toggleDeskOnly = origToggleDeskOnly;
""" + helpers + r"""
function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

(async () => {
assert(DESK_ONLY_KEY === 'whats-news-desk-only', 'storage key');
assert(readDeskOnly() === true, 'missing key defaults true');
assert(restoreDeskOnly() === true, 'restore default true');
assert(state.deskOnly === true, 'state default true');
assert(boxChecked === true, 'checkbox default checked');
assert(writes.length === 0, 'restore of missing key must not write');

wrapToggleDeskOnly();
wrapLoadSymbols();
await globalThis.loadSymbols();
assert(urls.join(',') === '/api/symbols?desk=1', 'boot load uses desk=1 when unsaved');
assert(writes.length === 0, 'boot load must not persist default');

await globalThis.toggleDeskOnly(false);
assert(mem[DESK_ONLY_KEY] === '0', 'uncheck persists 0');
assert(state.deskOnly === false, 'toggle sets state false');
assert(urls[urls.length - 1] === '/api/symbols', 'unchecked load omits desk=1');

await globalThis.toggleDeskOnly(true);
assert(mem[DESK_ONLY_KEY] === '1', 'check persists 1');
assert(urls[urls.length - 1] === '/api/symbols?desk=1', 'checked load uses desk=1');

const writesAfterToggle = writes.length;
boxChecked = true;
state.deskOnly = true;
restoreDeskOnly();
assert(boxChecked === true, 'restore 1 keeps checked');
assert(state.deskOnly === true, 'restore 1 keeps deskOnly');
assert(writes.length === writesAfterToggle, 'restore must not write');

mem[DESK_ONLY_KEY] = '0';
boxChecked = true;
state.deskOnly = true;
const writesBeforeReload = writes.length;
restoreDeskOnly();
assert(boxChecked === false, 'reload restores unchecked');
assert(state.deskOnly === false, 'reload restores deskOnly false');
assert(writes.length === writesBeforeReload, 'reload restore must not write');
urls.length = 0;
await globalThis.loadSymbols();
assert(urls.join(',') === '/api/symbols', 'reload load omits desk=1 when saved 0');
assert(writes.length === writesBeforeReload, 'wrapped load restore must not persist');

delete mem[DESK_ONLY_KEY];
boxChecked = false;
state.deskOnly = false;
assert(readDeskOnly() === true, 'cleared key reads as default true');
restoreDeskOnly();
assert(boxChecked === true && state.deskOnly === true, 'cleared key restores checked/true');

process.stdout.write(JSON.stringify({
    ok: true,
    key: DESK_ONLY_KEY,
    lastUrl: urls[urls.length - 1],
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


if __name__ == "__main__":
    unittest.main()
