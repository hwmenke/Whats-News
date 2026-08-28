/**
 * journal_filter.js — compact Trade journal list filter (localStorage).
 * Wraps renderJournal / openJournal after app.js. Does not rewrite journal HTML.
 * not a published rating.
 */
const JOURNAL_FILTER_KEY = 'whats-news-journal-filter';

function readJournalFilter() {
    try {
        const raw = localStorage.getItem(JOURNAL_FILTER_KEY);
        return raw == null ? '' : String(raw);
    } catch {
        return '';
    }
}

function writeJournalFilter(value) {
    try {
        const text = value == null ? '' : String(value);
        if (text) localStorage.setItem(JOURNAL_FILTER_KEY, text);
        else localStorage.removeItem(JOURNAL_FILTER_KEY);
    } catch { /* ignore quota */ }
}

function persistJournalFilter() {
    const el = document.getElementById('journal-filter');
    writeJournalFilter(el ? el.value : '');
}

function restoreJournalFilter() {
    const el = document.getElementById('journal-filter');
    if (el) el.value = readJournalFilter();
    applyJournalFilter();
}

function journalFilterQuery() {
    return (document.getElementById('journal-filter')?.value || '').trim().toLowerCase();
}

function matchesJournalFilter(symbol, note, q) {
    const needle = String(q == null ? journalFilterQuery() : q).trim().toLowerCase();
    if (!needle) return true;
    const code = String(symbol || '').toLowerCase();
    const text = String(note || '').toLowerCase();
    return code.includes(needle) || text.includes(needle);
}

function applyJournalFilter() {
    const list = document.getElementById('journal-list');
    if (!list) return;
    const q = journalFilterQuery();
    const items = list.querySelectorAll('.journal-item');
    let visible = 0;
    items.forEach(item => {
        const symbol = item.querySelector('.journal-sym')?.textContent || '';
        const note = item.querySelector('.journal-note-text')?.textContent || '';
        const show = matchesJournalFilter(symbol, note, q);
        item.hidden = !show;
        if (show) visible += 1;
    });
    let hint = list.querySelector('.journal-filter-empty');
    if (items.length && !visible && q) {
        if (!hint) {
            hint = document.createElement('div');
            hint.className = 'alert-log-empty journal-filter-empty';
            hint.textContent = 'No matching notes';
            list.appendChild(hint);
        }
    } else if (hint) {
        hint.remove();
    }
    const focus = list.querySelector('.journal-item-focus:not([hidden])');
    if (focus && typeof focus.scrollIntoView === 'function') {
        focus.scrollIntoView({ block: 'nearest' });
    }
}

function journalSymbolOnWatchlist(symbol) {
    const code = String(symbol || '').trim();
    if (!code) return false;
    const symbols = (typeof state !== 'undefined' && state && state.symbols) || [];
    return symbols.some(s => String(s.symbol || '') === code);
}

function onJournalListClick(ev) {
    if (ev.target.closest('button, .journal-close-btn, .journal-del-btn')) return;
    const item = ev.target.closest('.journal-item');
    if (!item || item.hidden) return;
    const date = String(item.dataset.date || '').slice(0, 10);
    const symbol = (item.querySelector('.journal-sym')?.textContent || '').trim();
    if (date) {
        const dateEl = document.getElementById('journal-date');
        if (dateEl) dateEl.value = date;
        if (typeof journalFocusDate !== 'undefined') journalFocusDate = date;
        else if (typeof globalThis !== 'undefined') globalThis.journalFocusDate = date;
        if (typeof renderJournal === 'function') renderJournal();
    }
    if (symbol && journalSymbolOnWatchlist(symbol) && typeof selectSymbol === 'function') {
        selectSymbol(symbol);
    }
}

function bindJournalFilterUi() {
    const el = document.getElementById('journal-filter');
    if (el && !el._journalFilterBound) {
        el._journalFilterBound = true;
        el.addEventListener('input', () => {
            persistJournalFilter();
            applyJournalFilter();
        });
    }
    const list = document.getElementById('journal-list');
    if (list && !list._journalFilterClicks) {
        list._journalFilterClicks = true;
        list.addEventListener('click', onJournalListClick);
    }
}

function wrapJournalRender() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.renderJournal !== 'function' || g.renderJournal._journalFilterWrapped) return;
    const orig = g.renderJournal;
    function renderJournalWithFilter() {
        orig.apply(this, arguments);
        applyJournalFilter();
    }
    renderJournalWithFilter._journalFilterWrapped = true;
    g.renderJournal = renderJournalWithFilter;
}

function wrapOpenJournal() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.openJournal !== 'function' || g.openJournal._journalFilterWrapped) return;
    const orig = g.openJournal;
    function openJournalWithFilter() {
        restoreJournalFilter();
        orig.apply(this, arguments);
    }
    openJournalWithFilter._journalFilterWrapped = true;
    g.openJournal = openJournalWithFilter;
}

function bootJournalFilter() {
    wrapJournalRender();
    wrapOpenJournal();
    bindJournalFilterUi();
    restoreJournalFilter();
}

if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootJournalFilter);
    } else {
        bootJournalFilter();
    }
}
