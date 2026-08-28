"""Contract tests: bar-click journal open stamps an empty note with the bar date."""

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

os.environ.setdefault("DATA_SERVICE_MODE", "embedded")

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

FORBIDDEN = (
    "scripts/app.js",
    "scripts/charts.js",
    "index.html",
    "portfolio.py",
    "scripts/spy_rs.js",
    "scripts/setup_scanner.js",
    "tests/test_journal_date_stamp.py",
)


_NODE_STAMP_SCRIPT = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');

function extractFn(name) {
    const header = 'function ' + name;
    const start = src.indexOf(header);
    if (start < 0) throw new Error('missing ' + name);
    const brace = src.indexOf('{', start);
    let depth = 0;
    let inStr = null;
    let escape = false;
    for (let i = brace; i < src.length; i++) {
        const ch = src[i];
        if (inStr) {
            if (escape) { escape = false; continue; }
            if (ch === '\\') { escape = true; continue; }
            if (ch === inStr) inStr = null;
            continue;
        }
        if (ch === '"' || ch === "'" || ch === '`') { inStr = ch; continue; }
        if (ch === '{') depth++;
        else if (ch === '}') {
            depth--;
            if (depth === 0) return src.slice(start, i + 1);
        }
    }
    throw new Error('unclosed ' + name);
}

const slice = [
    extractFn('journalNoteStamp'),
    extractFn('hasJournalNoteForSymbolDate'),
    extractFn('loadJournalEntries'),
    extractFn('onChartBarClick'),
    extractFn('openJournalForDate'),
].join('\n');

function assert(cond, msg) {
    if (!cond) throw new Error(msg);
}

function makeStore(seed) {
    const data = Object.assign({}, seed || {});
    return {
        data,
        getItem(key) { return Object.prototype.hasOwnProperty.call(data, key) ? data[key] : null; },
        setItem(key, val) { data[key] = String(val); },
        removeItem(key) { delete data[key]; },
    };
}

function makeEls(noteValue) {
    return {
        date: { value: '' },
        note: {
            value: noteValue == null ? '' : noteValue,
            placeholder: '',
            focused: false,
            sel: null,
            focus() { this.focused = true; },
            setSelectionRange(a, b) { this.sel = [a, b]; },
        },
    };
}

function boot(opts) {
    const els = makeEls(opts.noteValue);
    const store = makeStore(opts.store || {});
    const sandbox = {
        JOURNAL_KEY: 'whats-news-journal',
        journalFocusDate: null,
        journalOpened: false,
        state: { activeSymbol: opts.symbol == null ? 'AAPL' : opts.symbol },
        localStorage: store,
        document: {
            getElementById(id) {
                if (id === 'journal-date') return els.date;
                if (id === 'journal-note') return els.note;
                return null;
            },
        },
        openJournal() { sandbox.journalOpened = true; },
        toast() {},
    };
    vm.createContext(sandbox);
    vm.runInContext(slice, sandbox);
    return { sandbox, els, store };
}

const KEY = 'whats-news-journal';
const DATE = '2026-08-21';
const STAMP = '2026-08-21 ';

assert(journalStampFromBoot() === STAMP, 'stamp helper');

function journalStampFromBoot() {
    const { sandbox } = boot({});
    return sandbox.journalNoteStamp(DATE);
}

// 1. Empty compose, no stored note → stamp the bar date (one line) and focus.
{
    const { sandbox, els, store } = boot({ noteValue: '' });
    sandbox.onChartBarClick({ date: DATE, freq: 'daily' });
    assert(sandbox.journalOpened === true, 'opens journal');
    assert(els.date.value === DATE, 'date field is the bar date');
    assert(els.note.value === STAMP, 'empty note gets date stamp, got ' + JSON.stringify(els.note.value));
    assert(!els.note.value.includes('\n'), 'stamp is one line');
    assert(els.note.focused === true, 'compose focused so the user can type');
    assert(els.note.sel[0] === STAMP.length && els.note.sel[1] === STAMP.length, 'caret at end');
    assert(store.getItem(KEY) == null, 'open path must not persist');
    assert(sandbox.journalNoteStamp(DATE).indexOf(DATE) === 0, 'stamp starts with bar date');
}

// 2. Stored note for this symbol+date → leave it; do not stamp.
{
    const existing = [{ id: 'AAPL-1', symbol: 'AAPL', date: DATE, note: 'held the 20 EMA' }];
    const { sandbox, els, store } = boot({
        noteValue: '',
        store: { [KEY]: JSON.stringify(existing) },
    });
    sandbox.openJournalForDate(DATE, 'daily');
    assert(els.note.value === '', 'must not stamp over an existing note');
    assert(JSON.parse(store.getItem(KEY))[0].note === 'held the 20 EMA', 'stored note unchanged');
}

// 3. Typed but unsaved text → do not overwrite.
{
    const { sandbox, els } = boot({ noteValue: 'watching the high' });
    sandbox.openJournalForDate(DATE, 'daily');
    assert(els.note.value === 'watching the high', 'keep typed text');
}

// 4. Note on another date → still stamp.
{
    const { sandbox, els } = boot({
        noteValue: '',
        store: { [KEY]: JSON.stringify([{ symbol: 'AAPL', date: '2026-08-14', note: 'old' }]) },
    });
    sandbox.openJournalForDate(DATE, 'daily');
    assert(els.note.value === STAMP, 'other date does not block stamp');
}

// 5. Note on another symbol, same date → still stamp.
{
    const { sandbox, els } = boot({
        noteValue: '',
        store: { [KEY]: JSON.stringify([{ symbol: 'MSFT', date: DATE, note: 'other name' }]) },
    });
    sandbox.openJournalForDate(DATE, 'daily');
    assert(els.note.value === STAMP, 'other symbol does not block stamp');
}

// 6. Setup card entry (no note field) for same symbol+date → still stamp.
{
    const { sandbox, els } = boot({
        noteValue: '',
        store: { [KEY]: JSON.stringify([{ symbol: 'AAPL', date: DATE, entry: 100, stop: 95 }]) },
    });
    sandbox.openJournalForDate(DATE, 'daily');
    assert(els.note.value === STAMP, 'setup-without-note does not block stamp');
}

// 7. Whitespace-only compose counts as empty.
{
    const { sandbox, els } = boot({ noteValue: '   ' });
    sandbox.openJournalForDate(DATE, 'daily');
    assert(els.note.value === STAMP, 'whitespace is empty');
}

// 8. Empty/invalid date is a no-op.
{
    const { sandbox, els } = boot({ noteValue: '' });
    sandbox.onChartBarClick({ date: '', freq: 'daily' });
    sandbox.openJournalForDate('', 'daily');
    assert(sandbox.journalOpened === false, 'no open on empty date');
    assert(els.note.value === '', 'no stamp on empty date');
}

// 9. Weekly uses the week-ending bar date as the stamp (not a rating).
{
    const { sandbox, els } = boot({ noteValue: '' });
    sandbox.onChartBarClick({ date: DATE, freq: 'weekly' });
    assert(els.note.value === STAMP, 'weekly stamps week-ending date');
    assert(els.note.placeholder.indexOf('week-ending') >= 0, 'weekly placeholder');
}

// 10. Full ISO timestamp on the bar still stamps YYYY-MM-DD.
{
    const { sandbox, els } = boot({ noteValue: '' });
    sandbox.onChartBarClick({ date: '2026-08-21T15:30:00Z', freq: 'daily' });
    assert(els.date.value === DATE, 'slice to calendar date');
    assert(els.note.value === STAMP, 'stamp from ISO date');
}

process.stdout.write(JSON.stringify({
    ok: true,
    stamp: STAMP,
    stampFn: boot({}).sandbox.journalNoteStamp(DATE),
}));
"""


def _fn_chunk(src, header, until):
    start = src.index(header)
    end = src.index(until, start + 1)
    return src[start:end]


class JournalDateStampTests(unittest.TestCase):
    """Bar click prefills an empty note with the bar date; existing notes stay."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "scripts", "app.js"), encoding="utf-8") as fh:
            cls.app_js = fh.read()
        with open(os.path.join(ROOT, "scripts", "charts.js"), encoding="utf-8") as fh:
            cls.charts = fh.read()
        with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as fh:
            cls.html = fh.read()

    def test_helpers_live_on_journal_open_path(self):
        js = self.app_js
        self.assertIn("function journalNoteStamp", js)
        self.assertIn("function hasJournalNoteForSymbolDate", js)
        self.assertIn("function openJournalForDate", js)
        self.assertIn("function onChartBarClick", js)
        stamp = _fn_chunk(js, "function journalNoteStamp", "function hasJournalNoteForSymbolDate")
        self.assertIn("slice(0, 10)", stamp)
        self.assertNotIn("saveJournalEntries", stamp)
        has_note = _fn_chunk(js, "function hasJournalNoteForSymbolDate", "function onChartBarClick")
        self.assertIn("loadJournalEntries()", has_note)
        self.assertIn("e.symbol", has_note)
        self.assertIn("e.date", has_note)
        self.assertIn("e.note", has_note)
        self.assertNotIn("saveJournalEntries", has_note)

    def test_open_journal_for_date_stamps_empty_only(self):
        js = self.app_js
        open_fn = _fn_chunk(js, "function openJournalForDate", "function closeJournal")
        self.assertIn("journal-date", open_fn)
        self.assertIn("journal-note", open_fn)
        self.assertIn("journalNoteStamp(key)", open_fn)
        self.assertIn("hasJournalNoteForSymbolDate(symbol, key)", open_fn)
        self.assertIn("state.activeSymbol", open_fn)
        self.assertIn("!(noteEl.value || '').trim()", open_fn)
        self.assertIn("noteEl.value = journalNoteStamp(key)", open_fn)
        self.assertIn("noteEl.focus()", open_fn)
        self.assertIn("setSelectionRange", open_fn)
        self.assertIn("not a published rating", open_fn)
        self.assertNotIn("saveJournalEntries", open_fn)
        self.assertNotIn("saveJournalNote", open_fn)
        # Opening via J / Shift+J must not stamp.
        plain = _fn_chunk(js, "function openJournal()", "function journalNoteStamp")
        self.assertNotIn("journalNoteStamp", plain)
        self.assertNotIn("hasJournalNoteForSymbolDate", plain)

    def test_bar_click_still_routes_through_open_journal_for_date(self):
        charts, app_js = self.charts, self.app_js
        self.assertIn("function setupBarClickJournal", charts)
        self.assertIn("onChartBarClick({ freq, date })", charts)
        click = _fn_chunk(app_js, "function onChartBarClick", "function openJournalForDate")
        self.assertIn("openJournalForDate(date, payload && payload.freq)", click)
        self.assertIn('id="journal-date"', self.html)
        self.assertIn('id="journal-note"', self.html)
        self.assertIn('id="journal-compose"', self.html)

    def test_stamp_behavior_node(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(_NODE_STAMP_SCRIPT)
            runner = fh.name
        try:
            proc = subprocess.run(
                [node, runner, os.path.join(ROOT, "scripts", "app.js")],
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
        self.assertEqual(payload["stamp"], "2026-08-21 ")
        self.assertEqual(payload["stampFn"], "2026-08-21 ")
        self.assertNotIn("\n", payload["stamp"])

    def test_forbidden_files_have_no_published_rating_brand(self):
        brand = chr(105) + chr(98) + chr(100)
        needle = re.compile(brand, re.IGNORECASE)
        for path in FORBIDDEN:
            with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
                text = fh.read()
            self.assertIsNone(needle.search(text), msg=f"{path} must not contain that rating brand")


if __name__ == "__main__":
    unittest.main()
