"""
Network-free tests for the FRED macro layer.

Seeds synthetic observations into a temporary database so nothing here
touches fred.stlouisfed.org.
"""
import os
import tempfile
import unittest

import database as db
import fred_fetcher as fred


class MacroTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        cls._orig_db_path = db.DB_PATH
        db.DB_PATH = cls._tmp.name
        db.init_db()

        # Two ordinary series, one with a missing observation
        db.upsert_macro("T10Y2Y", [
            ("2024-01-01", 0.5), ("2024-01-02", 0.4),
            ("2024-01-03", None), ("2024-01-04", 0.2),
        ])
        db.upsert_macro("ICSA", [("2024-01-01", 210000.0), ("2024-01-08", 225000.0)])

        # USREC: one closed recession (03→05) and one still open at the end
        db.upsert_macro("USREC", [
            ("2024-01-01", 0.0),
            ("2024-01-02", 0.0),
            ("2024-01-03", 1.0),
            ("2024-01-04", 1.0),
            ("2024-01-05", 0.0),
            ("2024-01-06", 0.0),
            ("2024-01-07", 1.0),
            ("2024-01-08", 1.0),
        ])

        import app as app_module
        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        db.DB_PATH = cls._orig_db_path
        try:
            os.unlink(cls._tmp.name)
        except OSError:
            pass

    # ── storage ────────────────────────────────────────────────────────────
    def test_upsert_is_idempotent_and_updates(self):
        before = len(db.get_macro("T10Y2Y")["T10Y2Y"])
        db.upsert_macro("T10Y2Y", [("2024-01-02", 0.45)])
        after = db.get_macro("T10Y2Y")["T10Y2Y"]
        self.assertEqual(len(after), before)                 # no duplicate row
        self.assertEqual([p for p in after if p["date"] == "2024-01-02"][0]["value"], 0.45)

    def test_missing_observations_stay_null(self):
        obs = db.get_macro("T10Y2Y")["T10Y2Y"]
        gap = [p for p in obs if p["date"] == "2024-01-03"][0]
        self.assertIsNone(gap["value"])

    # ── endpoints ──────────────────────────────────────────────────────────
    def test_get_macro(self):
        r = self.client.get("/api/macro")
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertIn("T10Y2Y", d["data"])
        self.assertIn("ICSA", d["data"])
        # Catalogue travels with the payload so the UI can label/invert series
        ids = [s["id"] for s in d["series"]]
        self.assertIn("BAMLH0A0HYM2", ids)
        self.assertTrue(any(s["id"] == "ICSA" and s["invert"] for s in d["series"]))

    def test_recession_ranges_endpoint(self):
        r = self.client.get("/api/macro/recessions")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), [
            {"from": "2024-01-03", "to": "2024-01-05"},   # closed mid-series
            {"from": "2024-01-07", "to": "2024-01-08"},   # still open at the end
        ])

    # ── CSV parsing (no network) ───────────────────────────────────────────
    def test_parse_csv_handles_both_date_headers_and_dots(self):
        legacy = "DATE,T10Y2Y\n2024-01-01,0.50\n2024-01-02,.\n"
        rows = fred._parse_csv(legacy, "T10Y2Y")
        self.assertEqual(rows, [("2024-01-01", 0.5), ("2024-01-02", None)])

        modern = "observation_date,T10Y2Y\n2024-02-01,1.25\n"
        self.assertEqual(fred._parse_csv(modern, "T10Y2Y"), [("2024-02-01", 1.25)])

    def test_parse_csv_empty_input(self):
        self.assertEqual(fred._parse_csv("DATE,T10Y2Y\n", "T10Y2Y"), [])


if __name__ == "__main__":
    unittest.main()
