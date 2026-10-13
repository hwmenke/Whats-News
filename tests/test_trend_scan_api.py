import os
import unittest
from unittest.mock import patch

import pandas as pd

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import app as app_module


class TrendScanApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    @patch("app.adaptive.compute_adaptive_trend")
    @patch("app.md.get_ohlcv_df")
    @patch("app.md.list_symbol_codes", return_value=["AAPL"])
    @patch("app.md.list_desk_symbols", return_value=[{"symbol": "AAPL"}])
    def test_nonfinite_latest_close_returns_symbol_error(self, desk, symbols, ohlcv, trend):
        for price in (float("nan"), float("inf"), float("-inf")):
            for desk_mode in ("0", "1"):
                with self.subTest(price=price, desk=desk_mode):
                    ohlcv.return_value = pd.DataFrame({"close": [100.0] * 59 + [price]})
                    response = self.client.get(
                        "/api/trend-scan", query_string={"desk": desk_mode},
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get_json(), [{
                        "symbol": "AAPL", "error": "Latest close is unavailable",
                    }])
                    self.assertNotIn("NaN", response.get_data(as_text=True))
                    self.assertNotIn("Infinity", response.get_data(as_text=True))
        trend.assert_not_called()

    @patch("app.adaptive.compute_adaptive_trend", return_value={})
    @patch("app.md.get_ohlcv_df")
    @patch("app.md.list_symbol_codes", return_value=["AAPL"])
    def test_finite_latest_close_preserves_scan_metrics(self, symbols, ohlcv, trend):
        ohlcv.return_value = pd.DataFrame({"close": [100.0 + i for i in range(60)]})
        response = self.client.get("/api/trend-scan")
        self.assertEqual(response.status_code, 200)
        row = response.get_json()[0]
        self.assertNotIn("error", row)
        self.assertEqual(row["price"], 159.0)
        self.assertIsNotNone(row["kama10_pct"])
        trend.assert_called_once()

    @patch("app.md.list_symbol_codes")
    @patch("app.md.list_desk_symbols")
    def test_invalid_frequency_and_method_return_json_400_before_scanning(self, desk, symbols):
        for parameter, error in (
            ("freq", "freq must be 'daily' or 'weekly'"),
            ("method", "method must be 'kama' or 'adma'"),
        ):
            for value in ("", "unknown", "DAILY", "KAMA"):
                for desk_mode in ("0", "1"):
                    with self.subTest(parameter=parameter, value=value, desk=desk_mode):
                        response = self.client.get(
                            "/api/trend-scan",
                            query_string={parameter: value, "desk": desk_mode},
                        )
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(response.get_json(), {"error": error})
        symbols.assert_not_called()
        desk.assert_not_called()

    @patch("app.md.list_symbol_codes", return_value=[])
    def test_supported_frequencies_and_methods_preserve_empty_scan(self, symbols):
        for freq in ("daily", "weekly"):
            for method in ("kama", "adma"):
                with self.subTest(freq=freq, method=method):
                    response = self.client.get(
                        "/api/trend-scan", query_string={"freq": freq, "method": method},
                    )
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.get_json(), [])
        self.assertEqual(symbols.call_count, 4)

    @patch("app.md.list_symbol_codes")
    @patch("app.md.list_desk_symbols")
    def test_invalid_rsi_periods_return_json_400_before_scanning(self, desk, symbols):
        for value in ("abc", "", "1.5", "0", "-1", "nan", "inf"):
            for desk_mode in ("0", "1"):
                with self.subTest(rsi_period=value, desk=desk_mode):
                    response = self.client.get(
                        "/api/trend-scan",
                        query_string={"rsi_period": value, "desk": desk_mode},
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.get_json(), {
                        "error": "rsi_period must be a positive integer",
                    })
        symbols.assert_not_called()
        desk.assert_not_called()

    @patch("app.md.list_symbol_codes", return_value=[])
    def test_default_and_positive_rsi_periods_preserve_empty_scan(self, symbols):
        for query in ({}, {"rsi_period": "1"}, {"rsi_period": "21"}):
            with self.subTest(query=query):
                response = self.client.get("/api/trend-scan", query_string=query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), [])
        self.assertEqual(symbols.call_count, 3)
