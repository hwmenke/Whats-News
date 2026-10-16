"""Validate batch request bodies before any universe database access."""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import app as app_module


class UniverseBatchApiTests(unittest.TestCase):
    def test_invalid_bodies_are_json_errors_before_database_access(self):
        client = app_module.app.test_client()
        for route in ("archive", "refresh"):
            for body in ("", "{", "null", "false", "0", '"AAPL"', "[]", '["AAPL"]'):
                with self.subTest(route=route, body=body), patch(
                    "database.list_symbol_codes"
                ) as symbols, patch("database.list_symbols_with_ohlcv") as stored:
                    response = client.post(
                        f"/api/universe/{route}", data=body,
                        content_type="application/json",
                    )
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.get_json(), {"error": "body must be a JSON object"})
                    symbols.assert_not_called()
                    stored.assert_not_called()

    def test_empty_object_preserves_default_stream(self):
        client = app_module.app.test_client()
        for route in ("archive", "refresh"):
            with self.subTest(route=route), patch(
                "app.data_client.use_embedded", return_value=True
            ), patch("database.list_symbol_codes", return_value=[]) as symbols:
                response = client.post(f"/api/universe/{route}", json={})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "text/event-stream")
                self.assertIn('"total": 0', response.get_data(as_text=True))
                self.assertIn('"type": "done"', response.get_data(as_text=True))
                symbols.assert_called_once_with()
