/**
 * journal_export.js — compact Trade journal CSV download.
 * Filter-aware when #journal-filter is present. Loaded after journal_filter.js.
 * Does not change persist keys. Does not rewrite journal HTML.
 * not a published rating.
 */
const JOURNAL_EXPORT_FILENAME = 'whats-news-journal.csv';
const JOURNAL_EXPORT_CORE_COLS = ['date', 'symbol', 'note', 'closed'];

function journalExportLoadEntries() {
    if (typeof loadJournalEntries === 'function') {
        const rows = loadJournalEntries();
        return Array.isArray(rows) ? rows.slice() : [];
    }
    return [];
}

function journalExportVisibleEntries(entries) {
    const list = Array.isArray(entries) ? entries : [];
    const filterEl = typeof document !== 'undefined' ? document.getElementById('journal-filter') : null;
    if (!filterEl) return list.slice();
    const q = typeof journalFilterQuery === 'function'
        ? journalFilterQuery()
        : String(filterEl.value || '').trim().toLowerCase();
    if (!q) return list.slice();
    return list.filter(e => {
        if (typeof matchesJournalFilter === 'function') {
            return matchesJournalFilter(e && e.symbol, e && e.note, q);
        }
        const code = String((e && e.symbol) || '').toLowerCase();
        const text = String((e && e.note) || '').toLowerCase();
        return code.includes(q) || text.includes(q);
    });
}

function journalExportColumns(entries) {
    const cols = JOURNAL_EXPORT_CORE_COLS.slice();
    const seen = new Set(cols);
    (entries || []).forEach(e => {
        if (!e || typeof e !== 'object') return;
        Object.keys(e).forEach(k => {
            if (!seen.has(k)) {
                seen.add(k);
                cols.push(k);
            }
        });
    });
    return cols;
}

function journalCsvEscape(value) {
    if (value == null) return '';
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (typeof value === 'object') {
        try { value = JSON.stringify(value); } catch { value = String(value); }
    }
    const s = String(value);
    if (/[",\r\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
}

function journalExportCell(entry, col) {
    if (col === 'date') return journalCsvEscape(String((entry && entry.date) || '').slice(0, 10));
    if (col === 'closed') return (entry && entry.closed) ? 'true' : 'false';
    if (col === 'note') return journalCsvEscape(entry && entry.note != null ? entry.note : '');
    return journalCsvEscape(entry ? entry[col] : '');
}

function journalEntriesToCsv(entries) {
    const rows = journalExportVisibleEntries(entries);
    const cols = journalExportColumns(rows);
    const lines = [cols.join(',')];
    rows.forEach(e => {
        lines.push(cols.map(c => journalExportCell(e, c)).join(','));
    });
    return lines.join('\n');
}

function journalExportDownload(csv, filename) {
    const name = filename || JOURNAL_EXPORT_FILENAME;
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.setAttribute('download', name);
    const host = (typeof document !== 'undefined' && (document.body || document.documentElement)) || null;
    if (host && typeof host.appendChild === 'function') host.appendChild(a);
    a.click();
    if (typeof a.remove === 'function') a.remove();
    else if (host && typeof host.removeChild === 'function' && a.parentNode === host) host.removeChild(a);
    if (typeof URL.revokeObjectURL === 'function') URL.revokeObjectURL(url);
}

function exportJournalCsv() {
    const csv = journalEntriesToCsv(journalExportLoadEntries());
    journalExportDownload(csv, JOURNAL_EXPORT_FILENAME);
}

function bindJournalExportUi() {
    const btn = document.getElementById('btn-journal-export');
    if (btn && !btn._journalExportBound) {
        btn._journalExportBound = true;
        btn.addEventListener('click', exportJournalCsv);
    }
}

function bootJournalExport() {
    bindJournalExportUi();
}

if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootJournalExport);
    } else {
        bootJournalExport();
    }
}
