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


if __name__ == "__main__":
    unittest.main()
