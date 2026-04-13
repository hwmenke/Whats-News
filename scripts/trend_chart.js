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
    vis:    { lb: true, lrt: true, ldb: true, sdb: true, mrt: true, mdb: true },
    data:   null,
};

// ── Instances ─────────────────────────────────────────────────
let trendCharts    = { price: null, regime: null };
let trendSeries    = {
    // Background regime fills (on hidden left scale)
    bgLong: null, bgShort: null,
    // Price overlays
    candle:   null,
    sb: null, mb: null, lb: null,
    sdb: null, mrt: null, mdb: null, lrt: null, ldb: null,
    // Regime strip
    regLong: null, regMed: null, regShort: null,
};
let _trendObservers = [];   // ResizeObserver instances — cleaned up on destroy
let _regSyncing     = false;

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
    // Clean up resize observers first to prevent stale callbacks
    _trendObservers.forEach(obs => obs.disconnect());
    _trendObservers = [];

    Object.values(trendCharts).forEach(c => { if (c) c.remove(); });
    trendCharts = { price: null, regime: null };
    trendSeries = {
        bgLong: null, bgShort: null,
        candle: null, sb: null, mb: null, lb: null,
        sdb: null, mrt: null, mdb: null, lrt: null, ldb: null,
        regLong: null, regMed: null, regShort: null,
    };
    _regSyncing = false;
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

// ── Visibility toggles ────────────────────────────────────────
function _applyVis() {
    const LS = LightweightCharts.LineStyle;
    const show = (s, color, lw, ls) => {
        if (s) s.applyOptions({ visible: true, color, lineWidth: lw, lineStyle: ls });
    };
    const hide = s => { if (s) s.applyOptions({ visible: false }); };

    if (trendState.vis.lb)  show(trendSeries.lb,  TC.lb,  1.5, LS.Dashed);
    else                    hide(trendSeries.lb);

    if (trendState.vis.lrt) show(trendSeries.lrt, TC.lrt, 1,   LS.Dashed);
    else                    hide(trendSeries.lrt);

    if (trendState.vis.ldb) show(trendSeries.ldb, TC.ldb, 1,   LS.Dashed);
    else                    hide(trendSeries.ldb);

    if (trendState.vis.sdb) show(trendSeries.sdb, TC.sdb, 1,   LS.Dashed);
    else                    hide(trendSeries.sdb);

    if (trendState.vis.mrt) show(trendSeries.mrt, TC.mrt, 1.5, LS.Dashed);
    else                    hide(trendSeries.mrt);

    if (trendState.vis.mdb) show(trendSeries.mdb, TC.mdb, 1,   LS.Dashed);
    else                    hide(trendSeries.mdb);
}

function toggleTrendLine(key) {
    trendState.vis[key] = !trendState.vis[key];
    const btn = document.getElementById(`trend-toggle-${key}`);
    if (btn) btn.classList.toggle('trend-toggle-on', trendState.vis[key]);
    _applyVis();
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
    if (typeof state !== 'undefined' && state.activeSymbol) {
        loadAdaptiveTrendData(state.activeSymbol);
    }
}

// ── Signal panel ──────────────────────────────────────────────
function _updateSignalPanel(data, ohlcvRows) {
    const lastOf = arr => Array.isArray(arr) && arr.length ? arr[arr.length - 1] : null;
    const close  = ohlcvRows[ohlcvRows.length - 1].close;

    // Format price: 2 dp for large values (indices), 4 dp for FX
    const fmtP = v => {
        if (v == null || !isFinite(v)) return '—';
        return close > 100 ? v.toFixed(2) : v.toFixed(4);
    };

    const setCard = (id, text, cls) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent  = text;
        el.className    = `trend-signal-value ${cls}`;
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
