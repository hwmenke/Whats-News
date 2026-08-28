/**
 * Optional Last overlay — full-width horizontal line at the rightmost close.
 *
 * Not PDC. Session PDC is the prior bar's close (charts.js applySessionLevels).
 * This line is the current last print on the loaded series, so it stays put as
 * a live reference while scrolling history. Daily pane uses the last daily
 * close; weekly pane uses the last weekly close. Off by default. Not a
 * published rating. No extra market-data fetch — uses rawRows already on the desk.
 *
 * Isolated so chart specialists can keep editing packs / legend / prefetch
 * without a rewrite here. charts.js calls applyLastPriceIfOn() after daily
 * and weekly loadOHLCV, persistOverlays / applySavedOverlays via
 * lastPriceIsOn / setLastPriceOn, and forgetLastPriceLines() on destroy.
 */
const LAST_PRICE_COLOR = '#c026d3';
let lastPriceOn = false;
let lastPriceLines = { daily: [], weekly: [] };

function lastPriceIsOn() {
    return !!lastPriceOn;
}

function getLastPriceOn() {
    return lastPriceIsOn();
}

function setLastPriceOn(on, opts) {
    opts = opts || {};
    lastPriceOn = !!on;
    _syncLastPricePill();
    if (opts.apply !== false) applyLastPriceIfOn();
    if (opts.persist && typeof persistOverlays === 'function') persistOverlays();
    return lastPriceOn;
}

function lastCloseFromRows(rows) {
    const list = Array.isArray(rows) ? rows : [];
    for (let i = list.length - 1; i >= 0; i--) {
        const row = list[i];
        if (!row) continue;
        const close = Number(row.close);
        if (!Number.isFinite(close)) continue;
        return {
            time: row.date != null ? row.date : null,
            value: close,
        };
    }
    return null;
}

function lastPriceLineOptions(price) {
    const solid = (typeof LWC !== 'undefined' && LWC.LineStyle) ? LWC.LineStyle.Solid : 0;
    return {
        price,
        color: LAST_PRICE_COLOR,
        lineWidth: 1,
        lineStyle: solid,
        axisLabelVisible: true,
        title: 'Last',
    };
}

function forgetLastPriceLines() {
    lastPriceLines = { daily: [], weekly: [] };
}

function _clearLastPriceFreq(freq) {
    const s = (typeof series !== 'undefined' && series[freq]) ? series[freq].candle : null;
    const lines = lastPriceLines[freq] || [];
    if (s) {
        lines.forEach(line => {
            try { s.removePriceLine(line); } catch (_) {}
        });
    }
    lastPriceLines[freq] = [];
}

function _drawLastPriceFreq(freq) {
    _clearLastPriceFreq(freq);
    if (!lastPriceOn) return;
    const s = (typeof series !== 'undefined' && series[freq]) ? series[freq].candle : null;
    if (!s || typeof s.createPriceLine !== 'function') return;
    const rows = (typeof rawRows !== 'undefined' && rawRows && rawRows[freq])
        ? rawRows[freq]
        : [];
    const last = lastCloseFromRows(rows);
    if (!last) return;
    const line = s.createPriceLine(lastPriceLineOptions(last.value));
    lastPriceLines[freq] = [line];
}

function _syncLastPricePill() {
    const pill = document.getElementById('pill-last');
    if (!pill) return;
    pill.classList.toggle('active-last', lastPriceOn);
    pill.setAttribute('aria-pressed', lastPriceOn ? 'true' : 'false');
}

function applyLastPriceIfOn() {
    _syncLastPricePill();
    _drawLastPriceFreq('daily');
    _drawLastPriceFreq('weekly');
}

function toggleLastPrice() {
    return setLastPriceOn(!lastPriceOn, { persist: true });
}

if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
        const pill = document.getElementById('pill-last');
        if (!pill) return;
        pill.addEventListener('click', () => toggleLastPrice());
        _syncLastPricePill();
    });
}
