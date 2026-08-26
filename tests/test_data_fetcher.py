import unittest

import pandas as pd

import data_fetcher as fetcher


class AdjustmentSeamTests(unittest.TestCase):
    def test_detects_split_on_overlap(self):
        stored = {"2024-06-01": 100.0, "2024-06-02": 101.0}
        idx = pd.to_datetime(["2024-06-02", "2024-06-03"])
        df = pd.DataFrame({"close": [10.1, 10.4]}, index=idx)
        self.assertTrue(fetcher.adjustment_seam(stored, df))

    def test_no_seam_on_normal_overlap(self):
        stored = {"2024-06-01": 100.0, "2024-06-02": 101.0}
        idx = pd.to_datetime(["2024-06-02", "2024-06-03"])
        df = pd.DataFrame({"close": [101.2, 102.0]}, index=idx)
        self.assertFalse(fetcher.adjustment_seam(stored, df))

    def test_empty_is_not_a_seam(self):
        self.assertFalse(fetcher.adjustment_seam({}, pd.DataFrame()))
        self.assertFalse(fetcher.adjustment_seam({"2024-01-01": 10.0}, pd.DataFrame()))


if __name__ == "__main__":
    unittest.main()
