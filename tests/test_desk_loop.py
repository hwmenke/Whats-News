"""Desk loop: grouping annotations, news honesty, no invented fractal/win rates."""

import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["DATA_SERVICE_MODE"] = "embedded"

import data_client
import database as db
import ticker_lists as tl
import app as app_module


class DeskLoopTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmpdir.name, "desk.db")
        self._path_patch = patch.object(db, "DB_PATH", self.db_path)
        self._path_patch.start()
        db.init_db()
        os.environ["DATA_SERVICE_MODE"] = "embedded"
        data_client.DATA_SERVICE_MODE = "embedded"
        self.client = app_module.app.test_client()

    def tearDown(self):
        self._path_patch.stop()
        self._tmpdir.cleanup()

    def test_group_label_and_filter_kind(self):
        self.assertEqual(tl.filter_kind_for_tag("lib:intl_etfs"), "country")
        self.assertEqual(tl.filter_kind_for_tag("lib:sector_etfs"), "sector")
        self.assertEqual(tl.filter_kind_for_tag("lib:themes"), "theme")
        self.assertEqual(tl.filter_kind_for_tag("lib:broad_etfs"), "index")
        self.assertEqual(tl.group_label(""), "Ungrouped")
        self.assertEqual(tl.group_label("lib:intl_etfs"), "International ETFs")
        self.assertEqual(tl.group_label("sleeve:core"), "Core indices")
        row = tl.annotate_symbol({"symbol": "EWJ", "group_tag": "lib:intl_etfs"})
        self.assertEqual(row["filter_kind"], "country")
        self.assertEqual(row["group_label"], "International ETFs")

    def test_symbols_api_adds_group_fields(self):
        self.client.post("/api/universe/core50")
        desk = self.client.get("/api/symbols?desk=1").get_json()
        ewj = next(s for s in desk if s["symbol"] == "EWJ")
        self.assertEqual(ewj.get("filter_kind"), "country")
        self.assertTrue(ewj.get("group_label"))
        xlk = next(s for s in desk if s["symbol"] == "XLK")
        self.assertEqual(xlk.get("filter_kind"), "sector")

    def test_news_desk_empty_is_200(self):
        res = self.client.get("/api/news?desk=1")
        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body.get("articles"), [])
        self.assertNotIn("breaking", str(body).lower())

    def test_macro_ready_vs_missing(self):
        board = self.client.get("/api/macro/board").get_json()
        core = next(s for s in board["sleeves"] if s["id"] == "core")
        self.assertIn("ready_count", core)
        self.assertIn("missing_count", core)
        self.assertEqual(core["ready_count"] + core["missing_count"], len(core["tickers"]))

    def test_edges_and_fractal_stay_honest(self):
        edges = self.client.get("/api/edges/board").get_json()
        blob = str(edges).lower()
        self.assertNotIn("win rate", blob)
        self.assertNotIn("70%", blob)
        scan = self.client.get("/api/fractal/scan?desk=1").get_json()
        self.assertTrue(scan.get("available"))
        for row in scan.get("rows") or []:
            if row.get("d_65d") is None:
                self.assertIsNone(row.get("d_65d"))
        keys = {str(k).lower() for k in scan}
        self.assertNotIn("d_hat", keys)
        self.assertNotIn("70%", str(scan).lower())

    def test_web_desk_has_grouping_and_settings(self):
        with open("index.html", encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn('data-family="index"', html)
        self.assertIn(">Broad<", html)
        self.assertIn("news-scope", html)
        self.assertIn("desk-refresh-sec", html)
        with open("scripts/macro_desk.js", encoding="utf-8") as fh:
            js = fh.read()
        self.assertIn("edgeTag", js)
        self.assertNotIn("70%", js)
        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            setup = fh.read()
        self.assertIn("NEAR_HIGH", setup)
        self.assertIn("research label, not edge", html)
        self.assertIn("data-lens=\"finviz\"", html)
        self.assertIn("data-lens=\"hmm\"", html)
        self.assertIn("data-lens=\"combo\"", html)
        self.assertIn("/api/hmm/combo", html)


if __name__ == "__main__":
    unittest.main()
