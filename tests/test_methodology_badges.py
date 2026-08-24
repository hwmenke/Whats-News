"""Tests for methodology badge catalog + compute rules."""

import unittest

import methodology_badges as mb


class MethodologyBadgeTests(unittest.TestCase):
    def test_catalog_has_core_codes(self):
        for code in ("KQ", "MM", "ON", "DB", "SB4", "SBW", "SB9", "52W", "2A", "2B", "97C"):
            self.assertIn(code, mb.BADGE_CATALOG)

    def test_book_rts(self):
        self.assertEqual(mb.book_rts(1, 100), 99)
        self.assertEqual(mb.book_rts(100, 100), 1)
        self.assertIsNone(mb.book_rts(None, 10))

    def test_compute_kq_mm_sb4(self):
        out = mb.compute_badges(
            setups=["QULLA_BREAKOUT", "MINERVINI_TT", "EP"],
            change_pct=5.2,
            is_near_high=True,
            is_vol_surge=True,
            is_ep=True,
        )
        self.assertIn("KQ", out["codes"])
        self.assertIn("MM", out["codes"])
        self.assertIn("SB4", out["codes"])

    def test_compute_stockbee_week_and_9m(self):
        out = mb.compute_badges(ret_5d_pct=22.0, ret_9m_pct=150.0)
        self.assertIn("SBW", out["codes"])
        self.assertIn("SB9", out["codes"])

    def test_compute_darvas_and_stage(self):
        out = mb.compute_badges(
            setups=["DARVAS_BREAKOUT", "STAGE_2_EARLY"],
            darvas_state="breakout",
            early_stage2=True,
            stage=2,
        )
        self.assertIn("DB", out["codes"])
        self.assertIn("2A", out["codes"])
        self.assertNotIn("2B", out["codes"])

    def test_oneil_and_97_club(self):
        out = mb.compute_badges(
            stage=2,
            is_near_high=True,
            dist_20d_high_pct=-1.0,
            rs_rank_21d=1,
            rs_n=100,
        )
        self.assertIn("ON", out["codes"])
        self.assertIn("97C", out["codes"])
        self.assertEqual(out["rts"], 99)
        self.assertTrue(out["strike_zone"])

    def test_has_badge_compare_via_filter_op(self):
        import watchlist_filters as wf
        self.assertTrue(wf._compare("has_badge", ["KQ", "MM"], "MM"))
        self.assertFalse(wf._compare("has_badge", ["KQ"], "SB4"))


if __name__ == "__main__":
    unittest.main()
