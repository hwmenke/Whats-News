"""Caspar density + Book split + Font C contracts."""

import os
import unittest
from pathlib import Path

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
            "mobile/lib/ui/theme.dart",
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
        start_pnl = self.blob.find('id="pnl-area"')
        start_book = self.blob.find('id="book-area"')
        start_risk = self.blob.find('id="risk-area"')
        start_dm = self.blob.find('id="data-manager-area"')
        self.assertNotIn("btn-alpaca-sync", self.blob[start_pnl:start_book])
        self.assertIn("btn-alpaca-sync", self.blob[start_book:start_risk])
        self.assertNotIn("btn-alpaca-sync", self.blob[start_risk:start_dm])
        self.assertIn("gap: 0 !important", self.blob)
        self.assertIn("HARD spacing", self.blob)
        self.assertIn("body.board-focus #empty-state", self.blob)
        self.assertIn("body.workspace-scan #chart-area", self.blob)
        self.assertIn("flex-flow: column nowrap !important", self.blob)
        self.assertIn('class="risk-title visually-hidden"', self.blob)
        self.assertIn('class="mm-head visually-hidden"', self.blob)
        self.assertIn("--space-header-content: 10px", self.blob)
        self.assertIn("--space-section:        10px", self.blob)
        self.assertIn("--space-row:            30px", self.blob)
        self.assertIn("--space-cell-y:         2px", self.blob)
        self.assertIn("--space-cell-x:         8px", self.blob)
        self.assertIn("--space-bottom:         8px", self.blob)
        self.assertIn("--space-inset:          12px", self.blob)
        self.assertIn("headerContent = 10", self.blob)
        self.assertIn("static const double row = 30", self.blob)
        self.assertIn("static const double inset = 12", self.blob)
        self.assertIn("max(8, safeArea.bottom)", self.blob)
        book = Path("mobile/lib/ui/book_page.dart").read_text(encoding="utf-8")
        self.assertIn("mainAxisSize: MainAxisSize.min", book)
        self.assertIn("DeskSpace.headerContent", book)
        self.assertNotIn("height: DeskSpace.chrome", book[book.find("_riskSlivers"):book.find("_positionSlivers")])
        self.assertIn("if (!list.length) return '';", self.blob)
        self.assertIn("HOW TO READ — PATTERN SCANNER", self.blob)
        self.assertIn("HOW TO READ — RSI COUNTER", self.blob)
        self.assertIn("HOW TO READ — COIL", self.blob)
        self.assertIn("HOW TO READ — ENGINE state machine", self.blob)
        self.assertIn("_engTakeawayStrip", self.blob)
        self.assertIn("_engSymCol", self.blob)
        self.assertIn("ClipRect(", Path("mobile/lib/ui/scans_page.dart").read_text(encoding="utf-8"))
        self.assertIn("BoxFit.scaleDown", Path("mobile/lib/ui/scans_page.dart").read_text(encoding="utf-8"))
        self.assertIn("_engPtsTable", self.blob)
        self.assertIn("max-height: 168px", self.blob)
        macro = Path("scripts/macro_desk.js").read_text(encoding="utf-8")
        self.assertIn("wn-table", macro)
        self.assertIn("warnings-grid", macro)
        self.assertIn("/api/desk/seed-fetch", Path("app.py").read_text(encoding="utf-8"))
        self.assertIn("See docs/YAHOO_SEED.md", Path("app.py").read_text(encoding="utf-8"))
        self.assertIn("coil_n", Path("app.py").read_text(encoding="utf-8"))
        self.assertIn("reloadMapsAfterSeed", Path("mobile/lib/data/app_state.dart").read_text(encoding="utf-8"))
        self.assertIn("for (final r in b.rows) _nameChip(r.symbol, r.engine)", Path("mobile/lib/ui/scans_page.dart").read_text(encoding="utf-8"))
        self.assertTrue(Path("docs/YAHOO_SEED.md").is_file())

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
            "pattern_dw.png",
            "rsic_counter.png",
            "macro_sigma.png",
            "coil_map.png",
            "tms_regime.png",
            "sigma_grid.png",
            "command_takeaways.png",
            "setup_glance.png",
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
