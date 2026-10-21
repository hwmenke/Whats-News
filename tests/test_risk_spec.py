"""Quant Risk SPEC 2026-09-04 — thin blanks + Euler sum. No invented P&L."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ["DATA_SERVICE_MODE"] = "embedded"

import data_client
import database as db
import paper_book as pb
import risk_spec


def _gbm(n, seed, mu=0.0004, sigma=0.012):
    rng = np.random.default_rng(seed)
    r = rng.normal(mu, sigma, n)
    return 100.0 * np.exp(np.cumsum(r))


class RiskSpecTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "risk.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _put(self, symbol, closes, start="2022-01-03"):
        db.add_symbol(symbol)
        idx = pd.bdate_range(start, periods=len(closes))
        close = np.asarray(closes, dtype=float)
        frame = pd.DataFrame(
            {
                "open": close - 0.1,
                "high": close + 0.3,
                "low": close - 0.3,
                "close": close,
                "volume": np.full(len(close), 1_000_000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv(symbol, "daily", frame)

    def test_empty_and_two_names_are_blank(self):
        empty = pb.book_pnl()
        self.assertFalse(empty["risk"]["ready"])
        self.assertTrue(empty["risk"]["thin"])
        self.assertEqual(empty["risk"]["var"], {})
        self.assertEqual(empty["risk"]["names"], [])

        self._put("A", _gbm(80, 1))
        self._put("B", _gbm(80, 2))
        pb.upsert_position(symbol="A", qty=10, side="long")
        pb.upsert_position(symbol="B", qty=8, side="long")
        pnl = pb.book_pnl()
        self.assertFalse(pnl["risk"]["ready"])
        self.assertTrue(pnl["risk"]["thin"])
        self.assertIn("<3", pnl["risk"]["message"])
        self.assertEqual(pnl["risk"]["ranked"], [])
        self.assertEqual(pnl["risk"]["clusters"], [])

    def test_short_overlap_is_blank(self):
        for i, sym in enumerate(["A", "B", "C"]):
            self._put(sym, _gbm(40, 10 + i))
            pb.upsert_position(symbol=sym, qty=5, side="long")
        pnl = pb.book_pnl()
        self.assertFalse(pnl["risk"]["ready"])
        self.assertTrue(pnl["risk"]["thin"])
        self.assertIn("overlap", pnl["risk"]["message"].lower())
        self.assertIsNone(pnl["risk"]["var"].get("param_95") if pnl["risk"]["var"] else None)

    def test_singular_cov_is_blank(self):
        px = _gbm(80, 3)
        for sym in ("A", "B", "C"):
            self._put(sym, px)
            pb.upsert_position(symbol=sym, qty=4, side="long")
        pnl = pb.book_pnl()
        self.assertFalse(pnl["risk"]["ready"])
        self.assertTrue(pnl["risk"]["thin"])
        self.assertIn("singular", pnl["risk"]["message"].lower())

    def test_euler_sum_cvar_equals_param_var(self):
        self._put("AAA", _gbm(260, 1, sigma=0.011))
        self._put("BBB", _gbm(260, 2, sigma=0.014))
        self._put("CCC", _gbm(260, 3, sigma=0.010))
        self._put("SPY", _gbm(260, 4, sigma=0.009))
        pb.upsert_position(symbol="AAA", qty=10, side="long")
        pb.upsert_position(symbol="BBB", qty=6, side="long")
        pb.upsert_position(symbol="CCC", qty=8, side="long")
        pnl = pb.book_pnl()
        risk = pnl["risk"]
        self.assertTrue(risk["ready"], risk.get("message"))
        self.assertGreaterEqual(risk["overlap_days"], 60)
        self.assertTrue(risk["euler"]["param_95_ok"])
        self.assertAlmostEqual(
            risk["euler"]["cvar_sum_95"],
            risk["euler"]["var_95"],
            places=4,
        )
        cvar = sum(r["cvar_95"] or 0.0 for r in risk["names"])
        self.assertAlmostEqual(cvar, risk["euler"]["var_95"], places=1)
        v = risk["var"]
        self.assertEqual(v["hist_95"]["method"], "historical empirical quantile")
        self.assertEqual(v["param_95"]["method"], "parametric Gaussian μ=0, 60d Σ")
        self.assertIsNotNone(v["hist_95"]["pct"])
        self.assertIsNotNone(v["param_99"]["pct"])
        self.assertGreaterEqual(len(risk["ranked"]), 3)
        self.assertGreaterEqual(len(risk["clusters"]), 1)
        row = risk["names"][0]
        self.assertIn("weight_pct", row)
        self.assertIn("vol_20", row)
        self.assertIn("vol_60", row)
        self.assertIn("mvar_95", row)
        self.assertIn("pct_var", row)
        self.assertIn("flags", row)
        self.assertTrue(risk["perf"]["curve_kind"])
        self.assertIn("synthetic", risk["perf"]["curve_label"])
        blob = str(risk).lower()
        self.assertNotIn("bloomberg", blob)
        self.assertNotIn("10.95b", blob)

    def test_surface_no_scaffold_todo(self):
        blob = ""
        for path in (
            "index.html",
            "scripts/paper_book.js",
            "mobile/lib/ui/book_page.dart",
            "risk_spec.py",
        ):
            blob += Path(path).read_text(encoding="utf-8")
        self.assertIn("id=\"risk-clusters\"", blob)
        self.assertIn("Ranked %VaR", blob)
        self.assertIn("MVaR", blob)
        self.assertIn("evaluate", blob)
        self.assertNotIn("SPEC pending", blob)
        self.assertNotIn("risk-spec-pending", blob)
        self.assertIn("whats-news-risk-SPEC-2026-09-04.md", blob)


if __name__ == "__main__":
    unittest.main()
