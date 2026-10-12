"""Indicator regression tests using synthetic price series."""

import unittest

import pandas as pd

from indicators import _rsi


class RsiTests(unittest.TestCase):
    def test_rising_prices_reach_100_after_warmup(self):
        result = _rsi(pd.Series(range(20), dtype=float))
        self.assertTrue(result.iloc[:14].isna().all())
        self.assertTrue((result.iloc[14:] == 100.0).all())

    def test_falling_prices_reach_zero_after_warmup(self):
        result = _rsi(pd.Series(range(20, 0, -1), dtype=float))
        self.assertTrue(result.iloc[:14].isna().all())
        self.assertTrue((result.iloc[14:] == 0.0).all())

    def test_loss_after_rising_prices_returns_below_100(self):
        result = _rsi(pd.Series([*range(20), 18], dtype=float))
        self.assertEqual(result.iloc[-2], 100.0)
        self.assertAlmostEqual(result.iloc[-1], 100.0 * 13 / 14)

    def test_flat_prices_remain_undefined(self):
        result = _rsi(pd.Series([10.0] * 20))
        self.assertTrue(result.isna().all())
