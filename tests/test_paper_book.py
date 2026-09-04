"""Paper book: Fidelity CSV, VaR on a synthetic book, empty-book honesty."""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ["DATA_SERVICE_MODE"] = "embedded"

import data_client
import database as db
import paper_book as pb
import app as app_module


FIDELITY_CSV = """Account Name,Symbol,Description,Quantity,Last Price,Current Value,Cost Basis Average
Individual,AAPL,APPLE INC,10,$150.00,$1500.00,$140.00
Individual,MSFT,MICROSOFT CORP,-5,$400.00,"-$2,000.00",$380.00
Individual,SPAXX,FIDELITY GOVERNMENT MONEY MARKET,100.0,$1.00,$100.00,$1.00
"""


def _gbm(n, seed, mu=0.0004, sigma=0.012):
    rng = np.random.default_rng(seed)
    r = rng.normal(mu, sigma, n)
    return 100.0 * np.exp(np.cumsum(r))


class PaperBookTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "book.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _put_closes(self, symbol, closes, start="2022-01-03"):
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

    def test_parse_fidelity_csv(self):
        rows = pb.parse_fidelity_csv(FIDELITY_CSV)
        symbols = {r["symbol"] for r in rows}
        self.assertEqual(symbols, {"AAPL", "MSFT"})
        aapl = next(r for r in rows if r["symbol"] == "AAPL")
        msft = next(r for r in rows if r["symbol"] == "MSFT")
        self.assertEqual(aapl["qty"], 10.0)
        self.assertEqual(aapl["side"], "long")
        self.assertAlmostEqual(aapl["avg_cost"], 140.0)
        self.assertEqual(msft["qty"], -5.0)
        self.assertEqual(msft["side"], "short")

    def test_empty_book_is_honest_zeros(self):
        pnl = self.client.get("/api/book/pnl").get_json()
        self.assertFalse(pnl["ready"])
        self.assertIsNone(pnl["today_pnl"])
        self.assertIsNone(pnl["today_pnl_pct"])
        self.assertEqual(pnl["exposure"]["gross"], 0.0)
        self.assertEqual(pnl["positions"], [])
        self.assertNotIn("10950000000", str(pnl))
        self.assertNotIn("10.95", str(pnl).lower())
        self.assertIn("Empty paper book", pnl["message"])
        pos = self.client.get("/api/book/positions").get_json()
        self.assertEqual(pos["positions"], [])

    def test_import_and_manual_crud(self):
        res = self.client.post("/api/book/import", json={"csv": FIDELITY_CSV})
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["imported"], 2)
        listed = self.client.get("/api/book/positions").get_json()["positions"]
        self.assertEqual({p["symbol"] for p in listed}, {"AAPL", "MSFT"})
        add = self.client.post("/api/book/positions", json={
            "symbol": "SPY", "qty": 3, "side": "long", "avg_cost": 400,
        })
        self.assertEqual(add.status_code, 201)
        spy = add.get_json()
        gone = self.client.delete(f"/api/book/positions/{spy['id']}")
        self.assertEqual(gone.status_code, 200)
        symbols = {p["symbol"] for p in self.client.get("/api/book/positions").get_json()["positions"]}
        self.assertNotIn("SPY", symbols)

    def test_var_on_synthetic_book(self):
        aapl = _gbm(260, 1)
        spy = _gbm(260, 2)
        self._put_closes("AAPL", aapl)
        self._put_closes("SPY", spy)
        pb.upsert_position(symbol="AAPL", qty=10, side="long", avg_cost=float(aapl[0]))
        pnl = pb.book_pnl()
        self.assertTrue(pnl["ready"])
        self.assertIsNotNone(pnl["today_pnl"])
        self.assertIsNotNone(pnl["nav"])
        self.assertGreater(pnl["exposure"]["gross"], 0)
        self.assertIn("hist_95", pnl["var"])
        self.assertIsNotNone(pnl["var"]["hist_95"]["pct"])
        self.assertIsNotNone(pnl["var"]["param_95"]["pct"])
        self.assertIsNotNone(pnl["var"]["es_95"]["pct"])
        self.assertGreaterEqual(pnl["distribution"]["n"], 20)
        self.assertTrue(pnl["equity_curve"])
        # No invented AXE-scale NAV
        self.assertLess(abs(pnl["nav"]), 1e7)

    def test_unmarked_position_omits_fake_pnl(self):
        pb.upsert_position(symbol="ZZZZ", qty=5, side="long", avg_cost=10)
        pnl = pb.book_pnl()
        self.assertEqual(pnl["count"], 1)
        self.assertFalse(pnl["ready"])
        self.assertIsNone(pnl["today_pnl"])
        row = pnl["positions"][0]
        self.assertFalse(row["ready"])
        self.assertIsNone(row["price"])

    def test_short_exposure_sign(self):
        px = np.linspace(100, 110, 40)
        self._put_closes("MSFT", px)
        pb.upsert_position(symbol="MSFT", qty=5, side="short", avg_cost=105)
        pnl = pb.book_pnl()
        self.assertAlmostEqual(pnl["exposure"]["short"], 5 * 110, places=1)
        self.assertAlmostEqual(pnl["exposure"]["long"], 0.0)
        self.assertLess(pnl["nav"], 0)

    def test_concentration_and_drawdown_omit_when_thin(self):
        px = np.linspace(100, 101, 6)
        self._put_closes("THIN", px)
        pb.upsert_position(symbol="THIN", qty=1, side="long", avg_cost=100)
        pnl = pb.book_pnl()
        self.assertTrue(pnl["ready"])
        self.assertTrue(pnl["concentration"]["ready"])
        self.assertEqual(pnl["concentration"]["top_weight_pct"], 100.0)
        self.assertFalse(pnl["drawdown"]["ready"])
        self.assertIsNone(pnl["drawdown"]["max_dd_pct"])
        self.assertIn("CONCENTRATED", [a["id"] for a in pnl["alerts"]])
        self.assertNotIn("DD_WARNING", [a["id"] for a in pnl["alerts"]])

    def test_drawdown_warning_on_marked_nav(self):
        # Rise then drop ~15% so peak-to-trough crosses DD_WARNING (-10).
        up = np.linspace(100, 130, 20)
        down = np.linspace(130, 110, 16)
        self._put_closes("DD1", np.concatenate([up, down]))
        pb.upsert_position(symbol="DD1", qty=10, side="long", avg_cost=100)
        pnl = pb.book_pnl()
        self.assertTrue(pnl["drawdown"]["ready"])
        self.assertLessEqual(pnl["drawdown"]["max_dd_pct"], -10.0)
        self.assertIn("DD_WARNING", [a["id"] for a in pnl["alerts"]])

    def test_diversified_book_skips_concentrated_chip(self):
        for i, sym in enumerate(["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]):
            self._put_closes(sym, np.full(40, 10.0 + i * 0.01))
            pb.upsert_position(symbol=sym, qty=1, side="long", avg_cost=10)
        pnl = pb.book_pnl()
        self.assertTrue(pnl["concentration"]["ready"])
        self.assertLess(pnl["concentration"]["top_weight_pct"], 25.0)
        self.assertLess(pnl["concentration"]["hhi"], 2500.0)
        self.assertNotIn("CONCENTRATED", [a["id"] for a in pnl["alerts"]])

    def test_holdings_opinion_real_or_blank(self):
        self._put_closes("OPN", np.linspace(80, 120, 80))
        pb.upsert_position(symbol="OPN", qty=2, side="long", avg_cost=90)
        pnl = pb.book_pnl()
        row = pnl["positions"][0]
        self.assertIsNotNone(row["day_pct"])
        self.assertIsNotNone(row["vs_sma50"])
        self.assertIsNotNone(row["rsi14"])
        self.assertGreater(row["rsi14"], 50)
        # fractal / HMM may be blank if windows fail — never invented strings
        if row.get("fractal_read") is not None:
            self.assertIsInstance(row["fractal_read"], str)
        if row.get("hmm_label") is not None:
            self.assertIsInstance(row["hmm_label"], str)

    def test_surfaces_use_axe_layout_not_demo_billions(self):
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("scripts/paper_book.js", encoding="utf-8") as fh:
            js = fh.read()
        with open("mobile/lib/ui/book_page.dart", encoding="utf-8") as fh:
            dart = fh.read()
        blob = html + js + dart
        self.assertIn("TODAY'S P&amp;L", html)
        self.assertIn("Equities", js)
        self.assertIn("Net Exposure", js)
        self.assertIn("id=\"pnl-area\"", html)
        self.assertIn("id=\"book-area\"", html)
        self.assertIn("id=\"pnl-alert-chips\"", html)
        self.assertIn("Max DD", js)
        self.assertIn("_RiskChip", dart)
        self.assertIn("Fidelity", html)
        self.assertIn("_CsvPaste", dart)
        self.assertNotIn("10.95B", blob)
        self.assertNotIn("468.2", blob)
        self.assertNotIn("AXE CAPITAL", blob)


if __name__ == "__main__":
    unittest.main()
