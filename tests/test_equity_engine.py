"""Equity ENGINE / RSI-C / Pattern / Str — synthetic labels and empty honesty."""

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
import equity_engine as ee


def _frame(close, high=None, low=None, start="2023-01-02"):
    close = np.asarray(close, dtype=float)
    n = len(close)
    idx = pd.bdate_range(start, periods=n)
    hi = close + 0.40 if high is None else np.asarray(high, dtype=float)
    lo = close - 0.40 if low is None else np.asarray(low, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": hi,
            "low": lo,
            "close": close,
            "volume": np.full(n, 1_000_000.0),
        },
        index=idx,
    )


def _uptrend(n=90, start=80.0, end=150.0):
    return np.linspace(start, end, n)


def _crash(n=80, start=150.0, end=40.0):
    return np.linspace(start, end, n)


class FormulaCatalogTests(unittest.TestCase):
    def test_formulas_document_engine_vcp_str_rsic(self):
        cat = ee.catalog()
        for key in ("rsi_c", "vcp", "str", "engine", "pattern", "takeaway", "adma_stretch"):
            self.assertIn(key, cat["formulas"])
            self.assertTrue(cat["formulas"][key])
        self.assertIn("NO TRADE", cat["state_machine"])
        self.assertIn("OPPORTUNITY", cat["state_machine"])
        self.assertIn("SPEC 25/27", cat["fractal_note"])
        self.assertEqual(cat["controls"]["lookbacks"], list(range(2, 22)))
        self.assertEqual(cat["controls"]["rsi_n"], 14)
        self.assertEqual(cat["controls"]["lag"], 5)


class EmptyHonestyTests(unittest.TestCase):
    def test_empty_symbols_board(self):
        out = ee.board(symbols=[])
        self.assertFalse(out["ready"])
        self.assertEqual(out["rows"], [])
        self.assertIn("Empty", out["message"] or "")
        self.assertIn("Yahoo/SQLite", out["note"])

    def test_measure_no_daily_bars(self):
        row = ee.measure("NONE", daily=pd.DataFrame())
        self.assertFalse(row["ready"])
        self.assertIsNone(row["engine"])
        self.assertIn("No stored daily bars", row.get("error") or "")

    def test_rsi_c_blank_when_short(self):
        pack = ee.rsi_counter(pd.Series(np.linspace(10, 12, 10)))
        self.assertFalse(pack["ready"])
        self.assertIsNone(pack["state"])

    def test_str_omitted_under_56_bars(self):
        close = _uptrend(40)
        self.assertIsNone(ee.breakout_str(
            pd.Series(close + 0.4), pd.Series(close - 0.4), pd.Series(close),
        ))


class DeterministicLabelTests(unittest.TestCase):
    def test_rsi_c_os_extreme_on_crash(self):
        close = pd.Series(_crash(80))
        pack = ee.rsi_counter(close)
        self.assertTrue(pack["ready"])
        self.assertGreaterEqual(pack["pct_os20"], 0.90)
        self.assertEqual(pack["state"], "OS EXTREME")

    def test_rsi_c_ob_or_trend_on_uptrend(self):
        close = pd.Series(_uptrend(90))
        pack = ee.rsi_counter(close)
        self.assertTrue(pack["ready"])
        self.assertTrue(
            (pack["state"] or "").startswith("OB")
            or pack["state"] == "OVERBOUGHT"
            or (pack["state"] or "").startswith("TREND ↑"),
            pack["state"],
        )

    def test_vcp_tightening_after_wide_range(self):
        wide = 100 + 12 * np.sin(np.linspace(0, 8 * np.pi, 50))
        tight = np.full(12, 108.0) + 0.15 * np.sin(np.linspace(0, np.pi, 12))
        close = np.concatenate([wide, tight])
        high = close + np.concatenate([np.full(50, 2.0), np.full(12, 0.12)])
        low = close - np.concatenate([np.full(50, 2.0), np.full(12, 0.12)])
        # last close stays inside the prior 20-bar range
        high[-1] = close[-1] + 0.05
        low[-1] = close[-1] - 0.05
        vcp = ee.vcp_phase(pd.Series(high), pd.Series(low), pd.Series(close))
        self.assertIn(vcp["phase"], ("TIGHTENING", "COILED"))
        self.assertIsNotNone(vcp["range_10_50"])
        self.assertLessEqual(vcp["range_10_50"], ee.VCP_RANGE)
        self.assertEqual(vcp["note"], ee.VCP_NOTE)

    def test_vcp_break_up_on_20d_high(self):
        close = _uptrend(40, 100, 140)
        vcp = ee.vcp_phase(pd.Series(close + 0.3), pd.Series(close - 0.3), pd.Series(close))
        self.assertEqual(vcp["phase"], "BREAK ↑")

    def test_str_plus_on_20d_and_55d_break(self):
        base = np.full(70, 100.0)
        base[-1] = 130.0
        high = np.full(70, 101.0)
        high[-1] = 131.0
        low = np.full(70, 99.0)
        score = ee.breakout_str(pd.Series(high), pd.Series(low), pd.Series(base))
        self.assertIsNotNone(score)
        self.assertGreaterEqual(score, 4)
        self.assertLessEqual(score, 5)

    def test_str_minus_on_range_breakdown(self):
        base = np.full(70, 100.0)
        base[-1] = 70.0
        high = np.full(70, 101.0)
        low = np.full(70, 99.0)
        low[-1] = 69.0
        score = ee.breakout_str(pd.Series(high), pd.Series(low), pd.Series(base))
        self.assertIsNotNone(score)
        self.assertLessEqual(score, -4)

    def test_daily_pattern_breakout_and_breakdown(self):
        up = _uptrend(80, 80, 140)
        self.assertEqual(
            ee.daily_pattern(pd.Series(up + 0.4), pd.Series(up - 0.4), pd.Series(up)),
            "Breakout",
        )
        dn = _crash(80, 140, 60)
        self.assertEqual(
            ee.daily_pattern(pd.Series(dn + 0.4), pd.Series(dn - 0.4), pd.Series(dn)),
            "Breakdown",
        )

    def test_weekly_pattern_from_bottom(self):
        # 1Y high 180 early; last 26 weeks stay in the bottom third and print a 6M high
        first = np.linspace(80, 180, 26)
        base = np.full(25, 90.0)
        close = np.concatenate([first, base, np.array([110.0])])
        self.assertEqual(
            ee.weekly_pattern(pd.Series(close), pd.Series(close), pd.Series(close)),
            "From Bottom",
        )

    def test_engine_opportunity_on_agreed_uptrend(self):
        daily = _frame(_uptrend(90, 80, 160))
        weekly = _frame(_uptrend(60, 70, 150), start="2022-01-07")
        row = ee.measure("AAA", daily=daily, weekly=weekly)
        self.assertTrue(row["ready"])
        self.assertEqual(row["vcp"], "BREAK ↑")
        self.assertEqual(row["pattern_d"], "Breakout")
        self.assertIn(row["engine_primary"], ("OPPORTUNITY", "WATCH"))
        self.assertIn(row["engine_phase"], ("TRIGGERED", "ACCEPTED", "EXTENDED", "FORMING"))
        self.assertTrue(row["engine"].startswith(row["engine_primary"]))
        self.assertIn("VCP BREAK ↑", row["takeaway"])
        self.assertIn(row["sentiment"], ("LONG", "LEAN LONG"))
        self.assertGreaterEqual(row["bias"], 0.5)
        self.assertGreaterEqual(row["str"], 2)

    def test_engine_no_trade_when_short_history(self):
        daily = _frame(_uptrend(30, 100, 120))
        row = ee.measure("SHORT", daily=daily)
        self.assertTrue(row["ready"])
        self.assertEqual(row["engine_primary"], "NO TRADE")
        self.assertIn("NO TRADE", row["engine"])

    def test_no_invented_fractal_d(self):
        daily = _frame(_uptrend(40, 100, 110))
        row = ee.measure("NOD", daily=daily)
        self.assertIsNone(row["d_label"])
        self.assertIn("SPEC 25/27", row["fractal_note"])

    def test_pullback_in_uptrend_note(self):
        crash = _crash(70, 160, 50)
        daily = _frame(crash)
        # Weekly mixed grind so RSI-C stays in the 50–75 TREND↑ band (not OB)
        mixed = np.concatenate([
            np.linspace(80, 100, 30),
            100 + 2 * np.sin(np.linspace(0, 8 * np.pi, 25)),
        ])
        weekly = _frame(mixed, start="2022-01-07")
        row = ee.measure("PB", daily=daily, weekly=weekly)
        self.assertIsNotNone(row["pullback_in_uptrend"])
        self.assertIn("Daily OS", row["pullback_in_uptrend"])
        self.assertIn("not a trade", row["pullback_in_uptrend"])

    def test_takeaway_short_on_crash(self):
        daily = _frame(_crash(90, 180, 40))
        weekly = _frame(_crash(55, 160, 50), start="2022-01-07")
        row = ee.measure("DN", daily=daily, weekly=weekly)
        self.assertIn(row["sentiment"], ("SHORT", "LEAN SHORT"))
        self.assertIn("VCP BREAK ↓", row["takeaway"])
        self.assertLessEqual(row["bias"], -0.5)

    def test_rsi_counter_board_split_and_controls(self):
        frames = {
            "UP": _frame(_uptrend(90)),
            "DN": _frame(_crash(90)),
            "UP_W": _frame(_uptrend(55), start="2022-01-07"),
            "DN_W": _frame(_crash(55, 140, 50), start="2022-01-07"),
        }
        out = ee.rsi_counter_board(symbols=["UP", "DN"], frames=frames, rsi_n=14, lag=5)
        self.assertTrue(out["ready"])
        self.assertEqual(out["controls"]["rsi_n"], 14)
        self.assertEqual(out["controls"]["lag"], 5)
        self.assertIn("Daily LEFT", out["howto"])
        self.assertTrue(out["daily"]["oversold"] or out["weekly"]["oversold"])
        self.assertTrue(out["accelerating"] or out["fading"])

    def test_pattern_and_stretch_boards(self):
        frames = {
            "UP": _frame(_uptrend(90)),
            "DN": _frame(_crash(90)),
        }
        pats = ee.pattern_board(symbols=["UP", "DN"], frames=frames)
        self.assertGreaterEqual(pats["daily"]["counts"]["Breakout"], 1)
        self.assertGreaterEqual(pats["daily"]["counts"]["Breakdown"], 1)
        self.assertIn("3-month", pats["howto"])
        stretch = ee.stretch_board(symbols=["UP", "DN"], frames=frames)
        self.assertTrue(stretch["strongest"] or stretch["breakdowns"])
        self.assertIn("Gray tag", stretch["howto"])

    def test_command_nav_groups(self):
        out = ee.command_board(symbols=[])
        self.assertEqual(
            out["nav"],
            ["command", "setup", "pattern", "rsi_c", "macro", "sigma", "book", "chart"],
        )


class FlaskEngineApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "engine.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_catalog(self):
        body = self.client.get("/api/engine/catalog").get_json()
        self.assertIn("rsi_c", body["formulas"])
        self.assertIn("engine", body["formulas"])

    def test_empty_desk_boards(self):
        for path in (
            "/api/engine/command?desk=1",
            "/api/engine/board?desk=1",
            "/api/engine/rsi-counter?desk=1",
            "/api/engine/patterns?desk=1",
            "/api/engine/stretch?desk=1",
            "/api/engine/sigma?desk=1",
        ):
            body = self.client.get(path).get_json()
            self.assertFalse(body["ready"], path)
            self.assertIn("Empty", body.get("message") or "")

    def test_board_with_stored_uptrend(self):
        db.add_symbol("AAA")
        db.upsert_ohlcv("AAA", "daily", _frame(_uptrend(90)))
        body = self.client.get("/api/engine/board?desk=0").get_json()
        self.assertTrue(body["ready"])
        self.assertTrue(any(r["symbol"] == "AAA" for r in body["rows"]))
        row = next(r for r in body["rows"] if r["symbol"] == "AAA")
        self.assertTrue(row["engine"])
        self.assertTrue(row["takeaway"])


class SurfaceCopyTests(unittest.TestCase):
    def test_no_bloomberg_or_stockbee_scrape(self):
        paths = [
            "equity_engine.py",
            "index.html",
            "scripts/engine_desk.js",
            "mobile/lib/ui/scans_page.dart",
        ]
        blob = ""
        for path in paths:
            with open(path, encoding="utf-8") as fh:
                blob += fh.read()
        lower = blob.lower()
        self.assertNotIn("bloomberg", lower)
        self.assertNotIn("stockbee.blogspot", lower)
        self.assertIn("HOW TO READ", blob)
        self.assertIn("desk-ia-bar", blob)
        self.assertIn("/api/engine/board", blob)
        self.assertIn("pullback-in-uptrend", blob)


if __name__ == "__main__":
    unittest.main()
