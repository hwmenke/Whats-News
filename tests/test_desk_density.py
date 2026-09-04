"""Caspar density + Book split + Font C contracts."""

import os
import unittest

os.environ["DATA_SERVICE_MODE"] = "embedded"


class DeskDensityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        blob = ""
        for path in (
            "index.html",
            "styles/theme.css",
            "styles/main.css",
            "scripts/app.js",
            "scripts/desk_prefs.js",
            "scripts/paper_book.js",
            "scripts/engine_desk.js",
        ):
            with open(path, encoding="utf-8") as fh:
                blob += fh.read()
        cls.blob = blob

    def test_watchlist_default_collapsed_and_24px(self):
        self.assertIn("sidebar-collapsed", self.blob)
        self.assertIn("sidebarCollapsed: true", self.blob)
        self.assertIn("--wl-row-h", self.blob)
        self.assertIn("24px", self.blob)
        self.assertIn("watchlist-peek", self.blob)
        self.assertIn("renderWatchlistPeek", self.blob)
        self.assertIn("sidebar-extras", self.blob)

    def test_font_c_face_tokens(self):
        self.assertIn("--font-face-title", self.blob)
        self.assertIn("--font-face-body", self.blob)
        self.assertIn("--font-face-mono", self.blob)
        self.assertIn("IBM Plex Sans Condensed", self.blob)
        self.assertIn("IBM Plex Mono", self.blob)
        self.assertIn("'Inter'", self.blob)
        self.assertNotIn("Barlow Condensed", self.blob)

    def test_book_surfaces_split(self):
        self.assertIn('id="tab-risk"', self.blob)
        self.assertIn('id="risk-area"', self.blob)
        self.assertIn("Upload / Data", self.blob)
        self.assertIn("data-ia=\"pnl\"", self.blob)
        self.assertIn("data-ia=\"risk\"", self.blob)
        self.assertIn("showRiskArea", self.blob)
        self.assertIn("loadPaperRisk", self.blob)
        self.assertNotIn("Book+P&amp;L", self.blob)
        self.assertIn("board-focus", self.blob)
        self.assertIn("boardTabs", self.blob)

    def test_no_invented_numbers(self):
        low = self.blob.lower()
        self.assertNotIn("bloomberg", low)
        self.assertNotIn("10.95b", low)
        self.assertNotIn("gamma strip", low)


if __name__ == "__main__":
    unittest.main()
