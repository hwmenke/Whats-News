/**
 * scanner.js — Multi-timeframe watchlist scanner
 *
 * Displays a sortable, colour-coded heatmap table of technical metrics
 * for every symbol in the watchlist, across Daily / Weekly / Monthly
 * timeframes.
 *
 * Metric groups (all toggleable):
 *   RSI          — RSI(7), RSI(14), RSI(21)
 *   KAMA Ratios  — P/KAMA_fast %ile, P/KAMA_med %ile, KAMA cross %
 *   Momentum     — ROC 1M/3M/6M, Bollinger %B
 *   Volatility   — ATR%, Vol Ratio, 52W High dist, SMA200 dist
 *
 * Each cell is colour-coded with a 7-level heatmap:
 *   sc-s3 (strong bull) → sc-s2 → sc-s1 → sc-n → sc-b1 → sc-b2 → sc-b3 (strong bear)
 *   sc-hi1/2/3 for highlighted/momentum cells (blue)
 */

// ── State ─────────────────────────────────────────────────────────────
const scannerState = {
    mode:    'technical',          // 'technical' | 'jeff'
    data:    null,                 // technical scan rows
    jeff:    null,                 // jeff scan rows (raw, unfiltered)
    jeffSortKey: null,
    jeffSortDir: -1,
    filters: { grade: 'all', trigger: 'all', rvol: 'all', tier: 'all',
               notExt: false, above50: false },
    sortKey: null,
    sortDir: 1,
    visible: { rsi: true, kama: true, mom: true, vol: true, trend: true },
};

// ── Column definitions ─────────────────────────────────────────────────
// groups → metrics → timeframes → cells
const SCAN_GROUPS = [
    {
        id: 'rsi', label: 'RSI',
        metrics: [
            { key: 'rsi_7',  label: 'RSI(7)',  tfs: ['d','w','m'], fmt: 'rsi'   },
            { key: 'rsi_14', label: 'RSI(14)', tfs: ['d','w','m'], fmt: 'rsi'   },
            { key: 'rsi_21', label: 'RSI(21)', tfs: ['d','w','m'], fmt: 'rsi'   },
        ],
    },
    {
        id: 'kama', label: 'KAMA Ratios',
        metrics: [
            { key: 'p_kf_pct', label: 'P/KF %ile', tfs: ['d','w','m'], fmt: 'pct'   },
            { key: 'p_km_pct', label: 'P/KM %ile', tfs: ['d','w','m'], fmt: 'pct'   },
            { key: 'kf_km',    label: 'KF/KM%',    tfs: ['d','w','m'], fmt: 'cross' },
        ],
    },
    {
        id: 'mom', label: 'Momentum',
        metrics: [
            { key: 'roc_1m', label: 'ROC 1M', tfs: ['d','w','m'], fmt: 'roc' },
            { key: 'roc_3m', label: 'ROC 3M', tfs: ['d','w','m'], fmt: 'roc' },
            { key: 'roc_6m', label: 'ROC 6M', tfs: ['d','w'],     fmt: 'roc' },
            { key: 'bb_b',   label: 'BB %B',  tfs: ['d','w','m'], fmt: 'bbb' },
        ],
    },
    {
        id: 'vol', label: 'Volatility · Structure',
        metrics: [
            { key: 'atr_pct',   label: 'ATR%',     tfs: ['d','w'], fmt: 'atr'  },
            { key: 'vol_ratio', label: 'Vol Ratio', tfs: ['d'],     fmt: 'volr' },
            { key: 'dist_hi',   label: '52W Hi%',   tfs: ['d'],     fmt: 'dist' },
            { key: 'dist_sma',  label: 'Δ SMA200',  tfs: ['d'],     fmt: 'sma'  },
        ],
    },
    {
        id: 'trend', label: 'Trend',
        metrics: [
            { key: 'trend_score', label: 'Trend', tfs: ['d', 'w'], fmt: 'trend' },
        ],
    },
];

// ── Cell formatting + colour mapping ──────────────────────────────────
function _fmtCell(fmt, val) {
    if (val == null) return { text: '—', cls: 'sc-n' };

    switch (fmt) {

        case 'rsi': {
            // Low RSI = oversold = bull; high = overbought = bear
            const t = val.toFixed(1);
            const c = val < 25 ? 'sc-s3' : val < 35 ? 'sc-s2' : val < 45 ? 'sc-s1'
                    : val > 75 ? 'sc-b3' : val > 65 ? 'sc-b2' : val > 55 ? 'sc-b1' : 'sc-n';
            return { text: t, cls: c };
        }

        case 'pct': {
            // Percentile of price/KAMA — low = price cheap vs history (bull)
            const t = val.toFixed(0) + '%';
            const c = val < 20 ? 'sc-s3' : val < 35 ? 'sc-s2' : val < 45 ? 'sc-s1'
                    : val > 80 ? 'sc-b3' : val > 65 ? 'sc-b2' : val > 55 ? 'sc-b1' : 'sc-n';
            return { text: t, cls: c };
        }

        case 'cross': {
            // KF/KM cross: positive = fast > medium = bullish trend
            const t = (val >= 0 ? '+' : '') + val.toFixed(2) + '%';
            const c = val >  2 ? 'sc-s3' : val >  1 ? 'sc-s2' : val >  0 ? 'sc-s1'
                    : val < -2 ? 'sc-b3' : val < -1 ? 'sc-b2' : 'sc-b1';
            return { text: t, cls: c };
        }

        case 'roc': {
            // Rate of change — positive = momentum up
            const t = (val >= 0 ? '+' : '') + val.toFixed(1) + '%';
            const c = val >  15 ? 'sc-s3' : val >  5 ? 'sc-s2' : val >  0 ? 'sc-s1'
                    : val < -15 ? 'sc-b3' : val < -5 ? 'sc-b2' : 'sc-b1';
            return { text: t, cls: c };
        }

        case 'bbb': {
            // Bollinger %B: 0 = lower band (oversold), 1 = upper band (overbought)
            const t = val.toFixed(2);
            const c = val < 0.0  ? 'sc-s3' : val < 0.2 ? 'sc-s2' : val < 0.4 ? 'sc-s1'
                    : val > 1.0  ? 'sc-b3' : val > 0.8 ? 'sc-b2' : val > 0.6 ? 'sc-b1' : 'sc-n';
            return { text: t, cls: c };
        }

        case 'atr': {
            // ATR%: higher = more volatile (informational, not directional)
            const t = val.toFixed(2) + '%';
            const c = val > 5 ? 'sc-b2' : val > 3 ? 'sc-b1' : val > 1.5 ? 'sc-n' : 'sc-s1';
            return { text: t, cls: c };
        }

        case 'volr': {
            // Volume ratio: high = surge (blue highlight)
            const t = val.toFixed(2) + 'x';
            const c = val > 2.5 ? 'sc-hi3' : val > 1.75 ? 'sc-hi2' : val > 1.25 ? 'sc-hi1' : 'sc-n';
            return { text: t, cls: c };
        }

        case 'dist': {
            // Distance from period high: 0 = at high (momentum leader = blue)
            const t = val.toFixed(1) + '%';
            const c = val > -3  ? 'sc-hi2' : val > -10 ? 'sc-n'
                    : val > -25 ? 'sc-b1' : 'sc-b2';
            return { text: t, cls: c };
        }

        case 'sma': {
            // Distance above/below 200-bar SMA: above = uptrend (bull)
            const t = (val >= 0 ? '+' : '') + val.toFixed(1) + '%';
            const c = val > 20 ? 'sc-b1'  // very extended above = warning
                    : val >  0 ? 'sc-s1'  // above SMA = healthy uptrend
                    : val > -10 ? 'sc-b1'
                    : 'sc-b2';
            return { text: t, cls: c };
        }

        case 'trend': {
            if (val == null) return { text: '—', cls: 'sc-n' };
            const t = (val > 0 ? '+' : '') + val.toFixed(0);
            const c = val >= 2  ? 'sc-s3'
                    : val >= 1  ? 'sc-s2'
                    : val >  0  ? 'sc-s1'
                    : val <= -2 ? 'sc-b3'
                    : val <= -1 ? 'sc-b2'
                    : val <   0 ? 'sc-b1' : 'sc-n';
            return { text: t, cls: c };
        }
    }

    return { text: '—', cls: 'sc-n' };
}

// ── Composite signal score (−5 … +5) ─────────────────────────────────
function _score(row) {
    const d = row.d;
    const w = row.w;
    let s = 0, n = 0;

    // val < bullBelow = bullish, val > bearAbove = bearish
    const addRange = (val, bullBelow, bearAbove, wt = 1) => {
        if (val == null) return;
        s += val < bullBelow ? wt : val > bearAbove ? -wt : 0;
        n += wt;
    };
    // positive = bullish, negative = bearish
    const addDir = (val, wt = 1) => {
        if (val == null) return;
        s += val > 0 ? wt : val < 0 ? -wt : 0;
        n += wt;
    };

    if (d) {
        addRange(d.rsi_14,   45, 55);
        addRange(d.p_km_pct, 40, 60);
        addDir(d.kf_km);
        addDir(d.roc_1m);
        addRange(d.bb_b,   0.4, 0.6);
        addDir(d.trend_score);
    }
    if (w) {
        addRange(w.rsi_14,   45, 55, 0.5);
        addDir(w.kf_km,             0.5);
        addDir(w.roc_1m,            0.5);
        addDir(w.trend_score,       0.5);
    }

    if (n === 0) return null;
    return Math.max(-5, Math.min(5, Math.round(s * 5 / n)));
}

// ── Header builder ─────────────────────────────────────────────────────
function _buildHeader() {
    const tr1 = document.createElement('tr');  // group spans
    const tr2 = document.createElement('tr');  // metric sub-headers
    const tr3 = document.createElement('tr');  // D / W / M sort cells

    // Fixed columns — Symbol, Score, Price, Chg% — rowspan 3
    const fixed = [
        { label: 'Symbol', key: 'symbol' },
        { label: 'Score',  key: '_score'  },
        { label: 'Price',  key: 'price'   },
        { label: 'Chg%',   key: 'chg'     },
    ];
    for (const fc of fixed) {
        const th = _th('scan-th scan-th-fixed scan-sortable');
        th.textContent    = fc.label;
        th.rowSpan        = 3;
        th.dataset.sortKey = fc.key;
        th.addEventListener('click', () => sortScanner(fc.key));
        tr1.appendChild(th);
    }

    for (const grp of SCAN_GROUPS) {
        if (!scannerState.visible[grp.id]) continue;
        const totalCols = grp.metrics.reduce((s, m) => s + m.tfs.length, 0);

        // Row 1 — group label
        const thG = _th('scan-th scan-th-group');
        thG.textContent = grp.label;
        thG.colSpan     = totalCols;
        tr1.appendChild(thG);

        for (const m of grp.metrics) {
            // Row 2 — metric label, spans its timeframe cells
            const thM = _th('scan-th scan-th-metric');
            thM.textContent = m.label;
            thM.colSpan     = m.tfs.length;
            tr2.appendChild(thM);

            // Row 3 — D / W / M, clickable for sort
            for (const tf of m.tfs) {
                const sk  = `${tf}.${m.key}`;
                const thT = _th(`scan-th scan-th-tf scan-sortable${scannerState.sortKey === sk ? ' scan-sort-active' : ''}`);
                thT.textContent    = tf.toUpperCase();
                thT.dataset.sortKey = sk;
                thT.title          = `Sort by ${m.label} (${tf.toUpperCase()})`;
                thT.addEventListener('click', () => sortScanner(sk));
                tr3.appendChild(thT);
            }
        }
    }

    return [tr1, tr2, tr3];
}

// ── Row builder ────────────────────────────────────────────────────────
function _buildRow(row) {
    const tr = document.createElement('tr');
    tr.className = 'scan-row';
    if (row.error) tr.classList.add('scan-row-error');

    // Symbol — click to load
    const tdSym = _td('scan-td scan-td-sym');
    tdSym.textContent = row.symbol;
    tdSym.title = row.error ? `Error: ${row.error}` : `Load ${row.symbol}`;
    tdSym.addEventListener('click', () => {
        if (typeof selectSymbol === 'function') selectSymbol(row.symbol);
    });
    tr.appendChild(tdSym);

    // Score
    const sc    = _score(row);
    const scTd  = _td('scan-td scan-td-score');
    if (sc != null) {
        scTd.textContent  = sc > 0 ? `+${sc}` : `${sc}`;
        scTd.className   += sc >=  3 ? ' sc-s3' : sc >=  1 ? ' sc-s1'
                          : sc <= -3 ? ' sc-b3' : sc <= -1 ? ' sc-b1' : ' sc-n';
    } else {
        scTd.textContent = '—';
    }
    tr.appendChild(scTd);

    // Price
    const tdPrice = _td('scan-td scan-td-price');
    tdPrice.textContent = row.price != null
        ? row.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
        : '—';
    tr.appendChild(tdPrice);

    // Chg%
    const chgCls = row.chg != null ? (row.chg >= 0 ? 'sc-s1' : 'sc-b1') : 'sc-n';
    const tdChg  = _td(`scan-td ${chgCls}`);
    tdChg.textContent = row.chg != null
        ? (row.chg >= 0 ? '+' : '') + row.chg.toFixed(2) + '%'
        : '—';
    tr.appendChild(tdChg);

    // Metric cells
    for (const grp of SCAN_GROUPS) {
        if (!scannerState.visible[grp.id]) continue;
        for (const m of grp.metrics) {
            for (const tf of m.tfs) {
                const val         = row[tf]?.[m.key];
                const { text, cls } = _fmtCell(m.fmt, val);
                const td          = _td(`scan-td ${cls}`);
                td.textContent    = text;
                if (val != null) {
                    td.title = `${row.symbol}  ${m.label} (${tf.toUpperCase()}) = ${val}`;
                }
                tr.appendChild(td);
            }
        }
    }

    return tr;
}

// ── DOM helpers ────────────────────────────────────────────────────────
function _th(cls) {
    const el = document.createElement('th');
    el.className = cls;
    return el;
}

function _td(cls) {
    const el = document.createElement('td');
    el.className = cls;
    return el;
}

// ── Sort ───────────────────────────────────────────────────────────────
function sortScanner(key) {
    scannerState.sortDir = scannerState.sortKey === key ? scannerState.sortDir * -1 : 1;
    scannerState.sortKey = key;
    if (typeof persistence !== 'undefined') {
        _persistScanner();
    }
    if (scannerState.data) renderScannerTable(scannerState.data);
}

function _sorted(data) {
    const key = scannerState.sortKey;
    if (!key) return data;
    return [...data].sort((a, b) => {
        let va, vb;
        if      (key === 'symbol') { va = a.symbol;  vb = b.symbol; }
        else if (key === '_score') { va = _score(a); vb = _score(b); }
        else if (key === 'price')  { va = a.price;   vb = b.price;  }
        else if (key === 'chg')    { va = a.chg;     vb = b.chg;    }
        else {
            const [tf, metric] = key.split('.');
            va = a[tf]?.[metric];
            vb = b[tf]?.[metric];
        }
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === 'string') return va.localeCompare(vb) * scannerState.sortDir;
        return (va - vb) * scannerState.sortDir;
    });
}

// ── Render ─────────────────────────────────────────────────────────────
function renderScannerTable(data) {
    scannerState.data = data;
    const thead = document.getElementById('scanner-thead');
    const tbody = document.getElementById('scanner-tbody');
    const empty = document.getElementById('scanner-empty');
    if (!thead || !tbody) return;

    // Drop Jeff-mode styling/markup if we just came from that mode
    const table = document.getElementById('scanner-table');
    const wrap  = document.querySelector('.scanner-table-wrap');
    if (table) table.classList.remove('jf-table');
    if (wrap)  wrap.classList.remove('jf-table-wrap');
    if (empty) empty.innerHTML =
        '<div class="empty-icon">📡</div><p>No symbols in watchlist, or data not yet fetched.<br>' +
        'Add tickers, then click <strong>⟳ Scan All</strong>.</p>';

    // Header
    thead.innerHTML = '';
    const [tr1, tr2, tr3] = _buildHeader();
    thead.appendChild(tr1);
    thead.appendChild(tr2);
    thead.appendChild(tr3);

    // Rows
    tbody.innerHTML = '';
    const rows = _sorted(data);
    if (!rows.length) {
        empty.style.display = 'flex';
        return;
    }
    empty.style.display = 'none';
    rows.forEach(row => tbody.appendChild(_buildRow(row)));
}

// ── Group visibility toggle ────────────────────────────────────────────
function toggleScanGroup(id) {
    scannerState.visible[id] = !scannerState.visible[id];
    const btn = document.querySelector(`.scan-grp-btn[data-grp="${id}"]`);
    if (btn) btn.classList.toggle('scanner-toggle-on', scannerState.visible[id]);
    if (scannerState.data) renderScannerTable(scannerState.data);
}

// ── Data loading ───────────────────────────────────────────────────────
async function loadScannerData() {
    if (typeof persistence !== 'undefined') {
        const saved = persistence.loadTab('scanner');
        if (saved?.sortKey) {
            scannerState.sortKey = saved.sortKey;
            scannerState.sortDir = saved.sortDir ?? 1;
        }
    }

    const loadEl  = document.getElementById('scanner-loading');
    const btnScan = document.getElementById('btn-scan');
    const tsEl    = document.getElementById('scanner-ts');

    if (loadEl)   loadEl.style.display = 'flex';
    if (btnScan)  { btnScan.disabled = true; btnScan.innerHTML = '<span class="spinner"></span> Scanning…'; }

    try {
        const data = await apiFetch(`${API}/scanner`);
        if (!Array.isArray(data)) throw new Error('Unexpected response from server');
        renderScannerTable(data);
        if (tsEl) tsEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
    } catch (e) {
        toast('Scanner error: ' + e.message, 'error');
    } finally {
        if (loadEl)   loadEl.style.display = 'none';
        if (btnScan)  { btnScan.disabled = false; btnScan.innerHTML = '⟳ Scan All'; }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  JEFF SETUP SCANNER
// ═══════════════════════════════════════════════════════════════════════════════

// saveTab overwrites the whole tab object, so always persist the full state.
function _persistScanner() {
    if (typeof persistence === 'undefined') return;
    persistence.saveTab('scanner', {
        mode:        scannerState.mode,
        filters:     scannerState.filters,
        sortKey:     scannerState.sortKey,
        sortDir:     scannerState.sortDir,
        jeffSortKey: scannerState.jeffSortKey,
        jeffSortDir: scannerState.jeffSortDir,
    });
}

// ── Entry point + mode dispatch ────────────────────────────────────────────────

function initScanner() {
    if (typeof persistence !== 'undefined') {
        const saved = persistence.loadTab('scanner');
        if (saved?.mode)    scannerState.mode    = saved.mode;
        if (saved?.filters) scannerState.filters = { ...scannerState.filters, ...saved.filters };
        if (saved?.sortKey) { scannerState.sortKey = saved.sortKey; scannerState.sortDir = saved.sortDir ?? 1; }
        if (saved?.jeffSortKey) { scannerState.jeffSortKey = saved.jeffSortKey; scannerState.jeffSortDir = saved.jeffSortDir ?? -1; }
    }
    _syncScanModeUI();
    runScan();
}

function runScan() {
    if (scannerState.mode === 'jeff') loadJeffScan();
    else                              loadScannerData();
}

function setScanMode(mode) {
    if (scannerState.mode === mode) return;
    scannerState.mode = mode;
    _persistScanner();
    _syncScanModeUI();
    // Render from cache if we have it; otherwise fetch
    if (mode === 'jeff') {
        if (scannerState.jeff) _renderJeffScan();
        else                   loadJeffScan();
    } else {
        if (scannerState.data) renderScannerTable(scannerState.data);
        else                   loadScannerData();
    }
}

function _syncScanModeUI() {
    const jeff = scannerState.mode === 'jeff';
    document.querySelectorAll('.scan-mode-btn').forEach(b =>
        b.classList.toggle('scan-mode-on', b.dataset.mode === scannerState.mode));
    const tech = document.getElementById('scan-tech-groups');
    const filt = document.getElementById('scan-jeff-filters');
    const bann = document.getElementById('jeff-banner');
    if (tech) tech.style.display = jeff ? 'none' : '';
    if (filt) filt.style.display = jeff ? 'flex' : 'none';
    if (bann) bann.style.display = jeff ? '' : 'none';
}

// ── Data loading ───────────────────────────────────────────────────────────────

async function loadJeffScan() {
    const loadEl  = document.getElementById('scanner-loading');
    const btnScan = document.getElementById('btn-scan');
    const tsEl    = document.getElementById('scanner-ts');

    if (loadEl)  loadEl.style.display = 'flex';
    if (btnScan) { btnScan.disabled = true; btnScan.innerHTML = '<span class="spinner"></span> Scanning…'; }

    try {
        // Fetch scan + market context together; context failures are non-fatal
        const [scan, breadth, rstats] = await Promise.all([
            apiFetch(`${API}/jeff-scan`),
            apiFetch(`${API}/breadth`).catch(() => null),
            apiFetch(`${API}/r-analytics`).catch(() => null),
        ]);
        scannerState.jeff       = scan.rows || [];
        scannerState.jeffHasSpy = !!scan.spy_available;
        _renderJeffBanner(breadth, rstats);
        _renderJeffFilters();
        _renderJeffScan();
        if (tsEl) tsEl.textContent = 'Updated ' + new Date().toLocaleTimeString();
    } catch (e) {
        toast('Jeff scan error: ' + e.message, 'error');
    } finally {
        if (loadEl)  loadEl.style.display = 'none';
        if (btnScan) { btnScan.disabled = false; btnScan.innerHTML = '⟳ Scan All'; }
    }
}

// ── Market context banner ────────────────────────────────────────────────────────

function _renderJeffBanner(breadth, rstats) {
    const el = document.getElementById('jeff-banner');
    if (!el) return;
    if (!breadth || breadth.error) { el.innerHTML = ''; return; }

    const p50 = breadth.pct_above_50ma ?? 0;
    let regimeTxt, regimeCls;
    if      (p50 >= 70) { regimeTxt = 'Broad Uptrend';  regimeCls = 'jf-regime-bull'; }
    else if (p50 >= 50) { regimeTxt = 'Mixed Market';   regimeCls = 'jf-regime-mix';  }
    else if (p50 >= 30) { regimeTxt = 'Under Pressure'; regimeCls = 'jf-regime-warn'; }
    else                { regimeTxt = 'Broad Downtrend';regimeCls = 'jf-regime-bear'; }

    // Edge feedback: pull A-grade expectancy from r-analytics if present
    let edgeHtml = '';
    const gA = rstats?.grade_stats?.A;
    if (gA && gA.count) {
        const cls = gA.expectancy > 0 ? 'jf-pos' : 'jf-neg';
        edgeHtml = `<div class="jf-banner-edge">
            <span class="jf-edge-label">Your A setups</span>
            <span class="jf-edge-val ${cls}">${gA.expectancy > 0 ? '+' : ''}${gA.expectancy.toFixed(2)}R</span>
            <span class="jf-edge-sub">${gA.count} trade${gA.count === 1 ? '' : 's'}</span>
        </div>`;
    } else if (rstats && rstats.count) {
        const cls = rstats.expectancy > 0 ? 'jf-pos' : 'jf-neg';
        edgeHtml = `<div class="jf-banner-edge">
            <span class="jf-edge-label">Your edge</span>
            <span class="jf-edge-val ${cls}">${rstats.expectancy > 0 ? '+' : ''}${rstats.expectancy.toFixed(2)}R</span>
            <span class="jf-edge-sub">${rstats.count} trades</span>
        </div>`;
    }

    const warn = p50 < 30
        ? `<span class="jf-banner-warn">⚠ Broad downtrend — be selective with new longs</span>` : '';

    el.className = `jf-banner ${regimeCls}`;
    el.innerHTML = `
        <div class="jf-banner-main">
            <span class="jf-regime-pill">🌡 ${regimeTxt}</span>
            <span class="jf-stat"><b>${breadth.ad_ratio?.toFixed?.(2) ?? '—'}</b> A/D</span>
            <span class="jf-stat"><b>${p50}%</b> &gt;50MA</span>
            <span class="jf-stat jf-pos"><b>${breadth.new_highs ?? 0}</b> NH</span>
            <span class="jf-stat jf-neg"><b>${breadth.new_lows ?? 0}</b> NL</span>
            ${warn}
        </div>
        ${edgeHtml}`;
}

// ── Filter bar ─────────────────────────────────────────────────────────────────

function _renderJeffFilters() {
    const el = document.getElementById('scan-jeff-filters');
    if (!el) return;
    const f = scannerState.filters;
    const chip = (group, val, label) =>
        `<button class="jf-chip ${f[group] === val ? 'jf-chip-on' : ''}" onclick="setJeffFilter('${group}','${val}')">${label}</button>`;
    const toggle = (key, label) =>
        `<button class="jf-chip jf-chip-toggle ${f[key] ? 'jf-chip-on' : ''}" onclick="toggleJeffFilter('${key}')">${label}</button>`;

    el.innerHTML = `
        <div class="jf-fgrp"><span class="jf-flabel">Grade</span>
            ${chip('grade','all','All')}${chip('grade','A','A')}${chip('grade','AB','A+B')}</div>
        <div class="jf-fgrp"><span class="jf-flabel">Trigger</span>
            ${chip('trigger','all','All')}${chip('trigger','AT','At')}${chip('trigger','NEAR','Near')}</div>
        <div class="jf-fgrp"><span class="jf-flabel">RVOL</span>
            ${chip('rvol','all','All')}${chip('rvol','1','≥1')}${chip('rvol','1.5','≥1.5')}</div>
        <div class="jf-fgrp"><span class="jf-flabel">Tier</span>
            ${chip('tier','all','All')}${chip('tier','focus','🔥')}${chip('tier','stalk','🎯')}</div>
        <div class="jf-fgrp jf-fgrp-toggles">
            ${toggle('notExt','Not extended')}${toggle('above50','&gt;50MA')}</div>`;
}

function setJeffFilter(group, val) {
    scannerState.filters[group] = val;
    _persistScanner();
    _renderJeffFilters();
    _renderJeffScan();
}

function toggleJeffFilter(key) {
    scannerState.filters[key] = !scannerState.filters[key];
    _persistScanner();
    _renderJeffFilters();
    _renderJeffScan();
}

function _anyJeffFilter() {
    const f = scannerState.filters;
    return f.grade !== 'all' || f.trigger !== 'all' || f.rvol !== 'all' ||
           f.tier !== 'all' || f.notExt || f.above50;
}

function _filteredJeff() {
    const f = scannerState.filters;
    const anyActive = _anyJeffFilter();
    return (scannerState.jeff || []).filter(r => {
        if (r.error) return !anyActive;
        if (f.grade === 'A'  && r.grade !== 'A') return false;
        if (f.grade === 'AB' && r.grade !== 'A' && r.grade !== 'B') return false;
        if (f.trigger === 'AT'   && r.trigger_status !== 'AT') return false;
        if (f.trigger === 'NEAR' && r.trigger_status !== 'AT' && r.trigger_status !== 'NEAR') return false;
        if (f.rvol === '1'   && !(r.rvol >= 1.0)) return false;
        if (f.rvol === '1.5' && !(r.rvol >= 1.5)) return false;
        if (f.tier !== 'all' && r.tier !== f.tier) return false;
        if (f.notExt  && !(r.checks && r.checks.ext)) return false;
        if (f.above50 && !r.above_50ma) return false;
        return true;
    });
}

// ── Sorting ────────────────────────────────────────────────────────────────────

function sortJeff(key) {
    if (scannerState.jeffSortKey === key) scannerState.jeffSortDir *= -1;
    else { scannerState.jeffSortKey = key; scannerState.jeffSortDir = -1; }
    _persistScanner();
    _renderJeffScan();
}

function _sortedJeff(rows) {
    const key = scannerState.jeffSortKey;
    if (!key) return rows;               // keep server ranking
    const dir = scannerState.jeffSortDir;
    const gradeRank = { A: 0, B: 1, C: 2 };
    return [...rows].sort((a, b) => {
        if (a.error) return 1;
        if (b.error) return -1;
        let va, vb;
        if (key === 'symbol')     { va = a.symbol; vb = b.symbol; return va.localeCompare(vb) * dir; }
        else if (key === 'grade') { va = gradeRank[a.grade] ?? 3; vb = gradeRank[b.grade] ?? 3; }
        else if (key === 'trigger') { va = a.trigger_dist_pct ?? 999; vb = b.trigger_dist_pct ?? 999; }
        else { va = a[key]; vb = b[key]; }
        if (va == null) return 1;
        if (vb == null) return -1;
        return (va - vb) * dir;
    });
}

// ── Render ─────────────────────────────────────────────────────────────────────

const _JF_CRIT = [
    ['rvol', 'R', 'RVOL ≥ 1.0×'],
    ['ext',  'E', 'Not extended (<4× ATR from 50-MA)'],
    ['lod',  'L', 'Low-of-day tight (<0.6 ATR)'],
    ['vcp',  'V', 'Volatility contraction'],
    ['high', 'H', 'Near 52-week high (≥60th %ile)'],
    ['kama', 'K', 'KAMA aligned (≥2 of 3)'],
    ['rsi',  'M', 'RSI momentum (50–80)'],
];

function _jfReadyDots(n, total = 5) {
    let s = '';
    for (let i = 0; i < total; i++) s += `<span class="jf-dot ${i < n ? 'jf-dot-on' : 'jf-dot-off'}"></span>`;
    return s;
}

function _jfCritPills(checks) {
    if (!checks) return '';
    return _JF_CRIT.map(([k, l, t]) =>
        `<span class="jf-cdot ${checks[k] ? 'jf-c-on' : 'jf-c-off'}" title="${t}">${l}</span>`).join('');
}

const _JF_TIER_ICON = { focus: '🔥', stalk: '🎯', active: '⚡', watchlist: '' };

function _jfRow(r) {
    if (r.error) {
        return `<tr class="jf-row jf-row-err">
            <td></td>
            <td class="jf-sym-cell"><strong>${r.symbol}</strong></td>
            <td colspan="9" class="jf-err-msg">${r.error}
                <button class="jf-act jf-act-fetch" title="Open Data Manager"
                        onclick="event.stopPropagation(); switchTab('data-manager')">Fetch</button></td>
            <td></td>
        </tr>`;
    }

    const g       = (r.grade || 'C').toLowerCase();
    const tierIco = _JF_TIER_ICON[r.tier] || '';
    const chg     = r.ret_20d;
    const chgCls  = chg == null ? '' : chg >= 0 ? 'jf-pos' : 'jf-neg';

    // RVOL color
    const rvolCls = r.rvol >= 1.5 ? 'jf-rvol-hi' : r.rvol >= 1.0 ? 'jf-rvol-ok' : 'jf-rvol-lo';
    // Extension color
    const extCls  = r.atr_mult_50ma >= 4 ? 'jf-ext-bad' : r.atr_mult_50ma >= 2.5 ? 'jf-ext-warn' : 'jf-ext-ok';
    // KAMA color
    const kAlign  = r.kama_alignment ?? 0;
    const kCls    = kAlign === 3 ? 'jf-kama-3' : kAlign === 2 ? 'jf-kama-2' : kAlign === 1 ? 'jf-kama-1' : 'jf-kama-0';
    // Pattern color
    const patKey  = (r.pattern || '').toLowerCase().replace(/\s+/g, '-');
    // Trigger status
    const tStat   = (r.trigger_status || '').toLowerCase();
    const tDist   = r.trigger_dist_pct;
    // RS rank
    const rank    = r.rs_rank;
    const rankCls = rank == null ? '' : rank >= 70 ? 'jf-rs-hi' : rank >= 40 ? 'jf-rs-mid' : 'jf-rs-lo';
    const rsTitle = r.rs_vs_spy != null ? `${r.rs_vs_spy > 0 ? '+' : ''}${r.rs_vs_spy}% vs SPY (20d)` : 'Intra-list 60-day momentum rank';

    return `<tr class="jf-row jf-row-${g}" onclick="selectSymbol('${r.symbol}'); switchTab('charts')">
        <td><span class="jf-grade jf-grade-${g}">${r.grade}</span></td>

        <td class="jf-sym-cell">
            ${tierIco ? `<span class="jf-tier" title="${r.tier}">${tierIco}</span>` : ''}
            <strong>${r.symbol}</strong>
        </td>

        <td class="jf-price">
            <div class="jf-price-main">${r.last_close?.toFixed(2) ?? '—'}</div>
            ${chg != null ? `<div class="jf-price-sub ${chgCls}">${chg >= 0 ? '+' : ''}${chg.toFixed(1)}% <span class="jf-dim">20D</span></div>` : ''}
        </td>

        <td class="jf-ready">
            <div class="jf-ready-num">${r.readiness}<span class="jf-ready-denom">/5</span></div>
            <div class="jf-dots">${_jfReadyDots(r.readiness)}</div>
        </td>

        <td><span class="jf-pat jf-pat-${patKey}">${r.pattern || '—'}</span></td>

        <td class="jf-trig">
            <div class="jf-trig-price">${r.trigger?.toFixed(2) ?? '—'}</div>
            <span class="jf-trig-status jf-trig-${tStat}">${r.trigger_status}${tDist != null ? ` +${tDist}%` : ''}</span>
        </td>

        <td class="jf-num ${rvolCls}">${r.rvol != null ? r.rvol.toFixed(1) + '×' : '—'}</td>
        <td class="jf-num ${extCls}">${r.atr_mult_50ma != null ? r.atr_mult_50ma.toFixed(1) + '×' : '—'}</td>
        <td><span class="jf-kama ${kCls}">${kAlign}/3</span></td>

        <td class="jf-rs" title="${rsTitle}">
            ${rank != null ? `<div class="jf-rs-bar"><div class="jf-rs-fill ${rankCls}" style="width:${rank}%"></div></div><span class="jf-rs-num">${rank}</span>` : '—'}
        </td>

        <td class="jf-crit">${_jfCritPills(r.checks)}</td>

        <td class="jf-actions">
            <button class="jf-act" title="Move to Focus tier"
                    onclick="event.stopPropagation(); jeffSetTier('${r.symbol}','focus',this)">▲</button>
            <button class="jf-act" title="Size position (Risk Calc)"
                    onclick="event.stopPropagation(); jeffSizeIt('${r.symbol}', ${r.trigger ?? 'null'}, ${r.last_close ?? 'null'}, ${r.atr_14 ?? 'null'})">⚖</button>
            <button class="jf-act" title="Open chart"
                    onclick="event.stopPropagation(); selectSymbol('${r.symbol}'); switchTab('charts')">→</button>
        </td>
    </tr>`;
}

function _jfTh(key, label, title) {
    const active = scannerState.jeffSortKey === key;
    const arrow  = active ? (scannerState.jeffSortDir === -1 ? ' ▾' : ' ▴') : '';
    return `<th class="jf-th ${key ? 'jf-th-sort' : ''} ${active ? 'jf-th-active' : ''}"
                ${key ? `onclick="sortJeff('${key}')"` : ''} ${title ? `title="${title}"` : ''}>${label}${arrow}</th>`;
}

function _renderJeffScan() {
    const thead = document.getElementById('scanner-thead');
    const tbody = document.getElementById('scanner-tbody');
    const empty = document.getElementById('scanner-empty');
    const table = document.getElementById('scanner-table');
    const wrap  = document.querySelector('.scanner-table-wrap');
    if (!thead || !tbody) return;

    if (table) table.classList.add('jf-table');
    if (wrap)  wrap.classList.add('jf-table-wrap');

    const rows = _sortedJeff(_filteredJeff());

    thead.innerHTML = `<tr>
        ${_jfTh('grade',     'Grade')}
        ${_jfTh('symbol',    'Symbol')}
        ${_jfTh(null,        'Price')}
        ${_jfTh('readiness', 'Ready', 'Timing readiness: how many of the 5 entry criteria pass right now')}
        ${_jfTh(null,        'Pattern')}
        ${_jfTh('trigger',   'Trigger', 'Pivot resistance and distance to it')}
        ${_jfTh('rvol',      'RVOL')}
        ${_jfTh('atr_mult_50ma', 'ATR×50', 'ATR multiples above the 50-MA (>4 = too extended)')}
        ${_jfTh('kama_alignment', 'KAMA', 'Price above how many of KAMA-10/20/50')}
        ${_jfTh('rs_rank',   'RS', 'Relative strength rank (60-day momentum percentile)')}
        ${_jfTh(null,        'Criteria', 'R=RVOL · E=not Extended · L=LoD tight · V=VCP · H=near High · K=KAMA · M=Momentum/RSI')}
        ${_jfTh(null,        '')}
    </tr>`;

    if (!rows.length) {
        tbody.innerHTML = '';
        if (empty) {
            empty.style.display = 'flex';
            empty.innerHTML = _anyJeffFilter()
                ? '<div class="empty-icon">🔍</div><p>No setups match your filters.<br>Loosen the filters above.</p>'
                : '<div class="empty-icon">📡</div><p>No symbols scanned yet.<br>Add tickers, then click <strong>⟳ Scan All</strong>.</p>';
        }
        return;
    }
    if (empty) empty.style.display = 'none';
    tbody.innerHTML = rows.map(_jfRow).join('');
}

// ── Row actions ──────────────────────────────────────────────────────────────────

async function jeffSetTier(symbol, tier, btn) {
    const prevLabel = btn ? btn.textContent : null;
    if (btn) { btn.textContent = '…'; btn.disabled = true; }
    try {
        await apiFetch(`${API}/symbols/${encodeURIComponent(symbol)}/tier`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tier }),
        });
        // Optimistic local update so the tier icon + filter reflect immediately
        const row = (scannerState.jeff || []).find(r => r.symbol === symbol);
        if (row) row.tier = tier;
        toast(`${symbol} → ${tier}`, 'success');
        _renderJeffScan();
    } catch (e) {
        toast(`Could not move ${symbol}: ${e.message}`, 'error');
        if (btn) { btn.textContent = prevLabel; btn.disabled = false; }
    }
}

function jeffSizeIt(symbol, trigger, lastClose, atr14) {
    // Stage a prefill the Risk Calc will consume on init
    window._jeffSizePrefill = {
        symbol,
        entry: trigger || lastClose || null,
        stop:  (lastClose != null && atr14 != null) ? +(lastClose - atr14 * 1.5).toFixed(2) : null,
    };
    if (typeof selectSymbol === 'function') selectSymbol(symbol);
    switchTab('risk-calc');
}
