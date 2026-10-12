import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

import app as app_module


class KnnApiTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    @patch("app.knn_model.compute_knn_lookalike")
    def test_invalid_neighbor_counts_return_json_400(self, compute):
        for value in ("abc", "", "1.5", "0", "-1"):
            with self.subTest(k=value):
                response = self.client.get("/api/knn/AAPL", query_string={"k": value})
                self.assertEqual(response.status_code, 400)
                self.assertIn("error", response.get_json())
        compute.assert_not_called()

    @patch("app.knn_model.compute_knn_lookalike")
    def test_default_and_positive_counts_reach_calculation(self, compute):
        compute.return_value = {"neighbors": []}
        for query, expected in (({}, 15), ({"k": "1"}, 1), ({"k": "30"}, 30)):
            with self.subTest(query=query):
                response = self.client.get("/api/knn/aapl", query_string=query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"neighbors": []})
                compute.assert_called_with("AAPL", k=expected)

    @patch("app.knn_model.compute_knn_lookalike")
    def test_missing_data_preserves_json_404(self, compute):
        compute.return_value = {"error": "Not enough data for AAPL"}
        response = self.client.get("/api/knn/AAPL")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), compute.return_value)
