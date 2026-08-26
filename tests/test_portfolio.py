import os
import re
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import numpy as np
import pandas as pd

import app as app_module
import database as db
import portfolio


class PortfolioSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "p.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def _seed(self, symbol="AAPL", n=80):
        db.add_symbol(symbol)
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        close = 100 + np.linspace(0, 10, n) + np.sin(np.linspace(0, 6, n)) * 2
        df = pd.DataFrame(
            {
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": np.full(n, 1_000_000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv(symbol, "daily", df)

    def _seed_breakout(self, symbol="EPCO", n=80):
        """Flat-then-gap-up-on-volume series to exercise near-high/EP fields."""
        db.add_symbol(symbol)
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        close = np.full(n, 50.0)
        close[-1] = 55.0  # +10% gap day, new high
        volume = np.full(n, 1_000_000.0)
        volume[-1] = 3_000_000.0  # 3x average volume
        df = pd.DataFrame(
            {
                "open": np.concatenate([close[:-1] - 0.1, [52.5]]),  # ~5% gap open
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": volume,
            },
            index=idx,
        )
        db.upsert_ohlcv(symbol, "daily", df)

    def test_snapshot_ready(self):
        self._seed()
        snap = portfolio.snapshot_symbol("AAPL")
        self.assertTrue(snap["ready"])
        self.assertIn(snap["regime"], ("uptrend", "downtrend", "range"))
        self.assertIsNotNone(snap["rsi14"])
        self.assertIsNotNone(snap["stop_long_1_5atr"])

    def test_snapshot_breakout_fields(self):
        self._seed_breakout()
        snap = portfolio.snapshot_symbol("EPCO")
        self.assertTrue(snap["ready"])
        self.assertIn("dist_20d_high_pct", snap)
        self.assertIn("vol_ratio_5_20", snap)
        self.assertIn("gap_pct", snap)
        # Sitting at a fresh high, on volume, with a gap → all three flags true.
        self.assertTrue(snap["is_near_high"])
        self.assertTrue(snap["is_vol_surge"])
        self.assertTrue(snap["is_ep"])
        self.assertGreaterEqual(snap["breakout_score"], 3)
        self.assertGreater(snap["dist_20d_high_pct"], 0)

    def test_near_high_uses_including_today_ceiling(self):
        """A name 10% off the actual 20D high is not 'near high' even if prior-N dist is positive."""
        db.add_symbol("FADE")
        n = 80
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        close = np.full(n, 50.0)
        high = np.full(n, 50.5)
        high[-2] = 60.0
        close[-1] = 54.0
        high[-1] = 54.5
        df = pd.DataFrame(
            {
                "open": close - 0.1,
                "high": high,
                "low": close - 0.5,
                "close": close,
                "volume": np.full(n, 1_000_000.0),
            },
            index=idx,
        )
        db.upsert_ohlcv("FADE", "daily", df)
        snap = portfolio.snapshot_symbol("FADE")
        self.assertTrue(snap["ready"])
        self.assertLess(snap["pct_off_20d_high_pct"], -5)
        self.assertFalse(snap["is_near_high"])

    def test_breakout_queue_and_news_focus_prefer_strong_names(self):
        self._seed_breakout("EPCO")  # near-high + vol surge + EP
        self._seed("WEAK", n=80)     # plain uptrend, not near-high/vol-surge
        data = portfolio.portfolio_snapshot()
        self.assertIn("breakout_queue", data)
        queue_syms = [r["symbol"] for r in data["breakout_queue"]]
        self.assertIn("EPCO", queue_syms)
        # News focus must be driven by breakout/strong names, never the
        # weakest-RS name alone (see METHODOLOGY_REVIEW.md must-not-do #3).
        self.assertIn("EPCO", data["news_focus"])
        if data.get("weakest_rs"):
            weakest_sym = data["weakest_rs"]["symbol"]
            strongest_sym = data["strongest_rs"]["symbol"] if data.get("strongest_rs") else None
            if weakest_sym != strongest_sym and weakest_sym not in queue_syms:
                self.assertNotEqual(data["news_focus"][0], weakest_sym)

    def test_portfolio_endpoint(self):
        self._seed("AAPL")
        self._seed("MSFT", n=90)
        res = self.client.get("/api/portfolio/snapshot")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["ready_count"], 2)
        self.assertEqual(len(data["tape"]), 2)
        ranks = {r["symbol"]: r["rs_rank_21d"] for r in data["symbols"] if r.get("ready")}
        self.assertEqual(sorted(ranks.values()), [1, 2])
        self.assertIn(data["symbols"][0].get("alert"), (None, "RSI_OB", "RSI_OS"))
        self.assertIn("alerts", data)
        self.assertIn("news_focus", data)
        self.assertIsInstance(data.get("group_rollup"), list)
        self.assertIn("heatmap", data)
        self.assertTrue(any(r.get("peer_etf") for r in data["symbols"] if r.get("ready")))
        ready_row = next(r for r in data["symbols"] if r.get("ready"))
        self.assertIn("size_risk_100", ready_row)
        self.assertIn("is_near_high", ready_row)
        self.assertIn("vol_ratio_5_20", ready_row)
        self.assertIn("breakout_queue", data)

    def test_pm_desk_endpoint(self):
        self._seed("AAPL")
        res = self.client.get("/api/pm-desk/AAPL")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["ready"])

    def test_pm_desk_missing(self):
        db.add_symbol("ZZZ")
        res = self.client.get("/api/pm-desk/ZZZ")
        self.assertEqual(res.status_code, 404)

    def test_position_size_prefers_user_stop(self):
        # ATR path: stop distance = 1.5 × 2.0 = 3.0 → floor(100/3) = 33 shares
        atr = portfolio.position_size(100, 2.0, 100, 1.5)
        # Tighter user stop (distance 2.0) → more shares than ATR fallback
        user = portfolio.position_size(100, 2.0, 100, 1.5, stop_price=98)
        self.assertEqual(atr["stop_source"], "atr")
        self.assertEqual(user["stop_source"], "user_stop")
        self.assertEqual(user["stop_distance"], 2.0)
        self.assertEqual(atr["stop_distance"], 3.0)
        self.assertGreater(user["shares"], atr["shares"])

    def test_darvas_box_and_endpoint(self):
        self._seed("BOXA", n=80)
        snap = portfolio.snapshot_symbol("BOXA")
        self.assertTrue(snap["ready"])
        self.assertIn("darvas", snap)
        # Synthetic sine wave may or may not form a box; API must still respond.
        res = self.client.get("/api/darvas-box/BOXA")
        self.assertIn(res.status_code, (200, 404))
        if res.status_code == 200:
            body = res.get_json()
            self.assertIn(body["state"], ("in_box", "breakout", "failed"))
            self.assertGreater(body["top"], body["bottom"])

    def test_pm_desk_user_stop_and_risk_box(self):
        self._seed("AAPL")
        res = self.client.get("/api/pm-desk/AAPL?risk=100&stop=user&stop_price=90&target=120")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["size"]["stop_source"], "user_stop")
        self.assertIn("risk_box", data)
        self.assertEqual(data["risk_box"]["stop_mode"], "user")
        self.assertEqual(data["risk_box"]["stop"], 90)
        self.assertEqual(data["risk_box"]["target"], 120)
        self.assertIsNotNone(data["risk_box"]["r_multiple"])


class LabelHonestyTests(unittest.TestCase):
    """Guardrail: never brand book ranks as a published RS Rating or invent EPS."""

    def test_frontend_has_no_ibd_or_fake_eps(self):
        roots = ["scripts/app.js", "scripts/charts.js", "index.html", "portfolio.py"]
        banned = re.compile(r"\bIBD\b|\bEPS\s*Rating\b")
        for path in roots:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(
                banned.search(text),
                msg=f"{path} must not contain banned rating branding",
            )


class FrontendContractTests(unittest.TestCase):
    """Static contracts the desk JS must keep: method packs, copy gate, jump."""

    def test_method_chart_packs_wired(self):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            charts = fh.read()
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            scanner = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("METHOD_CHART_PACKS", charts)
        self.assertIn("minervini:", charts)
        self.assertIn("stockbee:", charts)
        self.assertIn("qulla:", charts)
        self.assertIn("function applyMethodPack", charts)
        self.assertIn("function computeSma", charts)
        self.assertIn("applyMethodPack(typeId)", scanner)
        self.assertIn('data-sma="50"', html)
        self.assertIn('data-sma="150"', html)
        self.assertIn('data-sma="200"', html)
        self.assertIn('data-ema="9"', html)
        self.assertIn('data-ema="20"', html)
        self.assertIn('id="method-pack-hint"', html)
        with open("scripts/desk_ux.js", encoding="utf-8") as fh:
            self.assertIn("function armModalFocus", fh.read())
        self.assertIn("brandt:", charts)
        self.assertIn("id: 'brandt'", scanner)
        self.assertIn("function openSetupOnChart", scanner)
        self.assertIn("isReviewWorkspace()", scanner)
        self.assertIn("methodPackIdFor(id)", scanner)
        self.assertIn("overlay: 'darvas'", charts)
        self.assertIn("overlay: 'stage'", charts)
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
            self.assertIn('class="pos-table"', app_js)
            self.assertIn("stayReview", app_js)

    def test_copy_setup_is_checklist_gated(self):
        with open("scripts/app.js", encoding="utf-8") as fh:
            app_js = fh.read()
        self.assertIn("Complete checklist before copying", app_js)
        self.assertIn("copySetupCard()", app_js)

    def test_palette_exposes_method_packs(self):
        with open("scripts/desk_palette.js", encoding="utf-8") as fh:
            pal = fh.read()
        self.assertIn("pack-minervini", pal)
        self.assertIn("pack-stockbee", pal)
        self.assertIn("pack-brandt", pal)
        self.assertIn("applyMethodPack", pal)


if __name__ == "__main__":
    unittest.main()
