import os
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import numpy as np
import pandas as pd

import database as db
import portfolio
import setup_scanner


class SetupScannerTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "setup_scan.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()

        idx = pd.date_range("2024-01-01", periods=60, freq="D")
        self.frame = pd.DataFrame(
            {
                "open": np.linspace(100, 130, 60),
                "high": np.linspace(101, 135, 60),
                "low": np.linspace(99, 128, 60),
                "close": np.linspace(100.5, 132, 60),
                "volume": np.full(60, 2_000_000.0),
            },
            index=idx,
        )
        db.add_symbol("TEST1")
        db.upsert_ohlcv("TEST1", "daily", self.frame)

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_scan_setups_returns_catalog(self):
        with patch("setup_scanner.md.list_symbols_with_ohlcv", return_value=["TEST1"]):
            out = setup_scanner.scan_setups(limit=10)
        self.assertIn("setup_catalog", out)
        self.assertIn("EP", out["setup_catalog"])
        self.assertEqual(out["scanned"], 1)
        self.assertGreaterEqual(out["count"], 0)

    def test_scan_filters_by_setup_tag(self):
        fake_row = {
            "symbol": "TEST1",
            "ready": True,
            "setups": ["EP", "NEAR_HIGH"],
            "setup_score": 2,
            "change_pct": 1.0,
        }
        with patch("setup_scanner._scan_one_setup", return_value=fake_row):
            out = setup_scanner.scan_setups(symbols=["TEST1"], setup_filter="EP")
        self.assertEqual(out["count"], 1)
        with patch("setup_scanner._scan_one_setup", return_value=fake_row):
            out2 = setup_scanner.scan_setups(symbols=["TEST1"], setup_filter="DARVAS_BOX")
        self.assertEqual(out2["count"], 0)

    def test_scan_payload_includes_adr_pct(self):
        with patch("setup_scanner.md.list_symbols_with_ohlcv", return_value=["TEST1"]):
            out = setup_scanner.scan_setups(limit=10)
        ready = [r for r in out["results"] if r.get("ready")]
        self.assertTrue(ready)
        row = ready[0]
        self.assertIn("adr_pct", row)
        daily = db.get_ohlcv("TEST1", "daily", limit=setup_scanner.SCAN_ADR_BARS)
        expected = setup_scanner.scan_adr_pct(daily)
        self.assertIsNotNone(expected)
        self.assertAlmostEqual(row["adr_pct"], expected)
        self.assertAlmostEqual(expected, round(portfolio.legend_adr_pct(daily), 2))
        self.assertIn("vol_ratio_5_20", row)
        self.assertIsNotNone(row["vol_ratio_5_20"])

    def test_scan_adr_pct_matches_legend_math(self):
        rows = [{"high": 102.41, "low": 100.0, "close": 100.0}] * 20
        self.assertAlmostEqual(setup_scanner.scan_adr_pct(rows), 2.41)
        self.assertEqual(portfolio.format_legend_adr(portfolio.legend_adr_pct(rows)), "ADR 2.41%")
        self.assertIsNone(setup_scanner.scan_adr_pct([{"high": 102.0, "low": 100.0, "close": 100.0}] * 4))
        self.assertIsNone(setup_scanner.scan_adr_pct(None))
        self.assertIsNone(setup_scanner.scan_adr_pct([]))


class SetupScanRowMetricChipTests(unittest.TestCase):
    """Glanceable ADR / RVOL chips on Scan hit rows — omit when missing, not N/A."""

    def test_chip_class_and_adr_field_contract(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        with open("setup_scanner.py", encoding="utf-8") as fh:
            py = fh.read()
        with open("styles/main.css", encoding="utf-8") as fh:
            css = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()

        self.assertIn("function formatSetupAdrChip", setup)
        self.assertIn("function formatSetupRvolChip", setup)
        self.assertIn("function setupMetricChipsHtml", setup)
        self.assertIn("setup-metric-chip", setup)
        self.assertIn("setup-metric-chips", setup)
        self.assertIn("row.adr_pct", setup)
        self.assertIn("row.vol_ratio_5_20", setup)
        self.assertIn("ADR ${", setup)
        self.assertIn("RVOL ${", setup)
        self.assertIn("toFixed(1)", setup)
        self.assertIn("setupMetricChipsHtml(row)", setup)
        self.assertIn("${row.symbol}${metricChips}", setup)
        self.assertNotIn("N/A", setup)
        self.assertNotIn("share float", setup.lower())
        self.assertNotIn("share_float", setup)

        self.assertIn("def scan_adr_pct", py)
        self.assertIn("legend_adr_pct", py)
        self.assertIn('"adr_pct": scan_adr_pct(daily_rows)', py)
        self.assertIn("SCAN_ADR_BARS", py)
        self.assertNotIn("share_float", py)
        self.assertNotIn("share float", py.lower())

        self.assertIn(".setup-metric-chip", css)
        self.assertIn(".setup-metric-chips", css)
        self.assertIn("color: var(--text-muted)", css)

        # Enter still opens the chart without leaving Scan.
        self.assertIn("Stay in Scan workspace", setup)
        self.assertNotIn("switchTab('charts')", setup)
        self.assertIn('data-workspace="chart"', html)
        self.assertIn('data-workspace="scan"', html)
        self.assertIn('data-workspace="review"', html)

        for blob in (setup, py, css):
            self.assertIsNone(re.search(r"ibd", blob, re.IGNORECASE))

    def test_chip_html_omits_missing_and_formats_compact(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        start = setup.index("function formatSetupAdrChip")
        end = setup.index("function renderSetupScanTable")
        fns = setup[start:end]
        script = fns + r"""
const both = setupMetricChipsHtml({adr_pct: 2.41, vol_ratio_5_20: 1.84});
const none = setupMetricChipsHtml({});
const adrOnly = setupMetricChipsHtml({adr_pct: 2.4});
const rvolOnly = setupMetricChipsHtml({vol_ratio_5_20: 1.8});
const missing = setupMetricChipsHtml({adr_pct: null, vol_ratio_5_20: null});
console.log(JSON.stringify({both, none, adrOnly, rvolOnly, missing}));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        import json
        out = json.loads(proc.stdout)
        self.assertIn('class="setup-metric-chip"', out["both"])
        self.assertIn("ADR 2.4%", out["both"])
        self.assertIn("RVOL 1.8\u00d7", out["both"])
        self.assertEqual(out["none"], "")
        self.assertEqual(out["missing"], "")
        self.assertIn("ADR 2.4%", out["adrOnly"])
        self.assertNotIn("RVOL", out["adrOnly"])
        self.assertIn("RVOL 1.8\u00d7", out["rvolOnly"])
        self.assertNotIn("ADR", out["rvolOnly"])
        for html in out.values():
            self.assertNotIn("N/A", html)


class SetupScanFilterPersistenceTests(unittest.TestCase):
    """Reload restores last Scan filter + universe; hit rows stay on the 60s cache."""

    def test_storage_key_and_restore_on_load_contract(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()

        self.assertIn("SETUP_FILTERS_STORAGE_KEY = 'whats-news-setup-filters'", setup)
        self.assertIn("whats-news-setup-filters", setup)
        self.assertIn("function readSetupFilters", setup)
        self.assertIn("function writeSetupFilters", setup)
        self.assertIn("function persistSetupFilters", setup)
        self.assertIn("function restoreSetupFilters", setup)
        self.assertIn("localStorage.getItem(SETUP_FILTERS_STORAGE_KEY)", setup)
        self.assertIn("localStorage.setItem(SETUP_FILTERS_STORAGE_KEY", setup)
        self.assertIn("restoreSetupFilters()", setup)
        self.assertIn("bindSetupUniverseToggle()", setup)
        self.assertIn("persistSetupFilters()", setup)

        init = setup[setup.index("async function initSetupScanner") : setup.index("function renderSetupFilterPills")]
        self.assertLess(init.index("restoreSetupFilters()"), init.index("apiFetch"))
        self.assertNotIn("loadSetupScan", init)

        restore = setup[setup.index("function restoreSetupFilters") : setup.index("function bindSetupUniverseToggle")]
        self.assertNotIn("loadSetupScan", restore)
        self.assertNotIn("sessionStorage", restore)
        self.assertIn("_setupFilter = saved.filter", restore)
        self.assertIn("el.checked = !!saved.universe", restore)

        self.assertIn("whats-news-setup-scan", setup)
        self.assertIn("sessionStorage.getItem(SETUP_SCAN_CACHE_KEY)", setup)
        self.assertIn("SETUP_SCAN_CACHE_TTL_MS = 60 * 1000", setup)

        self.assertIn("function setupMetricChipsHtml", setup)
        self.assertIn("setup-metric-chip", setup)
        self.assertIn("setupMetricChipsHtml(row)", setup)

        self.assertIn('id="chk-setup-universe"', html)
        self.assertIn('id="setup-filter-pills"', html)
        self.assertIn("loadSetupScan({ allowStaleRows: true })", app_js)
        self.assertNotIn("whats-news-setup-filters", app_js)

        self.assertIsNone(re.search(r"ibd", setup, re.IGNORECASE))
        self.assertIsNone(re.search(r"ibd", html, re.IGNORECASE))

    def test_restore_round_trip_without_scan(self):
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        start = setup.index("function currentSetupUniverse")
        end = setup.index("async function initSetupScanner")
        fns = setup[start:end]
        script = r"""
const mem = {};
const session = {};
let checkbox = { checked: true, addEventListener() {} };
global.localStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null),
    setItem: (k, v) => { mem[k] = String(v); },
};
global.sessionStorage = {
    getItem: k => (Object.prototype.hasOwnProperty.call(session, k) ? session[k] : null),
    setItem: (k, v) => { session[k] = String(v); },
};
global.document = {
    getElementById: id => (id === 'chk-setup-universe' ? checkbox : null),
};
let loadSetupScanCalls = 0;
global.loadSetupScan = () => { loadSetupScanCalls += 1; };
const SETUP_FILTERS_STORAGE_KEY = 'whats-news-setup-filters';
let _setupFilter = null;
""" + fns + r"""
writeSetupFilters('EP', false);
const saved = readSetupFilters();
_setupFilter = null;
checkbox.checked = true;
const applied = restoreSetupFilters();
persistSetupFilters();
const round = JSON.parse(localStorage.getItem(SETUP_FILTERS_STORAGE_KEY));
const empty = readSetupFilters();
localStorage.setItem(SETUP_FILTERS_STORAGE_KEY, 'not-json');
const bad = readSetupFilters();
localStorage.setItem(SETUP_FILTERS_STORAGE_KEY, JSON.stringify({ filter: 'ALL', universe: true }));
const all = readSetupFilters();
console.log(JSON.stringify({
    saved,
    applied,
    checkbox: checkbox.checked,
    filterAfter: _setupFilter,
    round,
    scanCalls: loadSetupScanCalls,
    sessionKeys: Object.keys(session),
    allFilter: all && all.filter,
    bad,
    key: SETUP_FILTERS_STORAGE_KEY,
}));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        import json
        out = json.loads(proc.stdout)
        self.assertEqual(out["key"], "whats-news-setup-filters")
        self.assertEqual(out["saved"], {"filter": "EP", "universe": False})
        self.assertEqual(out["applied"], {"filter": "EP", "universe": False})
        self.assertFalse(out["checkbox"])
        self.assertEqual(out["filterAfter"], "EP")
        self.assertEqual(out["round"], {"filter": "EP", "universe": False})
        self.assertEqual(out["scanCalls"], 0)
        self.assertEqual(out["sessionKeys"], [])
        self.assertIsNone(out["allFilter"])
        self.assertIsNone(out["bad"])


if __name__ == "__main__":
    unittest.main()
