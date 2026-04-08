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
const activeOverlays = { bb: true };

// ── Chart instances ─────────────────────────────────────────
let charts = {
    daily:  { main: null, rsi: null, macd: null, trend: null },
    weekly: { main: null, rsi: null, macd: null, trend: null },
};

// ── Series references ────────────────────────────────────────
let series = {
    daily: {
        candle: null, bb: {}, rsi: {}, macdLine: null,
        macdSig: null, macdHist: null, trend: null,
    },
    weekly: {
        candle: null, bb: {}, rsi: {}, macdLine: null,
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
};

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
    ['daily', 'weekly'].forEach(freq => {
        Object.values(charts[freq]).forEach(c => { if (c) c.remove(); });
        charts[freq] = { main: null, rsi: null, macd: null, trend: null };
        series[freq] = {
            candle: null, bb: {}, rsi: {}, macdLine: null,
            macdSig: null, macdHist: null, trend: null,
        };
        // Clear kama series refs
        Object.values(kamaPeriods).forEach(p => {
            p[`series_${freq}`] = null;
        });
    });
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
    syncTo(charts[freq].main, charts[freq].rsi, charts[freq].macd, charts[freq].trend);
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

// ── Resize observer ──────────────────────────────────────────
function setupResizeObserver() {
    const pairs = [
        ['chart-daily-main',   charts.daily.main],
        ['chart-daily-rsi',    charts.daily.rsi],
        ['chart-daily-macd',   charts.daily.macd],
        ['chart-daily-trend',  charts.daily.trend],
        ['chart-weekly-main',  charts.weekly.main],
        ['chart-weekly-rsi',   charts.weekly.rsi],
        ['chart-weekly-macd',  charts.weekly.macd],
        ['chart-weekly-trend', charts.weekly.trend],
    ];
    pairs.forEach(([id, chart]) => {
        const el = document.getElementById(id);
        if (!el || !chart) return;
        new ResizeObserver(entries => {
            for (const e of entries) {
                const { width, height } = e.contentRect;
                chart.resize(width, height);
            }
        }).observe(el);
    });
}

// ── Data loading helpers ─────────────────────────────────────
function toLineData(arr) {
    if (!arr) return [];
    return arr.map(d => (d.value == null ? { time: d.date } : { time: d.date, value: d.value }));
}

function loadOHLCV(freq, rows) {
    if (!series[freq].candle || !rows?.length) return;
    series[freq].candle.setData(rows.map(r => ({
        time: r.date, open: r.open, high: r.high, low: r.low, close: r.close,
    })));
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
}

function toggleOverlay(key) {
    activeOverlays[key] = !activeOverlays[key];
    ['daily', 'weekly'].forEach(f => applyOverlayVisibility(f));
    return activeOverlays[key];
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
