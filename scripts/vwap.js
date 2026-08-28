/**
 * Optional session VWAP on the daily price pane.
 *
 * Desk stores EOD daily bars (no intraday session tape). VWAP is therefore
 * a rolling anchored VWAP from the first loaded daily bar — not reset on
 * the visible range, and not an intraday session VWAP:
 *   typical = (high + low + close) / 3
 *   vwap   = cumsum(typical * volume) / cumsum(volume)
 * Weekly pane is skipped in v1. Off by default. Volume-weighted average
 * price overlay — not a published rating.
 *
 * Isolated so chart specialists can keep editing packs / legend / prefetch
 * without a rewrite here. charts.js calls applyVwapIfOn() on daily load
 * only, and persistOverlays / applySavedOverlays via vwapIsOn / setVwapOn.
 */
const VWAP_COLOR = '#f5c542';
let vwapOn = false;
let _vwapSeries = null;
let _vwapHost = null;

function vwapIsOn() {
    return !!vwapOn;
}

function getVwapOn() {
    return vwapIsOn();
}

function setVwapOn(on, opts) {
    opts = opts || {};
    vwapOn = !!on;
    _syncVwapPill();
    if (opts.apply !== false) applyVwapIfOn();
    if (opts.persist && typeof persistOverlays === 'function') persistOverlays();
    return vwapOn;
}

function typicalPrice(row) {
    if (!row) return null;
    const h = Number(row.high);
    const l = Number(row.low);
    const c = Number(row.close);
    if (!Number.isFinite(h) || !Number.isFinite(l) || !Number.isFinite(c)) return null;
    return (h + l + c) / 3;
}

function sessionVwapPoints(rows) {
    const list = Array.isArray(rows) ? rows : [];
    const out = [];
    let cumPv = 0;
    let cumVol = 0;
    for (let i = 0; i < list.length; i++) {
        const row = list[i] || {};
        const time = row.date != null ? row.date : null;
        const tp = typicalPrice(row);
        const rawVol = Number(row.volume);
        const vol = (Number.isFinite(rawVol) && rawVol > 0) ? rawVol : 0;
        if (tp != null && vol > 0) {
            cumPv += tp * vol;
            cumVol += vol;
        }
        if (time == null) continue;
        if (cumVol > 0) {
            out.push({ time, value: cumPv / cumVol });
        } else {
            out.push({ time });
        }
    }
    return out;
}

function _vwapLineOptions() {
    const solid = (typeof LWC !== 'undefined' && LWC.LineStyle) ? LWC.LineStyle.Solid : 0;
    return {
        color: VWAP_COLOR,
        lineWidth: 1.5,
        lineStyle: solid,
        priceLineVisible: false,
        lastValueVisible: true,
        visible: false,
        title: 'VWAP',
    };
}

function ensureVwapSeries() {
    const chart = (typeof charts !== 'undefined' && charts.daily) ? charts.daily.main : null;
    if (!chart) return null;
    if (_vwapHost === chart && _vwapSeries) return _vwapSeries;
    _vwapHost = chart;
    _vwapSeries = chart.addLineSeries(_vwapLineOptions());
    return _vwapSeries;
}

function forgetVwapSeries() {
    _vwapSeries = null;
    _vwapHost = null;
}

function _vwapSetLine(series, line, visible) {
    if (!series) return;
    series.setData(line);
    series.applyOptions({
        visible: !!(visible && line.length),
        lastValueVisible: true,
    });
}

function _vwapHide() {
    if (!_vwapSeries) return;
    try { _vwapSeries.applyOptions({ visible: false }); } catch (_) {}
}

function _syncVwapPill() {
    const pill = document.getElementById('pill-vwap');
    if (!pill) return;
    pill.classList.toggle('active-vwap', vwapOn);
    pill.setAttribute('aria-pressed', vwapOn ? 'true' : 'false');
}

function applyVwapIfOn() {
    _syncVwapPill();
    if (!vwapOn) {
        _vwapHide();
        return;
    }
    const rows = (typeof rawRows !== 'undefined' && rawRows && rawRows.daily)
        ? rawRows.daily
        : [];
    const points = sessionVwapPoints(rows);
    const line = points.filter(p => p && p.time != null);
    const hasValue = line.some(p => p.value != null);
    _vwapSetLine(ensureVwapSeries(), line, hasValue);
}

function toggleVwap() {
    return setVwapOn(!vwapOn, { persist: true });
}

if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
        const pill = document.getElementById('pill-vwap');
        if (!pill) return;
        pill.addEventListener('click', () => toggleVwap());
        _syncVwapPill();
    });
}
