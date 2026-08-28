import json
import os
import shutil
import subprocess
import tempfile
import unittest

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


_NODE_BUILDER_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const ctx = {
    document: { getElementById: () => null, addEventListener: () => {} },
    console,
};
vm.createContext(ctx);
vm.runInContext(src, ctx);
if (typeof ctx.buildNewsPriceMarkers !== 'function') {
    throw new Error('buildNewsPriceMarkers not on vm context');
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

assert.deep = (a, b, msg) => assert(JSON.stringify(a) === JSON.stringify(b), msg);

const off = ctx.buildNewsPriceMarkers(
    [{ title: 'Apple hits high', publish_time: '2026-08-21T14:00:00Z' }],
    rows,
    false
);
assert(Array.isArray(off) && off.length === 0, 'off must return []');

const weekend = ctx.buildNewsPriceMarkers([
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

const earn = ctx.buildNewsPriceMarkers([
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
const capped = ctx.buildNewsPriceMarkers(many, manyRows, true);
assert(capped.length === 12, 'cap 12, got ' + capped.length);
assert(capped[0].time === '2026-08-09', 'oldest of cap, got ' + capped[0].time);
assert(capped[capped.length - 1].time === '2026-08-20', 'newest of cap');

const nodate = ctx.buildNewsPriceMarkers(
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
