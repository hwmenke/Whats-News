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
    data:    null,
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
