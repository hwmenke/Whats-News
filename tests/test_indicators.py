"""Indicator regression tests using synthetic price series."""

import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from indicators import _kama, _macd, _rsi, _series_to_list, compute_indicators


class TrendScoreTests(unittest.TestCase):
    @patch("indicators.db.get_ohlcv_df")
    def test_non_finite_components_leave_trend_score_unavailable(self, mock_data):
        index = pd.date_range("2026-01-01", periods=4)
        mock_data.return_value = pd.DataFrame(
            {"close": [100.0] * 4, "high": [101.0] * 4, "low": [99.0] * 4},
            index=index,
        )
        for component in ("rsi", "cci", "macd"):
            with self.subTest(component=component):
                rsi = pd.Series([60.0] * 4, index=index)
                cci = pd.Series([10.0] * 4, index=index)
                macd = pd.Series([1.0] * 4, index=index)
                target = {"rsi": rsi, "cci": cci, "macd": macd}[component]
                target.iloc[:3] = [np.nan, np.inf, -np.inf]
                with patch("indicators._rsi", return_value=rsi), \
                     patch("indicators._cci", return_value=cci), \
                     patch("indicators._macd", return_value=(macd, macd, macd)):
                    result = compute_indicators("TEST")
                self.assertEqual(
                    [point["value"] for point in result["trend_score"]],
                    [None, None, None, 3.0],
                )
                json.dumps(result, allow_nan=False)


class EmaTests(unittest.TestCase):
    @patch("indicators.db.get_ohlcv_df")
    def test_missing_quotes_leave_ema_gaps_and_recover(self, mock_data):
        for missing in (np.nan, np.inf, -np.inf):
            with self.subTest(missing=missing):
                close = pd.Series(
                    [100 + i % 7 for i in range(40)], dtype=float,
                    index=pd.date_range("2026-01-01", periods=40),
                )
                close.iloc[30] = missing
                mock_data.return_value = pd.DataFrame(
                    {"close": close, "high": close + 1, "low": close - 1}
                )
                result = compute_indicators("TEST")
                clean = close.replace([np.inf, -np.inf], np.nan)
                for period in (10, 20):
                    points = result[f"ema_{period}"]
                    self.assertIsNone(points[30]["value"])
                    self.assertTrue(np.isfinite(points[29]["value"]))
                    self.assertTrue(np.isfinite(points[31]["value"]))
                    expected = clean.ewm(span=period, adjust=False).mean()
                    self.assertEqual(points, _series_to_list(expected.where(clean.notna())))

    @patch("indicators.db.get_ohlcv_df")
    def test_finite_quotes_preserve_pandas_ema(self, mock_data):
        close = pd.Series(
            [100 + i % 7 for i in range(40)], dtype=float,
            index=pd.date_range("2026-01-01", periods=40),
        )
        mock_data.return_value = pd.DataFrame(
            {"close": close, "high": close + 1, "low": close - 1}
        )
        result = compute_indicators("TEST")
        for period in (10, 20):
            self.assertEqual(result[f"ema_{period}"], _series_to_list(
                close.ewm(span=period, adjust=False).mean()
            ))


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
    def test_quote_gaps_restart_warmup_and_recover(self):
        for missing in (np.nan, np.inf, -np.inf):
            for gap in (0, 9, 15):
                with self.subTest(missing=missing, gap=gap):
                    close = pd.Series(
                        range(40), dtype=float,
                        index=pd.date_range("2026-01-01", periods=40),
                    )
                    close.iloc[gap] = missing
                    result = _kama(close, window=10)
                    self.assertTrue(result.iloc[gap:gap + 10].isna().all())
                    self.assertEqual(result.iloc[gap + 10], close.iloc[gap + 10])
                    pd.testing.assert_series_equal(
                        result.iloc[gap + 1:], _kama(close.iloc[gap + 1:], window=10)
                    )
                    pd.testing.assert_series_equal(
                        result.iloc[:gap], _kama(close.iloc[:gap], window=10)
                    )

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

    def test_complete_rising_history_preserves_recursive_updates(self):
        close = pd.Series(range(40), dtype=float)
        result = _kama(close, window=10)
        expected = 9.0
        for i in range(10, len(close)):
            expected += (2.0 / 3.0) ** 2 * (close.iloc[i] - expected)
            self.assertAlmostEqual(result.iloc[i], expected)


class MacdTests(unittest.TestCase):
    def test_missing_quotes_do_not_inherit_macd_readings(self):
        for missing in (np.nan, np.inf, -np.inf):
            with self.subTest(missing=missing):
                close = pd.Series(
                    [100 + i % 7 for i in range(40)], dtype=float,
                    index=pd.date_range("2026-01-01", periods=40),
                )
                close.iloc[30] = missing
                clean = close.replace([np.inf, -np.inf], np.nan)
                line = clean.ewm(span=12, adjust=False).mean() - clean.ewm(
                    span=26, adjust=False
                ).mean()
                signal = line.ewm(span=9, adjust=False).mean()
                for actual, expected in zip(_macd(close), (line, signal, line - signal)):
                    self.assertTrue(np.isfinite(actual.iloc[29]))
                    self.assertIsNone(_series_to_list(actual)[30]["value"])
                    self.assertTrue(np.isfinite(actual.iloc[31]))
                    pd.testing.assert_series_equal(actual, expected.where(clean.notna()))

    def test_finite_prices_match_pandas_macd(self):
        close = pd.Series([100 + i % 7 for i in range(40)], dtype=float)
        line = close.ewm(span=12, adjust=False).mean() - close.ewm(
            span=26, adjust=False
        ).mean()
        signal = line.ewm(span=9, adjust=False).mean()
        for actual, expected in zip(_macd(close), (line, signal, line - signal)):
            pd.testing.assert_series_equal(actual, expected)


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
