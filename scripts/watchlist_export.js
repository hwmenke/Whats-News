/**
 * watchlist_export.js — compact watchlist CSV download of visible tickers.
 * Respects Desk only (hides univ:* archive tags) and the watchlist filter.
 * Loaded after app.js. Does not fetch quotes. Does not change persist keys.
 * not a published rating.
 */
const WATCHLIST_EXPORT_FILENAME = 'whats-news-watchlist.csv';
const WATCHLIST_EXPORT_CORE_COLS = ['symbol', 'group_tag'];

function watchlistExportLoadRows() {
    if (typeof state !== 'undefined' && state && Array.isArray(state.symbols)) {
        return state.symbols.slice();
    }
    return [];
}

function watchlistExportDeskOnlyOn() {
    const el = typeof document !== 'undefined' ? document.getElementById('chk-desk-only') : null;
    if (el) return !!el.checked;
    if (typeof state !== 'undefined' && state && Object.prototype.hasOwnProperty.call(state, 'deskOnly')) {
        return !!state.deskOnly;
    }
    return true;
}

function watchlistExportIsUniverseRow(row) {
    const tag = String((row && row.group_tag) || '').toLowerCase();
    return tag.indexOf('univ:') === 0;
}

function watchlistExportQuery() {
    if (typeof watchlistFilterQuery === 'function') return watchlistFilterQuery();
    const el = typeof document !== 'undefined' ? document.getElementById('watchlist-filter') : null;
    return String((el && el.value) || '').trim().toUpperCase();
}

function watchlistExportRowMatches(row, q) {
    if (typeof matchesWatchlistFilter === 'function') {
        return matchesWatchlistFilter(row && row.symbol, row && row.group_tag, q);
    }
    const code = String((row && row.symbol) || '').toUpperCase();
    const tag = String((row && row.group_tag) || '').toUpperCase();
    return code.indexOf(q) >= 0 || tag.indexOf(q) >= 0;
}

function watchlistExportVisibleRows(rows) {
    let list = Array.isArray(rows) ? rows.slice() : [];
    list = list.filter(row => row && row.symbol);
    if (watchlistExportDeskOnlyOn()) {
        list = list.filter(row => !watchlistExportIsUniverseRow(row));
    }
    const filterEl = typeof document !== 'undefined' ? document.getElementById('watchlist-filter') : null;
    if (!filterEl) return list;
    const q = watchlistExportQuery();
    if (!q) return list;
    return list.filter(row => watchlistExportRowMatches(row, q));
}

function watchlistExportColumns(rows) {
    const cols = WATCHLIST_EXPORT_CORE_COLS.slice();
    const seen = new Set(cols);
    (rows || []).forEach(row => {
        if (!row || typeof row !== 'object') return;
        Object.keys(row).forEach(k => {
            if (!seen.has(k)) {
                seen.add(k);
                cols.push(k);
            }
        });
    });
    return cols;
}

function watchlistCsvEscape(value) {
    if (value == null) return '';
    if (typeof value === 'boolean') return value ? 'true' : 'false';
    if (typeof value === 'object') {
        try { value = JSON.stringify(value); } catch { value = String(value); }
    }
    const s = String(value);
    if (/[",\r\n]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
    return s;
}

function watchlistExportCell(row, col) {
    if (col === 'symbol') return watchlistCsvEscape(row && row.symbol);
    if (col === 'group_tag') return watchlistCsvEscape(row && row.group_tag != null ? row.group_tag : '');
    return watchlistCsvEscape(row ? row[col] : '');
}

function watchlistRowsToCsv(rows) {
    const visible = watchlistExportVisibleRows(rows);
    const cols = watchlistExportColumns(visible);
    const lines = [cols.join(',')];
    visible.forEach(row => {
        lines.push(cols.map(c => watchlistExportCell(row, c)).join(','));
    });
    return lines.join('\n');
}

function watchlistExportDownload(csv, filename) {
    const name = filename || WATCHLIST_EXPORT_FILENAME;
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

function exportWatchlistCsv() {
    const csv = watchlistRowsToCsv(watchlistExportLoadRows());
    watchlistExportDownload(csv, WATCHLIST_EXPORT_FILENAME);
}

function bindWatchlistExportUi() {
    const btn = document.getElementById('btn-watchlist-export');
    if (btn && !btn._watchlistExportBound) {
        btn._watchlistExportBound = true;
        btn.addEventListener('click', exportWatchlistCsv);
    }
}

function bootWatchlistExport() {
    bindWatchlistExportUi();
}

if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootWatchlistExport);
    } else {
        bootWatchlistExport();
    }
}
