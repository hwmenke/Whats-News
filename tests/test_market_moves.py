"""Market Moves QUANT-locked z — demeaned daily z + rolling 14d-return σ."""

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
import market_moves as mm


def _level_from_returns(rets, start=100.0):
    rets = np.asarray(rets, dtype=float)
    close = np.empty(len(rets) + 1, dtype=float)
    close[0] = start
    close[1:] = start * np.cumprod(1.0 + rets)
    return pd.Series(close)


class QuantLockZTests(unittest.TestCase):
    def test_daily_z_demeans_today_in_30_window(self):
        # 29 × 1% then today 4%. Demeaned z ≠ bare r/σ.
        rets = np.full(30, 0.01)
        rets[-1] = 0.04
        level = _level_from_returns(rets)
        z = mm.daily_z(level, kind="price")
        self.assertIsNotNone(z)
        w = pd.Series(rets)
        mu = float(w.mean())
        sig = float(w.std(ddof=1))
        expected = (0.04 - mu) / sig
        bare = 0.04 / sig
        self.assertAlmostEqual(z, expected, places=10)
        self.assertNotAlmostEqual(z, bare, places=6)
        self.assertLess(abs(z), abs(bare))

    def test_daily_z_blank_when_sigma_zero(self):
        level = pd.Series(np.full(40, 100.0))
        self.assertIsNone(mm.daily_z(level))

    def test_daily_z_blank_when_short(self):
        level = pd.Series(np.linspace(100, 110, 20))
        self.assertIsNone(mm.daily_z(level))

    def test_z14_uses_rolling_14d_return_sigma_not_daily_sqrt(self):
        # 112 flats at 100, then 14 prints at 110 → R_14 = 0.10.
        # σ of rolling 14d returns ≠ σ_daily · √14.
        close = np.concatenate([np.full(112, 100.0), np.full(14, 110.0)])
        level = pd.Series(close)
        z14 = mm.z_14d(level, kind="price")
        self.assertIsNotNone(z14)
        r14 = level / level.shift(14) - 1.0
        sample = r14.dropna().iloc[-126:]
        expected = float(r14.iloc[-1]) / float(sample.std(ddof=1))
        self.assertAlmostEqual(z14, expected, places=10)

        daily = level.pct_change().dropna()
        daily_sig = float(daily.iloc[-14:].std(ddof=1))
        wrong_last14 = float(r14.iloc[-1]) / daily_sig
        wrong_sqrt = float(r14.iloc[-1]) / (float(daily.std(ddof=1)) * np.sqrt(14.0))
        self.assertNotAlmostEqual(z14, wrong_last14, places=4)
        self.assertNotAlmostEqual(z14, wrong_sqrt, places=4)

    def test_z14_blank_when_too_few_ends(self):
        self.assertIsNone(mm.z_14d(pd.Series(np.linspace(10, 12, 16))))

    def test_day_pct_price_and_yield_bp(self):
        px = mm.move_row(pd.Series([100.0, 102.0]), kind="price")
        self.assertTrue(px["ready"])
        self.assertAlmostEqual(px["day_pct"], 2.0, places=2)
        self.assertIsNone(px["z"])
        yld = mm.move_row(pd.Series([4.20, 4.25]), kind="yield")
        self.assertAlmostEqual(yld["day_pct"], 5.0, places=2)  # 5 bp

    def test_extreme_bullet_at_abs_two(self):
        rets = np.full(30, 0.001)
        rets[-1] = 0.05
        row = mm.move_row(_level_from_returns(rets), kind="price")
        self.assertTrue(row["extreme"])
        self.assertGreaterEqual(abs(row["z"]), 2.0)


class MarketMovesBoardTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "moves.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _put(self, symbol, closes, start="2024-01-02"):
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

    def test_api_shape_and_blank_honesty(self):
        rets = np.full(160, 0.002)
        rets[-1] = 0.03
        self._put("^GSPC", _level_from_returns(rets).to_numpy())
        body = self.client.get("/api/market-moves").get_json()
        self.assertIn("asof", body)
        self.assertIn("groups", body)
        self.assertEqual(body.get("gamma"), None)
        self.assertIn("Yahoo", body["source"])
        self.assertIn("not CNBC", body["source"])
        labels = [g["label"] for g in body["groups"]]
        self.assertEqual(len(labels), 12)
        self.assertIn("INDEXES", labels)
        self.assertIn("BIG TECH", labels)
        self.assertIn("SECTORS", labels)
        indexes = next(g for g in body["groups"] if g["id"] == "indexes")
        spx = next(r for r in indexes["rows"] if r["name"] == "SPX")
        dax = next(r for r in indexes["rows"] if r["name"] == "DAX")
        self.assertTrue(spx["ready"])
        self.assertIsNotNone(spx["px"])
        self.assertIsNotNone(spx["z"])
        self.assertFalse(dax["ready"])
        self.assertIsNone(dax["px"])
        self.assertIsNone(dax["z"])
        blob = str(body).lower()
        self.assertNotIn("win rate", blob)
        self.assertNotIn("gamma strip", blob)

    def test_seed_adds_core_yahoo_names(self):
        res = self.client.post("/api/market-moves/seed", json={"groups": ["big_tech"]})
        self.assertIn(res.status_code, (200, 201))
        data = res.get_json()
        self.assertIn("AAPL", data["tickers"])
        self.assertIn("TSLA", data["tickers"])

    def test_surfaces_have_moves_nav_and_quant_lock(self):
        blob = ""
        for path in (
            "index.html",
            "scripts/market_moves.js",
            "styles/main.css",
            "market_moves.py",
            "mobile/lib/ui/scans_page.dart",
        ):
            with open(path, encoding="utf-8") as fh:
                blob += fh.read()
        self.assertIn("Market Moves", blob)
        self.assertIn("/api/market-moves", blob)
        self.assertIn("tab-moves", blob)
        self.assertIn("ddof=1", blob)
        self.assertIn("NOT bare r/σ", blob)
        self.assertNotIn("bloomberg", blob.lower())
        self.assertNotIn("stockbee.blogspot", blob.lower())


if __name__ == "__main__":
    unittest.main()
