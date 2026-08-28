import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


_NODE_BUILDER_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
global.document = { getElementById: () => null, addEventListener: () => {} };
vm.runInThisContext(src, { filename: 'news_markers.js' });
if (typeof buildNewsPriceMarkers !== 'function') {
    throw new Error('buildNewsPriceMarkers not defined');
}

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

const rows = [
    { date: '2026-08-18' },
    { date: '2026-08-19' },
    { date: '2026-08-20' },
    { date: '2026-08-21' },
];

const off = buildNewsPriceMarkers(
    [{ title: 'Apple hits high', publish_time: '2026-08-21T14:00:00Z' }],
    rows,
    false
);
assert(Array.isArray(off) && off.length === 0, 'off must return []');

const weekend = buildNewsPriceMarkers([
    { title: 'Weekend note', publish_time: '2026-08-22T15:00:00Z' },
    { title: 'Apple hits high', publish_time: '2026-08-21T14:00:00Z' },
], rows, true);
assert(weekend.length === 1, 'skip dates with no daily bar, got ' + weekend.length);
assert(weekend[0].time === '2026-08-21', 'land on matching bar, got ' + weekend[0].time);
assert(weekend[0].shape === 'circle', 'shape');
assert(weekend[0].position === 'belowBar', 'position');
assert(weekend[0].text === 'N', 'headline letter');
assert(weekend[0].color === '#c4b5fd', 'headline color');
assert(weekend[0].color !== '#fde047', 'must not use EP yellow');

const earn = buildNewsPriceMarkers([
    { title: 'Company reports quarterly earnings', publish_time: '2026-08-20T12:00:00Z' },
    { title: 'Street reacts to results', publish_time: '2026-08-20T18:00:00Z' },
], rows, true);
assert(earn.length === 1, 'collapse same bar');
assert(earn[0].text === 'E', 'earnings letter');
assert(earn[0].color === '#fb7185', 'earnings color');
assert(earn[0].time === '2026-08-20', 'earnings bar');

const many = [];
for (let i = 1; i <= 20; i++) {
    const day = String(i).padStart(2, '0');
    many.push({ title: 'Headline ' + i, publish_time: '2026-08-' + day + 'T12:00:00Z' });
}
const manyRows = [];
for (let i = 1; i <= 28; i++) {
    manyRows.push({ date: '2026-08-' + String(i).padStart(2, '0') });
}
const capped = buildNewsPriceMarkers(many, manyRows, true);
assert(capped.length === 12, 'cap 12, got ' + capped.length);
assert(capped[0].time === '2026-08-09', 'oldest of cap, got ' + capped[0].time);
assert(capped[capped.length - 1].time === '2026-08-20', 'newest of cap');

const nodate = buildNewsPriceMarkers(
    [{ title: 'No clock', publish_time: '' }, { title: 'Bad date', publish_time: 'not-a-date' }],
    rows,
    true
);
assert(nodate.length === 0, 'unparseable dates skipped');

process.stdout.write(JSON.stringify({ ok: true, n: capped.length }));
"""


class NewsMarkerBuilderTests(unittest.TestCase):
    def test_builder_cap_bar_match_and_earnings(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        src = os.path.join(ROOT, "scripts", "news_markers.js")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_BUILDER_SCRIPT)
            runner = fh.name
        try:
            proc = subprocess.run(
                [node, runner, src],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            os.unlink(runner)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["n"], 12)


_NODE_JUMP_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const markersSrc = fs.readFileSync(process.argv[2], 'utf8');
const chartsSrc = fs.readFileSync(process.argv[3], 'utf8');

global.document = {
    getElementById: () => null,
    addEventListener: () => {},
    querySelectorAll: () => [],
};
global.window = global;
global.localStorage = { getItem: () => null, setItem: () => {} };
global.ResizeObserver = class { observe() {} disconnect() {} };
global.LightweightCharts = {
    LineStyle: { Solid: 0, Dashed: 1, LargeDashed: 2 },
    ColorType: { Solid: 0 },
    createChart: () => null,
};

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

vm.runInThisContext(markersSrc, { filename: 'news_markers.js' });
vm.runInThisContext(chartsSrc, { filename: 'charts.js' });

assert(typeof newsDateKey === 'function', 'newsDateKey missing');
assert(typeof dailyBarIndexForDate === 'function', 'dailyBarIndexForDate missing');
assert(typeof scrollDailyToDate === 'function', 'scrollDailyToDate missing');

const rows = [
    { date: '2026-08-18' },
    { date: '2026-08-19' },
    { date: '2026-08-20' },
    { date: '2026-08-21' },
];

const key = newsDateKey('2026-08-21T14:00:00Z');
assert(key === '2026-08-21', 'NY/UTC date key, got ' + key);
assert(dailyBarIndexForDate(key, rows) === 3, 'matching bar index');

const weekend = newsDateKey('2026-08-22T15:00:00Z');
assert(weekend === '2026-08-22', 'weekend key, got ' + weekend);
assert(dailyBarIndexForDate(weekend, rows) === -1, 'weekend is a miss');
assert(dailyBarIndexForDate('', rows) === -1, 'empty key miss');
assert(dailyBarIndexForDate(null, rows) === -1, 'null key miss');

const unixKey = newsDateKey(Date.parse('2026-08-20T16:00:00Z') / 1000);
assert(unixKey === '2026-08-20', 'unix seconds NY key, got ' + unixKey);
assert(dailyBarIndexForDate(unixKey, rows) === 2, 'unix-derived bar');

assert(scrollDailyToDate(key, rows) === false, 'no live chart → false, not a throw');

process.stdout.write(JSON.stringify({ ok: true, key: key, weekend: weekend }));
"""


class NewsHeadlineJumpBarTests(unittest.TestCase):
    """Click this-ticker headline → scroll daily pane to that NY date's bar."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "scripts", "app.js"), encoding="utf-8") as fh:
            cls.app_js = fh.read()
        with open(os.path.join(ROOT, "scripts", "charts.js"), encoding="utf-8") as fh:
            cls.charts = fh.read()
        with open(os.path.join(ROOT, "scripts", "news_markers.js"), encoding="utf-8") as fh:
            cls.news_js = fh.read()
        cls.forbidden = [
            "scripts/app.js",
            "scripts/charts.js",
            "index.html",
            "portfolio.py",
            "scripts/spy_rs.js",
            "scripts/setup_scanner.js",
            "scripts/news_markers.js",
        ]

    def _handler_body(self):
        js = self.app_js
        start = js.index("function onThisTickerNewsClick")
        end = js.index("async function loadChartData", start)
        return js[start:end]

    def test_click_handler_reuses_news_date_key(self):
        body = self._handler_body()
        self.assertIn("function onThisTickerNewsClick", self.app_js)
        self.assertIn("onThisTickerNewsClick(article)", self.app_js)
        self.assertIn("newsDateKey(", body)
        self.assertIn("article && article.publish_time", body)
        self.assertIn("scrollDailyToDate", body)
        self.assertIn("dailyBarIndexForDate", body)
        self.assertIn("No matching daily bar for that headline", self.app_js)
        self.assertIn("function revealDailyChartKeepingWorkspace", self.app_js)
        self.assertNotIn("setWorkspace(", body)
        reveal = self.app_js[
            self.app_js.index("function revealDailyChartKeepingWorkspace")
            : self.app_js.index("function onThisTickerNewsClick")
        ]
        self.assertNotIn("setWorkspace(", reveal)
        self.assertIn("typeof newsDateKey === 'function'", body)
        self.assertNotIn("toISOString().slice(0, 10)", body)

    def test_scroll_hook_set_visible_range(self):
        charts = self.charts
        self.assertIn("function scrollDailyToDate", charts)
        self.assertIn("function dailyBarIndexForDate", charts)
        self.assertIn("window.scrollDailyToDate = scrollDailyToDate", charts)
        fn_start = charts.index("function scrollDailyToDate")
        fn_end = charts.index("function setupFitAllOnDoubleClick", fn_start)
        hook = charts[fn_start:fn_end]
        self.assertIn("setVisibleRange", hook)
        self.assertIn("scrollToPosition", hook)
        self.assertIn("setVisibleLogicalRange", hook)
        self.assertIn("rawRows.daily", hook)
        self.assertIn("dailyBarIndexForDate", hook)
        self.assertIn("DAILY_DEFAULT_BARS", hook)

    def test_render_news_wires_named_click_handler(self):
        js = self.app_js
        render_start = js.index("function renderNews")
        render_end = js.index("function _newsJumpMiss", render_start)
        render = js[render_start:render_end]
        self.assertIn("onThisTickerNewsClick(article)", render)
        self.assertIn("Jump daily chart to this headline date", render)
        self.assertIn("ev.metaKey || ev.ctrlKey", render)
        self.assertIn("newsDateKey", self.news_js)

    def test_workspace_stays_put(self):
        reveal = self.app_js[
            self.app_js.index("function revealDailyChartKeepingWorkspace")
            : self.app_js.index("function onThisTickerNewsClick")
        ]
        self.assertIn("never call setWorkspace", reveal)
        self.assertIn("showChartArea", reveal)
        self.assertNotIn("setWorkspace(", reveal)
        self.assertIn("state.workspace === 'scan'", reveal)

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in self.forbidden:
            with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")

    def test_news_date_key_matches_daily_bar_index(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        markers = os.path.join(ROOT, "scripts", "news_markers.js")
        charts = os.path.join(ROOT, "scripts", "charts.js")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_JUMP_SCRIPT)
            runner = fh.name
        try:
            proc = subprocess.run(
                [node, runner, markers, charts],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            os.unlink(runner)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["key"], "2026-08-21")
        self.assertEqual(payload["weekend"], "2026-08-22")
