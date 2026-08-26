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

// Overlay state
const activeOverlays = { bb: true, ep: true, darvas: true, stage: true };

// Persisted indicator-pane visibility key — mirrors scripts/app.js.
const PANES_STORAGE_KEY = 'whats-news-panes';

// Risk box (entry/stop/target) and Darvas box price lines — kept separate
// from the KAMA/BB/EMA overlay series since they're structural levels, not
// indicators, and are drawn via createPriceLine rather than a line series.
let riskLines = { daily: [], weekly: [] };
let darvasLines = { daily: [] };
let lastDarvasBox = null;
let stageSmaSeries = null; // weekly SMA30 line for stage analysis
let lastStageSmaData = [];

// Live ResizeObservers — tracked so destroyCharts() can disconnect them
// before the charts they reference get remove()'d (stale observers firing
// chart.resize() on a disposed chart throws "Object is disposed").
let resizeObservers = [];

// EMA stack (Qullamaggie "optional, beside KAMA") — off by default.
const EMA_PERIODS = [10, 21, 50];
const EMA_COLORS = { 10: '#fbbf24', 21: '#38bdf8', 50: '#a3e635' };
const activeEma = { 10: false, 21: false, 50: false };

// ── Chart instances ─────────────────────────────────────────
let charts = {
    daily:  { main: null, volume: null, rsi: null, macd: null, trend: null },
    weekly: { main: null, volume: null, rsi: null, macd: null, trend: null },
};

// ── Series references ────────────────────────────────────────
let series = {
    daily: {
        candle: null, volume: null, bb: {}, ema: {}, rsi: {}, macdLine: null,
        macdSig: null, macdHist: null, trend: null,
    },
    weekly: {
        candle: null, volume: null, bb: {}, ema: {}, rsi: {}, macdLine: null,
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
    vol_up:        '#22c55e66',
    vol_down:      '#ef444466',
    vol_surge_up:   '#f97316',
    vol_surge_down: '#f97316',
};

// Volume-surge / EP thresholds — mirror portfolio.py so chart markers agree with the tape.
const VOL_SURGE_RATIO = 1.5;
const EP_GAP_PCT = 4.0;

// ── Base chart options ────────────────────────────────────────
function baseOpts() {
    return {
        layout: {
            background: { color: '#0d1117' },
            textColor: '#8b949e',
            fontFamily: "'JetBrains Mono', monospace",
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
            candle: null, volume: null, bb: {}, ema: {}, rsi: {}, macdLine: null,
            macdSig: null, macdHist: null, trend: null,
        };
        // Clear kama series refs
        Object.values(kamaPeriods).forEach(p => {
            p[`series_${freq}`] = null;
        });
    });
    // Price lines die with their chart — drop the stale references.
    riskLines = { daily: [], weekly: [] };
    darvasLines = { daily: [] };
    stageSmaSeries = null;
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
        upColor: '#22c55e', downColor: '#ef4444',
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

    // EMA stack overlay series (10/21/50) — optional, off by default.
    EMA_PERIODS.forEach(p => {
        series[freq].ema[p] = charts[freq].main.addLineSeries({
            color: EMA_COLORS[p], lineWidth: 1.5, lineStyle: 0,
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
        priceLineVisible: false, lastValueVisible: false,
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

function initCharts() {
    destroyCharts();
    buildPanel('daily');
    buildPanel('weekly');
    syncPanels();
    setupResizeObserver();
    setupCrosshairLegend();
    applySavedPaneVisibility();
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

function paintOhlcLegend(freq, param) {
    const el = document.getElementById(`chart-legend-${freq}`);
    if (!el) return;
    const rows = rawRows[freq] || [];
    if (!rows.length) { el.textContent = ''; return; }
    const key = _legendTimeKey(param && param.time);
    let idx = key ? rows.findIndex(r => String(r.date).slice(0, 10) === key) : -1;
    if (idx < 0) idx = rows.length - 1;
    const row = rows[idx];
    const prev = rows[idx - 1];
    if (!row) { el.textContent = ''; return; }
    const n = v => (v == null || !Number.isFinite(Number(v)) ? '—' : Number(v).toFixed(2));
    const chg = prev && prev.close ? ((row.close / prev.close - 1) * 100) : null;
    const up = chg == null ? true : chg >= 0;
    el.classList.toggle('legend-up', up);
    el.classList.toggle('legend-down', !up);
    const chgStr = chg == null ? '' : `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%`;
    const vol = row.volume != null ? Number(row.volume).toLocaleString() : '—';
    el.textContent = `${row.date}  O ${n(row.open)}  H ${n(row.high)}  L ${n(row.low)}  C ${n(row.close)}  ${chgStr}  V ${vol}`;
}

function setupCrosshairLegend() {
    ['daily', 'weekly'].forEach(freq => {
        const chart = charts[freq].main;
        if (!chart) return;
        paintOhlcLegend(freq, {});
        chart.subscribeCrosshairMove(param => paintOhlcLegend(freq, param || {}));
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

function loadOHLCV(freq, rows) {
    if (!series[freq].candle || !rows?.length) return;
    rawRows[freq] = rows;

    series[freq].candle.setData(rows.map(r => ({
        time: r.date, open: r.open, high: r.high, low: r.low, close: r.close,
    })));

    // Volume — colored by direction, surge bars (>=1.5x 20-bar avg) flagged orange.
    if (series[freq].volume) {
        const vols = rows.map(r => r.volume || 0);
        let surgeCount = 0;
        const volData = rows.map((r, i) => {
            const windowVols = vols.slice(Math.max(0, i - 20), i);
            const avg20 = windowVols.length ? windowVols.reduce((a, b) => a + b, 0) / windowVols.length : null;
            const isSurge = avg20 && vols[i] / avg20 >= VOL_SURGE_RATIO;
            if (isSurge) surgeCount++;
            const up = r.close >= r.open;
            const color = isSurge ? (up ? C.vol_surge_up : C.vol_surge_down) : (up ? C.vol_up : C.vol_down);
            return { time: r.date, value: r.volume || 0, color };
        });
        series[freq].volume.setData(volData);

        const badge = document.getElementById(`chart-${freq}-vol-badge`);
        if (badge) {
            const last3Surges = volData.slice(-3).filter((_, i) => {
                const idx = volData.length - 3 + i;
                return idx >= 0 && volData[idx] && (volData[idx].color === C.vol_surge_up || volData[idx].color === C.vol_surge_down);
            }).length;
            if (last3Surges > 0) {
                badge.textContent = `${last3Surges}× surge (3 bars)`;
                badge.style.display = 'inline';
            } else {
                badge.style.display = 'none';
            }
        }
    }

    // EMA stack — client-side, mirrors optional KAMA overlay.
    const closes = rows.map(r => r.close);
    EMA_PERIODS.forEach(p => {
        const s = series[freq].ema[p];
        if (!s) return;
        const vals = computeEma(closes, p);
        s.setData(rows.map((r, i) => (vals[i] == null ? { time: r.date } : { time: r.date, value: vals[i] })));
    });

    applyEpMarkers(freq);
    applyOverlayVisibility(freq);
    paintOhlcLegend(freq, {});
}

// EP (episodic pivot) markers: gap-up ≥4% on ≥1.5x volume — the entry path
// that actually matters for momentum, distinct from RSI OB/OS alerts.
function applyEpMarkers(freq) {
    const s = series[freq].candle;
    if (!s) return;
    if (!activeOverlays.ep) {
        s.setMarkers([]);
        return;
    }
    const rows = rawRows[freq] || [];
    const markers = [];
    for (let i = 1; i < rows.length; i++) {
        const prevClose = rows[i - 1].close;
        const row = rows[i];
        if (!prevClose || !row.open) continue;
        const gapPct = (row.open / prevClose - 1) * 100;
        const windowVols = rows.slice(Math.max(0, i - 20), i).map(r => r.volume || 0);
        const avg20 = windowVols.length ? windowVols.reduce((a, b) => a + b, 0) / windowVols.length : null;
        const volRatio = avg20 ? (row.volume || 0) / avg20 : null;
        if (gapPct >= EP_GAP_PCT && volRatio != null && volRatio >= VOL_SURGE_RATIO) {
            markers.push({
                time: row.date, position: 'aboveBar', color: '#f97316',
                shape: 'arrowUp', text: `EP +${gapPct.toFixed(0)}%`,
            });
        }
    }
    s.setMarkers(markers);
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

    // EMA stack (10/21/50) — optional overlay, off by default
    EMA_PERIODS.forEach(p => {
        showHide(series[freq].ema[p], activeEma[p], EMA_COLORS[p], 1.5);
    });
}

function toggleOverlay(key) {
    activeOverlays[key] = !activeOverlays[key];
    ['daily', 'weekly'].forEach(f => {
        applyOverlayVisibility(f);
        if (key === 'ep') applyEpMarkers(f);
    });
    if (key === 'darvas') applyDarvasBox(lastDarvasBox);
    if (key === 'stage') applyStageSma(lastStageSmaData);
    return activeOverlays[key];
}

function ensureStageSmaSeries() {
    if (stageSmaSeries || !charts.weekly?.main) return;
    stageSmaSeries = charts.weekly.main.addLineSeries({
        color: '#14b8a6',
        lineWidth: 2,
        lineStyle: LWC.LineStyle.Solid,
        title: '30W SMA',
        priceLineVisible: false,
        lastValueVisible: true,
    });
}

function applyStageSma(points) {
    lastStageSmaData = points || [];
    ensureStageSmaSeries();
    if (!stageSmaSeries) return;
    if (!activeOverlays.stage || !lastStageSmaData.length) {
        stageSmaSeries.setData([]);
        stageSmaSeries.applyOptions({ visible: false });
        return;
    }
    const data = lastStageSmaData
        .filter(p => p.time && p.value != null)
        .map(p => ({ time: p.time, value: p.value }));
    stageSmaSeries.setData(data);
    stageSmaSeries.applyOptions({ visible: true, color: '#14b8a6', lineWidth: 2 });
}

function clearStageSma() {
    lastStageSmaData = [];
    if (stageSmaSeries) {
        try { stageSmaSeries.setData([]); } catch (_) {}
    }
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
}

// ── Indicator pane visibility (RSI / MACD / Trend) — hides both the chart
//    wrapper and its divider, on both daily + weekly, then resizes. ──────
function setIndicatorPane(pane, visible) {
    document.querySelectorAll(`.pane-optional[data-pane="${pane}"]`).forEach(el => { el.hidden = !visible; });
    document.querySelectorAll(`.chart-divider-${pane}`).forEach(el => { el.hidden = !visible; });
    const pill = document.getElementById(`pill-pane-${pane}`);
    if (pill) pill.classList.toggle('active', visible);
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
    ['daily', 'weekly'].forEach(f => applyOverlayVisibility(f));
    return activeEma[p];
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

function fitContent() {
    // Only fit the daily panel — the cross-panel sync propagates the date range to weekly.
    // Fitting both independently would leave them showing different periods.
    if (charts.daily.main) charts.daily.main.timeScale().fitContent();
}

// ── Public API for app.js (process-tools popover, pane pills, focus mode) ──
window.applyRiskBox      = applyRiskBox;
window.clearRiskBox      = clearRiskBox;
window.applyDarvasBox    = applyDarvasBox;
window.applyStageSma     = applyStageSma;
window.clearStageSma     = clearStageSma;
window.setIndicatorPane  = setIndicatorPane;
window.resizeAllCharts   = resizeAllCharts;
