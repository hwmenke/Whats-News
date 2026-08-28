"""Contract tests for Focus mode chrome density (body class + workspace CSS)."""

import json
import os
import re
import subprocess
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
        self.assertIn('id="pill-vwap"', html)
        self.assertIn('id="pill-last"', html)
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


class FocusModePersistenceTests(unittest.TestCase):
    """Focus (f) survives reload via localStorage; independent of last workspace."""

    @classmethod
    def setUpClass(cls):
        with open("scripts/app.js", encoding="utf-8") as fh:
            cls.app_js = fh.read()
        with open("index.html", encoding="utf-8") as fh:
            cls.html = fh.read()

    def test_storage_key_persist_and_restore_after_workspace(self):
        js = self.app_js
        self.assertIn("FOCUS_MODE_KEY = 'whats-news-focus-mode'", js)
        self.assertIn("whats-news-focus-mode", js)
        self.assertIn("whats-news-workspace", js)
        self.assertIn("function toggleFocusMode", js)
        self.assertIn("function restoreFocusMode", js)
        self.assertIn("localStorage.setItem(FOCUS_MODE_KEY, on ? '1' : '0')", js)
        self.assertIn("localStorage.getItem(FOCUS_MODE_KEY)", js)
        self.assertIn("toggleFocusMode(true, { silent: true })", js)
        self.assertIn("restoreFocusMode()", js)

        toggle = js[js.index("function toggleFocusMode") : js.index("function restoreFocusMode")]
        self.assertIn("localStorage.setItem(FOCUS_MODE_KEY", toggle)
        self.assertIn("setPressed(document.getElementById('pill-focus'), on)", toggle)
        self.assertIn("classList.toggle('focus-mode', on)", toggle)

        restore = js[js.index("function restoreFocusMode") : js.index("window.toggleFocusMode")]
        self.assertIn("getItem(FOCUS_MODE_KEY)", restore)
        self.assertIn("saved === '1'", restore)
        self.assertNotIn("WORKSPACE_KEY", restore)
        self.assertNotIn("getItem(WORKSPACE_KEY)", restore)
        self.assertNotIn("setWorkspace", restore)
        self.assertNotIn("sessionStorage", restore)

        boot = js[js.index("document.addEventListener('DOMContentLoaded'") :]
        self.assertIn("restoreFocusMode()", boot)
        self.assertIn("setWorkspace('scan', { skipChart: true })", boot)
        self.assertLess(
            boot.index("if (ws === 'scan') setWorkspace('scan', { skipChart: true })"),
            boot.index("restoreFocusMode()"),
        )
        self.assertGreater(boot.index("restoreFocusMode()"), boot.index("showEmptyState()"))

        html = self.html
        idx = html.index('id="pill-focus"')
        snippet = html[idx : idx + 220]
        self.assertIn('aria-pressed="false"', snippet)

        with open("scripts/setup_scanner.js", encoding="utf-8") as fh:
            self.assertNotIn("whats-news-focus-mode", fh.read())
        with open("scripts/charts.js", encoding="utf-8") as fh:
            self.assertNotIn("whats-news-focus-mode", fh.read())

    def test_reload_restores_focus_chrome_and_aria_pressed(self):
        js = self.app_js
        set_pressed = js[js.index("function setPressed") : js.index("function setTapeMode")]
        toggle = js[js.index("function toggleFocusMode") : js.index("function isKbdHelpOpen")]
        script = r"""
const FOCUS_MODE_KEY = 'whats-news-focus-mode';
const WORKSPACE_KEY = 'whats-news-workspace';
let localStorage, document, window, toast, pill, chip, toasts, resized;

function makeStore(seed) {
    const data = Object.assign({}, seed || {});
    return {
        data,
        getItem(key) { return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null; },
        setItem(key, val) { data[key] = String(val); },
        removeItem(key) { delete data[key]; },
    };
}

function makeClassList() {
    const classes = new Set();
    return {
        contains(name) { return classes.has(name); },
        add(name) { classes.add(name); },
        remove(name) { classes.delete(name); },
        toggle(name, on) {
            if (on === undefined) {
                if (classes.has(name)) classes.delete(name); else classes.add(name);
                return classes.has(name);
            }
            if (on) classes.add(name); else classes.delete(name);
            return !!on;
        },
    };
}

function installDesk(store) {
    localStorage = store;
    toasts = [];
    resized = 0;
    const pillAttrs = { 'aria-pressed': 'false' };
    pill = {
        classList: makeClassList(),
        setAttribute(k, v) { pillAttrs[k] = String(v); },
        getAttribute(k) { return Object.prototype.hasOwnProperty.call(pillAttrs, k) ? pillAttrs[k] : null; },
    };
    chip = { hidden: true };
    document = {
        body: { classList: makeClassList() },
        getElementById(id) {
            if (id === 'pill-focus') return pill;
            if (id === 'focus-mode-chip') return chip;
            return null;
        },
    };
    window = { resizeAllCharts() { resized += 1; } };
    toast = (msg) => { toasts.push(String(msg)); };
}

installDesk(makeStore());
""" + set_pressed + toggle + r"""
restoreFocusMode();
if (document.body.classList.contains('focus-mode')) throw new Error('empty storage must not turn focus on');
if (localStorage.getItem(FOCUS_MODE_KEY) !== null) throw new Error('restore must not create the focus key');
if (pill.getAttribute('aria-pressed') !== 'false') throw new Error('empty restore must leave aria-pressed false');
if (toasts.length) throw new Error('empty restore must not toast');

toggleFocusMode();
if (localStorage.getItem(FOCUS_MODE_KEY) !== '1') throw new Error('toggle on must persist 1');
if (!document.body.classList.contains('focus-mode')) throw new Error('toggle on must set body class');
if (pill.getAttribute('aria-pressed') !== 'true') throw new Error('toggle on must set aria-pressed true');
if (chip.hidden) throw new Error('toggle on must show chip');
if (!toasts.length) throw new Error('user toggle must toast');
if (resized < 1) throw new Error('toggle must resize charts');
if (localStorage.getItem(WORKSPACE_KEY) != null) throw new Error('focus persist must not write workspace key');

const saved = Object.assign({}, localStorage.data);
installDesk(makeStore(saved));
restoreFocusMode();
if (!document.body.classList.contains('focus-mode')) throw new Error('reload must restore focus-mode');
if (pill.getAttribute('aria-pressed') !== 'true') throw new Error('reload aria-pressed must match on');
if (chip.hidden) throw new Error('reload must show focus chip');
if (toasts.length) throw new Error('restore must be silent');

toggleFocusMode();
if (document.body.classList.contains('focus-mode')) throw new Error('second toggle must turn off');
if (pill.getAttribute('aria-pressed') !== 'false') throw new Error('toggle off aria-pressed false');
if (!chip.hidden) throw new Error('toggle off must hide chip');
if (localStorage.getItem(FOCUS_MODE_KEY) !== '0') throw new Error('toggle off must persist 0');

installDesk(makeStore({ [FOCUS_MODE_KEY]: '0', [WORKSPACE_KEY]: 'scan' }));
restoreFocusMode();
if (document.body.classList.contains('focus-mode')) throw new Error('saved 0 must not restore focus');
if (pill.getAttribute('aria-pressed') !== 'false') throw new Error('saved 0 aria-pressed false');

const reviewStore = makeStore({ [FOCUS_MODE_KEY]: '1', [WORKSPACE_KEY]: 'chart' });
installDesk(reviewStore);
restoreFocusMode();
if (!document.body.classList.contains('focus-mode')) throw new Error('focus restores independently of workspace');
if (pill.getAttribute('aria-pressed') !== 'true') throw new Error('review-or-chart restore aria-pressed true');
if (reviewStore.getItem(WORKSPACE_KEY) !== 'chart') throw new Error('restore must not rewrite workspace');

process.stdout.write(JSON.stringify({
    ok: true,
    key: FOCUS_MODE_KEY,
    restored: true,
    aria: pill.getAttribute('aria-pressed'),
}));
"""
        proc = subprocess.run(
            ["node", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["key"], "whats-news-focus-mode")
        self.assertTrue(payload["restored"])
        self.assertEqual(payload["aria"], "true")


if __name__ == "__main__":
    unittest.main()
