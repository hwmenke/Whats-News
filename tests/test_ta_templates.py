"""Tests for Minervini Trend Template + Stockbee mechanical helpers."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import setup_scanner
import ta_templates


def _uptrend_frame(n=260, start=40.0, end=120.0):
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    close = np.linspace(start, end, n)
    noise = np.sin(np.linspace(0, 12, n)) * 0.4
    close = close + noise
    return pd.DataFrame(
        {
            "open": close - 0.2,
            "high": close + 1.2,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 2_000_000.0),
        },
        index=idx,
    )


class TaTemplatesTests(unittest.TestCase):
    def test_minervini_trend_template_pass_on_strong_uptrend(self):
        df = _uptrend_frame()
        with patch("ta_templates.md.get_ohlcv_df", return_value=df):
            out = ta_templates.minervini_trend_template("MNVI")
        self.assertTrue(out["ready"])
        self.assertGreaterEqual(out["score"], 7)
        self.assertTrue(out["pass"])
        self.assertIn("MINERVINI_TT", out["tags"])

    def test_minervini_insufficient_bars(self):
        idx = pd.date_range("2024-01-01", periods=50, freq="B")
        close = np.linspace(10, 12, 50)
        df = pd.DataFrame(
            {
                "open": close - 0.1,
                "high": close + 0.2,
                "low": close - 0.2,
                "close": close,
                "volume": np.full(50, 1e6),
            },
            index=idx,
        )
        with patch("ta_templates.md.get_ohlcv_df", return_value=df):
            out = ta_templates.minervini_trend_template("SHORT")
        self.assertFalse(out["ready"])
        self.assertEqual(out["tags"], [])

    def test_stockbee_ep_and_ema(self):
        n = 80
        idx = pd.date_range("2024-01-01", periods=n, freq="B")
        close = np.linspace(50, 70, n)
        open_ = close.copy()
        volume = np.full(n, 1_000_000.0)
        open_[-1] = close[-2] * 1.06
        close[-1] = open_[-1] * 1.01
        volume[-1] = 3_000_000.0
        high = np.maximum(open_, close) + 0.5
        low = np.minimum(open_, close) - 0.5
        high[-1] = low[-1] + 8.0
        df = pd.DataFrame(
            {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
            index=idx,
        )
        with patch("ta_templates.md.get_ohlcv_df", return_value=df):
            out = ta_templates.stockbee_momentum("BEE")
        self.assertTrue(out["ready"])
        self.assertIn("STOCKBEE_EP", out["tags"])
        self.assertIn("STOCKBEE_EMA", out["tags"])
        self.assertIn("STOCKBEE_RE", out["tags"])

    def test_setup_families_include_minervini_stockbee(self):
        self.assertIn("minervini", setup_scanner.SETUP_FAMILIES)
        self.assertIn("stockbee", setup_scanner.SETUP_FAMILIES)
        self.assertIn("MINERVINI_TT", setup_scanner.SETUP_IDS)
        self.assertIn("STOCKBEE_EP", setup_scanner.SETUP_IDS)
        self.assertIn("MINERVINI_TT", setup_scanner.SETUP_FAMILIES["minervini"]["tags"])
        self.assertIn("STOCKBEE_ANT", setup_scanner.SETUP_FAMILIES["stockbee"]["tags"])


if __name__ == "__main__":
    unittest.main()
