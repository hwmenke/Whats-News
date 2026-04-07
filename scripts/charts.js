/**
 * charts.js — TradingView Lightweight Charts renderer
 * Handles candlestick chart, indicator overlays, and sub-charts.
 */

const LWC = LightweightCharts;

// Shared chart instances
let mainChart = null;
let rsiChart = null;
let macdChart = null;
let volChart = null;

// Series references
let candleSeries = null;
let smaSeries = {};
let emaSeries = {};
let bbSeries = {};
let rsiSeries = null;
let macdLineSeries = null;
let macdSignalSeries = null;
let macdHistSeries = null;
let obsSeries = null;
let volSeries = null;
let volSmaSeries = null;

// Active overlay flags
const activeOverlays = {
    sma20: true, sma50: true, sma200: false,
    ema12: false, ema26: false, bb: true
};

// Chart color palette
const COLORS = {
    sma20: '#3b82f6',
    sma50: '#eab308',
    sma200: '#a855f7',
    ema12: '#06b6d4',
    ema26: '#f97316',
    bb_upper: '#22c55e',
    bb_middle: '#22c55e',
    bb_lower: '#22c55e',
    rsi: '#f97316',
    macd_line: '#3b82f6',
    macd_signal: '#ef4444',
    macd_hist_pos: '#22c55e',
    macd_hist_neg: '#ef4444',
    vol: '#3b82f6',
    vol_sma: '#f97316',
};

// Default chart options
function baseChartOpts(container) {
    return {
        layout: {
            background: { color: '#0d1117' },
            textColor: '#8b949e',
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: 11,
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
        rightPriceScale: {
            borderColor: '#30363d',
        },
        timeScale: {
            borderColor: '#30363d',
            timeVisible: true,
            secondsVisible: false,
            rightOffset: 8,
            barSpacing: 8,
            fixLeftEdge: true,
        },
        handleScroll: true,
        handleScale: true,
    };
}

function destroyCharts() {
    if (mainChart) { mainChart.remove(); mainChart = null; }
    if (rsiChart) { rsiChart.remove(); rsiChart = null; }
    if (macdChart) { macdChart.remove(); macdChart = null; }
    if (volChart) { volChart.remove(); volChart = null; }
    smaSeries = {}; emaSeries = {}; bbSeries = {};
    candleSeries = rsiSeries = macdLineSeries = macdSignalSeries =
        macdHistSeries = volSeries = volSmaSeries = null;
}

function initCharts() {
    destroyCharts();

    const mainEl = document.getElementById('chart-main');
    const rsiEl = document.getElementById('chart-rsi');
    const macdEl = document.getElementById('chart-macd');
    const volEl = document.getElementById('chart-vol');

    // ── Main price chart ──────────────────────────────────────
    mainChart = LWC.createChart(mainEl, {
        ...baseChartOpts(mainEl),
        width: mainEl.clientWidth,
        height: mainEl.clientHeight,
    });

    candleSeries = mainChart.addCandlestickSeries({
        upColor: '#22c55e',
        downColor: '#ef4444',
        borderUpColor: '#22c55e',
        borderDownColor: '#ef4444',
        wickUpColor: '#22c55e',
        wickDownColor: '#ef4444',
    });

    // Overlay series (hidden until activated)
    ['sma20', 'sma50', 'sma200'].forEach(k => {
        smaSeries[k] = mainChart.addLineSeries({ color: COLORS[k], lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false });
    });
    ['ema12', 'ema26'].forEach(k => {
        emaSeries[k] = mainChart.addLineSeries({ color: COLORS[k], lineWidth: 1.5, lineStyle: 1, priceLineVisible: false, lastValueVisible: false });
    });
    bbSeries.upper = mainChart.addLineSeries({ color: COLORS.bb_upper, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });
    bbSeries.middle = mainChart.addLineSeries({ color: COLORS.bb_middle, lineWidth: 1, lineStyle: 0, priceLineVisible: false, lastValueVisible: false });
    bbSeries.lower = mainChart.addLineSeries({ color: COLORS.bb_lower, lineWidth: 1, lineStyle: 2, priceLineVisible: false, lastValueVisible: false });

    // ── RSI sub-chart ─────────────────────────────────────────
    rsiChart = LWC.createChart(rsiEl, {
        ...baseChartOpts(rsiEl),
        width: rsiEl.clientWidth,
        height: rsiEl.clientHeight,
        rightPriceScale: { borderColor: '#30363d', autoScale: false, scaleMargins: { top: 0.05, bottom: 0.05 } },
    });
    rsiChart.priceScale('right').applyOptions({ autoScale: false });

    rsiSeries = rsiChart.addLineSeries({
        color: COLORS.rsi, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true,
    });
    // OB/OS reference lines
    rsiChart.addLineSeries({ color: '#ef4444', lineWidth: 1, lineStyle: 3, priceLineVisible: false, lastValueVisible: false })
        .setData([{ time: '1990-01-01', value: 70 }, { time: '2099-01-01', value: 70 }]);
    rsiChart.addLineSeries({ color: '#22c55e', lineWidth: 1, lineStyle: 3, priceLineVisible: false, lastValueVisible: false })
        .setData([{ time: '1990-01-01', value: 30 }, { time: '2099-01-01', value: 30 }]);

    // ── MACD sub-chart ────────────────────────────────────────
    macdChart = LWC.createChart(macdEl, {
        ...baseChartOpts(macdEl),
        width: macdEl.clientWidth,
        height: macdEl.clientHeight,
    });

    macdHistSeries = macdChart.addHistogramSeries({
        color: COLORS.macd_hist_pos,
        priceLineVisible: false,
        lastValueVisible: false,
    });
    macdLineSeries = macdChart.addLineSeries({
        color: COLORS.macd_line, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false,
    });
    macdSignalSeries = macdChart.addLineSeries({
        color: COLORS.macd_signal, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false,
    });

    // ── Volume sub-chart ──────────────────────────────────────
    volChart = LWC.createChart(volEl, {
        ...baseChartOpts(volEl),
        width: volEl.clientWidth,
        height: volEl.clientHeight,
    });

    volSeries = volChart.addHistogramSeries({
        color: COLORS.vol + '99',
        priceLineVisible: false, lastValueVisible: false,
        priceFormat: { type: 'volume' },
    });
    volSmaSeries = volChart.addLineSeries({
        color: COLORS.vol_sma, lineWidth: 1.5, priceLineVisible: false, lastValueVisible: false,
    });

    // Sync all sub-charts scroll/scale with main
    syncCharts(mainChart, rsiChart, macdChart, volChart);
    syncCharts(rsiChart, mainChart);
    syncCharts(macdChart, mainChart);
    syncCharts(volChart, mainChart);

    // Resize observer
    setupResizeObserver();
}

// ── Sync time scales ────────────────────────────────────────
function syncCharts(source, ...targets) {
    source.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (!range) return;
        targets.forEach(t => {
            if (t && t !== source) {
                try { t.timeScale().setVisibleLogicalRange(range); } catch (_) { }
            }
        });
    });
}

// ── Resize ──────────────────────────────────────────────────
function setupResizeObserver() {
    const ids = ['chart-main', 'chart-rsi', 'chart-macd', 'chart-vol'];
    const charts = [mainChart, rsiChart, macdChart, volChart];
    ids.forEach((id, i) => {
        const el = document.getElementById(id);
        if (!el) return;
        new ResizeObserver(entries => {
            for (const entry of entries) {
                const { width, height } = entry.contentRect;
                if (charts[i]) charts[i].resize(width, height);
            }
        }).observe(el);
    });
}

// ── Load OHLCV data ────────────────────────────────────────
function loadOHLCV(rows) {
    if (!candleSeries || !rows || !rows.length) return;

    const candles = rows.map(r => ({
        time: r.date,
        open: r.open,
        high: r.high,
        low: r.low,
        close: r.close,
    }));

    const volumes = rows.map(r => ({
        time: r.date,
        value: r.volume,
        color: r.close >= r.open ? '#22c55e55' : '#ef444455',
    }));

    candleSeries.setData(candles);
    if (volSeries) volSeries.setData(volumes);
}

// ── Load indicators ─────────────────────────────────────────
function loadIndicators(data) {
    if (!data) return;

    function toLineData(arr) {
        if (!arr) return [];
        return arr.filter(d => d.value !== null && d.value !== undefined).map(d => ({ time: d.date, value: d.value }));
    }

    // Moving averages
    if (smaSeries.sma20) smaSeries.sma20.setData(toLineData(data.sma_20));
    if (smaSeries.sma50) smaSeries.sma50.setData(toLineData(data.sma_50));
    if (smaSeries.sma200) smaSeries.sma200.setData(toLineData(data.sma_200));
    if (emaSeries.ema12) emaSeries.ema12.setData(toLineData(data.ema_12));
    if (emaSeries.ema26) emaSeries.ema26.setData(toLineData(data.ema_26));

    // Bollinger Bands
    if (bbSeries.upper) bbSeries.upper.setData(toLineData(data.bb_upper));
    if (bbSeries.middle) bbSeries.middle.setData(toLineData(data.bb_middle));
    if (bbSeries.lower) bbSeries.lower.setData(toLineData(data.bb_lower));

    // RSI
    if (rsiSeries) rsiSeries.setData(toLineData(data.rsi));

    // MACD
    if (macdLineSeries) macdLineSeries.setData(toLineData(data.macd_line));
    if (macdSignalSeries) macdSignalSeries.setData(toLineData(data.macd_signal));
    if (macdHistSeries && data.macd_hist) {
        const histData = data.macd_hist
            .filter(d => d.value !== null && d.value !== undefined)
            .map(d => ({
                time: d.date,
                value: d.value,
                color: d.value >= 0 ? COLORS.macd_hist_pos + 'cc' : COLORS.macd_hist_neg + 'cc',
            }));
        macdHistSeries.setData(histData);
    }

    // Volume SMA overlay
    if (volSmaSeries) volSmaSeries.setData(toLineData(data.vol_sma_20));

    // Apply visibility based on active toggles
    applyOverlayVisibility();
}

// ── Overlay visibility toggle ───────────────────────────────
function applyOverlayVisibility() {
    const invisible = { color: 'transparent', visible: false };
    const showHide = (series, show, color, lineWidth = 1.5, lineStyle = 0) => {
        if (!series) return;
        series.applyOptions(show
            ? { color, lineWidth, lineStyle, visible: true }
            : { visible: false }
        );
    };

    showHide(smaSeries.sma20, activeOverlays.sma20, COLORS.sma20, 1.5);
    showHide(smaSeries.sma50, activeOverlays.sma50, COLORS.sma50, 1.5);
    showHide(smaSeries.sma200, activeOverlays.sma200, COLORS.sma200, 1.5);
    showHide(emaSeries.ema12, activeOverlays.ema12, COLORS.ema12, 1.5, 1);
    showHide(emaSeries.ema26, activeOverlays.ema26, COLORS.ema26, 1.5, 1);

    const bbVisible = activeOverlays.bb;
    showHide(bbSeries.upper, bbVisible, COLORS.bb_upper, 1, 2);
    showHide(bbSeries.middle, bbVisible, COLORS.bb_middle, 1, 0);
    showHide(bbSeries.lower, bbVisible, COLORS.bb_lower, 1, 2);
}

function toggleOverlay(key) {
    activeOverlays[key] = !activeOverlays[key];
    applyOverlayVisibility();
    return activeOverlays[key];
}

function fitContent() {
    if (mainChart) mainChart.timeScale().fitContent();
}
