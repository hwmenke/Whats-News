/**
 * trend_chart.js — Adaptive Trend System renderer
 *
 * Architecture:
 *   Left panel (65%) — price chart with all overlay lines + regime strip
 *   Right panel (35%) — composite signal badge + 8 detail cards
 *
 * Lines rendered on price chart:
 *   SB  (blue  solid  2px) — fast adaptive baseline
 *   MB  (red   solid  2px) — medium adaptive baseline  ← master regime
 *   LB  (orange dashed 1.5px) — long baseline          [toggleable]
 *   SDB (bright-green dashed 1px) — short TP band
 *   MDB (dark-green   dashed 1px) — medium TP band
 *   LDB (cyan         dashed 1px) — long TP band       [toggleable]
 *   MRT (dark-gray    dashed 1.5px) — medium stop band
 *   LRT (mid-gray     dashed 1px)  — long stop band    [toggleable]
 *
 * Regime strip (3 offset histograms, 130 px):
 *   Long horizon   plotted at  y = ±1 around base  +3
 *   Medium horizon plotted at  y = ±1 around base   0
 *   Short horizon  plotted at  y = ±1 around base  -3
 *   Reference price-lines label each band: LONG / MED / SHORT
 *
 * Signal panel:
 *   Composite signal  = sum of all 3 states  (-3 … +3)
 *   8 detail cards: Short/Medium/Long horizon, Last entry,
 *                   MRT stop, SDB TP1, MDB TP2, R:R ratio
 */

// ── State ────────────────────────────────────────────────────
const trendState = {
    method: 'kama',
    freq:   'daily',
    vis:    { sb: true, mb: true, lb: true, lrt: true, ldb: true, sdb: true, mrt: true, mdb: true },
    params: null,   // null = use defaults; object = custom optimised params
    data:   null,
};

// ── Line metadata (descriptions + colors) ─────────────────────
const LINE_META = {
    sb:  {
        color: '#3b82f6',
        label: 'SB — Short Baseline',
        params: 'KAMA · ER=10 · fast=2 · slow=15 · source=HLC/3',
        desc:  'Fast-adapting baseline. Tracks near-term momentum and is the primary input for the short-horizon regime. Turns quickly in trending markets, stays flat in chop.',
    },
    mb:  {
        color: '#ef4444',
        label: 'MB — Medium Baseline',
        params: 'KAMA · ER=20 · fast=2 · slow=30 · source=HLC/3',
        desc:  'Master trend line. Drives the medium-horizon regime that governs all trade management bands (MRT, MDB). When SB crosses above MB, a long regime entry fires.',
    },
    lb:  {
        color: '#f97316',
        label: 'LB — Long Baseline',
        params: 'KAMA · ER=40 · fast=2 · slow=60 · source=HLC/3',
        desc:  'Macro structure line. Very slow to react — only flips on sustained multi-month directional moves. Provides the long-horizon regime context for LRT / LDB bands.',
    },
    sdb: {
        color: '#22c55e',
        label: 'SDB — Short Deviation Band  (TP1)',
        params: 'Center=SB · +2.0 × ATR(20) · ratchets UP in long regime',
        desc:  'First take-profit target. Ratcheting band anchored to SB — moves only in the direction of the trade and never pulls back. Reset on regime flip.',
    },
    mrt: {
        color: '#475569',
        label: 'MRT — Medium Retracement  (Stop)',
        params: 'Center=MB · −2.25 × ATR(20) · ratchets UP in long regime',
        desc:  'Trailing stop level. Sits 2.25 ATR on the loss side of MB and tightens as MB advances. Exit here on an adverse move. Never retreats against the trade.',
    },
    mdb: {
        color: '#16a34a',
        label: 'MDB — Medium Deviation Band  (TP2)',
        params: 'Center=MB · +4.5 × ATR(20) · ratchets UP in long regime',
        desc:  'Main take-profit target. Exactly 2× the stop distance, giving a built-in 2:1 R:R. Ratchets in the direction of the trade; resets on medium-regime flip.',
    },
    lrt: {
        color: '#6b7280',
        label: 'LRT — Long Retracement  (Wide Stop)',
        params: 'Center=LB · −2.25 × ATR(20) · ratchets in long-horizon regime',
        desc:  'Wide trailing stop for long-horizon positions. Based on LB so it only tightens on sustained macro trends. Use for position-level sizing against macro structure.',
    },
    ldb: {
        color: '#06b6d4',
        label: 'LDB — Long Deviation Band  (Extended Target)',
        params: 'Center=LB · +4.5 × ATR(20) · ratchets in long-horizon regime',
        desc:  'Extended target for multi-month positions. Only meaningful in confirmed long-horizon regimes. Gives a sense of how far macro momentum can carry the move.',
    },
};

// ── Instances ─────────────────────────────────────────────────
let trendCharts    = { price: null, regime: null };
let trendSeries    = {
    bgLong: null, bgShort: null,
    candle:   null,
    sb: null, mb: null, lb: null,
    sdb: null, mrt: null, mdb: null, lrt: null, ldb: null,
    regLong: null, regMed: null, regShort: null,
};

// Weekly chart instances (Both mode only)
let trendChartsW   = { price: null, regime: null };
let trendSeriesW   = {
    bgLong: null, bgShort: null,
    candle:   null,
    sb: null, mb: null, lb: null,
    sdb: null, mrt: null, mdb: null, lrt: null, ldb: null,
    regLong: null, regMed: null, regShort: null,
};

let _trendObservers = [];   // ResizeObserver instances — cleaned up on destroy
let _regSyncing     = false;
let _regSyncingW    = false;

// ── Colors ───────────────────────────────────────────────────
const TC = {
    sb:     '#3b82f6',   // blue    — fast baseline
    mb:     '#ef4444',   // red     — medium baseline
    lb:     '#f97316',   // orange  — long baseline
    sdb:    '#22c55e',   // bright-green — short TP
    mdb:    '#16a34a',   // dark-green   — medium TP
    ldb:    '#06b6d4',   // cyan         — long TP
    mrt:    '#475569',   // slate        — medium stop
    lrt:    '#6b7280',   // gray         — long stop
    bull:   '#22c55e',
    bear:   '#ef4444',
    neut:   '#4a5568',
};

// ── Base chart options ────────────────────────────────────────
function _trendBaseOpts() {
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
    _trendObservers.forEach(obs => obs.disconnect());
    _trendObservers = [];

    Object.values(trendCharts).forEach(c => { if (c) try { c.remove(); } catch(_) {} });
    trendCharts = { price: null, regime: null };
    trendSeries = {
        bgLong: null, bgShort: null,
        candle: null, sb: null, mb: null, lb: null,
        sdb: null, mrt: null, mdb: null, lrt: null, ldb: null,
        regLong: null, regMed: null, regShort: null,
    };
    _regSyncing = false;
}

function destroyWeeklyTrendCharts() {
    Object.values(trendChartsW).forEach(c => { if (c) try { c.remove(); } catch(_) {} });
    trendChartsW = { price: null, regime: null };
    trendSeriesW = {
        bgLong: null, bgShort: null,
        candle: null, sb: null, mb: null, lb: null,
        sdb: null, mrt: null, mdb: null, lrt: null, ldb: null,
        regLong: null, regMed: null, regShort: null,
    };
    _regSyncingW = false;
}

// ── Observe helper (stores observer for later cleanup) ────────
function _observe(elId, chart) {
    const el = document.getElementById(elId);
    if (!el || !chart) return;
    const obs = new ResizeObserver(entries => {
        for (const e of entries) {
            const { width, height } = e.contentRect;
            if (width > 0 && height > 0) {
                try { chart.resize(width, height); } catch (_) {}
            }
        }
    });
    obs.observe(el);
    _trendObservers.push(obs);
}

// ── Build ─────────────────────────────────────────────────────
function buildTrendCharts() {
    destroyTrendCharts();

    const priceEl  = document.getElementById('trend-chart-price');
    const regimeEl = document.getElementById('trend-chart-regime');
    if (!priceEl || !regimeEl) return;

    // ── Price chart ──────────────────────────────────────────
    trendCharts.price = LightweightCharts.createChart(priceEl, {
        ..._trendBaseOpts(),
        width:  priceEl.clientWidth  || 600,
        height: priceEl.clientHeight || 400,
        // Hidden left scale used exclusively for full-height background fills
        leftPriceScale: {
            visible:      false,
            scaleMargins: { top: 0, bottom: 0 },
        },
    });

    // ── Background regime fills (added BEFORE candles → renders behind) ──
    // Both series live on the hidden left scale, which auto-fits to [-1, +1].
    // Long  regime → bgLong  bar: base=-1 → value=+1  (full height green)
    // Short regime → bgShort bar: base=+1 → value=-1  (full height red)
    // Neutral      → value equals base (zero-height, invisible)
    trendSeries.bgLong = trendCharts.price.addHistogramSeries({
        priceScaleId:     'left',
        color:            'rgba(34,197,94,0.07)',
        base:             -1,
        priceLineVisible: false,
        lastValueVisible: false,
    });
    trendSeries.bgShort = trendCharts.price.addHistogramSeries({
        priceScaleId:     'left',
        color:            'rgba(239,68,68,0.07)',
        base:             1,
        priceLineVisible: false,
        lastValueVisible: false,
    });

    // Candlesticks
    trendSeries.candle = trendCharts.price.addCandlestickSeries({
        upColor:       '#22c55e', downColor:       '#ef4444',
        borderUpColor: '#22c55e', borderDownColor: '#ef4444',
        wickUpColor:   '#22c55e', wickDownColor:   '#ef4444',
    });

    const _line = (color, lw, ls, title, lastVal = false) =>
        trendCharts.price.addLineSeries({
            color, lineWidth: lw,
            lineStyle:        ls,
            priceLineVisible: false,
            lastValueVisible: lastVal,
            title,
        });

    const LS = LightweightCharts.LineStyle;

    // Baselines (lastValueVisible = true for SB + MB only — keep axis clean)
    trendSeries.sb  = _line(TC.sb,  2,   LS.Solid,  'SB',  true);
    trendSeries.mb  = _line(TC.mb,  2,   LS.Solid,  'MB',  true);
    trendSeries.lb  = _line(TC.lb,  1.5, LS.Dashed, 'LB',  false);

    // Bands
    trendSeries.sdb = _line(TC.sdb, 1,   LS.Dashed, 'SDB', false);
    trendSeries.mrt = _line(TC.mrt, 1.5, LS.Dashed, 'MRT', false);
    trendSeries.mdb = _line(TC.mdb, 1,   LS.Dashed, 'MDB', false);
    trendSeries.lrt = _line(TC.lrt, 1,   LS.Dashed, 'LRT', false);
    trendSeries.ldb = _line(TC.ldb, 1,   LS.Dashed, 'LDB', false);

    // ── Regime strip (3 offset histograms) ───────────────────
    trendCharts.regime = LightweightCharts.createChart(regimeEl, {
        ..._trendBaseOpts(),
        width:  regimeEl.clientWidth  || 600,
        height: regimeEl.clientHeight || 130,
        rightPriceScale: {
            borderColor:  '#30363d',
            scaleMargins: { top: 0.08, bottom: 0.08 },
        },
    });

    const _hist = (base) => trendCharts.regime.addHistogramSeries({
        base,
        priceLineVisible: false,
        lastValueVisible: false,
    });

    trendSeries.regLong  = _hist(3);
    trendSeries.regMed   = _hist(0);
    trendSeries.regShort = _hist(-3);

    // Reference lines anchor the scale and label the three bands.
    // Use a very transparent color so they don't dominate visually.
    const _ref = (series, price, title, color) =>
        series.createPriceLine({
            price, color, lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true, title,
        });

    _ref(trendSeries.regLong,  3,   'LONG',  TC.lb  + '60');
    _ref(trendSeries.regMed,   0,   'MED',   TC.neut + '80');
    _ref(trendSeries.regShort, -3,  'SHORT', TC.lb  + '60');

    // ── Cross-sync price ↔ regime ─────────────────────────────
    trendCharts.price.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (_regSyncing || !range) return;
        _regSyncing = true;
        try { trendCharts.regime.timeScale().setVisibleLogicalRange(range); } catch (_) {}
        _regSyncing = false;
    });
    trendCharts.regime.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (_regSyncing || !range) return;
        _regSyncing = true;
        try { trendCharts.price.timeScale().setVisibleLogicalRange(range); } catch (_) {}
        _regSyncing = false;
    });

    // ── Resize observers ─────────────────────────────────────
    _observe('trend-chart-price',  trendCharts.price);
    _observe('trend-chart-regime', trendCharts.regime);
}

// ── Build weekly charts (used in Both mode) ───────────────────
function buildWeeklyTrendCharts() {
    destroyWeeklyTrendCharts();

    const priceEl  = document.getElementById('trend-chart-price-w');
    const regimeEl = document.getElementById('trend-chart-regime-w');
    if (!priceEl || !regimeEl) return;

    trendChartsW.price = LightweightCharts.createChart(priceEl, {
        ..._trendBaseOpts(),
        width:  priceEl.clientWidth  || 600,
        height: priceEl.clientHeight || 300,
        leftPriceScale: { visible: false, scaleMargins: { top: 0, bottom: 0 } },
    });

    trendSeriesW.bgLong = trendChartsW.price.addHistogramSeries({
        priceScaleId: 'left', color: 'rgba(34,197,94,0.07)',
        base: -1, priceLineVisible: false, lastValueVisible: false,
    });
    trendSeriesW.bgShort = trendChartsW.price.addHistogramSeries({
        priceScaleId: 'left', color: 'rgba(239,68,68,0.07)',
        base: 1, priceLineVisible: false, lastValueVisible: false,
    });
    trendSeriesW.candle = trendChartsW.price.addCandlestickSeries({
        upColor: '#22c55e', downColor: '#ef4444',
        borderUpColor: '#22c55e', borderDownColor: '#ef4444',
        wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });

    const _lineW = (color, lw, ls, title, lastVal = false) =>
        trendChartsW.price.addLineSeries({
            color, lineWidth: lw, lineStyle: ls,
            priceLineVisible: false, lastValueVisible: lastVal, title,
        });
    const LS = LightweightCharts.LineStyle;

    trendSeriesW.sb  = _lineW(TC.sb,  2,   LS.Solid,  'SB',  true);
    trendSeriesW.mb  = _lineW(TC.mb,  2,   LS.Solid,  'MB',  true);
    trendSeriesW.lb  = _lineW(TC.lb,  1.5, LS.Dashed, 'LB',  false);
    trendSeriesW.sdb = _lineW(TC.sdb, 1,   LS.Dashed, 'SDB', false);
    trendSeriesW.mrt = _lineW(TC.mrt, 1.5, LS.Dashed, 'MRT', false);
    trendSeriesW.mdb = _lineW(TC.mdb, 1,   LS.Dashed, 'MDB', false);
    trendSeriesW.lrt = _lineW(TC.lrt, 1,   LS.Dashed, 'LRT', false);
    trendSeriesW.ldb = _lineW(TC.ldb, 1,   LS.Dashed, 'LDB', false);

    trendChartsW.regime = LightweightCharts.createChart(regimeEl, {
        ..._trendBaseOpts(),
        width:  regimeEl.clientWidth  || 600,
        height: regimeEl.clientHeight || 90,
        rightPriceScale: { borderColor: '#30363d', scaleMargins: { top: 0.08, bottom: 0.08 } },
    });

    const _histW = (base) => trendChartsW.regime.addHistogramSeries({
        base, priceLineVisible: false, lastValueVisible: false,
    });

    trendSeriesW.regLong  = _histW(3);
    trendSeriesW.regMed   = _histW(0);
    trendSeriesW.regShort = _histW(-3);

    const _refW = (series, price, title, color) =>
        series.createPriceLine({ price, color, lineWidth: 1,
            lineStyle: LightweightCharts.LineStyle.Dashed,
            axisLabelVisible: true, title });

    _refW(trendSeriesW.regLong,  3,  'LONG',  TC.lb   + '60');
    _refW(trendSeriesW.regMed,   0,  'MED',   TC.neut + '80');
    _refW(trendSeriesW.regShort, -3, 'SHORT', TC.lb   + '60');

    // Cross-sync weekly price ↔ regime
    trendChartsW.price.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (_regSyncingW || !range) return;
        _regSyncingW = true;
        try { trendChartsW.regime.timeScale().setVisibleLogicalRange(range); } catch (_) {}
        _regSyncingW = false;
    });
    trendChartsW.regime.timeScale().subscribeVisibleLogicalRangeChange(range => {
        if (_regSyncingW || !range) return;
        _regSyncingW = true;
        try { trendChartsW.price.timeScale().setVisibleLogicalRange(range); } catch (_) {}
        _regSyncingW = false;
    });

    _observe('trend-chart-price-w',  trendChartsW.price);
    _observe('trend-chart-regime-w', trendChartsW.regime);
}

// ── Data helpers ──────────────────────────────────────────────
function _toLine(arr) {
    if (!Array.isArray(arr)) return [];
    return arr
        .filter(d => d.value != null && isFinite(d.value))
        .map(d => ({ time: d.date, value: d.value }));
}

/**
 * Map regime array (+1/-1/0) to histogram data offset around `base`.
 *   Long  (+1) → base + 1  (bar extends up from base)
 *   Short (-1) → base - 1  (bar extends down from base)
 *   Neutral(0) → base      (zero-height bar, invisible)
 */
function _regData(arr, base) {
    if (!Array.isArray(arr)) return [];
    return arr.map(d => {
        const v = d.value || 0;
        return {
            time:  d.date,
            value: base + v,
            color: v > 0 ? TC.bull + 'cc'
                 : v < 0 ? TC.bear + 'cc'
                 :         TC.neut + '22',
        };
    });
}

// ── Load data into charts ─────────────────────────────────────
function loadTrendData(data, ohlcvRows) {
    if (!data || data.error || !ohlcvRows?.length || !trendSeries.candle) return;
    trendState.data = data;

    // Candlesticks
    trendSeries.candle.setData(
        ohlcvRows.map(r => ({
            time: r.date, open: r.open, high: r.high, low: r.low, close: r.close,
        }))
    );

    // Background regime shading — driven by medium_state (master regime)
    // bgLong fills green  when medium is long;  invisible otherwise
    // bgShort fills red   when medium is short; invisible otherwise
    if (Array.isArray(data.medium_state) && trendSeries.bgLong && trendSeries.bgShort) {
        trendSeries.bgLong.setData(
            data.medium_state.map(d => ({
                time:  d.date,
                value: d.value > 0 ? 1 : -1,
                color: 'rgba(34,197,94,0.07)',
            }))
        );
        trendSeries.bgShort.setData(
            data.medium_state.map(d => ({
                time:  d.date,
                value: d.value < 0 ? -1 : 1,
                color: 'rgba(239,68,68,0.07)',
            }))
        );
    }

    // Baselines
    trendSeries.sb.setData(_toLine(data.sb));
    trendSeries.mb.setData(_toLine(data.mb));
    trendSeries.lb.setData(_toLine(data.lb));

    // Bands
    trendSeries.sdb.setData(_toLine(data.sdb));
    trendSeries.mrt.setData(_toLine(data.mrt));
    trendSeries.mdb.setData(_toLine(data.mdb));
    trendSeries.lrt.setData(_toLine(data.lrt));
    trendSeries.ldb.setData(_toLine(data.ldb));

    // Entry markers (long ▲ below bar, short ▼ above bar)
    const markers = [];
    (data.entry_long  || []).forEach(d => {
        if (d.value) markers.push({
            time: d.date, position: 'belowBar', color: TC.bull,
            shape: 'arrowUp', text: 'L',
        });
    });
    (data.entry_short || []).forEach(d => {
        if (d.value) markers.push({
            time: d.date, position: 'aboveBar', color: TC.bear,
            shape: 'arrowDown', text: 'S',
        });
    });
    // ISO date strings sort lexicographically — safe for YYYY-MM-DD
    markers.sort((a, b) => a.time.localeCompare(b.time));
    trendSeries.candle.setMarkers(markers);

    // Regime histograms
    trendSeries.regLong.setData(_regData(data.long_state,   3));
    trendSeries.regMed.setData(_regData(data.medium_state,  0));
    trendSeries.regShort.setData(_regData(data.short_state, -3));

    // Apply overlay visibility toggles
    _applyVis();

    // Fit to full history
    trendCharts.price.timeScale().fitContent();

    // Update signal panel cards
    _updateSignalPanel(data, ohlcvRows);
}

// ── Load weekly data into weekly charts ───────────────────────
function loadWeeklyTrendData(data, ohlcvRows) {
    if (!data || data.error || !ohlcvRows?.length || !trendSeriesW.candle) return;

    trendSeriesW.candle.setData(
        ohlcvRows.map(r => ({ time: r.date, open: r.open, high: r.high, low: r.low, close: r.close }))
    );

    if (Array.isArray(data.medium_state) && trendSeriesW.bgLong && trendSeriesW.bgShort) {
        trendSeriesW.bgLong.setData(
            data.medium_state.map(d => ({ time: d.date, value: d.value > 0 ? 1 : -1, color: 'rgba(34,197,94,0.07)' }))
        );
        trendSeriesW.bgShort.setData(
            data.medium_state.map(d => ({ time: d.date, value: d.value < 0 ? -1 : 1, color: 'rgba(239,68,68,0.07)' }))
        );
    }

    trendSeriesW.sb.setData(_toLine(data.sb));
    trendSeriesW.mb.setData(_toLine(data.mb));
    trendSeriesW.lb.setData(_toLine(data.lb));
    trendSeriesW.sdb.setData(_toLine(data.sdb));
    trendSeriesW.mrt.setData(_toLine(data.mrt));
    trendSeriesW.mdb.setData(_toLine(data.mdb));
    trendSeriesW.lrt.setData(_toLine(data.lrt));
    trendSeriesW.ldb.setData(_toLine(data.ldb));

    const markers = [];
    (data.entry_long  || []).forEach(d => {
        if (d.value) markers.push({ time: d.date, position: 'belowBar', color: TC.bull, shape: 'arrowUp', text: 'L' });
    });
    (data.entry_short || []).forEach(d => {
        if (d.value) markers.push({ time: d.date, position: 'aboveBar', color: TC.bear, shape: 'arrowDown', text: 'S' });
    });
    markers.sort((a, b) => a.time.localeCompare(b.time));
    trendSeriesW.candle.setMarkers(markers);

    trendSeriesW.regLong.setData(_regData(data.long_state,   3));
    trendSeriesW.regMed.setData(_regData(data.medium_state,  0));
    trendSeriesW.regShort.setData(_regData(data.short_state, -3));

    trendChartsW.price.timeScale().fitContent();

    // Update weekly column in signal panel
    _updateSignalPanelW(data, ohlcvRows);
}

// ── Visibility toggles ────────────────────────────────────────
function _applyVis() {
    const LS = LightweightCharts.LineStyle;
    const show = (s, color, lw, ls) => {
        if (s) s.applyOptions({ visible: true, color, lineWidth: lw, lineStyle: ls });
    };
    const hide = s => { if (s) s.applyOptions({ visible: false }); };

    if (trendState.vis.sb)  show(trendSeries.sb,  TC.sb,  2,   LS.Solid);
    else                    hide(trendSeries.sb);

    if (trendState.vis.mb)  show(trendSeries.mb,  TC.mb,  2,   LS.Solid);
    else                    hide(trendSeries.mb);

    if (trendState.vis.lb)  show(trendSeries.lb,  TC.lb,  1.5, LS.Dashed);
    else                    hide(trendSeries.lb);

    if (trendState.vis.sdb) show(trendSeries.sdb, TC.sdb, 1,   LS.Dashed);
    else                    hide(trendSeries.sdb);

    if (trendState.vis.mrt) show(trendSeries.mrt, TC.mrt, 1.5, LS.Dashed);
    else                    hide(trendSeries.mrt);

    if (trendState.vis.mdb) show(trendSeries.mdb, TC.mdb, 1,   LS.Dashed);
    else                    hide(trendSeries.mdb);

    if (trendState.vis.lrt) show(trendSeries.lrt, TC.lrt, 1,   LS.Dashed);
    else                    hide(trendSeries.lrt);

    if (trendState.vis.ldb) show(trendSeries.ldb, TC.ldb, 1,   LS.Dashed);
    else                    hide(trendSeries.ldb);
}

function toggleTrendLine(key) {
    trendState.vis[key] = !trendState.vis[key];
    const btn = document.getElementById(`trend-toggle-${key}`);
    if (btn) btn.classList.toggle('trend-toggle-on', trendState.vis[key]);
    _applyVis();
}

// ── Line description strip ────────────────────────────────────
// Maps line key to the param keys that describe it (for live readback)
const _LINE_PARAM_KEYS = {
    sb:  ['sb_er',  'sb_slow'],
    mb:  ['mb_er',  'mb_slow'],
    lb:  ['lb_er',  'lb_slow'],
    sdb: ['atr_er', 'atr_fast', 'atr_slow'],
    mrt: ['atr_er', 'atr_fast', 'atr_slow'],
    mdb: ['atr_er', 'atr_fast', 'atr_slow'],
    lrt: ['atr_er', 'atr_fast', 'atr_slow'],
    ldb: ['atr_er', 'atr_fast', 'atr_slow'],
};

function showLineDesc(key) {
    const el   = document.getElementById('trend-line-desc');
    const meta = LINE_META[key];
    if (!el || !meta) return;

    // Build live params string if custom params are active
    let paramsStr = meta.params;
    const liveP   = trendState.params;
    if (liveP) {
        const relevantKeys = _LINE_PARAM_KEYS[key] || [];
        const liveStr = relevantKeys
            .filter(k => liveP[k] != null)
            .map(k => `${k}=${liveP[k]}`)
            .join(' · ');
        if (liveStr) paramsStr = liveStr + ' ★ optimised';
    }

    el.innerHTML =
        `<span class="tld-dot" style="background:${meta.color}"></span>` +
        `<span class="tld-label">${meta.label}</span>` +
        `<span class="tld-sep">·</span>` +
        `<span class="tld-params">${paramsStr}</span>` +
        `<span class="tld-sep">—</span>` +
        `<span class="tld-desc">${meta.desc}</span>`;
    el.style.opacity = '1';
}

function clearLineDesc() {
    const el = document.getElementById('trend-line-desc');
    if (el) el.style.opacity = '0';
}

// ── Method / freq selectors ───────────────────────────────────
function setTrendMethod(method) {
    trendState.method = method;
    document.querySelectorAll('.trend-method-btn').forEach(btn => {
        btn.classList.toggle('trend-active', btn.dataset.val === method);
    });
    if (typeof state !== 'undefined' && state.activeSymbol) {
        loadAdaptiveTrendData(state.activeSymbol);
    }
}

function setTrendFreq(freq) {
    trendState.freq = freq;
    document.querySelectorAll('.trend-freq-btn').forEach(btn => {
        btn.classList.toggle('trend-active', btn.dataset.val === freq);
    });

    // Show/hide weekly panel and W columns in signal panel
    const weeklyPanel  = document.getElementById('trend-panel-weekly');
    const compColW     = document.getElementById('trend-composite-col-w');
    const wValEls      = document.querySelectorAll('.trend-sig-val-w');
    const isBoth       = freq === 'both';

    if (weeklyPanel)  weeklyPanel.style.display  = isBoth ? '' : 'none';
    if (compColW)     compColW.style.display      = isBoth ? '' : 'none';
    wValEls.forEach(el => { el.style.display      = isBoth ? '' : 'none'; });

    // Destroy weekly charts when leaving Both mode
    if (!isBoth) destroyWeeklyTrendCharts();

    if (typeof state !== 'undefined' && state.activeSymbol) {
        loadAdaptiveTrendData(state.activeSymbol);
    }
}

// ── Signal panel ──────────────────────────────────────────────
function _updateSignalPanel(data, ohlcvRows) {
    if (!ohlcvRows?.length || !data) return;
    const lastOf = arr => Array.isArray(arr) && arr.length ? arr[arr.length - 1] : null;
    const close  = ohlcvRows[ohlcvRows.length - 1]?.close;
    if (!close) return;

    // Format price: 2 dp for large values (indices), 4 dp for FX
    const fmtP = v => {
        if (v == null || !isFinite(v)) return '—';
        return close > 100 ? v.toFixed(2) : v.toFixed(4);
    };

    const setCard = (id, text, cls) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = text;
        el.className   = el.classList.contains('trend-sig-val-w')
            ? `trend-sig-val-w ${cls}`
            : `trend-sig-val ${cls}`;
    };

    // Current regime states
    const ss = lastOf(data.short_state)?.value  || 0;
    const ms = lastOf(data.medium_state)?.value || 0;
    const ls = lastOf(data.long_state)?.value   || 0;

    // ── Composite signal (-3 … +3) ────────────────────────────
    const comp = ss + ms + ls;
    const compMap = {
         3: ['STRONG LONG',  'bull-strong'],
         2: ['LONG',         'bull'],
         1: ['LEAN LONG',    'bull-soft'],
         0: ['NEUTRAL',      'neutral'],
        '-1': ['LEAN SHORT', 'bear-soft'],
        '-2': ['SHORT',      'bear'],
        '-3': ['STRONG SHORT','bear-strong'],
    };
    const [compLabel, compCls] = compMap[String(comp)] || ['—', 'neutral'];
    const compEl = document.getElementById('trend-composite');
    if (compEl) {
        compEl.textContent = compLabel;
        compEl.className   = `trend-composite-badge ${compCls}`;
    }

    const arrow = s => s > 0 ? '↑' : s < 0 ? '↓' : '–';
    const alignEl = document.getElementById('trend-align');
    if (alignEl) {
        alignEl.textContent =
            `Short ${arrow(ss)}  ·  Medium ${arrow(ms)}  ·  Long ${arrow(ls)}`;
    }

    // Strength bar (filled dots 0-3)
    const strengthEl = document.getElementById('trend-strength');
    if (strengthEl) {
        const abs  = Math.abs(comp);
        const dot  = '●';  const empty = '○';
        strengthEl.textContent = Array.from({ length: 3 }, (_, i) => i < abs ? dot : empty).join(' ');
        strengthEl.className   = `trend-strength-bar ${comp >= 0 ? 'bull' : 'bear'}`;
    }

    // ── Individual states ─────────────────────────────────────
    const stateLabel = v => v > 0 ? 'LONG' : v < 0 ? 'SHORT' : 'NEUTRAL';
    const stateClass = v => v > 0 ? 'bull'  : v < 0 ? 'bear'  : 'neutral';
    setCard('trend-sig-short',  stateLabel(ss), stateClass(ss));
    setCard('trend-sig-medium', stateLabel(ms), stateClass(ms));
    setCard('trend-sig-long',   stateLabel(ls), stateClass(ls));

    // ── Last entry signal ─────────────────────────────────────
    const allEntries = [
        ...(data.entry_long  || []).filter(d => d.value).map(d => ({ date: d.date, dir: 'LONG'  })),
        ...(data.entry_short || []).filter(d => d.value).map(d => ({ date: d.date, dir: 'SHORT' })),
    ].sort((a, b) => a.date.localeCompare(b.date));

    if (allEntries.length) {
        const e = allEntries[allEntries.length - 1];
        setCard('trend-sig-entry', `${e.dir}  ${e.date}`, e.dir === 'LONG' ? 'bull' : 'bear');
    } else {
        setCard('trend-sig-entry', '—', 'neutral');
    }

    // ── Band levels ───────────────────────────────────────────
    const mrtV = lastOf(data.mrt)?.value;
    const sdbV = lastOf(data.sdb)?.value;
    const mdbV = lastOf(data.mdb)?.value;
    const atrV = lastOf(data.atr)?.value;

    setCard('trend-sig-mrt', fmtP(mrtV), 'neutral');
    setCard('trend-sig-sdb', fmtP(sdbV), 'neutral');
    setCard('trend-sig-mdb', fmtP(mdbV), 'neutral');

    // ── R:R ratio ─────────────────────────────────────────────
    // Only meaningful when in an active medium-state regime
    if (close > 0 && mrtV != null && mdbV != null && isFinite(mrtV) && isFinite(mdbV) && ms !== 0) {
        const risk   = Math.abs(close - mrtV);
        const reward = Math.abs(mdbV - close);
        if (risk > 1e-10) {
            const rr  = reward / risk;
            const cls = rr >= 2.0 ? 'bull'
                      : rr >= 1.0 ? 'neutral'
                      :             'bear';
            setCard('trend-sig-rr', `${rr.toFixed(2)} : 1  (ATR ${fmtP(atrV)})`, cls);
        } else {
            setCard('trend-sig-rr', `ATR ${fmtP(atrV)}`, 'neutral');
        }
    } else {
        setCard('trend-sig-rr', atrV != null ? `ATR ${fmtP(atrV)}` : '—', 'neutral');
    }
}

// ── Weekly column update ──────────────────────────────────────
function _updateSignalPanelW(data, ohlcvRows) {
    if (!ohlcvRows?.length || !data) return;
    const lastOf = arr => Array.isArray(arr) && arr.length ? arr[arr.length - 1] : null;
    const close  = ohlcvRows[ohlcvRows.length - 1]?.close;
    if (!close) return;

    const fmtP = v => {
        if (v == null || !isFinite(v)) return '—';
        return close > 100 ? v.toFixed(2) : v.toFixed(4);
    };
    const setW = (id, text, cls) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = text;
        el.className   = `trend-sig-val-w ${cls}`;
    };

    const ss = lastOf(data.short_state)?.value  || 0;
    const ms = lastOf(data.medium_state)?.value || 0;
    const ls = lastOf(data.long_state)?.value   || 0;
    const comp = ss + ms + ls;

    const compMap = {
         3: ['STRONG LONG',  'bull-strong'],
         2: ['LONG',         'bull'],
         1: ['LEAN LONG',    'bull-soft'],
         0: ['NEUTRAL',      'neutral'],
        '-1': ['LEAN SHORT', 'bear-soft'],
        '-2': ['SHORT',      'bear'],
        '-3': ['STRONG SHORT','bear-strong'],
    };
    const [compLabel, compCls] = compMap[String(comp)] || ['—', 'neutral'];

    const compWEl = document.getElementById('trend-composite-w');
    if (compWEl) {
        compWEl.textContent = compLabel;
        compWEl.className   = `trend-composite-badge ${compCls}`;
    }
    const strengthWEl = document.getElementById('trend-strength-w');
    if (strengthWEl) {
        const abs = Math.abs(comp);
        const dot = '●'; const empty = '○';
        strengthWEl.textContent = Array.from({ length: 3 }, (_, i) => i < abs ? dot : empty).join(' ');
        strengthWEl.className   = `trend-strength-bar ${comp >= 0 ? 'bull' : 'bear'}`;
    }

    const stateLabel = v => v > 0 ? 'LONG' : v < 0 ? 'SHORT' : 'NEUT';
    const stateClass = v => v > 0 ? 'bull' : v < 0 ? 'bear'  : 'neutral';
    setW('trend-sig-short-w',  stateLabel(ss), stateClass(ss));
    setW('trend-sig-medium-w', stateLabel(ms), stateClass(ms));
    setW('trend-sig-long-w',   stateLabel(ls), stateClass(ls));
}

// ── Signal panel collapse / expand ────────────────────────────
function toggleTrendSignalPanel() {
    const panel  = document.getElementById('trend-panel-signal');
    const tab    = document.getElementById('trend-sig-tab');
    const colBtn = document.getElementById('trend-sig-collapse-btn');
    if (!panel) return;

    const isCollapsed = panel.classList.contains('collapsed');
    panel.classList.toggle('collapsed', !isCollapsed);

    if (tab) {
        tab.style.display  = isCollapsed ? 'none' : 'flex';
        tab.textContent    = '›';
    }
    if (colBtn) {
        colBtn.textContent = isCollapsed ? '‹' : '›';
        colBtn.title       = isCollapsed ? 'Hide panel' : 'Show panel';
    }

    // Trigger chart resize after transition
    setTimeout(() => {
        [trendCharts.price, trendCharts.regime, trendChartsW.price, trendChartsW.regime].forEach(c => {
            if (!c) return;
            try {
                const el = c.chartElement?.parentElement;
                if (el) c.resize(el.clientWidth, el.clientHeight);
            } catch (_) {}
        });
    }, 280);
}

// ── Signal info tooltips ──────────────────────────────────────
const _SIG_INFO = {
    short: {
        title: 'Short Horizon Regime',
        desc:  'Driven by SB (fast KAMA). Reflects near-term momentum — flips quickly in trending markets, stays flat in choppy conditions.',
        params: 'SB · ER=10 · fast=2 · slow=15',
    },
    medium: {
        title: 'Medium Horizon Regime',
        desc:  'Master trend signal driven by MB. Governs all trade management bands (MRT stop, MDB target). Entry fires when SB crosses MB.',
        params: 'MB · ER=20 · fast=2 · slow=30',
    },
    long: {
        title: 'Long Horizon Regime',
        desc:  'Macro structure driven by LB. Only flips on sustained multi-month moves. Context for LRT wide stop and LDB extended target.',
        params: 'LB · ER=40 · fast=2 · slow=60',
    },
    entry: {
        title: 'Last Entry Signal',
        desc:  'Most recent LONG or SHORT entry — fires when SB crosses MB (medium regime flip). Date shown for reference.',
        params: 'SB cross MB · medium regime change',
    },
    mrt: {
        title: 'MRT — Trailing Stop',
        desc:  'Medium Retracement Band. Sits 2.25 ATR below MB in a long regime. Ratchets upward as MB advances; never retreats against the trade.',
        params: 'MB − 2.25 × ATR(20) · ratchets in long regime',
    },
    sdb: {
        title: 'SDB — Target 1',
        desc:  'Short Deviation Band. First take-profit level. 2.0 ATR above SB. Ratcheting band — moves only in the direction of the trade.',
        params: 'SB + 2.0 × ATR(20) · ratchets in long regime',
    },
    mdb: {
        title: 'MDB — Target 2',
        desc:  'Medium Deviation Band. Main take-profit at 4.5 ATR above MB — exactly 2× the stop distance, giving a built-in 2:1 R:R.',
        params: 'MB + 4.5 × ATR(20) · ratchets in long regime',
    },
    rr: {
        title: 'Risk : Reward Ratio',
        desc:  'Live R:R = distance to MDB ÷ distance to MRT from current close. ≥ 2:1 = green (favorable). Only meaningful in an active regime.',
        params: '(MDB − close) ÷ (close − MRT)',
    },
};

function _initSigTooltips() {
    const tip = document.getElementById('trend-sig-tooltip');
    if (!tip) return;

    document.querySelectorAll('.trend-sig-info-btn').forEach(btn => {
        btn.addEventListener('mouseenter', e => {
            const key  = btn.dataset.infoKey;
            const info = _SIG_INFO[key];
            if (!info) return;

            tip.innerHTML =
                `<div class="ts-tip-title">${info.title}</div>` +
                `<div class="ts-tip-desc">${info.desc}</div>` +
                `<div class="ts-tip-params">${info.params}</div>`;

            // Position tooltip to the left of the button, avoid overflow
            const rect = btn.getBoundingClientRect();
            const tipW = 220;
            let left = rect.left - tipW - 8;
            if (left < 8) left = rect.right + 8;
            let top  = rect.top - 10;
            if (top + 120 > window.innerHeight) top = window.innerHeight - 130;

            tip.style.left = left + 'px';
            tip.style.top  = top  + 'px';
            tip.classList.add('ts-tip-visible');
        });

        btn.addEventListener('mouseleave', () => {
            tip.classList.remove('ts-tip-visible');
        });
    });
}

// Call once DOM is ready (trend tab is rendered)
document.addEventListener('DOMContentLoaded', _initSigTooltips);

// ── Parameter optimization ────────────────────────────────
let _optAbortCtrl = null;

async function runTrendOptimize() {
    const symbol = (typeof state !== 'undefined') ? state.activeSymbol : null;
    if (!symbol) return;

    // Cancel any in-flight optimization
    if (_optAbortCtrl) { _optAbortCtrl.abort(); _optAbortCtrl = null; }
    _optAbortCtrl = new AbortController();

    const btn   = document.getElementById('btn-trend-optimize');
    const panel = document.getElementById('trend-opt-panel');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Optimizing…'; }
    if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }

    try {
        const res = await fetch(
            `${typeof API !== 'undefined' ? API : '/api'}/adaptive-trend/${symbol}/optimize`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ freq: trendState.freq, method: trendState.method }),
                signal: _optAbortCtrl.signal,
            }
        );
        if (!res.ok) {
            const err = await res.json().catch(() => ({ error: res.statusText }));
            throw new Error(err.error || res.statusText);
        }
        const data = await res.json();
        _renderOptPanel(data);
    } catch (e) {
        if (e.name === 'AbortError') return;   // user navigated away
        if (panel) {
            panel.style.display = 'flex';
            panel.innerHTML = `<span class="trend-opt-error">Optimize failed: ${e.message}</span>`;
        }
    } finally {
        _optAbortCtrl = null;
        if (btn) { btn.disabled = false; btn.textContent = '⚡ Optimize'; }
    }
}

function _renderOptPanel(data) {
    const panel = document.getElementById('trend-opt-panel');
    if (!panel) return;

    const imp     = data.improvement_pct ?? 0;
    const impSign = imp >= 0 ? '+' : '';
    const impCls  = imp > 1  ? 'opt-pos' : imp < -1 ? 'opt-neg' : 'opt-neut';
    const changed = data.changed || [];

    // Build changed-params HTML
    const PARAM_LABELS = {
        sb_er: 'SB ER', sb_slow: 'SB slow',
        mb_er: 'MB ER', mb_slow: 'MB slow',
        lb_er: 'LB ER', lb_slow: 'LB slow',
        atr_fast: 'ATR fast', atr_slow: 'ATR slow', atr_er: 'ATR ER',
    };
    const opt  = data.optimal_params  || {};
    const def  = data.default_params  || {};
    const changedHtml = changed.length === 0
        ? '<span class="opt-no-change">Default params already optimal</span>'
        : changed.map(k => {
            const label = PARAM_LABELS[k] || k;
            const from  = def[k] ?? '?';
            const to    = opt[k] ?? '?';
            return `<span class="opt-param-chip">${label}: <s>${from}</s> → <strong>${to}</strong></span>`;
          }).join('');

    panel.innerHTML = `
        <div class="trend-opt-summary">
            <span class="opt-score-label">Score improvement:</span>
            <span class="opt-score ${impCls}">${impSign}${imp.toFixed(1)}%</span>
            <span class="opt-sep">·</span>
            <span class="opt-baseline-label">baseline</span>
            <span class="opt-score-val">${(data.baseline_score ?? 0).toFixed(4)}</span>
            <span class="opt-arrow">→</span>
            <span class="opt-score-val">${(data.best_score ?? 0).toFixed(4)}</span>
        </div>
        <div class="trend-opt-params">${changedHtml}</div>
        <div class="trend-opt-actions">
            <button class="btn btn-primary btn-sm trend-opt-apply"
                    onclick="applyOptimizedParams(${JSON.stringify(JSON.stringify(opt))})">
                ✓ Apply
            </button>
            <button class="btn btn-ghost btn-sm" onclick="closeTrendOptPanel()">✕ Dismiss</button>
        </div>
    `;
    panel.style.display = 'flex';

    // Show reset button if already using custom params
    _syncResetBtn();
}

function applyOptimizedParams(paramsJson) {
    const params = typeof paramsJson === 'string' ? JSON.parse(paramsJson) : paramsJson;
    trendState.params = params;
    _syncResetBtn();
    closeTrendOptPanel();
    const symbol = (typeof state !== 'undefined') ? state.activeSymbol : null;
    if (symbol && typeof loadAdaptiveTrendData === 'function') {
        loadAdaptiveTrendData(symbol);
    }
}

function resetTrendParams() {
    trendState.params = null;
    _syncResetBtn();
    closeTrendOptPanel();
    const symbol = (typeof state !== 'undefined') ? state.activeSymbol : null;
    if (symbol && typeof loadAdaptiveTrendData === 'function') {
        loadAdaptiveTrendData(symbol);
    }
}

function closeTrendOptPanel() {
    const panel = document.getElementById('trend-opt-panel');
    if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
}

function _syncResetBtn() {
    const btn = document.getElementById('btn-trend-reset-params');
    if (btn) btn.style.display = trendState.params ? 'inline-flex' : 'none';
}
