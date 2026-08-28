"""Contract tests for Yahoo throttle auto-retry (backoff + cancel on ticker change)."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

FORBIDDEN_IBD = (
    "scripts/app.js",
    "scripts/charts.js",
    "index.html",
    "portfolio.py",
    "scripts/spy_rs.js",
    "scripts/setup_scanner.js",
)

_NODE_RETRY_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
const start = src.indexOf('const YAHOO_THROTTLE_AUTO_RETRY_DELAYS_MS');
const end = src.indexOf('function paintYahooThrottleMessage');
if (start < 0 || end < 0 || end <= start) {
    throw new Error('could not extract throttle auto-retry helpers');
}
const slice = src.slice(start, end);
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(
    slice + `
this.YAHOO_THROTTLE_AUTO_RETRY_DELAYS_MS = YAHOO_THROTTLE_AUTO_RETRY_DELAYS_MS;
this.YAHOO_THROTTLE_AUTO_RETRY_MAX = YAHOO_THROTTLE_AUTO_RETRY_MAX;
this.YAHOO_THROTTLE_AUTO_RETRY_JITTER = YAHOO_THROTTLE_AUTO_RETRY_JITTER;
this.yahooThrottleRetryDelayMs = yahooThrottleRetryDelayMs;
this.yahooThrottleShouldCancelOnTickerChange = yahooThrottleShouldCancelOnTickerChange;
this.yahooThrottleAutoRetriesRemain = yahooThrottleAutoRetriesRemain;
this.cancelYahooThrottleAutoRetry = cancelYahooThrottleAutoRetry;
this.getRetryGen = () => _yahooThrottleRetryGen;
this.getRetrySymbol = () => _yahooThrottleRetrySymbol;
this.getRetryAttempt = () => _yahooThrottleRetryAttempt;
this.setRetrySymbol = (s) => { _yahooThrottleRetrySymbol = s; };
`,
    sandbox
);

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

assert(Array.isArray(sandbox.YAHOO_THROTTLE_AUTO_RETRY_DELAYS_MS), 'delays array');
assert(sandbox.YAHOO_THROTTLE_AUTO_RETRY_DELAYS_MS.length === 2, 'two backoff steps');
assert(sandbox.YAHOO_THROTTLE_AUTO_RETRY_DELAYS_MS[0] === 4000, 'first wait 4s');
assert(sandbox.YAHOO_THROTTLE_AUTO_RETRY_DELAYS_MS[1] === 12000, 'second wait 12s');
assert(sandbox.YAHOO_THROTTLE_AUTO_RETRY_MAX === 2, 'max 2 auto retries');
assert(sandbox.YAHOO_THROTTLE_AUTO_RETRY_DELAYS_MS.length === sandbox.YAHOO_THROTTLE_AUTO_RETRY_MAX, 'delays match max');

assert(sandbox.yahooThrottleRetryDelayMs(0, 0.5) === 4000, 'no-jitter first delay');
assert(sandbox.yahooThrottleRetryDelayMs(1, 0.5) === 12000, 'no-jitter second delay');
assert(sandbox.yahooThrottleRetryDelayMs(0, 0) === 3200, 'jitter low 4s');
assert(sandbox.yahooThrottleRetryDelayMs(0, 1) === 4800, 'jitter high 4s');
assert(sandbox.yahooThrottleRetryDelayMs(1, 0) === 9600, 'jitter low 12s');
assert(sandbox.yahooThrottleRetryDelayMs(1, 1) === 14400, 'jitter high 12s');

assert(sandbox.yahooThrottleShouldCancelOnTickerChange(null, 'MSFT') === false, 'nothing pending');
assert(sandbox.yahooThrottleShouldCancelOnTickerChange('', 'MSFT') === false, 'empty pending');
assert(sandbox.yahooThrottleShouldCancelOnTickerChange('AAPL', 'MSFT') === true, 'ticker change cancels');
assert(sandbox.yahooThrottleShouldCancelOnTickerChange('AAPL', 'aapl') === false, 'same ticker case-insensitive');
assert(sandbox.yahooThrottleShouldCancelOnTickerChange('AAPL', 'AAPL') === false, 'same ticker');

assert(sandbox.yahooThrottleAutoRetriesRemain(0) === true, 'attempt 0 remains');
assert(sandbox.yahooThrottleAutoRetriesRemain(1) === true, 'attempt 1 remains');
assert(sandbox.yahooThrottleAutoRetriesRemain(2) === false, 'attempt 2 exhausted');

sandbox.setRetrySymbol('AAPL');
const gen0 = sandbox.getRetryGen();
sandbox.cancelYahooThrottleAutoRetry();
assert(sandbox.getRetryGen() === gen0 + 1, 'cancel bumps generation so pending timers no-op');
assert(sandbox.getRetrySymbol() === null, 'cancel clears retry symbol');
assert(sandbox.getRetryAttempt() === 0, 'cancel resets attempt');

process.stdout.write(JSON.stringify({ ok: true }));
"""


def _fn_chunk(src, header, nbytes=900):
    idx = src.index(header)
    return src[idx : idx + nbytes]


class YahooThrottleAutoRetryContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "scripts", "app.js"), encoding="utf-8") as fh:
            cls.app_js = fh.read()
        with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as fh:
            cls.html = fh.read()

    def test_backoff_constants_and_max_two_retries(self):
        js = self.app_js
        self.assertIn("const YAHOO_THROTTLE_AUTO_RETRY_DELAYS_MS = [4000, 12000]", js)
        self.assertIn("const YAHOO_THROTTLE_AUTO_RETRY_MAX = 2", js)
        self.assertIn("function yahooThrottleRetryDelayMs", js)
        self.assertIn("function yahooThrottleAutoRetriesRemain", js)
        self.assertIn("function scheduleYahooThrottleAutoRetry", js)
        self.assertIn("function armYahooThrottleAutoRetry", js)
        self.assertIn("Retrying in ${secondsLeft}s.", js)
        show = _fn_chunk(js, "function showYahooThrottleBanner")
        self.assertIn("scheduleYahooThrottleAutoRetry", show)

    def test_cancel_on_ticker_change_and_manual_retry(self):
        js = self.app_js
        self.assertIn("function cancelYahooThrottleAutoRetry", js)
        self.assertIn("function yahooThrottleShouldCancelOnTickerChange", js)
        select = _fn_chunk(js, "async function selectSymbol")
        self.assertIn("yahooThrottleShouldCancelOnTickerChange(_yahooThrottleRetrySymbol, symbol)", select)
        self.assertIn("cancelYahooThrottleAutoRetry()", select)
        retry = _fn_chunk(js, "async function retryYahooFetch")
        self.assertIn("if (!auto) cancelYahooThrottleAutoRetry()", retry)
        self.assertIn("opts.auto === true", retry)

    def test_prefetch_stays_skipped_after_429(self):
        js = self.app_js
        self.assertIn("Skip prefetch after a 429 so we do not pile onto Yahoo.", js)
        prefetch = _fn_chunk(js, "function scheduleNeighborPrefetch")
        self.assertIn("isYahooThrottle(lastFetchError)", prefetch)
        self.assertIn("return;", prefetch)

    def test_banner_keeps_manual_retry(self):
        html = self.html
        self.assertIn('id="yahoo-throttle-banner"', html)
        self.assertIn('id="btn-yahoo-retry"', html)
        self.assertIn("Retry fetch", html)
        self.assertIn('id="yahoo-throttle-message"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("btn-yahoo-retry", self.app_js)
        self.assertIn("retryYahooFetch", self.app_js)

    def test_forbidden_files_have_no_ibd_substring(self):
        for rel in FORBIDDEN_IBD:
            with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
                blob = fh.read()
            self.assertIsNone(
                re.search(r"ibd", blob, re.IGNORECASE),
                msg=f"{rel} must not contain the IBD substring",
            )

    def test_helpers_backoff_and_cancel_in_node(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        src = os.path.join(ROOT, "scripts", "app.js")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_RETRY_SCRIPT)
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


if __name__ == "__main__":
    unittest.main()
