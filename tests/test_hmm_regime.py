"""SPY Gaussian HMM — research labels only, no invented win rates."""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ["DATA_SERVICE_MODE"] = "embedded"

import data_client
import database as db
import hmm_regime as hmm
import app as app_module


def _two_regime_returns(n=400, seed=4):
    """Clear vol shift: first half quiet, second half loud."""
    rng = np.random.default_rng(seed)
    a = rng.normal(0.0004, 0.004, n // 2)
    b = rng.normal(-0.0002, 0.022, n - n // 2)
    return np.concatenate([a, b])


def _closes_from_returns(r, p0=100.0):
    return p0 * np.exp(np.cumsum(r))


class HmmMathTests(unittest.TestCase):
    def test_recovers_two_vol_states(self):
        r = _two_regime_returns()
        fit = hmm.fit_gaussian_hmm(r, n_states=2, seed=3)
        self.assertIsNotNone(fit)
        vols = np.sqrt(fit["var"])
        self.assertGreaterEqual(len(vols), 2)
        self.assertGreater(float(vols.max()), float(vols.min()) * 1.4)
        labels = hmm._label_states(fit["mu"], fit["var"])
        self.assertIn("low-vol", labels)
        self.assertIn("high-vol", labels)
        interpreted = hmm.interpret_fit(r, [f"d{i}" for i in range(len(r))], fit)
        self.assertEqual(len(interpreted["states"]), 2)
        for st in interpreted["states"]:
            self.assertEqual(st["occupancy_note"], "share of fit-window days (not a win rate)")
            self.assertNotIn("win", st["label"])

    def test_three_state_labels_from_fit(self):
        rng = np.random.default_rng(9)
        r = np.concatenate([
            rng.normal(0.001, 0.004, 160),
            rng.normal(-0.001, 0.008, 160),
            rng.normal(0.0, 0.03, 160),
        ])
        fit = hmm.fit_gaussian_hmm(r, n_states=3, seed=1)
        self.assertIsNotNone(fit)
        labels = hmm._label_states(fit["mu"], fit["var"])
        self.assertEqual(len(labels), 3)
        self.assertIn("stress", labels)
        self.assertTrue({"risk-on", "risk-off", "stress"} <= set(labels) or "stress" in labels)

    def test_short_series_unavailable(self):
        self.assertIsNone(hmm.fit_gaussian_hmm([0.01, -0.01, 0.0], n_states=2))
        empty = hmm.empty_regime("short")
        self.assertFalse(empty["available"])
        self.assertEqual(empty["current_probs"], [])
        self.assertIsNone(empty["current_state_id"])


class HmmApiTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "hmm.db")
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

    def test_regime_empty_without_bars(self):
        res = self.client.get("/api/hmm/regime?symbol=SPY")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertFalse(body.get("available"))
        self.assertEqual(body.get("current_probs") or [], [])
        blob = str(body).lower()
        self.assertNotIn("win_rate", body)
        self.assertNotIn("regime flip → buy", blob)
        self.assertNotIn("flip → buy", blob)
        self.assertIn("not a win rate", blob)
        self.assertIn("research label, not edge", blob)

    def test_scan_empty_without_bars(self):
        res = self.client.get("/api/hmm/scan?desk=1")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertFalse(body.get("ready"))
        self.assertEqual(body.get("rows"), [])
        self.assertIn("research label, not edge", str(body).lower())

    def test_spy_fit_and_inherit(self):
        r = _two_regime_returns(360, seed=8)
        self._put_closes("SPY", _closes_from_returns(r))
        db.add_symbol("AAPL")
        body = self.client.get("/api/hmm/regime?symbol=SPY&force=1").get_json()
        self.assertTrue(body["available"])
        self.assertIn(body["current_label"], ("low-vol", "high-vol"))
        self.assertEqual(len(body["current_probs"]), 2)
        self.assertTrue(body["path"])
        self.assertTrue(body["research_label"])
        inh = self.client.get("/api/hmm/regime?symbol=AAPL").get_json()
        self.assertTrue(inh["inherited"])
        self.assertEqual(inh["current_label"], body["current_label"])
        scan = self.client.get("/api/hmm/scan?desk=1").get_json()
        self.assertTrue(scan["available"])
        aapl = next(r for r in scan["rows"] if r["symbol"] == "AAPL")
        self.assertTrue(aapl["inherited"])
        self.assertEqual(aapl["spy_state"], body["current_label"])
        self.assertIn("SPY state =", aapl["tag"])
        self.assertEqual(aapl["note"], "research label, not edge")
        blob = str(scan).lower()
        self.assertNotIn("win_rate", scan)
        self.assertIn("not a win rate", blob)
        self.assertNotIn("70%", blob)

    def test_status_copy(self):
        body = self.client.get("/api/hmm/status").get_json()
        self.assertTrue(body["research_label"])
        self.assertIn("not edge", body["note"])
        self.assertNotIn("win_rate", body)

    def test_combo_empty_without_bars(self):
        res = self.client.get("/api/hmm/combo?desk=1")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertFalse(body.get("available"))
        self.assertEqual(body.get("rows"), [])
        self.assertIn("real flag", str(body).lower() + body.get("note", "").lower() + " flag")

    def test_combo_and_requires_every_real_flag(self):
        r = _two_regime_returns(360, seed=5)
        self._put_closes("SPY", _closes_from_returns(r))
        db.add_symbol("AAPL")
        miss = self.client.get("/api/hmm/combo?desk=1&force=1").get_json()
        self.assertTrue(miss.get("available"))
        self.assertEqual(miss.get("rows"), [])
        self.assertIn("not invented", miss.get("reason", "").lower())

        def fragile_only(symbol, closes=None):
            if str(symbol).upper() != "AAPL":
                return {"symbol": symbol, "tags": [], "read": "orderly", "d_65d": 1.6}
            return {"symbol": "AAPL", "tags": ["FRAGILE"], "read": "FRAGILE", "d_65d": 1.2}

        def setups_ep(symbol):
            if str(symbol).upper() != "AAPL":
                return {"symbol": symbol, "ready": True, "setups": []}
            return {"symbol": "AAPL", "ready": True, "setups": ["EP", "VOL_SURGE"]}

        with patch("fractal_scan.measure_symbol", side_effect=fragile_only), patch(
            "setup_scanner._scan_one_setup", side_effect=setups_ep
        ):
            hit = self.client.get("/api/hmm/combo?desk=1").get_json()
        self.assertEqual([row["symbol"] for row in hit["rows"]], ["AAPL"])
        self.assertTrue(hit["rows"][0]["fragile"])
        self.assertIn("EP", hit["rows"][0]["setups"])
        self.assertIn("FRAGILE", hit["rows"][0]["flags"])

        def no_ep(symbol):
            return {"symbol": str(symbol).upper(), "ready": True, "setups": ["NEAR_HIGH"]}

        with patch("fractal_scan.measure_symbol", side_effect=fragile_only), patch(
            "setup_scanner._scan_one_setup", side_effect=no_ep
        ):
            skipped = self.client.get("/api/hmm/combo?desk=1").get_json()
        self.assertEqual(skipped.get("rows"), [])

    def test_highvol_view_empty_when_not_high_vol(self):
        r = _two_regime_returns(360, seed=2)
        self._put_closes("SPY", _closes_from_returns(r))
        body = self.client.get("/api/hmm/scan?desk=1&view=highvol&force=1").get_json()
        self.assertTrue(body.get("available"))
        if not body.get("spy", {}).get("high_vol"):
            self.assertEqual(body.get("rows"), [])
            self.assertIn("not high-vol", body.get("reason", "").lower())


if __name__ == "__main__":
    unittest.main()
