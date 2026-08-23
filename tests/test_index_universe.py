import unittest
from unittest.mock import patch

import index_universe as iu


class IndexUniverseTests(unittest.TestCase):
    def test_normalize_ticker(self):
        self.assertEqual(iu.normalize_ticker("brk.b"), "BRK-B")
        self.assertEqual(iu.normalize_ticker("  aapl  "), "AAPL")
        self.assertIsNone(iu.normalize_ticker(""))
        self.assertIsNone(iu.normalize_ticker("BAD TICKER!"))

    def test_universe_group_tag(self):
        self.assertEqual(iu.universe_group_tag("sp500"), "univ:sp500")
        self.assertTrue(iu.is_universe_tag("univ:sp500"))
        self.assertFalse(iu.is_universe_tag("tech"))

    def test_registry_for_api(self):
        reg = iu.registry_for_api()
        self.assertGreaterEqual(len(reg), 5)
        ids = {r["id"] for r in reg}
        self.assertIn("sp500", ids)
        self.assertIn("russell2000", ids)

    @patch("index_universe.fetch_index_symbols")
    def test_merged_universe_dedupes(self, mock_fetch):
        mock_fetch.side_effect = lambda idx: {
            "sp500": ["AAPL", "MSFT"],
            "sp400": ["MSFT", "GOOG"],
        }.get(idx, [])

        merged = iu.merged_universe(["sp500", "sp400"])
        self.assertEqual(merged["total_unique"], 3)
        self.assertEqual(sorted(merged["symbols"]), ["AAPL", "GOOG", "MSFT"])
        self.assertIn("sp500", merged["symbol_indices"]["MSFT"])


if __name__ == "__main__":
    unittest.main()
