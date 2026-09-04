"""Visual maps + TMAC* / TES / TD approx — synthetic labels, empty honesty."""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ["DATA_SERVICE_MODE"] = "embedded"

import app as app_module
import data_client
import database as db
import engine_maps as em
import equity_engine as ee


def _frame(close, start="2023-01-02"):
    close = np.asarray(close, dtype=float)
    idx = pd.bdate_range(start, periods=len(close))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.4,
            "low": close - 0.4,
            "close": close,
            "volume": np.full(len(close), 1_000_000.0),
        },
        index=idx,
    )


class TmacStarTests(unittest.TestCase):
    def test_tmac_star_high_near_63d_high(self):
        close = np.linspace(80, 150, 90)
        heat = ee.tmac_star(pd.Series(close + 0.3), pd.Series(close - 0.3), pd.Series(close))
        self.assertIsNotNone(heat)
        self.assertGreaterEqual(heat, 70)
        self.assertLessEqual(heat, 99)

    def test_tmac_star_blank_when_short(self):
        close = np.linspace(100, 110, 20)
        self.assertIsNone(ee.tmac_star(pd.Series(close), pd.Series(close), pd.Series(close)))

    def test_measure_exposes_tmac_star_not_bare_tmac(self):
        row = ee.measure("AAA", daily=_frame(np.linspace(80, 150, 90)))
        self.assertIn("tmac_star", row)
        self.assertEqual(row["heat_proxy"], row["tmac_star"])
        self.assertNotIn("tmac", [k for k in row if k == "tmac"])
        self.assertEqual(row["tmac_note"], "TMAC* heat proxy — never branded TMAC")
        self.assertIn("0.50*range_pct", ee.tmac_star.__doc__)
        self.assertIn("never brand as bare tmac", ee.tmac_star.__doc__.lower())

    def test_tmac_star_uses_spec_weights(self):
        close = pd.Series(np.linspace(80, 150, 90))
        high = close + 0.3
        low = close - 0.3
        rp = ee.range_pct_63(high, low, close)
        rsi = ee.last_rsi(close, 14)
        vh = ee.vol_heat(high, low, close)
        expected = int(min(99, max(0, round(0.50 * rp + 0.35 * rsi + 0.15 * vh))))
        self.assertEqual(ee.tmac_star(high, low, close), expected)

    def test_tmac_star_low_in_downtrend(self):
        close = np.linspace(150, 40, 90)
        heat = ee.tmac_star(pd.Series(close + 0.3), pd.Series(close - 0.3), pd.Series(close))
        self.assertIsNotNone(heat)
        self.assertLessEqual(heat, 30)
        self.assertGreaterEqual(heat, 0)


class TesAndTdTests(unittest.TestCase):
    def test_tes_emerging_and_neutral(self):
        self.assertEqual(ee.tes_state(1.32, 0.02, 3, "TREND ↑", "BREAK ↑", 90), "EMERGING L")
        self.assertEqual(ee.tes_state(1.60, 0.01, 0, "MIXED", None, 40), "CHOP L")
        self.assertEqual(ee.tes_state(1.52, 0.01, 0, "TREND ↑", "TIGHTENING", 50), "RANGE/CHOP")
        self.assertEqual(ee.tes_state(1.46, 0.20, 0, "MIXED", None, 80), "TRANSITION L")
        self.assertEqual(ee.tes_state(1.49, 0.01, 0, "MIXED", None, 90), "NEUTRAL L")
        self.assertIsNone(ee.tes_state(None, 0.2, 3, "TREND ↑", "COILED", 90))

    def test_td_setup_on_steady_decline(self):
        close = pd.Series(np.linspace(120, 40, 40))
        pack = ee.td_sequential_approx(close)
        self.assertIsNotNone(pack["td_count"])
        self.assertLess(pack["td_count"], 0)
        self.assertIn("honest approx", pack["td_note"])
        self.assertNotIn("★", str(pack))
        if pack["td_flag"]:
            self.assertIn(pack["td_flag"], ("9B", "13B"))

    def test_td_blank_when_short(self):
        self.assertIsNone(ee.td_sequential_approx(pd.Series([1, 2, 3]))["td_count"])


class CoilAndClassTests(unittest.TestCase):
    def test_coil_compressed_after_quiet_weeks(self):
        wide = 100 + 8 * np.sin(np.linspace(0, 10, 30))
        tight = 100 + 0.2 * np.sin(np.linspace(0, 4, 20))
        pack = ee.weekly_coil(pd.Series(np.concatenate([wide, tight])))
        self.assertIsNotNone(pack["coil_12"])
        self.assertLessEqual(pack["coil_12"], 0.65)
        self.assertIn(pack["coil_state"], ("COMPRESSED", "COILING", "NORMAL"))

    def test_coil_blank_when_short(self):
        self.assertIsNone(ee.weekly_coil(pd.Series(np.linspace(1, 2, 10)))["coil_12"])

    def test_asset_class_public_proxies(self):
        self.assertEqual(em.asset_class("SPY"), "Equity Idx")
        self.assertEqual(em.asset_class("XLK"), "US Sector")
        self.assertEqual(em.asset_class("TLT"), "Rates")
        self.assertEqual(em.asset_class("GLD"), "Commodity")
        self.assertEqual(em.asset_class("AAPL"), "Stock")
        self.assertEqual(em.asset_class("^VIX"), "Vol/Risk")
        self.assertEqual(em.asset_class("EEM"), "Country")


class MapsBoardTests(unittest.TestCase):
    def test_empty_maps(self):
        out = em.maps_board(symbols=[])
        self.assertFalse(out["ready"])
        self.assertIn("Empty", out["message"] or "")
        self.assertEqual(out["scanner"]["rows"], [])
        self.assertEqual(out["rotation"]["points"], [])

    def test_rotation_and_coil_points(self):
        frames = {
            "UP": _frame(np.linspace(80, 160, 280)),
            "DN": _frame(np.linspace(160, 70, 280)),
        }
        out = em.maps_board(symbols=["UP", "DN"], frames=frames)
        self.assertTrue(out["ready"])
        self.assertTrue(out["rotation"]["points"] or out["scanner"]["rows"])
        self.assertIn("RSI(14)", out["rotation"]["howto"])
        self.assertIn("tighter", out["coil"]["howto"].lower())
        self.assertIn("r12/r26", out["coil"]["howto"])
        self.assertIn("by_zone", out["tms_regime"])
        spy = out["tms_regime"]["spy_strip"]
        if spy.get("label"):
            self.assertIn(spy["label"], ("RISK-ON", "MIXED", "RISK-OFF"))
        self.assertIn("±13", out["fractal_td"]["howto"])
        self.assertNotIn("★", str(out))
        for row in out["scanner"]["rows"]:
            if row.get("td_flag"):
                self.assertIn(row["td_flag"], ("9B", "9S", "13B", "13S"))
        # Fractal markers only when D exists
        for p in out["fractal_td"]["points"]:
            self.assertIsNotNone(p["x"])

    def test_formulas_include_tmac_tes_coil(self):
        cat = ee.catalog()
        self.assertIn("tmac_star", cat["formulas"])
        self.assertIn("0.50*range_pct", cat["formulas"]["tmac_star"])
        self.assertIn("0.35*rsi14", cat["formulas"]["tmac_star"])
        self.assertIn("0.15*vol_heat", cat["formulas"]["tmac_star"])
        self.assertIn("heat_proxy", cat["formulas"]["tmac_star"])
        self.assertIn("never branded TMAC", cat["formulas"]["tmac_star"])
        self.assertIn("r12/r26", cat["formulas"]["coil"])
        self.assertIn("COMPRESSED≤0.45", cat["formulas"]["coil"])
        self.assertIn("tes", cat["formulas"])
        self.assertIn("coil", cat["formulas"])


class FlaskMapsTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "maps.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_empty_desk_maps(self):
        body = self.client.get("/api/engine/maps?desk=1").get_json()
        self.assertFalse(body["ready"])
        self.assertIn("Empty", body.get("message") or "")

    def test_surfaces_tmac_star_and_maps(self):
        blob = ""
        for path in (
            "index.html",
            "scripts/engine_desk.js",
            "scripts/setup_scanner.js",
            "setup_scanner.py",
            "mobile/lib/ui/scans_page.dart",
            "engine_maps.py",
            "equity_engine.py",
        ):
            with open(path, encoding="utf-8") as fh:
                blob += fh.read()
        self.assertIn("TMAC*", blob)
        self.assertIn("heat_proxy", blob)
        self.assertIn("0.50*range_pct", blob)
        self.assertIn("never branded TMAC", blob)
        self.assertIn("function setupTmacHeat", blob)
        self.assertIn("tmac_star", blob)
        self.assertIn("/api/engine/maps", blob)
        self.assertIn("HOW TO READ", blob)
        self.assertIn("HOW TO READ — COIL", blob)
        self.assertIn("HOW TO READ — TMS REGIME", blob)
        self.assertIn("_engPtsTable", blob)
        self.assertIn("if (!list.length) return '';", blob)
        self.assertIn("wn-table", blob)
        self.assertNotIn('<li class="engine-dim">none</li>', blob)
        self.assertIn("r12/r26", blob)
        self.assertIn("RISK-ON", blob)
        self.assertNotIn("bloomberg", blob.lower())
        self.assertNotIn("stockbee.blogspot", blob.lower())
        self.assertNotIn("★ TD13", blob)
        self.assertNotRegex(blob, r"\bwin rate \d")


if __name__ == "__main__":
    unittest.main()
