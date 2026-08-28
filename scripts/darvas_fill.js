/**
 * Darvas box fill — low-opacity orange band between box top and bottom
 * on the daily price pane. Edges stay the dashed price lines in charts.js.
 *
 * Daily only. Off/on follows activeOverlays.darvas via applyDarvasBox /
 * clearDarvasBox. Isolated so other chart specialists can keep editing
 * packs / legend / news markers / alerts without a rewrite here.
 */
const DARVAS_FILL_ORANGE = 'rgba(249, 115, 22, 0.16)';
const DARVAS_FILL_LINE = 'rgba(249, 115, 22, 0)';

let _darvasFillSeries = null;
let _darvasFillHost = null;

function _darvasFillOverlayOn() {
    return typeof activeOverlays !== 'undefined' && !!activeOverlays.darvas;
}

function _darvasFillPx(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}

function _darvasFillTimes(box) {
    const rows = (typeof rawRows !== 'undefined' && rawRows && rawRows.daily)
        ? rawRows.daily
        : [];
    if (!rows.length) return [];
    const since = box && box.since ? String(box.since).slice(0, 10) : '';
    let start = 0;
    if (since) {
        const idx = rows.findIndex(r => String(r.date).slice(0, 10) >= since);
        if (idx >= 0) start = idx;
    }
    return rows.slice(start).map(r => String(r.date).slice(0, 10));
}

function clearDarvasFill() {
    if (!_darvasFillSeries) return;
    try {
        _darvasFillSeries.setData([]);
        _darvasFillSeries.applyOptions({ visible: false });
    } catch (_) { /* chart disposed */ }
}

function ensureDarvasFillSeries() {
    const chart = (typeof charts !== 'undefined' && charts.daily) ? charts.daily.main : null;
    if (!chart) return null;
    if (_darvasFillHost === chart && _darvasFillSeries) return _darvasFillSeries;
    _darvasFillHost = chart;
    // Area series from box bottom (baseValue) up to box top. ~16% opacity so
    // candles stay readable; v4 draws later series on top of candles.
    _darvasFillSeries = chart.addAreaSeries({
        topColor: DARVAS_FILL_ORANGE,
        bottomColor: DARVAS_FILL_ORANGE,
        lineColor: DARVAS_FILL_LINE,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        visible: false,
        autoscaleInfoProvider: () => null,
    });
    return _darvasFillSeries;
}

function applyDarvasFill(box) {
    if (!_darvasFillOverlayOn() || !box) {
        clearDarvasFill();
        return;
    }
    const top = _darvasFillPx(box.top);
    const bottom = _darvasFillPx(box.bottom);
    if (top == null || bottom == null || top <= bottom) {
        clearDarvasFill();
        return;
    }
    const times = _darvasFillTimes(box);
    if (!times.length) {
        clearDarvasFill();
        return;
    }
    const s = ensureDarvasFillSeries();
    if (!s) return;
    try {
        s.applyOptions({
            visible: true,
            baseValue: { type: 'price', price: bottom },
            topColor: DARVAS_FILL_ORANGE,
            bottomColor: DARVAS_FILL_ORANGE,
            lineColor: DARVAS_FILL_LINE,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
        });
        s.setData(times.map(t => ({ time: t, value: top })));
    } catch (_) {
        clearDarvasFill();
    }
}
