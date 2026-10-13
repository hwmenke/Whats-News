import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import app as app_module


class TrendScanApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

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
