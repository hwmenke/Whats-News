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

    def test_drop_partial_single_week_bar(self):
        idx = pd.to_datetime(["2024-06-13", "2024-06-14"])  # Thu-Fri of a week ending 14th
        daily = pd.DataFrame({"close": [10.0, 10.2]}, index=idx)
        weekly = pd.DataFrame(
            {"open": [10.0], "high": [10.2], "low": [10.0], "close": [10.2], "volume": [1]},
            index=pd.to_datetime(["2024-06-14"]),
        )
        out = fetcher.drop_partial_first_week(daily, weekly)
        self.assertTrue(out.empty)


if __name__ == "__main__":
    unittest.main()
