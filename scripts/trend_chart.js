/**
 * trend_chart.js — Adaptive Trend System chart renderer
 * Uses TradingView Lightweight Charts.
 *
 * Renders:
 *   - Price chart: candlesticks + SB/MB/LB baselines + SDB/MRT/MDB/LRT/LDB bands
 *   - Regime chart: short/medium/long state histograms
 *   - Entry markers on price chart
 *   - Signal summary cards (current values)
 */

// ── State ────────────────────────────────────────────────────
const trendState = {
    method:       'kama',
    freq:         'daily',
    visibleLines: { lb: true, lrt: true, ldb: true },
    data:         null,
};

// ── Chart instances ──────────────────────────────────────────
let trendCharts = {
    price:   null,
    regime:  null,
    regimes: null,  // multi-regime history panel
};

// ── Series ───────────────────────────────────────────────────
let trendSeries = {
    candle:  null,
    sb:      null,
    mb:      null,
    lb:      null,
    sdb:     null,
    mrt:     null,
    mdb:     null,
    lrt:     null,
    ldb:     null,
    // regime sub-chart (single medium state)
    regime:  null,
    // regimes history chart
    shortReg:  null,
    medReg:    null,
    longReg:   null,
};

// ── Colors ───────────────────────────────────────────────────
const TC = {
    sb:       '#3b82f6',   // blue  — fast baseline
    mb:       '#ef4444',   // red   — medium baseline
    lb:       '#f97316',   // orange — long baseline
    sdb:      '#22c55e',   // bright green — short TP band
    mdb:      '#16a34a',   // darker green — medium TP band
    ldb:      '#06b6d4',   // cyan — long TP band
    mrt:      '#374151',   // dark gray — medium stop
    lrt:      '#6b7280',   // mid gray — long stop
    entry_l:  '#22c55e',
    entry_s:  '#ef4444',
    reg_long:    '#22c55e',
    reg_short:   '#ef4444',
    reg_neutral: '#4a5568',
};

// ── Base chart options ────────────────────────────────────────
function trendBaseOpts() {
    return {
        layout: {
            background:  { color: '#0d1117' },
            textColor:   '#8b949e',
            fontFamily:  "'JetBrains Mono', monospace",
            fontSize:    10,
        },
        grid: {
            vertLines: { color: '#1c2230' },
            horzLines: { color: '#1c2230' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: { color: '#3d4965', labelBackgroundColor: '#1c2230' },
            horzLine: { color: '#3d4965', labelBackgroundColor: '#1c2230' },
        },
        rightPriceScale: { borderColor: '#30363d' },
        timeScale: {
            borderColor:    '#30363d',
            timeVisible:    true,
            secondsVisible: false,
            rightOffset:    6,
            barSpacing:     6,
            fixLeftEdge:    true,
        },
        handleScroll: true,
        handleScale:  true,
    };
}

// ── Destroy ───────────────────────────────────────────────────
function destroyTrendCharts() {
    Object.values(trendCharts).forEach(c => { if (c) c.remove(); });
    trendCharts  = { price: null, regime: null, regimes: null };
    trendSeries  = {
        candle: null, sb: null, mb: null, lb: null,
        sdb: null, mrt: null, mdb: null, lrt: null, ldb: null,
        regime: null, shortReg: null, medReg: null, longReg: null,
    };
}

// ── Build charts ──────────────────────────────────────────────
function buildTrendCharts() {
    destroyTrendCharts();

    const priceEl   = document.getElementById('trend-chart-price');
    const regimeEl  = document.getElementById('trend-chart-regime');
    const regimesEl = document.getElementById('trend-chart-regimes');

    // ── Price chart ──────────────────────────────────────────
    trendCharts.price = LightweightCharts.createChart(priceEl, {
        ...trendBaseOpts(), width: priceEl.clientWidth, height: priceEl.clientHeight,
    });

    // Candlesticks
    trendSeries.candle = trendCharts.price.addCandlestickSeries({
        upColor:        '#22c55e', downColor:        '#ef4444',
        borderUpColor:  '#22c55e', borderDownColor:  '#ef4444',
        wickUpColor:    '#22c55e', wickDownColor:    '#ef4444',
    });

    // Baseline lines
    trendSeries.sb = trendCharts.price.addLineSeries({
        color: TC.sb, lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        priceLineVisible: false, lastValueVisible: true,
        title: 'SB',
    });
    trendSeries.mb = trendCharts.price.addLineSeries({
        color: TC.mb, lineWidth: 2,
        lineStyle: LightweightCharts.LineStyle.Solid,
        priceLineVisible: false, lastValueVisible: true,
        title: 'MB',
    });
    trendSeries.lb = trendCharts.price.addLineSeries({
        color: TC.lb, lineWidth: 1.5,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        priceLineVisible: false, lastValueVisible: true,
        title: 'LB',
    });

    // TP bands (dashed)
    trendSeries.sdb = trendCharts.price.addLineSeries({
        color: TC.sdb, lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        priceLineVisible: false, lastValueVisible: false,
        title: 'SDB',
    });
    trendSeries.mdb = trendCharts.price.addLineSeries({
        color: TC.mdb, lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        priceLineVisible: false, lastValueVisible: false,
        title: 'MDB',
    });
    trendSeries.ldb = trendCharts.price.addLineSeries({
        color: TC.ldb, lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        priceLineVisible: false, lastValueVisible: false,
        title: 'LDB',
    });

    // Stop bands (dashed)
    trendSeries.mrt = trendCharts.price.addLineSeries({
        color: TC.mrt, lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        priceLineVisible: false, lastValueVisible: false,
        title: 'MRT',
    });
    trendSeries.lrt = trendCharts.price.addLineSeries({
        color: TC.lrt, lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed,
        priceLineVisible: false, lastValueVisible: false,
        title: 'LRT',
    });

    // ── Regime mini-chart (medium state only) ────────────────
    trendCharts.regime = LightweightCharts.createChart(regimeEl, {
        ...trendBaseOpts(), width: regimeEl.clientWidth, height: regimeEl.clientHeight,
        rightPriceScale: {
            borderColor: '#30363d',
            autoScale:   false,
            scaleMargins: { top: 0.1, bottom: 0.1 },
        },
    });
    trendCharts.regime.priceScale('right').applyOptions({ autoScale: false });
    trendSeries.regime = trendCharts.regime.addHistogramSeries({
        priceLineVisible: false, lastValueVisible: false,
    });
    trendSeries.regime.createPriceLine({
        price: 0, color: '#30363d', lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: false,
    });

    // ── Regimes history chart (all three states) ─────────────
    trendCharts.regimes = LightweightCharts.createChart(regimesEl, {
        ...trendBaseOpts(), width: regimesEl.clientWidth, height: regimesEl.clientHeight,
        rightPriceScale: {
            borderColor: '#30363d',
            autoScale:   false,
            scaleMargins: { top: 0.05, bottom: 0.05 },
        },
    });
    trendCharts.regimes.priceScale('right').applyOptions({ autoScale: false });
    // Plot three offset series so they don't overlap:
    // long_state at +3, medium_state at 0, short_state at -3
    trendSeries.longReg  = trendCharts.regimes.addHistogramSeries({
        base: 3, priceLineVisible: false, lastValueVisible: false,
    });
    trendSeries.medReg   = trendCharts.regimes.addHistogramSeries({
        base: 0, priceLineVisible: false, lastValueVisible: false,
    });
    trendSeries.shortReg = trendCharts.regimes.addHistogramSeries({
        base: -3, priceLineVisible: false, lastValueVisible: false,
    });
    // Reference lines
    [3, 0, -3].forEach(p => {
        trendSeries.medReg.createPriceLine({
            price: p, color: '#30363d', lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed, axisLabelVisible: true, title: p === 3 ? 'L' : p === 0 ? 'M' : 'S',
        });
    });

    // ── Cross-sync: price ↔ regime ───────────────────────────
    _trendSync(trendCharts.price,   trendCharts.regime, trendCharts.regimes);
    _trendSync(trendCharts.regime,  trendCharts.price);
    _trendSync(trendCharts.regimes, trendCharts.price);

    // ── Resize observers ─────────────────────────────────────
    [
        ['trend-chart-price',   trendCharts.price],
        ['trend-chart-regime',  trendCharts.regime],
        ['trend-chart-regimes', trendCharts.regimes],
    ].forEach(([id, chart]) => {
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

let _trendSyncing = false;
function _trendSync(source, ...targets) {
    source.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (_trendSyncing || !range) return;
        _trendSyncing = true;
        targets.forEach(t => {
            if (t) try { t.timeScale().setVisibleLogicalRange(range); } catch (_) {}
        });
        _trendSyncing = false;
    });
}

// ── Data loading ──────────────────────────────────────────────
function loadTrendOHLCV(rows) {
    if (!trendSeries.candle || !rows?.length) return;
    trendSeries.candle.setData(rows.map(r => ({
        time: r.date, open: r.open, high: r.high, low: r.low, close: r.close,
    })));
}

function _toLine(arr) {
    if (!arr) return [];
    return arr
        .filter(d => d.value != null)
        .map(d => ({ time: d.date, value: d.value }));
}

function _regimeHistogram(arr, offset) {
    /**
     * Convert {date, value} regime array (values: -1, 0, +1) to histogram
     * data centred around `offset`.
     */
    if (!arr) return [];
    return arr.map(d => {
        const v = d.value;
        const color = v > 0 ? TC.reg_long + 'cc'
                    : v < 0 ? TC.reg_short + 'cc'
                    : TC.reg_neutral + '44';
        // Height: 1 bar unit in the direction of the state
        return { time: d.date, value: offset + v, color };
    });
}

function loadTrendData(data, ohlcvRows) {
    if (!trendSeries.candle) return;
    trendState.data = data;

    loadTrendOHLCV(ohlcvRows);

    // Baselines
    trendSeries.sb.setData(_toLine(data.sb));
    trendSeries.mb.setData(_toLine(data.mb));
    trendSeries.lb.setData(_toLine(data.lb));

    // Bands
    trendSeries.sdb.setData(_toLine(data.sdb));
    trendSeries.mdb.setData(_toLine(data.mdb));
    trendSeries.ldb.setData(_toLine(data.ldb));
    trendSeries.mrt.setData(_toLine(data.mrt));
    trendSeries.lrt.setData(_toLine(data.lrt));

    // Entry markers
    const markers = [];
    (data.entry_long  || []).forEach(d => {
        if (d.value) markers.push({ time: d.date, position: 'belowBar', color: TC.entry_l, shape: 'arrowUp',   text: 'L' });
    });
    (data.entry_short || []).forEach(d => {
        if (d.value) markers.push({ time: d.date, position: 'aboveBar', color: TC.entry_s, shape: 'arrowDown', text: 'S' });
    });
    markers.sort((a, b) => a.time < b.time ? -1 : 1);
    trendSeries.candle.setMarkers(markers);

    // Regime mini-chart (medium_state mapped to +1/0/-1 with colours)
    if (trendSeries.regime && data.medium_state) {
        trendSeries.regime.setData(
            data.medium_state.map(d => ({
                time: d.date, value: d.value,
                color: d.value > 0 ? TC.reg_long + 'cc'
                     : d.value < 0 ? TC.reg_short + 'cc'
                     : TC.reg_neutral + '44',
            }))
        );
    }

    // Multi-regime history (all three)
    if (trendSeries.longReg && data.long_state) {
        trendSeries.longReg.setData(_regimeHistogram(data.long_state, 3));
    }
    if (trendSeries.medReg && data.medium_state) {
        trendSeries.medReg.setData(_regimeHistogram(data.medium_state, 0));
    }
    if (trendSeries.shortReg && data.short_state) {
        trendSeries.shortReg.setData(_regimeHistogram(data.short_state, -3));
    }

    // Apply visibility toggles
    applyTrendLineVisibility();

    // Fit content
    if (trendCharts.price) trendCharts.price.timeScale().fitContent();

    // Update signal summary cards
    updateTrendSignalCards(data, ohlcvRows);
}

// ── Signal summary cards ──────────────────────────────────────
function updateTrendSignalCards(data, ohlcvRows) {
    const last = arr => arr && arr.length ? arr[arr.length - 1] : null;
    const fmt  = v => (v != null && isFinite(v)) ? v.toFixed(4) : '—';

    const lastClose = ohlcvRows?.length ? ohlcvRows[ohlcvRows.length - 1].close : null;
    const fmtPrice  = v => {
        if (v == null) return '—';
        // Show 2 dp for large values, 4 for small (FX)
        return lastClose && lastClose > 100 ? v.toFixed(2) : v.toFixed(4);
    };

    const stateLabel = v => v === 1 ? 'LONG' : v === -1 ? 'SHORT' : 'NEUTRAL';
    const stateClass = v => v === 1 ? 'bull' : v === -1 ? 'bear' : 'neutral';

    const setCard = (id, text, cls) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = text;
        el.className = `trend-signal-value ${cls}`;
    };

    const ss = last(data.short_state);
    const ms = last(data.medium_state);
    const ls = last(data.long_state);
    setCard('trend-sig-short',  stateLabel(ss?.value), stateClass(ss?.value));
    setCard('trend-sig-medium', stateLabel(ms?.value), stateClass(ms?.value));
    setCard('trend-sig-long',   stateLabel(ls?.value), stateClass(ls?.value));

    // Last entry signal
    let lastEntry = '—';
    let entryClass = 'neutral';
    const allEntries = [
        ...(data.entry_long  || []).filter(d => d.value).map(d => ({ date: d.date, dir: 'LONG' })),
        ...(data.entry_short || []).filter(d => d.value).map(d => ({ date: d.date, dir: 'SHORT' })),
    ].sort((a, b) => a.date < b.date ? -1 : 1);
    if (allEntries.length) {
        const e = allEntries[allEntries.length - 1];
        lastEntry = `${e.dir} ${e.date}`;
        entryClass = e.dir === 'LONG' ? 'bull' : 'bear';
    }
    setCard('trend-sig-entry', lastEntry, entryClass);

    // Band values
    const mrtLast = last(data.mrt);
    const sdbLast = last(data.sdb);
    const mdbLast = last(data.mdb);
    const atrLast = last(data.atr);
    setCard('trend-sig-mrt', fmtPrice(mrtLast?.value), 'neutral');
    setCard('trend-sig-sdb', fmtPrice(sdbLast?.value), 'neutral');
    setCard('trend-sig-mdb', fmtPrice(mdbLast?.value), 'neutral');
    setCard('trend-sig-atr', fmtPrice(atrLast?.value), 'neutral');
}

// ── Visibility toggles ────────────────────────────────────────
function applyTrendLineVisibility() {
    const vis = trendState.visibleLines;
    const hide = s => { if (s) s.applyOptions({ visible: false }); };
    const show = (s, color, lw, ls) => {
        if (s) s.applyOptions({ visible: true, color, lineWidth: lw, lineStyle: ls });
    };

    if (vis.lb)  show(trendSeries.lb,  TC.lb,  1.5, LightweightCharts.LineStyle.Dashed);
    else          hide(trendSeries.lb);

    if (vis.lrt) show(trendSeries.lrt, TC.lrt, 1, LightweightCharts.LineStyle.Dashed);
    else          hide(trendSeries.lrt);

    if (vis.ldb) show(trendSeries.ldb, TC.ldb, 1, LightweightCharts.LineStyle.Dashed);
    else          hide(trendSeries.ldb);
}

function toggleTrendLine(key) {
    trendState.visibleLines[key] = !trendState.visibleLines[key];
    const btn = document.getElementById(`trend-toggle-${key}`);
    if (btn) btn.classList.toggle('trend-toggle-active', trendState.visibleLines[key]);
    applyTrendLineVisibility();
}

// ── Method / freq controls ────────────────────────────────────
function setTrendMethod(method) {
    trendState.method = method;
    ['kama', 'adma'].forEach(m => {
        const btn = document.getElementById(`trend-method-${m}`);
        if (btn) btn.classList.toggle('trend-method-active', m === method);
    });
    // Reload if we have a symbol
    if (typeof state !== 'undefined' && state.activeSymbol) {
        loadAdaptiveTrendData(state.activeSymbol);
    }
}

function setTrendFreq(freq) {
    trendState.freq = freq;
    ['daily', 'weekly'].forEach(f => {
        const btn = document.getElementById(`trend-freq-${f}`);
        if (btn) btn.classList.toggle('trend-freq-active', f === freq);
    });
    if (typeof state !== 'undefined' && state.activeSymbol) {
        loadAdaptiveTrendData(state.activeSymbol);
    }
}
