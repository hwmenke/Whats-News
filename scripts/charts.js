/**
 * charts.js — TradingView Lightweight Charts renderer
 * Two side-by-side panels: Daily and Weekly, each with Price / RSI / MACD / Trend Score.
 * Dynamic KAMA periods and Bollinger Bands as overlays.
 */

const LWC = LightweightCharts;

// ── KAMA period management ──────────────────────────────────
// Maps period → { color, seriesDaily, seriesWeekly }
const kamaPeriods = {};

// Colour pool for dynamically added KAMA lines
const KAMA_COLORS = [
    '#3b82f6', '#eab308', '#a855f7', '#06b6d4',
    '#f97316', '#ec4899', '#14b8a6', '#f43f5e',
];
let kamaColorIdx = 0;
function nextKamaColor() {
    const c = KAMA_COLORS[kamaColorIdx % KAMA_COLORS.length];
    kamaColorIdx++;
    return c;
}

// Overlay state. Defaults: BB off, EP on, Darvas on. vs-SPY / News / VWAP live
// in spy_rs.js / news_markers.js / vwap.js (off until the user toggles). Alert
// lines use whats-news-price-alerts in price_alerts.js, not this overlay blob.
const activeOverlays = { bb: false, ep: true, darvas: true };
const OVERLAY_DEFAULTS = {
    bb: false,
    ep: true,
    darvas: true,
    spy_rs: false,
    news_markers: false,
    vwap: false,
};

// Persisted indicator-pane visibility key — mirrors scripts/app.js.
const PANES_STORAGE_KEY = 'whats-news-panes';
const PACKS_STORAGE_KEY = 'whats-news-chart-packs';
const OVERLAYS_STORAGE_KEY = 'whats-news-chart-overlays';

// Risk box (entry/stop/target) and Darvas box price lines — kept separate
// from the KAMA/BB/EMA overlay series since they're structural levels, not
// indicators, and are drawn via createPriceLine rather than a line series.
let riskLines = { daily: [], weekly: [] };
let darvasLines = { daily: [] };
let lastDarvasBox = null;
// Prior-day + 52-week price levels (daily pane only) — PDH/PDL/PDC, not ratings.
let sessionLevels = { daily: [] };

// Default visible window after load. Daily ~6 months of sessions; weekly keeps
// a longer lookback. Double-click a price pane (fitAllContent) to see every bar.
const DAILY_DEFAULT_BARS = 126;
const WEEKLY_DEFAULT_BARS = 104;
const FIFTY_TWO_WEEK_BARS = 252;

// Live ResizeObservers — tracked so destroyCharts() can disconnect them
// before the charts they reference get remove()'d (stale observers firing
// chart.resize() on a disposed chart throws "Object is disposed").
let resizeObservers = [];

// EMA stack (Qullamaggie 10/21/50 beside KAMA) + Stockbee pack 9/20.
const EMA_PERIODS = [9, 10, 20, 21, 50];
const EMA_COLORS = { 9: '#f472b6', 10: '#fbbf24', 20: '#22d3ee', 21: '#38bdf8', 50: '#a3e635' };
const activeEma = { 9: false, 10: false, 20: false, 21: false, 50: false };

// SMA 50/150/200 — Minervini-style trend MAs (honest MA overlay, not a rating).
// SMA 10/40 — weekly trend MAs (Weinstein-style stage, not a rating); daily no-ops.
const SMA_PERIODS = [10, 40, 50, 150, 200];
const SMA_COLORS = { 10: '#4ade80', 40: '#f59e0b', 50: '#e879f9', 150: '#c084fc', 200: '#818cf8' };
const SMA_WEEKLY_ONLY = new Set([10, 40]);
const activeSma = { 10: false, 40: false, 50: false, 150: false, 200: false };

// Method packs keyed from existing setup-scanner tags (EP / Darvas / near-high).
const CHART_PACKS = {
    minervini: {
        sma: [50, 150, 200],
        ema: [],
        setups: ['DARVAS_BOX', 'DARVAS_BREAKOUT', 'NEAR_HIGH'],
    },
    stockbee: {
        sma: [],
        ema: [9, 20],
        setups: ['EP', 'VOL_SURGE', 'BREAKOUT_QUEUE'],
    },
    weinstein: {
        sma: [10, 40],
        ema: [],
        setups: [],
    },
};
const activePacks = { minervini: false, stockbee: false, weinstein: false };

// Last hovered OHLC index/time per pane — keep it when the crosshair leaves.
const lastLegend = { daily: { idx: null, time: null }, weekly: { idx: null, time: null } };

// Client-side MA values at each bar so the legend can show SMA/EMA at the held bar.
const maCache = { daily: { ema: {}, sma: {} }, weekly: { ema: {}, sma: {} } };

// ── Chart instances ─────────────────────────────────────────
let charts = {
    daily:  { main: null, volume: null, rsi: null, macd: null, trend: null },
    weekly: { main: null, volume: null, rsi: null, macd: null, trend: null },
};

// ── Series references ────────────────────────────────────────
let series = {
    daily: {
        candle: null, volume: null, volumeSma: null, bb: {}, ema: {}, sma: {}, rsi: {}, macdLine: null,
        macdSig: null, macdHist: null, trend: null,
    },
    weekly: {
        candle: null, volume: null, volumeSma: null, bb: {}, ema: {}, sma: {}, rsi: {}, macdLine: null,
        macdSig: null, macdHist: null, trend: null,
    },
};

// ── Colours ──────────────────────────────────────────────────
const C = {
    bb_upper:      '#22c55e',
    bb_middle:     '#22c55e',
    bb_lower:      '#22c55e',
    rsi7:          '#06b6d4',
    rsi14:         '#f97316',
    rsi21:         '#a855f7',
    macd_line:     '#3b82f6',
    macd_signal:   '#ef4444',
    macd_hist_pos: '#22c55e',
    macd_hist_neg: '#ef4444',
    trend_pos:     '#22c55e',
    trend_neg:     '#ef4444',
    trend_zero:    '#4a5568',
    vol_up:         '#22c55e33',
    vol_down:       '#ef444433',
    vol_surge_up:   '#fb923c',
    vol_surge_down: '#fb7185',
    vol_climax_up:  '#fdba74',
    vol_climax_down:'#fda4af',
    vol_sma:        '#7d93b0',
};

// Volume-surge / EP thresholds — mirror portfolio.py so chart markers agree with the tape.
const VOL_SURGE_RATIO = 1.5;
const VOL_CLIMAX_RATIO = 2.0;
const EP_GAP_PCT = 4.0;
const VOL_SMA_PERIOD = 20;

// ── Base chart options ────────────────────────────────────────
function baseOpts() {
    return {
        layout: {
            background: { color: '#0d1117' },
            textColor: '#8b949e',
            fontFamily: "'IBM Plex Mono', monospace",
            fontSize: 10,
        },
        grid: {
            vertLines: { color: '#1c2230' },
            horzLines: { color: '#1c2230' },
        },
        crosshair: {
            mode: LWC.CrosshairMode.Normal,
            vertLine: { color: '#3d4965', labelBackgroundColor: '#1c2230' },
            horzLine: { color: '#3d4965', labelBackgroundColor: '#1c2230' },
        },
        rightPriceScale: { borderColor: '#30363d' },
        timeScale: {
            borderColor: '#30363d',
            timeVisible: true,
            secondsVisible: false,
            rightOffset: 6,
            barSpacing: 6,
            fixLeftEdge: true,
        },
        handleScroll: true,
        handleScale: true,
    };
}

// ── Destroy all charts ────────────────────────────────────────
function destroyCharts() {
    // Stale ResizeObservers from a prior initCharts() call would otherwise
    // keep firing chart.resize() against instances we're about to remove()
    // below, throwing "Object is disposed" — disconnect them first.
    resizeObservers.forEach(ro => ro.disconnect());
    resizeObservers = [];
    ['daily', 'weekly'].forEach(freq => {
        Object.values(charts[freq]).forEach(c => { if (c) c.remove(); });
        charts[freq] = { main: null, volume: null, rsi: null, macd: null, trend: null };
        series[freq] = {
            candle: null, volume: null, volumeSma: null, bb: {}, ema: {}, sma: {}, rsi: {}, macdLine: null,
            macdSig: null, macdHist: null, trend: null,
        };
        lastLegend[freq] = { idx: null, time: null };
        maCache[freq] = { ema: {}, sma: {} };
        // Clear kama series refs
        Object.values(kamaPeriods).forEach(p => {
            p[`series_${freq}`] = null;
        });
    });
    // Price lines die with their chart — drop the stale references.
    riskLines = { daily: [], weekly: [] };
    darvasLines = { daily: [] };
    sessionLevels = { daily: [] };
    if (typeof forgetPriceAlertLines === 'function') forgetPriceAlertLines();
    if (typeof forgetSpyRsSeries === 'function') forgetSpyRsSeries();
    if (typeof forgetVwapSeries === 'function') forgetVwapSeries();
}

// ── Build one panel (daily or weekly) ────────────────────────
function buildPanel(freq) {
    const pfx   = `chart-${freq}`;
    const mainEl  = document.getElementById(`${pfx}-main`);
    const rsiEl   = document.getElementById(`${pfx}-rsi`);
    const macdEl  = document.getElementById(`${pfx}-macd`);
    const trendEl = document.getElementById(`${pfx}-trend`);

    // Price chart
    charts[freq].main = LWC.createChart(mainEl, {
        ...baseOpts(), width: mainEl.clientWidth, height: mainEl.clientHeight,
    });
    series[freq].candle = charts[freq].main.addCandlestickSeries({
        upColor: '#0d1117', downColor: '#ef4444',
        borderUpColor: '#22c55e', borderDownColor: '#ef4444',
        wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });

    // BB overlay series
    series[freq].bb.upper  = charts[freq].main.addLineSeries({ color: C.bb_upper,  lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
    series[freq].bb.middle = charts[freq].main.addLineSeries({ color: C.bb_middle, lineWidth: 1, lineStyle: 0, priceLineVisible: false, lastValueVisible: false });
    series[freq].bb.lower  = charts[freq].main.addLineSeries({ color: C.bb_lower,  lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });

    // KAMA overlay series for this panel
    Object.values(kamaPeriods).forEach(meta => {
        meta[`series_${freq}`] = charts[freq].main.addLineSeries({
            color: meta.color, lineWidth: 1.5,
            priceLineVisible: false, lastValueVisible: false,
        });
    });

    // EMA stack overlay series (10/21/50 pills + 9/20 Stockbee pack).
    EMA_PERIODS.forEach(p => {
        series[freq].ema[p] = charts[freq].main.addLineSeries({
            color: EMA_COLORS[p], lineWidth: p === 9 || p === 20 ? 2 : 1.5, lineStyle: 0,
            priceLineVisible: false, lastValueVisible: false, visible: false,
        });
    });

    // SMA packs — weekly-only 10/40 are not created on the daily pane.
    SMA_PERIODS.forEach(p => {
        if (SMA_WEEKLY_ONLY.has(p) && freq !== 'weekly') return;
        series[freq].sma[p] = charts[freq].main.addLineSeries({
            color: SMA_COLORS[p], lineWidth: p === 40 || p === 200 ? 2 : 1.5, lineStyle: p === 200 ? 2 : 0,
            priceLineVisible: false, lastValueVisible: false, visible: false,
        });
    });

    // Volume chart — price/volume first. Bars color-flip on 1.5x-avg surge.
    const volEl = document.getElementById(`${pfx}-volume`);
    charts[freq].volume = LWC.createChart(volEl, {
        ...baseOpts(), width: volEl.clientWidth, height: volEl.clientHeight,
    });
    series[freq].volume = charts[freq].volume.addHistogramSeries({
        priceFormat: { type: 'volume' },
        priceLineVisible: false, lastValueVisible: true,
    });
    // 20-bar volume SMA on the histogram pane (same window length as _avg20Vol).
    // Always-on and muted so relative volume is glanceable — not a published rating.
    series[freq].volumeSma = charts[freq].volume.addLineSeries({
        color: C.vol_sma,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
        priceFormat: { type: 'volume' },
    });

    // RSI chart
    charts[freq].rsi = LWC.createChart(rsiEl, {
        ...baseOpts(), width: rsiEl.clientWidth, height: rsiEl.clientHeight,
        rightPriceScale: { borderColor: '#30363d', autoScale: false, scaleMargins: { top: 0.05, bottom: 0.05 } },
    });
    charts[freq].rsi.priceScale('right').applyOptions({ autoScale: false });

    series[freq].rsi[7]  = charts[freq].rsi.addLineSeries({ color: C.rsi7,  lineWidth: 1,   lineStyle: 2, priceLineVisible: false, lastValueVisible: true });
    series[freq].rsi[14] = charts[freq].rsi.addLineSeries({ color: C.rsi14, lineWidth: 1.5, lineStyle: 0, priceLineVisible: false, lastValueVisible: true });
    series[freq].rsi[21] = charts[freq].rsi.addLineSeries({ color: C.rsi21, lineWidth: 1,   lineStyle: 2, priceLineVisible: false, lastValueVisible: true });
    series[freq].rsi[14].createPriceLine({ price: 80, color: '#ef444488', lineWidth: 1, lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: true, title: 'OB' });
    series[freq].rsi[14].createPriceLine({ price: 50, color: '#4a556888', lineWidth: 1, lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: false });
    series[freq].rsi[14].createPriceLine({ price: 20, color: '#22c55e88', lineWidth: 1, lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: true, title: 'OS' });

    // MACD chart
    charts[freq].macd = LWC.createChart(macdEl, {
        ...baseOpts(), width: macdEl.clientWidth, height: macdEl.clientHeight,
    });
    series[freq].macdHist = charts[freq].macd.addHistogramSeries({ color: C.macd_hist_pos, priceLineVisible: false, lastValueVisible: false });
    series[freq].macdLine = charts[freq].macd.addLineSeries({ color: C.macd_line,   lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
    series[freq].macdSig  = charts[freq].macd.addLineSeries({ color: C.macd_signal, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });

    // Trend score chart
    charts[freq].trend = LWC.createChart(trendEl, {
        ...baseOpts(), width: trendEl.clientWidth, height: trendEl.clientHeight,
        rightPriceScale: { borderColor: '#30363d', autoScale: false, scaleMargins: { top: 0.1, bottom: 0.1 } },
    });
    charts[freq].trend.priceScale('right').applyOptions({ autoScale: false });

    series[freq].trend = charts[freq].trend.addHistogramSeries({
        priceLineVisible: false, lastValueVisible: true,
    });
    // Reference line at 0
    series[freq].trend.createPriceLine({ price: 0, color: '#30363d', lineWidth: 1, lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: false });

    // Sync sub-charts to main
    syncTo(charts[freq].main, charts[freq].volume, charts[freq].rsi, charts[freq].macd, charts[freq].trend);
    syncTo(charts[freq].volume, charts[freq].main);
    syncTo(charts[freq].rsi,   charts[freq].main);
    syncTo(charts[freq].macd,  charts[freq].main);
    syncTo(charts[freq].trend, charts[freq].main);
}

function chartsAreLive() {
    return !!(charts.daily.main && charts.weekly.main);
}

function initCharts() {
    // Reuse live instances on ticker switch — disposing 10 Lightweight Charts
    // (+ observers + crosshair subscriptions) on every name is the slow path.
    if (chartsAreLive()) return;
    destroyCharts();
    buildPanel('daily');
    buildPanel('weekly');
    syncPanels();
    setupResizeObserver();
    setupCrosshairLegend();
    setupBarClickJournal();
    setupFitAllOnDoubleClick();
    applySavedPaneVisibility();
    applySavedOverlays();
    applySavedPacks();
}

function _legendTimeKey(time) {
    if (time == null) return null;
    if (typeof time === 'object' && time.year) {
        const m = String(time.month).padStart(2, '0');
        const d = String(time.day).padStart(2, '0');
        return `${time.year}-${m}-${d}`;
    }
    return String(time).slice(0, 10);
}

function _fmtPx(v) {
    return (v == null || !Number.isFinite(Number(v))) ? '—' : Number(v).toFixed(2);
}

function smaShown(freq, p) {
    return !!activeSma[p] && !(SMA_WEEKLY_ONLY.has(p) && freq !== 'weekly');
}

function _maLegendBits(freq, idx) {
    const bits = [];
    SMA_PERIODS.forEach(p => {
        if (!smaShown(freq, p)) return;
        const v = maCache[freq]?.sma?.[p]?.[idx];
        if (v == null) return;
        bits.push(`<span class="lg-ma" style="color:${SMA_COLORS[p]}">S${p} ${_fmtPx(v)}</span>`);
    });
    EMA_PERIODS.forEach(p => {
        if (!activeEma[p]) return;
        const v = maCache[freq]?.ema?.[p]?.[idx];
        if (v == null) return;
        bits.push(`<span class="lg-ma" style="color:${EMA_COLORS[p]}">E${p} ${_fmtPx(v)}</span>`);
    });
    return bits.join(' ');
}

function paintOhlcLegend(freq, param) {
    const el = document.getElementById(`chart-legend-${freq}`);
    if (!el) return;
    const rows = rawRows[freq] || [];
    if (!rows.length) {
        el.textContent = '';
        if (typeof paintLinkedTwinIfLive === 'function') paintLinkedTwinIfLive(freq);
        return;
    }
    const key = _legendTimeKey(param && param.time);
    let idx;
    if (key) {
        idx = rows.findIndex(r => String(r.date).slice(0, 10) === key);
        if (idx < 0) return; // keep last painted OHLC
        lastLegend[freq] = { idx, time: key };
    } else if (lastLegend[freq].idx != null && lastLegend[freq].idx < rows.length) {
        // Crosshair left the pane — keep the last hovered bar, don't snap to latest.
        idx = lastLegend[freq].idx;
    } else {
        idx = rows.length - 1;
        lastLegend[freq] = { idx, time: String(rows[idx].date).slice(0, 10) };
    }
    const row = rows[idx];
    const prev = rows[idx - 1];
    if (!row) {
        el.textContent = '';
        if (typeof paintLinkedTwinIfLive === 'function') paintLinkedTwinIfLive(freq);
        return;
    }
    const chg = prev && prev.close ? ((row.close / prev.close - 1) * 100) : null;
    const up = chg == null ? true : chg >= 0;
    const held = idx !== rows.length - 1;
    el.classList.toggle('legend-up', up);
    el.classList.toggle('legend-down', !up);
    el.classList.toggle('legend-held', held);
    const tone = up ? 'lg-up' : 'lg-down';
    const chgStr = chg == null ? '' : `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`;
    const vol = row.volume != null ? Number(row.volume).toLocaleString() : '—';
    const maBits = _maLegendBits(freq, idx);
    // Always-on ADR% / RVOL / 52H gap (daily) + dist-to-SMA200. Helper in legend_stats.js.
    const statBits = (typeof legendStatHtmlBits === 'function') ? legendStatHtmlBits(freq, idx) : '';
    el.innerHTML = `<span class="lg-date">${row.date}</span>`
        + ` <span class="${tone}">O ${_fmtPx(row.open)}</span>`
        + ` <span class="lg-h">H ${_fmtPx(row.high)}</span>`
        + ` <span class="lg-l">L ${_fmtPx(row.low)}</span>`
        + ` <span class="${tone}">C ${_fmtPx(row.close)}</span>`
        + (chgStr ? ` <span class="${tone}">${chgStr}</span>` : '')
        + ` <span class="lg-v">V ${vol}</span>`
        + (statBits ? ` ${statBits}` : '')
        + (maBits ? ` ${maBits}` : '');
    // Twin readout: matching weekly (or daily) bar. Helper lives in linked_ohlc.js.
    if (typeof paintLinkedTwinIfLive === 'function') paintLinkedTwinIfLive(freq);
}

function setupCrosshairLegend() {
    ['daily', 'weekly'].forEach(freq => {
        const chart = charts[freq].main;
        if (!chart) return;
        paintOhlcLegend(freq, {});
        chart.subscribeCrosshairMove(param => paintOhlcLegend(freq, param || {}));
    });
}

// Click a daily price bar → journal focused on that date.
// Weekly uses the week-ending date on the bar (same handler; empty click is a no-op).
// Daily Shift/modifier-click is delegated to onDailyPriceAlertClick when present;
// a true return skips onChartBarClick so the journal path is not stolen.
function setupBarClickJournal() {
    ['daily', 'weekly'].forEach(freq => {
        const chart = charts[freq].main;
        if (!chart) return;
        chart.subscribeClick(param => {
            if (freq === 'daily' && typeof onDailyPriceAlertClick === 'function') {
                if (onDailyPriceAlertClick(param)) return;
            }
            const date = _legendTimeKey(param && param.time);
            if (!date) return;
            if (typeof onChartBarClick === 'function') onChartBarClick({ freq, date });
        });
    });
}

// ── Within-panel sync (same freq → logical range by bar index) ──
function syncTo(source, ...targets) {
    source.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (!range) return;
        targets.forEach(t => {
            if (t && t !== source) {
                try { t.timeScale().setVisibleLogicalRange(range); } catch (_) {}
            }
        });
    });
}

// ── Cross-panel sync (daily ↔ weekly by actual date range) ────
let _crossSyncing = false;
function syncPanels() {
    const d = charts.daily.main;
    const w = charts.weekly.main;
    if (!d || !w) return;

    d.timeScale().subscribeVisibleTimeRangeChange(range => {
        if (_crossSyncing || !range) return;
        _crossSyncing = true;
        try { w.timeScale().setVisibleRange(range); } catch (_) {}
        _crossSyncing = false;
    });
    w.timeScale().subscribeVisibleTimeRangeChange(range => {
        if (_crossSyncing || !range) return;
        _crossSyncing = true;
        try { d.timeScale().setVisibleRange(range); } catch (_) {}
        _crossSyncing = false;
    });
}

// ── Chart element/instance pairs — shared by the resize observer,
//    manual resizeAllCharts(), and anything else that needs to iterate. ──
function chartResizePairs() {
    return [
        ['chart-daily-main',    charts.daily.main],
        ['chart-daily-volume',  charts.daily.volume],
        ['chart-daily-rsi',     charts.daily.rsi],
        ['chart-daily-macd',    charts.daily.macd],
        ['chart-daily-trend',   charts.daily.trend],
        ['chart-weekly-main',   charts.weekly.main],
        ['chart-weekly-volume', charts.weekly.volume],
        ['chart-weekly-rsi',    charts.weekly.rsi],
        ['chart-weekly-macd',   charts.weekly.macd],
        ['chart-weekly-trend',  charts.weekly.trend],
    ];
}

// ── Resize observer ──────────────────────────────────────────
function setupResizeObserver() {
    chartResizePairs().forEach(([id, chart]) => {
        const el = document.getElementById(id);
        if (!el || !chart) return;
        const ro = new ResizeObserver(entries => {
            for (const e of entries) {
                const { width, height } = e.contentRect;
                try { chart.resize(width, height); } catch (_) { /* chart disposed */ }
            }
        });
        ro.observe(el);
        resizeObservers.push(ro);
    });
}

// Manual resize pass — used right after toggling pane/focus-mode visibility,
// where a hidden→visible flex change may not always fire a ResizeObserver
// callback in every browser before the next paint.
function resizeAllCharts() {
    chartResizePairs().forEach(([id, chart]) => {
        const el = document.getElementById(id);
        if (!el || !chart) return;
        const rect = el.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
            try { chart.resize(rect.width, rect.height); } catch (_) { /* chart disposed */ }
        }
    });
}

// ── Data loading helpers ─────────────────────────────────────
function toLineData(arr) {
    if (!arr) return [];
    return arr.map(d => (d.value == null ? { time: d.date } : { time: d.date, value: d.value }));
}

// Raw OHLCV rows kept per-freq so EMA/EP/volume-surge overlays can be
// recomputed client-side on toggle without a re-fetch.
let rawRows = { daily: [], weekly: [] };

function computeEma(closes, period) {
    const out = new Array(closes.length).fill(null);
    if (closes.length < period) return out;
    const k = 2 / (period + 1);
    let ema = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
    out[period - 1] = ema;
    for (let i = period; i < closes.length; i++) {
        ema = closes[i] * k + ema * (1 - k);
        out[i] = ema;
    }
    return out;
}

function computeSma(closes, period) {
    const out = new Array(closes.length).fill(null);
    if (closes.length < period) return out;
    let sum = 0;
    for (let i = 0; i < closes.length; i++) {
        sum += closes[i];
        if (i >= period) sum -= closes[i - period];
        if (i >= period - 1) out[i] = sum / period;
    }
    return out;
}

function _avg20Vol(rows, i) {
    const windowVols = rows.slice(Math.max(0, i - 20), i).map(r => r.volume || 0);
    if (!windowVols.length) return null;
    return windowVols.reduce((a, b) => a + b, 0) / windowVols.length;
}

// 20-bar SMA of volume (includes the current bar). Window length matches
// _avg20Vol / RVOL so bars vs the line are glanceable relative volume —
// not a published rating.
function volumeSmaPoints(rows, period) {
    const p = period || VOL_SMA_PERIOD;
    const list = rows || [];
    const vols = list.map(r => r.volume || 0);
    const smaVals = computeSma(vols, p);
    return list.map((r, i) => (
        smaVals[i] == null ? { time: r.date } : { time: r.date, value: smaVals[i] }
    ));
}

function loadOHLCV(freq, rows) {
    if (freq === 'daily') clearSessionLevels();
    if (!series[freq].candle || !rows?.length) return;
    rawRows[freq] = rows;
    lastLegend[freq] = { idx: null, time: null };
    maCache[freq] = { ema: {}, sma: {} };

    series[freq].candle.setData(rows.map(r => ({
        time: r.date, open: r.open, high: r.high, low: r.low, close: r.close,
    })));

    // Volume — muted by direction; 1.5× surge and 2× climax pop in solid orange.
    const volRatios = new Array(rows.length).fill(null);
    if (series[freq].volume) {
        const volData = rows.map((r, i) => {
            const avg20 = _avg20Vol(rows, i);
            const ratio = avg20 ? (r.volume || 0) / avg20 : null;
            volRatios[i] = ratio;
            const up = r.close >= r.open;
            let color = up ? C.vol_up : C.vol_down;
            if (ratio != null && ratio >= VOL_CLIMAX_RATIO) {
                color = up ? C.vol_climax_up : C.vol_climax_down;
            } else if (ratio != null && ratio >= VOL_SURGE_RATIO) {
                color = up ? C.vol_surge_up : C.vol_surge_down;
            }
            return { time: r.date, value: r.volume || 0, color };
        });
        series[freq].volume.setData(volData);
        if (series[freq].volumeSma) {
            series[freq].volumeSma.setData(volumeSmaPoints(rows, VOL_SMA_PERIOD));
        }
        updateVolBadge(freq, volRatios);
    }

    const closes = rows.map(r => r.close);
    EMA_PERIODS.forEach(p => {
        const s = series[freq].ema[p];
        const vals = computeEma(closes, p);
        maCache[freq].ema[p] = vals;
        if (!s) return;
        s.setData(rows.map((r, i) => (vals[i] == null ? { time: r.date } : { time: r.date, value: vals[i] })));
    });
    SMA_PERIODS.forEach(p => {
        if (SMA_WEEKLY_ONLY.has(p) && freq !== 'weekly') return;
        const s = series[freq].sma[p];
        const vals = computeSma(closes, p);
        maCache[freq].sma[p] = vals;
        if (!s) return;
        s.setData(rows.map((r, i) => (vals[i] == null ? { time: r.date } : { time: r.date, value: vals[i] })));
    });

    applyPriceMarkers(freq);
    applyOverlayVisibility(freq);
    if (freq === 'daily') applySessionLevels();
    // vs-SPY comparison line lives in spy_rs.js (off by default).
    // Same pill drives daily + weekly; weekly SPY alignment is in spy_rs.js.
    if (typeof applySpyRsIfOn === 'function') applySpyRsIfOn();
    // User price-alert lines live in price_alerts.js (per-symbol localStorage).
    if (freq === 'daily' && typeof applyPriceAlerts === 'function') applyPriceAlerts();
    // Darvas fill lives in darvas_fill.js — refresh times after daily bars load.
    if (freq === 'daily' && typeof applyDarvasFill === 'function') applyDarvasFill(lastDarvasBox);
    // News date markers live in news_markers.js (off by default).
    if (freq === 'daily' && typeof applyNewsMarkersIfOn === 'function') applyNewsMarkersIfOn();
    // Session VWAP lives in vwap.js (off by default). Daily only — weekly skip in v1.
    if (freq === 'daily' && typeof applyVwapIfOn === 'function') applyVwapIfOn();
    paintOhlcLegend(freq, {});
}

function updateVolBadge(freq, volRatios) {
    const badge = document.getElementById(`chart-${freq}-vol-badge`);
    if (!badge) return;
    const n = volRatios.length;
    const last = n ? volRatios[n - 1] : null;
    let ago = null;
    for (let i = n - 1; i >= 0; i--) {
        if (volRatios[i] != null && volRatios[i] >= VOL_SURGE_RATIO) {
            ago = n - 1 - i;
            break;
        }
    }
    badge.classList.toggle('vol-surge-now', last != null && last >= VOL_SURGE_RATIO);
    if (last != null && last >= VOL_SURGE_RATIO) {
        badge.textContent = `NOW ${last.toFixed(1)}×`;
        badge.style.display = 'inline';
    } else if (ago != null && ago <= 15) {
        badge.textContent = `surge ${ago}b`;
        badge.style.display = 'inline';
    } else {
        badge.style.display = 'none';
    }
}

function updateEpBadge(freq, epIndexes, nBars) {
    const badge = document.getElementById(`chart-${freq}-ep-badge`);
    if (!badge) return;
    const last20 = epIndexes.filter(i => i >= nBars - 20).length;
    const lastIdx = epIndexes.length ? epIndexes[epIndexes.length - 1] : null;
    const ago = lastIdx != null ? nBars - 1 - lastIdx : null;
    if (last20 > 0) {
        badge.textContent = ago === 0 ? 'EP now' : `${last20} EP /20`;
        badge.style.display = 'inline';
    } else if (ago != null && ago <= 60) {
        badge.textContent = `EP ${ago}b`;
        badge.style.display = 'inline';
    } else {
        badge.style.display = 'none';
    }
}

// EP (episodic pivot) markers: gap-up ≥4% on ≥1.5× volume.
// 2× volume climax (non-EP) gets a below-bar square so surges stay glanceable on price.
function applyPriceMarkers(freq) {
    const s = series[freq].candle;
    if (!s) return;
    const rows = rawRows[freq] || [];
    const markers = [];
    const epIndexes = [];
    const lookback = 20;
    for (let i = 1; i < rows.length; i++) {
        const prevClose = rows[i - 1].close;
        const row = rows[i];
        if (!prevClose || !row.open) continue;
        const gapPct = (row.open / prevClose - 1) * 100;
        const avg20 = _avg20Vol(rows, i);
        const volRatio = avg20 ? (row.volume || 0) / avg20 : null;
        const isEp = gapPct >= EP_GAP_PCT && volRatio != null && volRatio >= VOL_SURGE_RATIO;
        const inLookback = i >= rows.length - lookback;
        if (isEp) {
            epIndexes.push(i);
            if (activeOverlays.ep) {
                markers.push({
                    time: row.date, position: 'aboveBar', color: '#fde047',
                    shape: 'arrowUp', text: `EP +${gapPct.toFixed(0)}%`,
                    size: inLookback ? 2 : 1,
                });
            }
        } else if (volRatio != null && volRatio >= VOL_CLIMAX_RATIO && inLookback) {
            markers.push({
                time: row.date, position: 'belowBar', color: '#38bdf8',
                shape: 'square', text: `${volRatio.toFixed(1)}×`, size: 1,
            });
        }
    }
    // News dates live in news_markers.js (off by default). Merge into this
    // array — setMarkers replaces the whole set, so a second call would drop EP.
    if (freq === 'daily' && typeof collectNewsPriceMarkers === 'function') {
        const extra = collectNewsPriceMarkers(rows);
        if (extra && extra.length) {
            for (let i = 0; i < extra.length; i++) markers.push(extra[i]);
            markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
        }
    }
    s.setMarkers(markers);
    updateEpBadge(freq, epIndexes, rows.length);
}

function applyEpMarkers(freq) {
    applyPriceMarkers(freq);
}

function loadIndicatorsToPanel(freq, data) {
    if (!data) return;

    // KAMA
    Object.entries(kamaPeriods).forEach(([p, meta]) => {
        const s = meta[`series_${freq}`];
        if (s) s.setData(toLineData(data[`kama_${p}`]));
    });

    // Bollinger Bands
    if (series[freq].bb.upper)  series[freq].bb.upper.setData(toLineData(data.bb_upper));
    if (series[freq].bb.middle) series[freq].bb.middle.setData(toLineData(data.bb_middle));
    if (series[freq].bb.lower)  series[freq].bb.lower.setData(toLineData(data.bb_lower));

    // RSI
    [7, 14, 21].forEach(p => {
        if (series[freq].rsi[p]) series[freq].rsi[p].setData(toLineData(data[`rsi_${p}`]));
    });

    // MACD
    if (series[freq].macdLine) series[freq].macdLine.setData(toLineData(data.macd_line));
    if (series[freq].macdSig)  series[freq].macdSig.setData(toLineData(data.macd_signal));
    if (series[freq].macdHist && data.macd_hist) {
        series[freq].macdHist.setData(
            data.macd_hist.map(d => {
                if (d.value == null) return { time: d.date };
                return {
                    time: d.date, value: d.value,
                    color: d.value >= 0 ? C.macd_hist_pos + 'cc' : C.macd_hist_neg + 'cc',
                };
            })
        );
    }

    // Trend score histogram — colour by score value
    if (series[freq].trend && data.trend_score) {
        series[freq].trend.setData(
            data.trend_score.map(d => {
                if (d.value == null) return { time: d.date };
                return {
                    time: d.date, value: d.value,
                    color: d.value > 0 ? C.trend_pos + 'cc'
                         : d.value < 0 ? C.trend_neg + 'cc'
                         : C.trend_zero + 'cc',
                };
            })
        );
    }

    applyOverlayVisibility(freq);
}

// ── Overlay visibility ───────────────────────────────────────
function applyOverlayVisibility(freq) {
    const showHide = (s, show, color, lw = 1, ls = 0) => {
        if (!s) return;
        s.applyOptions(show ? { color, lineWidth: lw, lineStyle: ls, visible: true } : { visible: false });
    };

    // BB
    const bbOn = activeOverlays.bb;
    showHide(series[freq].bb.upper,  bbOn, C.bb_upper,  1, 2);
    showHide(series[freq].bb.middle, bbOn, C.bb_middle, 1, 0);
    showHide(series[freq].bb.lower,  bbOn, C.bb_lower,  1, 2);

    // KAMA
    Object.values(kamaPeriods).forEach(meta => {
        const s = meta[`series_${freq}`];
        showHide(s, meta.active, meta.color, 1.5);
    });

    // EMA stack (10/21/50 pills + 9/20 pack)
    EMA_PERIODS.forEach(p => {
        const packLine = p === 9 || p === 20;
        showHide(series[freq].ema[p], activeEma[p], EMA_COLORS[p], packLine ? 2 : 1.5);
        if (series[freq].ema[p]) {
            series[freq].ema[p].applyOptions({ lastValueVisible: !!activeEma[p] && packLine });
        }
    });

    // SMA packs (10/40 weekly-only; 50/150/200 both panes)
    SMA_PERIODS.forEach(p => {
        const on = smaShown(freq, p);
        showHide(series[freq].sma[p], on, SMA_COLORS[p], p === 40 || p === 200 ? 2 : 1.5, p === 200 ? 2 : 0);
        if (series[freq].sma[p]) {
            series[freq].sma[p].applyOptions({ lastValueVisible: on });
        }
    });
}

function toggleOverlay(key) {
    activeOverlays[key] = !activeOverlays[key];
    ['daily', 'weekly'].forEach(f => {
        applyOverlayVisibility(f);
        if (key === 'ep') applyPriceMarkers(f);
    });
    if (key === 'darvas') applyDarvasBox(lastDarvasBox);
    persistOverlays();
    syncOverlayPills();
    return activeOverlays[key];
}

// ── Risk box (entry / stop / target) — daily + weekly candle series ────
function clearRiskBox() {
    ['daily', 'weekly'].forEach(freq => {
        const s = series[freq].candle;
        if (s) riskLines[freq].forEach(line => { try { s.removePriceLine(line); } catch (_) {} });
        riskLines[freq] = [];
    });
}

function applyRiskBox(entry, stop, target) {
    clearRiskBox();
    ['daily', 'weekly'].forEach(freq => {
        const s = series[freq].candle;
        if (!s) return;
        const lines = [];
        if (entry != null && Number.isFinite(entry)) {
            lines.push(s.createPriceLine({
                price: entry, color: '#22c55e', lineWidth: 2,
                lineStyle: LWC.LineStyle.Solid, axisLabelVisible: true, title: 'Entry',
            }));
        }
        if (stop != null && Number.isFinite(stop)) {
            lines.push(s.createPriceLine({
                price: stop, color: '#ef4444', lineWidth: 2,
                lineStyle: LWC.LineStyle.Solid, axisLabelVisible: true, title: 'Stop',
            }));
        }
        if (target != null && Number.isFinite(target)) {
            lines.push(s.createPriceLine({
                price: target, color: '#3b82f6', lineWidth: 2,
                lineStyle: LWC.LineStyle.Solid, axisLabelVisible: true, title: 'Target',
            }));
        }
        riskLines[freq] = lines;
    });
}

// ── Darvas box — top/bottom dashed orange, daily main only ─────────────
function clearDarvasBox() {
    const s = series.daily.candle;
    if (s) darvasLines.daily.forEach(line => { try { s.removePriceLine(line); } catch (_) {} });
    darvasLines.daily = [];
    if (typeof clearDarvasFill === 'function') clearDarvasFill();
}

function applyDarvasBox(box) {
    lastDarvasBox = box || null;
    clearDarvasBox();
    if (!lastDarvasBox || !activeOverlays.darvas) return;
    const s = series.daily.candle;
    if (!s) return;
    const lines = [];
    if (lastDarvasBox.top != null) {
        lines.push(s.createPriceLine({
            price: lastDarvasBox.top, color: '#f97316', lineWidth: 1,
            lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: true, title: 'Box top',
        }));
    }
    if (lastDarvasBox.bottom != null) {
        lines.push(s.createPriceLine({
            price: lastDarvasBox.bottom, color: '#f97316', lineWidth: 1,
            lineStyle: LWC.LineStyle.Dashed, axisLabelVisible: true, title: 'Box bottom',
        }));
    }
    darvasLines.daily = lines;
    if (typeof applyDarvasFill === 'function') applyDarvasFill(lastDarvasBox);
}

// ── Session levels: prior day high/low/close + 52-week high/low (daily) ──
function _finitePx(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}

function _samePx(a, b) {
    if (a == null || b == null) return false;
    return Math.abs(a - b) <= Math.max(0.01, Math.abs(a) * 1e-4);
}

function _addSessionLine(s, price, color, title, lineStyle) {
    const px = _finitePx(price);
    if (px == null) return null;
    return s.createPriceLine({
        price: px,
        color,
        lineWidth: 1,
        lineStyle: lineStyle || LWC.LineStyle.Dashed,
        axisLabelVisible: true,
        title,
    });
}

function clearSessionLevels() {
    const s = series.daily.candle;
    if (s) sessionLevels.daily.forEach(line => { try { s.removePriceLine(line); } catch (_) {} });
    sessionLevels.daily = [];
}

function applySessionLevels() {
    clearSessionLevels();
    const s = series.daily.candle;
    const rows = rawRows.daily || [];
    if (!s || rows.length < 2) return;
    const prior = rows[rows.length - 2];
    const pdh = _finitePx(prior.high);
    const pdl = _finitePx(prior.low);
    const pdc = _finitePx(prior.close);
    const lines = [];
    const add = line => { if (line) lines.push(line); };
    add(_addSessionLine(s, pdh, '#f87171', 'PDH'));
    add(_addSessionLine(s, pdl, '#4ade80', 'PDL'));
    add(_addSessionLine(s, pdc, '#8b949e', 'PDC'));

    const windowRows = rows.slice(Math.max(0, rows.length - FIFTY_TWO_WEEK_BARS));
    let hi = null;
    let lo = null;
    windowRows.forEach(r => {
        const h = _finitePx(r.high);
        const l = _finitePx(r.low);
        if (h != null) hi = hi == null ? h : Math.max(hi, h);
        if (l != null) lo = lo == null ? l : Math.min(lo, l);
    });
    // Skip 52H/52L when they sit on PDH/PDL so axis labels don't stack.
    if (hi != null && !_samePx(hi, pdh)) {
        add(_addSessionLine(s, hi, '#eab308', '52H', LWC.LineStyle.LargeDashed));
    }
    if (lo != null && !_samePx(lo, pdl)) {
        add(_addSessionLine(s, lo, '#06b6d4', '52L', LWC.LineStyle.LargeDashed));
    }
    sessionLevels.daily = lines;
}

// ── Indicator pane visibility (RSI / MACD / Trend) — hides both the chart
//    wrapper and its divider, on both daily + weekly, then resizes. ──────
function setIndicatorPane(pane, visible) {
    document.querySelectorAll(`.pane-optional[data-pane="${pane}"]`).forEach(el => { el.hidden = !visible; });
    document.querySelectorAll(`.chart-divider-${pane}`).forEach(el => { el.hidden = !visible; });
    const pill = document.getElementById(`pill-pane-${pane}`);
    if (pill) {
        pill.classList.toggle('active', visible);
        pill.setAttribute('aria-pressed', visible ? 'true' : 'false');
    }
    resizeAllCharts();
}

function applySavedPaneVisibility() {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(PANES_STORAGE_KEY) || '{}') || {}; } catch (_) { saved = {}; }
    // Default: every optional pane stays hidden — price-first, chart-first.
    ['rsi', 'macd', 'trend'].forEach(pane => setIndicatorPane(pane, !!saved[pane]));
}

function toggleEma(period) {
    const p = Number(period);
    activeEma[p] = !activeEma[p];
    ['daily', 'weekly'].forEach(f => {
        applyOverlayVisibility(f);
        paintOhlcLegend(f, { time: lastLegend[f].time });
    });
    return activeEma[p];
}

function syncPackPills() {
    document.querySelectorAll('[data-chart-pack]').forEach(el => {
        const on = !!activePacks[el.dataset.chartPack];
        el.classList.toggle('active-pack', on);
    });
}

function persistPacks() {
    try { localStorage.setItem(PACKS_STORAGE_KEY, JSON.stringify(activePacks)); } catch (_) {}
}

function readStoredObject(key) {
    try {
        const raw = localStorage.getItem(key);
        if (raw == null || raw === '') return null;
        const parsed = JSON.parse(raw);
        return (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) ? parsed : null;
    } catch (_) {
        return null;
    }
}

function syncOverlayPills() {
    const bb = document.getElementById('pill-bb');
    if (bb) {
        bb.classList.toggle('active-bb', !!activeOverlays.bb);
        bb.setAttribute('aria-pressed', activeOverlays.bb ? 'true' : 'false');
    }
    const ep = document.getElementById('pill-ep-markers');
    if (ep) {
        ep.classList.toggle('active-ep', !!activeOverlays.ep);
    }
    const box = document.getElementById('pill-darvas');
    if (box) {
        box.classList.toggle('active-darvas', !!activeOverlays.darvas);
    }
}

function collectOverlayState() {
    return {
        bb: !!activeOverlays.bb,
        ep: !!activeOverlays.ep,
        darvas: !!activeOverlays.darvas,
        spy_rs: (typeof spyRsIsOn === 'function') ? !!spyRsIsOn() : false,
        news_markers: (typeof newsMarkersIsOn === 'function') ? !!newsMarkersIsOn() : false,
        vwap: (typeof vwapIsOn === 'function') ? !!vwapIsOn() : false,
    };
}

function persistOverlays() {
    try { localStorage.setItem(OVERLAYS_STORAGE_KEY, JSON.stringify(collectOverlayState())); } catch (_) {}
}

function applySavedOverlays() {
    const saved = readStoredObject(OVERLAYS_STORAGE_KEY);
    // No key → user never toggled. Keep defaults (vs-SPY / News / VWAP stay off).
    if (!saved) {
        syncOverlayPills();
        return;
    }
    const merged = Object.assign({}, OVERLAY_DEFAULTS, saved);
    activeOverlays.bb = !!merged.bb;
    activeOverlays.ep = !!merged.ep;
    activeOverlays.darvas = !!merged.darvas;
    if (typeof setSpyRsOn === 'function') {
        setSpyRsOn(!!merged.spy_rs, { persist: false, apply: false });
    }
    if (typeof setNewsMarkersOn === 'function') {
        setNewsMarkersOn(!!merged.news_markers, { persist: false, apply: false });
    }
    if (typeof setVwapOn === 'function') {
        setVwapOn(!!merged.vwap, { persist: false, apply: false });
    }
    syncOverlayPills();
}

function setChartPack(id, on, opts = {}) {
    const pack = CHART_PACKS[id];
    if (!pack) return false;
    activePacks[id] = !!on;
    pack.sma.forEach(p => { activeSma[p] = !!on; });
    pack.ema.forEach(p => { activeEma[p] = !!on; });
    ['daily', 'weekly'].forEach(f => {
        applyOverlayVisibility(f);
        paintOhlcLegend(f, { time: lastLegend[f].time });
    });
    syncPackPills();
    if (opts.persist !== false) persistPacks();
    return activePacks[id];
}

function toggleChartPack(id) {
    return setChartPack(id, !activePacks[id]);
}

function setChartPacksForSetups(setups) {
    const tags = new Set(setups || []);
    if (!tags.size) return;
    Object.entries(CHART_PACKS).forEach(([id, pack]) => {
        if ((pack.setups || []).some(t => tags.has(t))) setChartPack(id, true);
    });
}

function applySavedPacks() {
    const saved = readStoredObject(PACKS_STORAGE_KEY);
    if (!saved) {
        syncPackPills();
        return;
    }
    Object.keys(CHART_PACKS).forEach(id => {
        if (saved[id] != null) setChartPack(id, !!saved[id], { persist: false });
    });
    syncPackPills();
}

function toggleSma(period) {
    const p = Number(period);
    activeSma[p] = !activeSma[p];
    ['daily', 'weekly'].forEach(f => {
        applyOverlayVisibility(f);
        paintOhlcLegend(f, { time: lastLegend[f].time });
    });
    return activeSma[p];
}

// ── KAMA period management ────────────────────────────────────
/**
 * Add a KAMA period. If charts exist, adds live series to both panels.
 * Returns the color assigned.
 */
function addKamaPeriod(period) {
    const p = String(period);
    if (kamaPeriods[p]) return null; // already present

    const color = nextKamaColor();
    kamaPeriods[p] = { color, active: true, series_daily: null, series_weekly: null };

    // If charts are already built, add the series live
    if (charts.daily.main) {
        kamaPeriods[p].series_daily = charts.daily.main.addLineSeries({
            color, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false,
        });
    }
    if (charts.weekly.main) {
        kamaPeriods[p].series_weekly = charts.weekly.main.addLineSeries({
            color, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false,
        });
    }
    return color;
}

function removeKamaPeriod(period) {
    const p = String(period);
    if (!kamaPeriods[p]) return;
    // Remove series from both charts
    ['daily', 'weekly'].forEach(freq => {
        const s = kamaPeriods[p][`series_${freq}`];
        if (s && charts[freq].main) {
            try { charts[freq].main.removeSeries(s); } catch (_) {}
        }
    });
    delete kamaPeriods[p];
}

function toggleKamaPeriod(period) {
    const p = String(period);
    if (!kamaPeriods[p]) return;
    kamaPeriods[p].active = !kamaPeriods[p].active;
    ['daily', 'weekly'].forEach(f => applyOverlayVisibility(f));
    return kamaPeriods[p].active;
}

function _fitPaneToBars(chart, n, bars) {
    if (!chart || !n) return;
    const from = Math.max(0, n - bars);
    try {
        chart.timeScale().setVisibleLogicalRange({ from, to: n });
    } catch (_) { /* chart disposed */ }
}

function _unlockCrossSync() {
    requestAnimationFrame(() => { _crossSyncing = false; });
}

function fitContent() {
    // Default daily view: last ~6 months of bars. Full-history zoom-out is slow to read.
    // Weekly keeps a longer lookback. Double-click a price pane for every bar.
    const dailyN = (rawRows.daily || []).length;
    const weeklyN = (rawRows.weekly || []).length;
    _crossSyncing = true;
    try {
        _fitPaneToBars(charts.daily.main, dailyN, DAILY_DEFAULT_BARS);
        _fitPaneToBars(charts.weekly.main, weeklyN, WEEKLY_DEFAULT_BARS);
    } finally {
        _unlockCrossSync();
    }
}

function fitAllContent() {
    _crossSyncing = true;
    try {
        if (charts.daily.main) charts.daily.main.timeScale().fitContent();
        if (charts.weekly.main) charts.weekly.main.timeScale().fitContent();
    } catch (_) { /* chart disposed */ }
    _unlockCrossSync();
}

// News headline → daily bar. Exact YYYY-MM-DD match against rawRows.daily
// (same key newsDateKey emits). No weekend snap — caller toasts a miss.
function dailyBarIndexForDate(date, rows) {
    const key = String(date || '').slice(0, 10);
    if (!key) return -1;
    const bars = Array.isArray(rows) ? rows : ((typeof rawRows !== 'undefined' && rawRows && rawRows.daily) ? rawRows.daily : []);
    for (let i = 0; i < bars.length; i++) {
        const barKey = String(bars[i] && bars[i].date != null ? bars[i].date : '').slice(0, 10);
        if (barKey === key) return i;
    }
    return -1;
}

function scrollDailyToDate(date, rowsOpt) {
    const rows = Array.isArray(rowsOpt)
        ? rowsOpt
        : ((typeof rawRows !== 'undefined' && rawRows && rawRows.daily) ? rawRows.daily : []);
    const idx = dailyBarIndexForDate(date, rows);
    if (idx < 0) return false;
    const chart = charts.daily && charts.daily.main;
    if (!chart || !chart.timeScale) return false;
    const n = rows.length;
    const pad = Math.max(8, Math.floor(DAILY_DEFAULT_BARS / 2));
    const fromIdx = Math.max(0, idx - pad);
    const toIdx = Math.min(n - 1, Math.max(fromIdx, idx + pad));
    const fromTime = rows[fromIdx] && rows[fromIdx].date;
    const toTime = rows[toIdx] && rows[toIdx].date;
    try {
        const scale = chart.timeScale();
        if (fromTime && toTime && fromIdx !== toIdx) {
            scale.setVisibleRange({ from: fromTime, to: toTime });
        } else {
            const fromEnd = (n - 1) - idx;
            scale.scrollToPosition(-fromEnd, false);
        }
        scale.setVisibleLogicalRange({ from: fromIdx, to: toIdx + 1 });
    } catch (_) { /* chart disposed or range rejected */ }
    return true;
}

function scrollToLatestBar() {
    // Jump both price panes to the latest bar / real-time right edge.
    // Restores the default ~126-session daily window (weekly longer lookback)
    // if the user had panned away. Double-click still fits all bars.
    const dailyN = (rawRows.daily || []).length;
    const weeklyN = (rawRows.weekly || []).length;
    _crossSyncing = true;
    try {
        _fitPaneToBars(charts.daily.main, dailyN, DAILY_DEFAULT_BARS);
        _fitPaneToBars(charts.weekly.main, weeklyN, WEEKLY_DEFAULT_BARS);
        if (charts.daily.main) {
            try { charts.daily.main.timeScale().scrollToRealTime(); } catch (_) {}
        }
        if (charts.weekly.main) {
            try { charts.weekly.main.timeScale().scrollToRealTime(); } catch (_) {}
        }
    } finally {
        _unlockCrossSync();
    }
}

function setupFitAllOnDoubleClick() {
    ['chart-daily-main', 'chart-weekly-main'].forEach(id => {
        const el = document.getElementById(id);
        if (!el || el.dataset.wnFitAll) return;
        el.dataset.wnFitAll = '1';
        el.title = 'Double-click to fit all data';
        el.addEventListener('dblclick', () => fitAllContent());
    });
}

// ── Public API for app.js (process-tools popover, pane pills, focus mode) ──
window.applyRiskBox      = applyRiskBox;
window.clearRiskBox      = clearRiskBox;
window.applyDarvasBox    = applyDarvasBox;
window.setIndicatorPane  = setIndicatorPane;
window.resizeAllCharts   = resizeAllCharts;
window.toggleChartPack   = toggleChartPack;
window.setChartPack      = setChartPack;
window.setChartPacksForSetups = setChartPacksForSetups;
window.chartsAreLive     = chartsAreLive;
window.fitAllContent     = fitAllContent;
window.scrollDailyToDate = scrollDailyToDate;
window.dailyBarIndexForDate = dailyBarIndexForDate;
window.scrollToLatestBar = scrollToLatestBar;

if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
        applySavedOverlays();
        applySavedPacks();
    });
}
