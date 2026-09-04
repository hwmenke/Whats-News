"""Macro / Edges boards from stored bars — no invented PX, z, VIX, or win rates."""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ["DATA_SERVICE_MODE"] = "embedded"

import data_client
import database as db
import ticker_lists as tl
import macro_board as mb
import app as app_module


class MacroBoardTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "macro.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _put_closes(self, symbol, closes, start="2024-01-02"):
        db.add_symbol(symbol)
        idx = pd.bdate_range(start, periods=len(closes))
        close = np.asarray(closes, dtype=float)
        frame = pd.DataFrame(
            {
                "open": close - 0.1,
                "high": close + 0.3,
                "low": close - 0.3,
                "close": close,
                "volume": np.full(len(close), 2_000_000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv(symbol, "daily", frame)
        return frame

    def test_sleeves_match_market_moves_categories(self):
        ids = {s["id"] for s in tl.sleeves()}
        for needed in (
            "core", "broad_etfs", "sector_etfs", "intl_etfs",
            "themes", "rates", "commodities", "mega_tech",
        ):
            self.assertIn(needed, ids)
        lib_ids = {c["id"] for c in tl.TICKER_LIBRARY}
        self.assertIn("themes", lib_ids)
        self.assertIn("rates", lib_ids)
        self.assertIn("commodities", lib_ids)
        self.assertIn("DBA", tl.get_sleeve("commodities")["tickers"])
        self.assertIn("UUP", tl.get_sleeve("rates")["tickers"])
        self.assertGreaterEqual(len(tl.core50_tickers()), 45)
        self.assertLessEqual(len(tl.core50_tickers()), 55)
        self.assertEqual(tl.filter_kind_for_tag("lib:intl_etfs"), "country")
        self.assertEqual(tl.filter_kind_for_tag("lib:sector_etfs"), "sector")
        self.assertEqual(tl.filter_kind_for_tag("lib:themes"), "theme")

    def test_macro_board_omits_missing_and_marks_z(self):
        # Quiet grind then a +4 sigma jump so |z30| ≥ 2.
        grind = np.linspace(100.0, 101.0, 40)
        closes = np.concatenate([grind, np.array([105.5])])
        self._put_closes("SPY", closes)
        board = self.client.get("/api/macro/board")
        self.assertEqual(board.status_code, 200)
        body = board.get_json()
        self.assertFalse(body["regime"]["ready"])
        self.assertIn("not invented", body["regime"]["note"].lower())
        core = next(s for s in body["sleeves"] if s["id"] == "core")
        spy = next(r for r in core["rows"] if r["symbol"] == "SPY")
        qqq = next(r for r in core["rows"] if r["symbol"] == "QQQ")
        self.assertTrue(spy["ready"])
        self.assertIsNotNone(spy["px"])
        self.assertIsNotNone(spy["day_pct"])
        self.assertGreaterEqual(abs(spy["z30"]), 2.0)
        self.assertTrue(spy["extreme"])
        self.assertFalse(qqq.get("ready"))
        self.assertIsNone(qqq.get("px"))

    def test_vix_regime_from_stored_bars_only(self):
        quiet = np.full(60, 13.5)
        self._put_closes("^VIX", quiet)
        body = self.client.get("/api/macro/board").get_json()
        self.assertTrue(body["regime"]["ready"])
        self.assertEqual(body["regime"]["label"], "QUIET")
        self.assertAlmostEqual(body["regime"]["vix"], 13.5, places=1)

    def test_edges_board_has_rsi_and_no_win_rates(self):
        closes = np.linspace(90.0, 120.0, 220)
        self._put_closes("SPY", closes)
        db.add_symbol("SPY")
        db.set_symbol_group("SPY", "sleeve:core")
        body = self.client.get("/api/edges/board").get_json()
        self.assertEqual(self.client.get("/api/edges/board").status_code, 200)
        blob = str(body).lower()
        self.assertNotIn("70%", blob)
        self.assertNotIn("win rate", blob)
        core = next(s for s in body["sections"] if s["id"] == "core")
        spy = next(r for r in core["rows"] if r["symbol"] == "SPY")
        self.assertTrue(spy["ready"])
        self.assertIsNotNone(spy["d_rsi14"])
        self.assertIsNotNone(spy["vs50d"])
        self.assertIsNotNone(spy["vs200d"])
        self.assertIn(spy["slope200"], ("up", "down", "flat"))
        self.assertIsInstance(spy["tags"], list)

    def test_fractal_is_honest_stub(self):
        res = self.client.get("/api/fractal/status")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertFalse(body["available"])
        self.assertIn("invent", body["reason"].lower())

    def test_core50_seed_tags_library_groups(self):
        res = self.client.post("/api/universe/core50")
        self.assertIn(res.status_code, (200, 201))
        data = res.get_json()
        self.assertGreaterEqual(data["count"], 45)
        desk = self.client.get("/api/symbols?desk=1").get_json()
        tags = {s["symbol"]: s.get("group_tag") for s in desk}
        self.assertTrue(tags["AAPL"].startswith("lib:"))
        self.assertTrue(tags["EWJ"].startswith("lib:"))
        self.assertTrue(tags["XLK"].startswith("lib:"))

    def test_web_and_phone_share_macro_surface(self):
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('id="tab-macro"', html)
        self.assertIn('id="macro-area"', html)
        self.assertIn("scripts/macro_desk.js", html)
        with open("scripts/macro_desk.js", encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn("/api/macro/board", js)
        self.assertIn("/api/edges/board", js)
        self.assertNotIn("70%", js)

    def test_move_stats_needs_two_closes(self):
        empty = mb.move_stats(pd.Series(dtype=float))
        self.assertFalse(empty["ready"])
        one = mb.move_stats(pd.Series([100.0]))
        self.assertFalse(one["ready"])
        two = mb.move_stats(pd.Series([100.0, 102.0]))
        self.assertTrue(two["ready"])
        self.assertAlmostEqual(two["day_pct"], 2.0, places=2)
        self.assertIsNone(two["z30"])


if __name__ == "__main__":
    unittest.main()
