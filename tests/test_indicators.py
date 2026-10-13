"""Indicator regression tests using synthetic price series."""

import json
import unittest

import numpy as np
import pandas as pd

from indicators import _kama, _rsi, _series_to_list


class IndicatorSerializationTests(unittest.TestCase):
    def test_non_finite_values_are_null_in_strict_json(self):
        values = pd.Series(
            [np.nan, np.inf, -np.inf, 0.0, 12.5],
            index=pd.date_range("2026-01-01", periods=5),
        )
        points = _series_to_list(values)
        payload = json.loads(json.dumps(points, allow_nan=False))
        self.assertEqual(
            [point["value"] for point in payload],
            [None, None, None, 0.0, 12.5],
        )
        self.assertEqual(
            [point["date"] for point in payload],
            [date.strftime("%Y-%m-%d") for date in values.index],
        )


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
    def test_missing_quotes_do_not_inherit_rsi_readings(self):
        for missing in (np.nan, np.inf, -np.inf):
            for prices in (list(range(25)), [100 + i % 3 for i in range(25)]):
                with self.subTest(missing=missing, prices=prices):
                    close = pd.Series(prices, dtype=float)
                    close.iloc[20] = missing
                    result = _rsi(close)
                    self.assertTrue(np.isfinite(result.iloc[19]))
                    self.assertTrue(pd.isna(result.iloc[20]))
                    self.assertIsNone(_series_to_list(pd.Series(
                        [result.iloc[20]], index=pd.date_range("2026-01-01", periods=1)
                    ))[0]["value"])
                    self.assertTrue(np.isfinite(result.iloc[22]))
                    expected = _rsi(close.replace([np.inf, -np.inf], np.nan))
                    pd.testing.assert_series_equal(result, expected)

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
