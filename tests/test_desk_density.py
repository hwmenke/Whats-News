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
            "scripts/warnings_desk.js",
            "risk_spec.py",
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
        self.assertIn("Public Sans", self.blob)
        self.assertIn("JetBrains Mono", self.blob)
        self.assertIn("'Inter'", self.blob)
        self.assertNotIn("IBM Plex Sans Condensed", self.blob)
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
        self.assertIn('id="warnings-area"', self.blob)
        self.assertIn('id="tab-warnings"', self.blob)
        self.assertIn("loadWarnings", self.blob)
        self.assertIn("scan-help", self.blob)
        self.assertIn("whats-news-risk-SPEC-2026-09-04.md", self.blob)
        self.assertIn("risk-clusters", self.blob)
        self.assertIn("overflow-x: auto", self.blob)
        self.assertIn("risk-more", self.blob)
        self.assertLess(
            self.blob.find("Ranked %VaR"),
            self.blob.find('id="risk-portfolio"'),
            "ranked %VaR must sit above portfolio chrome",
        )
        self.assertNotIn("btn-alpaca-sync", self.blob[self.blob.find('id="risk-area"'):self.blob.find('id="data-manager-area"')])
        self.assertIn("gap: 0 !important", self.blob)
        self.assertIn("HARD spacing", self.blob)
        self.assertIn("body.board-focus #empty-state", self.blob)
        self.assertIn("body.workspace-scan #chart-area", self.blob)
        self.assertIn("flex-flow: column nowrap !important", self.blob)
        self.assertIn('class="risk-title visually-hidden"', self.blob)
        self.assertIn('class="mm-head visually-hidden"', self.blob)

    def test_hard_ui_lock_font_c_v41_not_v2_v3(self):
        theme = ""
        with open("styles/theme.css", encoding="utf-8") as fh:
            theme = fh.read()
        self.assertIn("visual-v41", self.blob)
        self.assertIn("Public Sans", theme)
        self.assertIn("JetBrains Mono", theme)
        self.assertIn("--board-border:   none", theme)
        self.assertIn("--heat-green-rgb: 34, 197, 94", theme)
        self.assertNotIn("#f4f2ec", theme.lower())
        self.assertNotIn("Fraunces", theme)
        self.assertNotIn("id=\"engine-hero\"", self.blob)
        self.assertIn(".v3-hero { display: none; }", theme)

    def test_density_screenshots_on_disk(self):
        from pathlib import Path
        root = Path("docs/screenshots/density")
        for name in (
            "watchlist_before.png",
            "watchlist_after.png",
            "watchlist_after_open.png",
            "book_upload.png",
            "book_pnl.png",
            "book_risk.png",
        ):
            path = root / name
            self.assertTrue(path.is_file(), name)
            self.assertGreater(path.stat().st_size, 10_000, name)

    def test_no_invented_numbers(self):
        low = self.blob.lower()
        self.assertNotIn("bloomberg", low)
        self.assertNotIn("10.95b", low)
        self.assertNotIn("gamma strip", low)


if __name__ == "__main__":
    unittest.main()
