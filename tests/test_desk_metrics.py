"""Tests for symbol_metrics cache + desk_metrics helpers."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import database as db
import desk_metrics


class SymbolMetricsDbTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "metrics.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_upsert_and_query(self):
        n = db.upsert_symbol_metrics([
            {
                "symbol": "AAA",
                "ready": True,
                "as_of": "2024-06-01",
                "price": 10.5,
                "change_pct": 2.0,
                "ret_21d_pct": 8.0,
                "stage": 2,
                "setup_score": 3,
                "payload": {"symbol": "AAA", "ready": True, "setups": ["EP"], "badge_codes": ["KQ"]},
            }
        ])
        self.assertEqual(n, 1)
        row = db.get_symbol_metrics("AAA")
        self.assertTrue(row["ready"])
        self.assertEqual(row["payload"]["setups"], ["EP"])
        many = db.get_symbol_metrics_many(["AAA"])
        self.assertEqual(len(many), 1)
        st = db.metrics_status()
        self.assertEqual(st["ready"], 1)

    def test_finalize_payloads_ranks_and_badges(self):
        rows = [
            {
                "symbol": "A",
                "ready": True,
                "payload": {
                    "symbol": "A",
                    "ready": True,
                    "ret_21d_pct": 20,
                    "setups": ["MINERVINI_TT", "QULLA_BREAKOUT"],
                    "is_near_high": True,
                    "is_vol_surge": True,
                    "change_pct": 5,
                },
            },
            {
                "symbol": "B",
                "ready": True,
                "payload": {
                    "symbol": "B",
                    "ready": True,
                    "ret_21d_pct": 5,
                    "setups": [],
                    "change_pct": 0,
                },
            },
        ]
        desk_metrics.finalize_payloads(rows)
        self.assertEqual(rows[0]["payload"]["rs_rank_21d"], 1)
        self.assertEqual(rows[1]["payload"]["rs_rank_21d"], 2)
        self.assertIn("MM", rows[0]["payload"]["badge_codes"])
        self.assertIn("KQ", rows[0]["payload"]["badge_codes"])


class MarketContextTests(unittest.TestCase):
    def test_constructive_and_defensive(self):
        constructive = [
            {
                "symbol": f"U{i}",
                "ready": True,
                "regime": "uptrend",
                "regime_weekly": "uptrend",
                "stage": 2,
                "change_pct": 1.0,
                "is_ep": False,
                "setups": [],
                "strike_zone": True,
            }
            for i in range(10)
        ]
        ctx = desk_metrics.market_context(constructive)
        self.assertEqual(ctx["n"], 10)
        self.assertEqual(ctx["regime"], "constructive")
        self.assertGreaterEqual(ctx["pct_dual_up"], 90)
        self.assertIn("licensed", (ctx.get("honest") or "").lower())

        defensive = [
            {
                "symbol": f"D{i}",
                "ready": True,
                "regime": "downtrend",
                "regime_weekly": "downtrend",
                "stage": 4,
                "change_pct": -1.0,
                "is_ep": False,
                "setups": [],
            }
            for i in range(10)
        ]
        dctx = desk_metrics.market_context(defensive)
        self.assertEqual(dctx["regime"], "defensive")

    def test_freshness_stale_when_bars_newer(self):
        rows = [{"as_of": "2024-01-01", "ready": True}]
        with patch("desk_metrics.dc.get_max_ohlcv_date", return_value="2024-01-10"):
            meta = desk_metrics.freshness_meta(rows)
        self.assertTrue(meta["stale"])
        self.assertEqual(meta["freshness"], "stale")

    def test_freshness_fresh_when_caught_up(self):
        rows = [{"as_of": "2024-01-10", "ready": True}]
        with patch("desk_metrics.dc.get_max_ohlcv_date", return_value="2024-01-10"):
            meta = desk_metrics.freshness_meta(rows)
        self.assertFalse(meta["stale"])
        self.assertEqual(meta["freshness"], "fresh")


class DeskMetricsCacheServeTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "metrics2.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        self._mode = patch("data_client.DATA_SERVICE_MODE", "embedded")
        self._mode.start()
        db.init_db()
        db.upsert_symbol_metrics([
            {
                "symbol": "HOT",
                "ready": True,
                "price": 100,
                "change_pct": 4.5,
                "ret_21d_pct": 12,
                "stage": 2,
                "setup_score": 4,
                "payload": {
                    "symbol": "HOT",
                    "ready": True,
                    "setups": ["EP", "QULLA_BREAKOUT"],
                    "families": ["qullamaggie"],
                    "badge_codes": ["KQ", "SB4"],
                    "badges": [{"id": "KQ", "tone": "kq", "label": "Qullamaggie", "kind": "method", "title": "KQ"}],
                    "change_pct": 4.5,
                    "setup_score": 4,
                    "stage": 2,
                    "rs_rank_21d": 1,
                    "rs_n": 1,
                },
            }
        ])

    def tearDown(self):
        self._mode.stop()
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_scan_setups_serves_cache(self):
        import setup_scanner
        with patch("setup_scanner.md.list_symbols_with_ohlcv", return_value=["HOT"]):
            out = setup_scanner.scan_setups(symbols=["HOT"], use_cache=True)
        self.assertTrue(out.get("from_cache"))
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["results"][0]["symbol"], "HOT")
        self.assertIn("KQ", out["results"][0].get("badge_codes") or [])
        self.assertIn("market_context", out)
        self.assertIn("cache", out)


if __name__ == "__main__":
    unittest.main()
