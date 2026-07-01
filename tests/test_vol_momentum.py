"""Tests for the vol-adjusted momentum turnover-brake module."""

import os
import tempfile
import unittest

import numpy as np

# Point the DB at a temp file BEFORE importing database/app
_tmpdir = tempfile.mkdtemp()
os.environ["FINDASH_DB_DIR"] = _tmpdir

import database as db          # noqa: E402
import vol_momentum as vm      # noqa: E402


def _store_series(symbol: str, daily_ret: float, n: int = 200, vol: float = 0.0):
    """Insert a synthetic price path with constant drift and optional noise."""
    rng = np.random.default_rng(42)
    price = 100.0
    conn = db.get_connection()
    for i in range(n):
        shock = rng.normal(0, vol) if vol > 0 else 0.0
        price *= (1.0 + daily_ret + shock)
        d = f"2024-{(i // 28) % 12 + 1:02d}-{i % 28 + 1:02d}"
        # Ensure strictly increasing dates: use a simple counter-based ISO date
        d = np.datetime64("2024-01-01") + np.timedelta64(i, "D")
        conn.execute(
            "INSERT OR REPLACE INTO ohlcv (symbol, freq, date, open, high, low, close, volume)"
            " VALUES (?, 'daily', ?, ?, ?, ?, ?, 1e6)",
            (symbol, str(d), price, price * 1.01, price * 0.99, price),
        )
    conn.commit()
    conn.close()
    db.add_symbol(symbol)


class VolMomentumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        # Strong up-trend, flat, and down-trend with mild noise
        _store_series("UPP", +0.004, vol=0.005)
        _store_series("FLT",  0.000, vol=0.005)
        _store_series("DWN", -0.004, vol=0.005)

    def setUp(self):
        vm.reset_state()

    def test_signal_ordering_and_rank(self):
        res = vm.compute_vol_momentum()
        self.assertNotIn("error", res)
        by_sym = {r["symbol"]: r for r in res["rows"]}
        self.assertGreater(by_sym["UPP"]["s"], by_sym["FLT"]["s"])
        self.assertGreater(by_sym["FLT"]["s"], by_sym["DWN"]["s"])
        self.assertEqual(by_sym["UPP"]["rank"], 1)
        self.assertEqual(by_sym["DWN"]["rank"], len(res["rows"]))

    def test_target_weights_dollar_neutral_and_gross_capped(self):
        res = vm.compute_vol_momentum({"l_max": 1.0})
        w = [r["w_target"] for r in res["rows"]]
        self.assertAlmostEqual(sum(w), 0.0, places=3)              # Σ w* = 0
        self.assertLessEqual(sum(abs(x) for x in w), 1.0 + 1e-6)   # Σ|w*| ≤ L_max

    def test_first_run_trades_and_partial_adjustment(self):
        lam = 0.5
        res = vm.compute_vol_momentum({"lam": lam, "kappa": 0.1})
        for r in res["rows"]:
            if r["decision"] == "TRADE":
                # w_prev = 0 on first run, so w_new must be λ·w_target.
                # Both fields are independently rounded to 4dp in the response,
                # so allow a half-ulp of that rounding.
                self.assertAlmostEqual(r["w_new"], lam * r["w_target"], delta=1e-4)

    def test_no_trade_band_when_dw_small(self):
        # Apply once so state ≈ targets, then recompute: Δw ≈ (1-λ)·w* small-ish;
        # with a huge δ_w band everything must be held.
        vm.apply_vol_momentum({"lam": 1.0})
        res = vm.compute_vol_momentum({"delta_w": 10.0})
        for r in res["rows"]:
            self.assertEqual(r["decision"], "NO_TRADE_BAND")
            self.assertEqual(r["w_new"], r["w_prev"])

    def test_signal_band_holds_when_ds_small(self):
        vm.apply_vol_momentum({"lam": 1.0})
        # Same data → identical S, so |S − S_prev| = 0 < δ_S → band holds
        res = vm.compute_vol_momentum({"delta_s": 0.001})
        for r in res["rows"]:
            self.assertEqual(r["decision"], "NO_TRADE_BAND")

    def test_turnover_brake_blocks_trades(self):
        # κ enormous → Gain ≤ κ·Cost everywhere (Cost > 0 since w_prev=0) → BRAKE
        res = vm.compute_vol_momentum({"kappa": 1e12, "delta_w": 0.0, "delta_s": 0.0})
        for r in res["rows"]:
            self.assertIn(r["decision"], ("BRAKE",))
            self.assertEqual(r["w_new"], r["w_prev"])

    def test_baskets_respect_tau(self):
        res = vm.compute_vol_momentum({"tau": 0.0, "kappa": 0.0,
                                       "delta_w": 0.0, "delta_s": 0.0})
        by_sym = {r["symbol"]: r for r in res["rows"]}
        self.assertEqual(by_sym["UPP"]["basket"], "LONG")
        self.assertEqual(by_sym["DWN"]["basket"], "SHORT")
        # τ huge → nothing qualifies for a basket even when traded
        res2 = vm.compute_vol_momentum({"tau": 1e9, "kappa": 0.0,
                                        "delta_w": 0.0, "delta_s": 0.0})
        for r in res2["rows"]:
            if r["decision"] == "TRADE":
                self.assertEqual(r["basket"], "NEUTRAL")

    def test_apply_persists_state(self):
        res = vm.apply_vol_momentum({"lam": 1.0})
        self.assertEqual(res["applied"], len(res["rows"]))
        state = vm._load_state()
        for r in res["rows"]:
            self.assertAlmostEqual(state[r["symbol"]]["weight"], r["w_new"], places=6)
            self.assertAlmostEqual(state[r["symbol"]]["signal"], r["s"], places=6)

    def test_invalid_params_rejected(self):
        self.assertIn("error", vm.compute_vol_momentum({"lam": 0}))
        self.assertIn("error", vm.compute_vol_momentum({"lam": 1.5}))
        self.assertIn("error", vm.compute_vol_momentum({"l_max": -1}))


class VolMomentumApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import app as app_module
        cls.client = app_module.app.test_client()

    def test_get_endpoint(self):
        r = self.client.get("/api/vol-momentum?kappa=0.5&lam=0.7")
        self.assertIn(r.status_code, (200, 422))
        body = r.get_json()
        if r.status_code == 200:
            self.assertIn("rows", body)
            self.assertAlmostEqual(body["params"]["kappa"], 0.5)
            self.assertAlmostEqual(body["params"]["lam"], 0.7)

    def test_get_rejects_bad_param(self):
        r = self.client.get("/api/vol-momentum?kappa=abc")
        self.assertEqual(r.status_code, 400)

    def test_reset_endpoint(self):
        r = self.client.delete("/api/vol-momentum/state")
        self.assertEqual(r.status_code, 200)
        self.assertIn("cleared", r.get_json())


if __name__ == "__main__":
    unittest.main()
