"""Scanner pack: MA / RSI / Breakout + style tags + empty breadth honesty."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ["DATA_SERVICE_MODE"] = "embedded"

import app as app_module
import data_client
import database as db
import scan_pack as sp


def _frame(close, volume=None, start="2023-01-02"):
    close = np.asarray(close, dtype=float)
    n = len(close)
    idx = pd.bdate_range(start, periods=n)
    vol = np.asarray(volume if volume is not None else np.full(n, 1_000_000.0), dtype=float)
    return pd.DataFrame(
        {
            "open": close - 0.15,
            "high": close + 0.40,
            "low": close - 0.40,
            "close": close,
            "volume": vol,
        },
        index=idx,
    )


def _uptrend(n=220, start=80.0, end=150.0):
    return np.linspace(start, end, n)


class ScanPackMeasureTests(unittest.TestCase):
    def test_stacked_ma_on_uptrend(self):
        close = _uptrend(220)
        row = sp.measure("AAA", df=_frame(close))
        self.assertTrue(row["ready"])
        self.assertTrue(row["stacked_ma"])
        self.assertIn("STACKED_MA", row["tags"])
        self.assertTrue(row["match"]["ma"])
        self.assertGreater(row["vs50"], 0)
        self.assertGreater(row["vs200"], 0)

    def test_pullback_to_rising_sma20(self):
        base = _uptrend(80, 100, 140)
        sma20 = float(base[-20:].mean())
        fade = base.copy()
        fade[-1] = sma20 * 0.99  # −1% vs SMA20, inside the pullback band
        row = sp.measure("BBB", df=_frame(fade))
        self.assertIsNotNone(row["vs20"])
        self.assertGreaterEqual(row["vs20"], -3.0)
        self.assertLessEqual(row["vs20"], 0.5)
        self.assertTrue(row["sma20_rising"])
        self.assertTrue(row["pullback_rising_ma"])
        self.assertIn("PULLBACK_RISING_MA", row["tags"])
        self.assertTrue(row["match"]["ma"])

    def test_rsi_oversold_and_rising_from_os(self):
        up = _uptrend(80, 120, 160)
        crash = np.linspace(160, 90, 18)
        dumped = np.concatenate([up, crash])
        os_row = sp.measure("OS", df=_frame(dumped))
        self.assertIsNotNone(os_row["rsi14"])
        self.assertLessEqual(os_row["rsi14"], 30)
        self.assertTrue(os_row["rsi_os"])
        self.assertIn("RSI_OS", os_row["tags"])
        self.assertTrue(os_row["match"]["rsi"])

        bounce = dumped.copy()
        bounce[-1] = bounce[-2] * 1.04
        bounce[-2] = bounce[-3] * 1.03
        rise = sp.measure("OS2", df=_frame(bounce))
        self.assertTrue(rise["rsi_os"] or rise["rsi_rising_from_os"])
        if rise["rsi_rising_from_os"]:
            self.assertIn("RSI_RISING_FROM_OS", rise["tags"])
            self.assertLess(rise["rsi14_prev"], 30)
            self.assertGreater(rise["rsi14"], rise["rsi14_prev"])

    def test_breakout_near_52w_and_vol_surge(self):
        close = _uptrend(260, 50, 100)
        vol = np.full(260, 1_000_000.0)
        vol[-1] = 3_000_000.0
        high_boost = _frame(close, volume=vol)
        high_boost["high"] = high_boost["close"] + 0.1
        high_boost.iloc[-1, high_boost.columns.get_loc("high")] = close[-1]
        row = sp.measure("CCC", df=high_boost)
        self.assertTrue(row["near_52w"])
        self.assertTrue(row["vol_surge"])
        self.assertIn("NEAR_52W", row["tags"])
        self.assertIn("VOL_SURGE", row["tags"])
        self.assertIn("BREAKOUT", row["tags"])
        self.assertTrue(row["match"]["breakout"])

    def test_oneil_rs_vs_spy_no_eps(self):
        spy = _uptrend(80, 100, 105)
        winner = _uptrend(80, 100, 130)
        row = sp.measure("WIN", df=_frame(winner), spy_df=_frame(spy))
        self.assertIsNotNone(row["rs_spy_63d"])
        self.assertGreater(row["rs_spy_63d"], 0)
        self.assertIn("ONEIL_RS", row["tags"])
        self.assertIn("oneil", row["styles"])
        self.assertEqual(row["oneil_note"], "price/RS only — no fundamentals feed")
        self.assertNotIn("eps", str(row).lower())

    def test_vcp_proxy_range_shrink_near_high(self):
        # 50 wide days then 10 tight days sitting at the high
        wide = 100 + 8 * np.sin(np.linspace(0, 12, 50))
        tight = np.linspace(107.2, 108.0, 12)
        close = np.concatenate([wide, tight])
        df = _frame(close)
        df.loc[df.index[:50], "high"] = df["close"].iloc[:50] + 6
        df.loc[df.index[:50], "low"] = df["close"].iloc[:50] - 6
        df.loc[df.index[50:], "high"] = df["close"].iloc[50:] + 0.15
        df.loc[df.index[50:], "low"] = df["close"].iloc[50:] - 0.15
        row = sp.measure("VCP", df=df)
        self.assertIsNotNone(row["range_10_50"])
        self.assertLessEqual(row["range_10_50"], 0.55)
        self.assertTrue(row["near_nd"] or row["near_52w"])
        self.assertTrue(row["vcp_proxy"])
        self.assertIn("VCP_PROXY", row["tags"])
        self.assertIn("honest proxy", row["vcp_note"])

    def test_qulla_uses_existing_ep_vol_near_high(self):
        close = _uptrend(40, 90, 110)
        vol = np.full(40, 800_000.0)
        vol[-1] = 2_400_000.0
        df = _frame(close, volume=vol)
        df.iloc[-1, df.columns.get_loc("open")] = close[-2] * 1.05
        df.iloc[-1, df.columns.get_loc("close")] = close[-2] * 1.06
        row = sp.measure("EP1", df=df)
        self.assertTrue(row["is_ep"] or row["vol_surge"] or row["near_nd"])
        self.assertIn("QULLA", row["tags"])
        self.assertTrue(row["match"]["qulla"])


class ScanPackBreadthTests(unittest.TestCase):
    def test_empty_universe_is_honest(self):
        strip = sp.breadth(symbols=[], frames={})
        self.assertFalse(strip["ready"])
        self.assertIsNone(strip["pct_above_sma50"])
        self.assertIsNone(strip["pct_above_sma200"])
        self.assertIsNone(strip["adv_1d"])
        self.assertIsNone(strip["ad_1d"])
        self.assertEqual(strip["n"], 0)
        msg = (strip["message"] or "").lower()
        self.assertTrue("empty" in msg or "desk list" in msg)
        if strip.get("stored_n"):
            self.assertNotIn("no stored bars", msg)
        self.assertNotIn("stockbee.blogspot", strip["note"].lower())

    def test_breadth_from_our_frames(self):
        up = _frame(_uptrend(220, 80, 140))
        down = _frame(np.linspace(140, 80, 220))
        strip = sp.breadth(
            symbols=["UP", "DN"],
            frames={"UP": up, "DN": down, "SPY": _frame(_uptrend(220, 100, 110))},
        )
        self.assertTrue(strip["ready"])
        self.assertEqual(strip["n"], 2)
        self.assertIsNotNone(strip["pct_above_sma50"])
        self.assertIsNotNone(strip["adv_1d"])
        self.assertEqual(strip["adv_1d"] + strip["dec_1d"] + strip["unch_1d"], 2)


class ScanPackApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "pack.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_flask_empty_desk_breadth(self):
        body = self.client.get("/api/scans/breadth?desk=1").get_json()
        self.assertFalse(body["ready"])
        self.assertIsNone(body["pct_above_sma50"])
        self.assertIn("Empty", body["message"] or "")
        self.assertEqual(body.get("stored_n"), 0)

    def test_never_empty_universe_when_stored_n(self):
        db.add_symbol("ARCH")
        db.set_symbol_group("ARCH", "univ:sp500")
        db.upsert_ohlcv("ARCH", "daily", _frame(_uptrend(80)))
        out = sp.empty_breadth()
        self.assertGreater(out["stored_n"], 0)
        self.assertNotIn("empty universe", (out["message"] or "").lower())
        body = self.client.get("/api/scans/breadth?desk=1").get_json()
        self.assertGreater(body["stored_n"], 0)
        self.assertNotIn("empty universe", (body["message"] or "").lower())
        pack = self.client.get("/api/scans/pack?desk=1&lens=ma").get_json()
        self.assertNotIn("empty universe", (pack.get("message") or "").lower())
        self.assertNotIn("empty universe", ((pack.get("breadth") or {}).get("message") or "").lower())

    @patch("data_fetcher.fetch_and_store")
    @patch("market_moves.fetch_core")
    def test_desk_seed_fetch_mocked(self, mock_core, mock_fetch):
        mock_core.return_value = {
            "seeded": {"tickers": ["SPY"]},
            "fetched": [{"symbol": "SPY", "daily_rows": 250}],
            "failed": [],
        }
        mock_fetch.return_value = {"symbol": "AAA", "daily_rows": 250}
        db.add_symbol("AAA")
        body = self.client.post("/api/desk/seed-fetch", json={"core50": False, "delay": 0}).get_json()
        self.assertIn("desk_extra", body)
        self.assertIn("stored_n", body)
        self.assertIn("YAHOO_SEED", body.get("note") or "")
        mock_core.assert_called_once()
        self.assertTrue(mock_fetch.called)
        missing = (body["desk_extra"] or {}).get("missing_before") or []
        self.assertIn("AAA", missing)

    def test_flask_pack_filters_ma(self):
        close = _uptrend(220)
        db.add_symbol("AAA")
        db.upsert_ohlcv("AAA", "daily", _frame(close))
        body = self.client.get("/api/scans/pack?desk=0&lens=ma").get_json()
        self.assertEqual(body["lens"], "ma")
        self.assertGreaterEqual(body["count"], 1)
        self.assertTrue(any(r["symbol"] == "AAA" for r in body["rows"]))
        self.assertIn("stacked_ma", body["formulas"])

    def test_surfaces_mention_pack_and_not_stockbee_scrape(self):
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        with open("scripts/scan_pack.js", encoding="utf-8") as fh:
            js = fh.read()
        with open("mobile/lib/ui/scans_page.dart", encoding="utf-8") as fh:
            dart = fh.read()
        blob = html + js + dart
        self.assertIn("scan-breadth", html)
        self.assertIn("/api/scans/pack", js)
        self.assertIn("not certified VCP", js + dart)
        self.assertNotIn("stockbee.blogspot", blob.lower())
        self.assertIn("stored_n", js)
        self.assertIn("empty universe", js.lower())
        self.assertIn("/api/desk/seed-fetch", Path("mobile/lib/data/api_client.dart").read_text(encoding="utf-8"))
        self.assertIn("docs/YAHOO_SEED.md", Path("docs/YAHOO_SEED.md").read_text(encoding="utf-8"))
        self.assertIn("Seed registers names", Path("docs/YAHOO_SEED.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
