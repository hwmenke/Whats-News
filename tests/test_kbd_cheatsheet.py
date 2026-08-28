"""Contract tests: ? cheatsheet lists existing hotkeys that were missing."""

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
    "tests/test_kbd_cheatsheet.py",
)


def _read(rel):
    with open(rel, encoding="utf-8") as fh:
        return fh.read()


def _kbd_help(html):
    start = html.index('id="kbd-help"')
    return html[start:].split("</dl>", 1)[0]


def _help_rows(kbd):
    return re.findall(r"<div><dt>(.*?)</dt><dd>(.*?)</dd></div>", kbd, re.S)


def _dd_for_kbd(kbd, needle):
    for dt, dd in _help_rows(kbd):
        if needle in dt:
            return dt, dd
    return None, None


class KbdCheatsheetTests(unittest.TestCase):
    """#kbd-help documents real shortcuts; no invented hotkeys."""

    @classmethod
    def setUpClass(cls):
        cls.html = _read("index.html")
        cls.app_js = _read("scripts/app.js")
        cls.css = _read("styles/main.css")
        cls.alerts = _read("scripts/price_alerts.js")
        cls.kbd = _kbd_help(cls.html)

    def test_missing_keys_appear_in_kbd_help(self):
        kbd = self.kbd
        self.assertIn('id="kbd-help"', kbd)

        y_dt, y_dd = _dd_for_kbd(kbd, "<kbd>y</kbd>")
        self.assertIsNotNone(y_dt)
        self.assertIn("Copy painted OHLC", y_dd)

        dot_dt, dot_dd = _dd_for_kbd(kbd, "<kbd>.</kbd>")
        self.assertIsNotNone(dot_dt)
        self.assertIn("Jump to latest bar", dot_dd)

        one_dt, one_dd = _dd_for_kbd(kbd, "<kbd>1</kbd>")
        self.assertIsNotNone(one_dt)
        self.assertIn("<kbd>2</kbd>", one_dt)
        self.assertIn("<kbd>3</kbd>", one_dt)
        self.assertIn("workspace", one_dd.lower())

        shift_j_dt, shift_j_dd = _dd_for_kbd(kbd, "⇧J")
        self.assertIsNotNone(shift_j_dt)
        self.assertIn("journal", shift_j_dd.lower())

        click_dt, click_dd = _dd_for_kbd(kbd, "⇧-click")
        self.assertIsNotNone(click_dt)
        self.assertIn("Note:", click_dd)
        self.assertIn("alert", click_dd.lower())

        slash_dt, slash_dd = _dd_for_kbd(kbd, "<kbd>/</kbd>")
        self.assertIsNotNone(slash_dt)
        self.assertIn("Jump palette", slash_dd)

    def test_cheatsheet_stays_compact(self):
        rows = _help_rows(self.kbd)
        self.assertGreaterEqual(len(rows), 12)
        self.assertLessEqual(len(rows), 16)
        for dt, dd in rows:
            self.assertLessEqual(len(re.sub(r"<[^>]+>", "", dd).strip()), 64)

        css = self.css
        help_css = css[css.index(".kbd-help-list {") :]
        help_css = help_css.split(".desk-palette-input", 1)[0]
        self.assertIn("grid-template-columns: max-content 1fr", help_css)
        self.assertIn("flex-wrap: nowrap", help_css)
        self.assertNotIn("grid-template-columns: 88px", help_css)

    def test_documented_hotkeys_already_exist(self):
        kb = self.app_js[self.app_js.index("function setupPmKeyboard") :]
        kb = kb.split("// ── KNN Functions", 1)[0]
        self.assertIn("e.key === 'y'", kb)
        self.assertIn("copyPaintedOhlc()", kb)
        self.assertIn("e.key === '.'", kb)
        self.assertIn("scrollToLatestBar()", kb)
        self.assertIn("e.key === '1'", kb)
        self.assertIn("e.key === '2'", kb)
        self.assertIn("e.key === '3'", kb)
        self.assertIn("setWorkspace", kb)
        self.assertIn("e.shiftKey && (e.key === 'J'", kb)
        self.assertIn("toggleJournal()", kb)
        self.assertIn("e.key === '/' && !e.shiftKey", kb)
        self.assertIn("openDeskPalette('jump')", kb)
        self.assertIn("Shift+click", self.alerts)
        self.assertIn("createPriceLine", self.alerts)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            text = _read(path)
            self.assertIsNone(
                needle.search(text),
                msg=f"{path} must not contain that rating brand",
            )


if __name__ == "__main__":
    unittest.main()
