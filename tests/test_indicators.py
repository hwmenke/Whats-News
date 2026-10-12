"""Indicator regression tests using synthetic price series."""

import unittest

import pandas as pd

from indicators import _kama, _rsi


class KamaTests(unittest.TestCase):
    def test_short_histories_preserve_index_and_missing_warmup(self):
        for count in (0, 1, 9):
            with self.subTest(count=count):
                close = pd.Series(
                    range(count), index=pd.date_range("2026-01-01", periods=count),
                    dtype=float,
                )
                result = _kama(close, window=10)
                pd.testing.assert_index_equal(result.index, close.index)
                self.assertEqual(len(result), count)
                self.assertTrue(result.isna().all())

    def test_seed_and_first_update_after_warmup(self):
        result = _kama(pd.Series(range(11), dtype=float), window=10)
        self.assertTrue(result.iloc[:9].isna().all())
        self.assertEqual(result.iloc[9], 9.0)
        self.assertAlmostEqual(result.iloc[10], 9.0 + (2.0 / 3.0) ** 2)


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
