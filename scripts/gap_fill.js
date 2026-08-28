/**
 * Optional Gap overlay — horizontal lines at the most recent unfilled daily
 * gap (open vs prior close).
 *
 * Gap up: today's open > prior close; gap down: open < prior close. A gap
 * stays unfilled until a later daily bar (including the gap day) trades
 * back through the prior close (low <= prior close on a gap up; high >=
 * prior close on a gap down). Two price lines mark gap high / gap low.
 * Daily pane only — weekly skipped in v1. Off by default. Overlay only —
 * not a published rating. No extra market-data fetch — uses rawRows.daily
 * already on the desk.
 *
 * Isolated so chart specialists can keep editing packs / legend / Last /
 * VWAP without a rewrite here. charts.js calls applyGapFillIfOn() on daily
 * load only, persistOverlays / applySavedOverlays via gapFillIsOn /
 * setGapFillOn, and forgetGapFillLines() on destroy.
 */
const GAP_FILL_COLOR = '#2dd4bf';
let gapFillOn = false;
let gapFillLines = { daily: [] };

function gapFillIsOn() {
    return !!gapFillOn;
}

function getGapFillOn() {
    return gapFillIsOn();
}

function setGapFillOn(on, opts) {
    opts = opts || {};
    gapFillOn = !!on;
    _syncGapFillPill();
    if (opts.apply !== false) applyGapFillIfOn();
    if (opts.persist && typeof persistOverlays === 'function') persistOverlays();
    return gapFillOn;
}

function _finiteGapPx(v) {
    if (v == null || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}

function gapZoneFromOpen(openPx, priorClose) {
    const open = _finiteGapPx(openPx);
    const prior = _finiteGapPx(priorClose);
    if (open == null || prior == null) return null;
    if (open === prior) return null;
    const up = open > prior;
    return {
        high: up ? open : prior,
        low: up ? prior : open,
        open,
        priorClose: prior,
        direction: up ? 'up' : 'down',
    };
}

function _gapFilledFrom(rows, startIdx, zone) {
    if (!zone) return true;
    const list = Array.isArray(rows) ? rows : [];
    for (let j = startIdx; j < list.length; j++) {
        const bar = list[j];
        if (!bar) continue;
        if (zone.direction === 'up') {
            const low = _finiteGapPx(bar.low);
            if (low != null && low <= zone.priorClose) return true;
        } else {
            const high = _finiteGapPx(bar.high);
            if (high != null && high >= zone.priorClose) return true;
        }
    }
    return false;
}

function mostRecentUnfilledGap(rows) {
    const list = Array.isArray(rows) ? rows : [];
    for (let i = list.length - 1; i >= 1; i--) {
        const row = list[i];
        const prior = list[i - 1];
        if (!row || !prior) continue;
        const zone = gapZoneFromOpen(row.open, prior.close);
        if (!zone) continue;
        if (_gapFilledFrom(list, i, zone)) continue;
        return {
            time: row.date != null ? row.date : null,
            high: zone.high,
            low: zone.low,
            open: zone.open,
            priorClose: zone.priorClose,
            direction: zone.direction,
            index: i,
        };
    }
    return null;
}

function gapFillLineOptions(price, title) {
    const dashed = (typeof LWC !== 'undefined' && LWC.LineStyle) ? LWC.LineStyle.Dashed : 2;
    return {
        price,
        color: GAP_FILL_COLOR,
        lineWidth: 1,
        lineStyle: dashed,
        axisLabelVisible: true,
        title: title || 'Gap',
    };
}

function forgetGapFillLines() {
    gapFillLines = { daily: [] };
}

function _clearGapFillDaily() {
    const s = (typeof series !== 'undefined' && series.daily) ? series.daily.candle : null;
    const lines = gapFillLines.daily || [];
    if (s) {
        lines.forEach(line => {
            try { s.removePriceLine(line); } catch (_) {}
        });
    }
    gapFillLines.daily = [];
}

function _drawGapFillDaily() {
    _clearGapFillDaily();
    if (!gapFillOn) return;
    const s = (typeof series !== 'undefined' && series.daily) ? series.daily.candle : null;
    if (!s || typeof s.createPriceLine !== 'function') return;
    const rows = (typeof rawRows !== 'undefined' && rawRows && rawRows.daily)
        ? rawRows.daily
        : [];
    const gap = mostRecentUnfilledGap(rows);
    if (!gap) return;
    const lines = [];
    lines.push(s.createPriceLine(gapFillLineOptions(gap.high, 'GapH')));
    if (gap.low !== gap.high) {
        lines.push(s.createPriceLine(gapFillLineOptions(gap.low, 'GapL')));
    }
    gapFillLines.daily = lines;
}

function _syncGapFillPill() {
    const pill = document.getElementById('pill-gap');
    if (!pill) return;
    pill.classList.toggle('active-gap', gapFillOn);
    pill.setAttribute('aria-pressed', gapFillOn ? 'true' : 'false');
}

function applyGapFillIfOn() {
    _syncGapFillPill();
    _drawGapFillDaily();
}

function toggleGapFill() {
    return setGapFillOn(!gapFillOn, { persist: true });
}

if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
        const pill = document.getElementById('pill-gap');
        if (!pill) return;
        pill.addEventListener('click', () => toggleGapFill());
        _syncGapFillPill();
    });
}
