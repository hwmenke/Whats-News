"""Contract tests: `.` jumps daily/weekly panes to the latest bar."""

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
    "tests/test_jump_latest_bar.py",
)


class JumpLatestBarHotkeyTests(unittest.TestCase):
    """Period key restores the default ~126-session daily fit at the right edge."""

    @classmethod
    def setUpClass(cls):
        with open("scripts/charts.js", encoding="utf-8") as fh:
            cls.charts = fh.read()
        with open("scripts/app.js", encoding="utf-8") as fh:
            cls.app_js = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            cls.html = fh.read()

    def test_helper_name_restores_default_daily_window(self):
        charts = self.charts
        self.assertIn("function scrollToLatestBar", charts)
        self.assertIn("window.scrollToLatestBar = scrollToLatestBar", charts)
        self.assertIn("const DAILY_DEFAULT_BARS = 126", charts)
        helper = charts[charts.index("function scrollToLatestBar") :]
        helper = helper.split("function setupFitAllOnDoubleClick", 1)[0]
        self.assertIn("scrollToRealTime()", helper)
        self.assertIn("DAILY_DEFAULT_BARS", helper)
        self.assertIn("WEEKLY_DEFAULT_BARS", helper)
        self.assertIn("_fitPaneToBars(charts.daily.main, dailyN, DAILY_DEFAULT_BARS)", helper)
        self.assertIn("_fitPaneToBars(charts.weekly.main, weeklyN, WEEKLY_DEFAULT_BARS)", helper)
        self.assertIn("latest bar", helper.lower())
        self.assertNotIn("function fitAllContent", helper)

    def test_hotkey_period_in_setup_pm_keyboard(self):
        app_js = self.app_js
        self.assertIn("function setupPmKeyboard", app_js)
        kb = app_js[app_js.index("function setupPmKeyboard") :]
        kb = kb.split("// ── KNN Functions", 1)[0]
        self.assertIn("e.key === '.'", kb)
        self.assertIn("scrollToLatestBar()", kb)
        y_at = kb.index("e.key === 'y'")
        dot_at = kb.index("e.key === '.'")
        self.assertGreater(dot_at, y_at)
        self.assertNotIn("scrollToLatestBar()", kb[kb.index("e.key === 'c'") : kb.index("e.key === 'c'") + 120])

    def test_cheatsheet_line(self):
        html = self.html
        self.assertIn("<kbd>.</kbd>", html)
        self.assertIn("Jump to latest bar (restore ~126-session daily window)", html)
        kbd = html[html.index('id="kbd-help"') :]
        kbd = kbd.split("</dl>", 1)[0]
        self.assertIn("<kbd>.</kbd>", kbd)
        self.assertLess(kbd.index("<kbd>y</kbd>"), kbd.index("<kbd>.</kbd>"))
        self.assertLess(kbd.index("<kbd>.</kbd>"), kbd.index("<kbd>?</kbd>"))

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")


if __name__ == "__main__":
    unittest.main()
