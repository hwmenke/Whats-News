/**
 * Copy the currently painted daily OHLC legend (sticky hovered/held bar)
 * to the clipboard as a one-line string. Not a published rating.
 *
 * Uses lastLegend.daily (legend-held) — not always the last print.
 * Twin weekly bits are an optional suffix when linkedBarFor is present.
 *
 * Example: AAPL 2026-08-27 O 226.10 H 228.40 L 225.00 C 227.55 +0.82%
 */
function _copyOhlcPx(v) {
    if (typeof _fmtPx === 'function') return _fmtPx(v);
    return (v == null || !Number.isFinite(Number(v))) ? '—' : Number(v).toFixed(2);
}

function _copyOhlcDailyRows() {
    if (typeof rawRows !== 'undefined' && rawRows && Array.isArray(rawRows.daily)) {
        return rawRows.daily;
    }
    return [];
}

function _copyOhlcDailyLegend() {
    if (typeof lastLegend !== 'undefined' && lastLegend && lastLegend.daily) {
        return lastLegend.daily;
    }
    return { idx: null, time: null };
}

function _copyOhlcSymbol() {
    if (typeof state !== 'undefined' && state && state.activeSymbol) {
        return String(state.activeSymbol).toUpperCase();
    }
    return '';
}

/** Hovered/held daily index when valid; otherwise the last bar (same as paint). */
function paintedDailyOhlcIndex(rows, legend) {
    const list = rows || [];
    if (!list.length) return -1;
    const idx = legend && legend.idx;
    if (idx != null && idx >= 0 && idx < list.length) return idx;
    return list.length - 1;
}

function _copyOhlcChgPct(row, prev) {
    if (!row || !prev || !prev.close) return '';
    const chg = (Number(row.close) / Number(prev.close) - 1) * 100;
    if (!Number.isFinite(chg)) return '';
    return ` ${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`;
}

function _copyOhlcTwinSuffix(dateKey) {
    if (typeof linkedBarFor !== 'function' || !dateKey) return '';
    const hit = linkedBarFor('daily', dateKey);
    if (!hit || !hit.row) return '';
    const row = hit.row;
    const date = String(row.date).slice(0, 10);
    return ` · W ${date} O ${_copyOhlcPx(row.open)} H ${_copyOhlcPx(row.high)} L ${_copyOhlcPx(row.low)} C ${_copyOhlcPx(row.close)}`;
}

function formatPaintedOhlcLine() {
    const rows = _copyOhlcDailyRows();
    const idx = paintedDailyOhlcIndex(rows, _copyOhlcDailyLegend());
    if (idx < 0) return null;
    const row = rows[idx];
    if (!row) return null;
    const prev = idx > 0 ? rows[idx - 1] : null;
    const sym = _copyOhlcSymbol();
    const date = String(row.date).slice(0, 10);
    const daily = `${sym} ${date} O ${_copyOhlcPx(row.open)} H ${_copyOhlcPx(row.high)} L ${_copyOhlcPx(row.low)} C ${_copyOhlcPx(row.close)}${_copyOhlcChgPct(row, prev)}`;
    return daily + _copyOhlcTwinSuffix(date);
}

function copyPaintedOhlc() {
    const line = formatPaintedOhlcLine();
    if (!line) {
        if (typeof toast === 'function') toast('No OHLC to copy', 'warning');
        return;
    }
    const ok = () => { if (typeof toast === 'function') toast('OHLC copied', 'success'); };
    const fail = () => { if (typeof toast === 'function') toast('Clipboard failed', 'error'); };
    if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(line).then(ok, fail);
        return;
    }
    fail();
}
