"""Filter extras for setup scanner."""

import unittest

import setup_scanner as ss


class SetupFilterExtrasTests(unittest.TestCase):
    def _rows(self):
        return [
            {
                "symbol": "A",
                "ready": True,
                "setups": ["EP", "VOL_SURGE"],
                "families": ["qullamaggie"],
                "setup_score": 3,
                "change_pct": 5.0,
                "vol_ratio_5_20": 2.0,
                "rs_rank_21d": 5,
                "rs_n": 10,
                "regime": "uptrend",
                "regime_weekly": "uptrend",
                "badge_codes": ["KQ", "SB4"],
                "rts": 80,
                "strike_zone": True,
                "stage": 2,
            },
            {
                "symbol": "B",
                "ready": True,
                "setups": ["RSI_OS"],
                "families": [],
                "setup_score": 1,
                "change_pct": -2.0,
                "vol_ratio_5_20": 0.8,
                "rs_rank_21d": 50,
                "rs_n": 50,
                "regime": "downtrend",
                "regime_weekly": "downtrend",
                "badge_codes": [],
                "rts": 20,
                "strike_zone": False,
                "stage": 4,
            },
        ]

    def test_min_change_and_dual_up(self):
        out = ss._filter_and_rollup(
            self._rows(),
            symbols_scanned=2,
            min_change=3,
            dual_up=True,
            from_cache=True,
        )
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["results"][0]["symbol"], "A")

    def test_rsi_extreme(self):
        out = ss._filter_and_rollup(
            self._rows(),
            symbols_scanned=2,
            rsi_extreme=True,
            from_cache=True,
        )
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["results"][0]["symbol"], "B")

    def test_strike_and_min_rts(self):
        out = ss._filter_and_rollup(
            self._rows(),
            symbols_scanned=2,
            strike=True,
            min_rts=70,
            from_cache=True,
        )
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["results"][0]["symbol"], "A")

    def test_triage_sort_prefers_rts(self):
        rows = self._rows()
        rows[0]["setup_score"] = 2
        rows[1]["setup_score"] = 2
        rows[1]["rts"] = 90
        rows[1]["change_pct"] = 0
        out = ss._filter_and_rollup(rows, symbols_scanned=2, from_cache=True)
        self.assertEqual(out["results"][0]["symbol"], "B")

    def test_tight_coil_in_catalog(self):
        self.assertIn("TIGHT_COIL", ss.SETUP_IDS)
        self.assertIn("TIGHT_COIL", ss.SETUP_FAMILIES["stockbee"]["tags"])

    def test_pullback_in_catalog(self):
        self.assertIn("PULLBACK_EMA", ss.SETUP_IDS)
        self.assertTrue(ss.is_kama_pullback({"regime": "uptrend", "vs_kama20_pct": -4}))
        self.assertFalse(ss.is_kama_pullback({"regime": "uptrend", "vs_kama20_pct": -20}))
        self.assertFalse(ss.is_kama_pullback({"regime": "downtrend", "vs_kama20_pct": -2}))

    def test_liquidity_floors(self):
        rows = self._rows()
        rows[0]["price"] = 80
        rows[0]["dollar_vol_20d"] = 50_000_000
        rows[1]["price"] = 2
        rows[1]["dollar_vol_20d"] = 1_000_000
        out = ss._filter_and_rollup(
            rows,
            symbols_scanned=2,
            min_price=5,
            min_dollar_vol=20_000_000,
            from_cache=True,
        )
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["results"][0]["symbol"], "A")

    def test_liquidity_floor_drops_null_adv(self):
        rows = self._rows()
        rows[0]["price"] = 80
        rows[0]["dollar_vol_20d"] = None
        rows[1]["price"] = 80
        rows[1]["dollar_vol_20d"] = 50_000_000
        out = ss._filter_and_rollup(
            rows,
            symbols_scanned=2,
            min_price=5,
            min_dollar_vol=20_000_000,
            from_cache=True,
        )
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["results"][0]["symbol"], "B")

    def test_r_to_box(self):
        self.assertEqual(ss._r_to_box(100, 85, 10), 1.0)
        self.assertIsNone(ss._r_to_box(100, 85, None))

    def test_live_rs_ranked_on_universe_not_filter(self):
        rows = self._rows()
        out = ss._filter_and_rollup(
            rows,
            symbols_scanned=2,
            setup_filter="EP",
            from_cache=False,
        )
        self.assertEqual(out["count"], 1)
        # A is the only EP but both rows are in the universe; rank must be vs 2.
        self.assertEqual(out["results"][0]["rs_n"], 2)

    def test_max_rs_ranks_before_filter_on_live(self):
        rows = self._rows()
        rows[0]["rs_rank_21d"] = None
        rows[1]["rs_rank_21d"] = None
        rows[0]["ret_21d_pct"] = 20.0
        rows[1]["ret_21d_pct"] = 1.0
        out = ss._filter_and_rollup(
            rows,
            symbols_scanned=2,
            max_rs=1,
            from_cache=False,
        )
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["results"][0]["symbol"], "A")
        self.assertEqual(out["results"][0]["rs_rank_21d"], 1)


if __name__ == "__main__":
    unittest.main()
