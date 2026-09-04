"""Board column + measure registry — Market Moves + ENGINE."""

import os
import unittest

os.environ["DATA_SERVICE_MODE"] = "embedded"

import app as app_module
import board_registry as br


class BoardRegistryTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_json_and_yaml_twins_exist(self):
        self.assertTrue(br.JSON_PATH.is_file())
        self.assertTrue(br.YAML_PATH.is_file())
        yaml_text = br.YAML_PATH.read_text(encoding="utf-8")
        self.assertIn("measure id", yaml_text)
        for bid in ("market_moves", "engine_setup", "engine_sigma", "engine_maps", "setup"):
            self.assertIn(bid, yaml_text)
        self.assertIn("engine:", yaml_text)
        self.assertIn("macro:", yaml_text)
        self.assertIn("mm.z", yaml_text)
        self.assertIn("eng.tmac_star", yaml_text)
        self.assertNotIn("bloomberg", yaml_text.lower())

    def test_catalog_api_shape(self):
        body = self.client.get("/api/boards/registry").get_json()
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["theme"], "visual_v41")
        self.assertIn("market_moves", body["boards"])
        self.assertIn("engine_setup", body["boards"])
        for bid in ("market_moves", "engine", "setup", "macro"):
            self.assertIn(bid, body["boards"])
        self.assertEqual(body.get("canonical_boards"), ["market_moves", "engine", "setup", "macro"])
        with open("styles/theme.css", encoding="utf-8") as fh:
            theme = fh.read()
        self.assertIn("Public Sans", theme)
        self.assertIn("JetBrains Mono", theme)
        self.assertNotIn("IBM Plex Sans Condensed", theme)
        self.assertIn("--font-face-title", theme)
        self.assertIn("#111111", theme)
        self.assertIn("utilitarian red/green", theme)
        mm = body["boards"]["market_moves"]["columns"]
        self.assertEqual([c["id"] for c in mm], ["name", "px", "day_pct", "z", "z14"])
        z = next(c for c in mm if c["id"] == "z")
        self.assertEqual(z["key"], "z")
        self.assertEqual(z["format"], "z_1")
        self.assertEqual(z["heat"], "z")
        self.assertEqual(z["heat_scale"]["extreme"], 2)
        self.assertIn("NOT bare r/σ", z["formula"])
        tmac = next(c for c in body["boards"]["engine_setup"]["columns"] if c["id"] == "tmac_star")
        self.assertEqual(tmac["key"], "tmac_star")
        self.assertIn("never branded TMAC", tmac["formula"])
        self.assertIn("SharedPreferences", body["flutter_path"])
        blob = str(body).lower()
        self.assertNotIn("bloomberg", blob)
        self.assertNotIn("gamma strip", blob)

    def test_locked_columns_cannot_hide(self):
        hidden = br.apply_layout("market_moves", {"hidden": ["name", "z"], "order": ["z14", "name", "px", "day_pct", "z"]})
        ids = [c["id"] for c in hidden]
        self.assertEqual(ids, ["z14", "name", "px", "day_pct"])
        self.assertIn("name", ids)
        self.assertNotIn("z", ids)

    def test_engine_payloads_stamp_columns(self):
        moves = self.client.get("/api/market-moves").get_json()
        self.assertEqual(moves.get("board_id"), "market_moves")
        self.assertEqual([c["id"] for c in moves["columns"]], ["name", "px", "day_pct", "z", "z14"])
        setup = self.client.get("/api/engine/board?desk=1").get_json()
        self.assertEqual(setup.get("board_id"), "engine_setup")
        self.assertIn("tmac_star", [c["id"] for c in setup["columns"]])
        sigma = self.client.get("/api/engine/sigma?desk=1").get_json()
        self.assertEqual(sigma.get("board_id"), "engine_sigma")
        maps = self.client.get("/api/engine/maps?desk=1").get_json()
        self.assertEqual(maps.get("board_id"), "engine_maps")
        tes = next(c for c in maps["columns"] if c["id"] == "tes")
        self.assertEqual(tes["key"], "tes_state")
        self.assertIn("dir5", [c["id"] for c in maps["columns"]])

    def test_surfaces_wire_customize_and_theme(self):
        blob = ""
        for path in (
            "index.html",
            "scripts/board_registry.js",
            "scripts/market_moves.js",
            "scripts/engine_desk.js",
            "styles/theme.css",
            "mobile/lib/ui/scans_page.dart",
            "mobile/lib/data/api_client.dart",
        ):
            with open(path, encoding="utf-8") as fh:
                blob += fh.read()
        self.assertIn("data-customize-board=\"market_moves\"", blob)
        self.assertIn("data-customize-board=\"engine_setup\"", blob)
        self.assertIn("BoardRegistry", blob)
        self.assertIn("boardColumns", blob)
        self.assertIn("Public Sans", blob)
        self.assertIn("JetBrains Mono", blob)
        self.assertNotIn("IBM Plex Sans Condensed", blob)
        self.assertIn("visual-v41", blob)
        self.assertIn("/api/boards/registry", blob)
        self.assertIn("getBoardRegistry", blob)
        self.assertNotIn("bloomberg", blob.lower())


if __name__ == "__main__":
    unittest.main()
