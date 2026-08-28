"""Contract tests for Focus mode chrome density (body class + workspace CSS)."""

import os
import re
import unittest

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")


FORBIDDEN = (
    "scripts/app.js",
    "scripts/charts.js",
    "index.html",
    "portfolio.py",
    "scripts/spy_rs.js",
    "scripts/setup_scanner.js",
    "tests/test_focus_chrome.py",
    "styles/main.css",
)


class FocusChromeDensityTests(unittest.TestCase):
    """Focus (f) hides extra chrome; Scan list and Review drawers stay."""

    @classmethod
    def setUpClass(cls):
        with open("scripts/app.js", encoding="utf-8") as fh:
            cls.app_js = fh.read()
        with open("styles/main.css", encoding="utf-8") as fh:
            cls.css = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            cls.html = fh.read()

    def test_body_class_toggle_and_aria_pressed(self):
        js = self.app_js
        self.assertIn("function toggleFocusMode", js)
        self.assertIn("document.body.classList.toggle('focus-mode', on)", js)
        self.assertIn("setPressed(document.getElementById('pill-focus'), on)", js)
        self.assertIn("window.resizeAllCharts?.()", js)
        self.assertIn("window.toggleFocusMode = toggleFocusMode", js)
        self.assertIn("e.key === 'f'", js)
        self.assertIn("toggleFocusMode()", js)

        html = self.html
        self.assertIn('id="pill-focus"', html)
        idx = html.index('id="pill-focus"')
        snippet = html[idx : idx + 220]
        self.assertIn('aria-pressed="false"', snippet)
        self.assertIn('id="focus-mode-chip"', html)
        self.assertIn("class=\"workspace-chart\"", html)
        self.assertIn("function setPressed", js)
        self.assertIn("aria-pressed", js)

    def test_css_chart_workspace_hides_tape_heatmap_book_extra_nav(self):
        css = self.css
        self.assertIn("body.focus-mode #portfolio-tape", css)
        self.assertIn(".focus-mode #portfolio-tape { display: none !important; }", css)
        self.assertIn("body.focus-mode.workspace-chart #book-drawer", css)
        self.assertIn("body.focus-mode.workspace-chart #journal-drawer", css)
        self.assertIn("body.focus-mode.workspace-chart #regime-heatmap", css)
        self.assertIn("body.focus-mode.workspace-chart #alert-log", css)
        self.assertIn("body.focus-mode:not(.workspace-review) #book-drawer", css)
        self.assertIn("body.focus-mode:not(.workspace-review) #regime-heatmap", css)
        self.assertIn("body.focus-mode:not(.workspace-review) #alert-log", css)
        self.assertIn("body.focus-mode:not(.workspace-review) .main-nav-tabs > .tab-btn", css)
        self.assertIn("body.focus-mode.workspace-chart .main-nav-tabs > .tab-btn", css)
        self.assertIn("body.focus-mode.workspace-chart #chart-area", css)
        self.assertIn("body.focus-mode:not(.workspace-review) #pm-desk", css)
        self.assertIn("display: none !important", css)

    def test_css_scan_keeps_setup_table(self):
        css = self.css
        self.assertIn("body.focus-mode.workspace-scan #scanner-area", css)
        self.assertIn("body.focus-mode.workspace-scan .setup-scanner-panel", css)
        self.assertIn("body.focus-mode.workspace-scan #chart-area", css)
        scan_keep = css[css.index("body.focus-mode.workspace-scan #scanner-area") :]
        block = scan_keep.split("}", 1)[0]
        self.assertIn("display: flex !important", block)
        self.assertNotIn(
            "body.focus-mode.workspace-scan #scanner-area { display: none",
            css.replace("\n", " "),
        )
        self.assertIn("body.focus-mode.workspace-scan #book-drawer", css)
        self.assertIn("body.focus-mode.workspace-scan .main-nav-tabs > .tab-btn", css)

    def test_css_review_keeps_news_journal_book(self):
        css = self.css
        self.assertIn("body.focus-mode.workspace-review #book-drawer", css)
        self.assertIn("body.focus-mode.workspace-review #journal-drawer", css)
        self.assertIn("body.focus-mode.workspace-review #regime-heatmap", css)
        self.assertIn("body.focus-mode.workspace-review #alert-log", css)
        review_book = css[css.index("body.focus-mode.workspace-review #book-drawer") :]
        review_block = review_book.split("}", 1)[0]
        self.assertIn("display: flex !important", review_block)
        self.assertNotRegex(
            css,
            r"body\.focus-mode\.workspace-review #book-drawer[^}]*display:\s*none",
        )
        self.assertNotRegex(
            css,
            r"body\.focus-mode\.workspace-review #journal-drawer[^}]*display:\s*none",
        )
        self.assertNotRegex(
            css,
            r"body\.focus-mode\.workspace-review #news-area[^}]*display:\s*none",
        )
        self.assertIn(":not(.workspace-review)", css)

    def test_overlay_strip_pills_legend_stay_reachable(self):
        css, html = self.css, self.html
        self.assertIn("body.focus-mode:not(.workspace-review) #chart-overlays-bar", css)
        self.assertIn("body.focus-mode.workspace-chart #chart-overlays-bar", css)
        self.assertIn("body.focus-mode.workspace-scan #chart-overlays-bar", css)
        overlays = css[css.index("body.focus-mode.workspace-chart #chart-overlays-bar") :]
        overlay_block = overlays.split("}", 1)[0]
        self.assertIn("display: flex !important", overlay_block)
        self.assertIn('id="chart-overlays-bar"', html)
        self.assertIn('id="pill-spy-rs"', html)
        self.assertIn('id="pill-pane-rsi"', html)
        self.assertIn('id="pill-pane-macd"', html)
        self.assertIn('id="pill-pane-trend"', html)
        self.assertIn('id="pill-pack-minervini"', html)
        self.assertIn('id="pill-pack-stockbee"', html)
        self.assertIn('id="pill-pack-weinstein"', html)
        self.assertIn('id="chart-legend-daily"', html)
        self.assertIn('id="chart-legend-weekly"', html)
        self.assertIn('id="pill-focus"', html)

    def test_no_new_workspace_and_toggle_restores(self):
        html, js = self.html, self.app_js
        self.assertEqual(html.count('data-workspace="chart"'), 1)
        self.assertEqual(html.count('data-workspace="scan"'), 1)
        self.assertEqual(html.count('data-workspace="review"'), 1)
        self.assertNotIn("data-workspace=\"focus\"", html)
        self.assertNotIn("workspace-focus", js)
        self.assertNotIn("workspace-focus", self.css)
        self.assertIn("classList.toggle('focus-mode', on)", js)
        self.assertIn("function setWorkspace", js)
        self.assertIn("workspace-scan", js)
        self.assertIn("workspace-review", js)
        self.assertIn("workspace-chart", js)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")


if __name__ == "__main__":
    unittest.main()
