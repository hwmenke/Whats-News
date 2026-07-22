/**
 * setups.js — Breakout / breakdown *setup* scanner UI.
 *
 * Sweeps a universe (via /api/setups) for coiled bases and parabolic moves,
 * then renders a sortable, colour-coded table. Client-side filters by setup
 * family (bases / parabolic), direction (up / down / watch) and whether the
 * setup has actually triggered. Click a symbol to open its chart.
 */

// ── State ──────────────────────────────────────────────────────────────
const setupsState = {
    raw:        null,      // last raw result array from the API
    typeFilter: 'all',     // all | base | parab
    dirFilter:  'all',     // all | up | down | watch
    sortKey:    'score',
    sortDir:    -1,        // -1 = descending
    fetchTimer: null,
    loaded:     false,
};

// Columns: key, label, numeric?, formatter
const SETUP_COLS = [
    { key: 'symbol',    label: 'Symbol',  num: false },
    { key: 'setup',     label: 'Setup',   num: false },
    { key: 'direction', label: 'Dir',     num: false },
    { key: 'score',     label: 'Score',   num: true,  fmt: v => v?.toFixed(0) },
    { key: 'price',     label: 'Price',   num: true,  fmt: v => v?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) },
    { key: 'chg',       label: 'Day %',   num: true,  fmt: v => (v >= 0 ? '+' : '') + v?.toFixed(2) + '%', heat: 'signed' },
    { key: 'rsi',       label: 'RSI',     num: true,  fmt: v => v?.toFixed(0), heat: 'rsi' },
    { key: 'roc20',     label: '20d ROC', num: true,  fmt: v => (v >= 0 ? '+' : '') + v?.toFixed(1) + '%', heat: 'signed' },
    { key: 'ext50',     label: 'vs 50MA', num: true,  fmt: v => (v >= 0 ? '+' : '') + v?.toFixed(1) + '%', heat: 'signed' },
    { key: 'atr_pct',   label: 'ATR%',    num: true,  fmt: v => v?.toFixed(1) },
    { key: 'bw_pctl',   label: 'BBW %ile',num: true,  fmt: v => v?.toFixed(0), heat: 'squeeze' },
    { key: 'dist_hi',   label: '52w High',num: true,  fmt: v => v?.toFixed(1) + '%', heat: 'signed' },
    { key: 'vol_ratio', label: 'Vol×',    num: true,  fmt: v => v?.toFixed(2) + '×', heat: 'vol' },
    { key: 'base_hi',   label: 'Base Hi', num: true,  fmt: v => v?.toFixed(2) },
    { key: 'base_lo',   label: 'Base Lo', num: true,  fmt: v => v?.toFixed(2) },
];

const SETUP_FAMILY = {
    BASE_COILING: 'base', BASE_BREAKOUT: 'base', BASE_BREAKDOWN: 'base',
    PARABOLIC_UP: 'parab', PARABOLIC_DOWN: 'parab', PARABOLIC_REVERSAL: 'parab',
};

// ── Entry ──────────────────────────────────────────────────────────────
function initSetups() {
    // Show whatever we already have; otherwise prompt for a scan.
    if (setupsState.raw) {
        renderSetups();
    } else {
        _setupsEmpty(true);
    }
}

async function loadSetups() {
    const uniSel = document.getElementById('setups-universe');
    const universe = uniSel ? uniSel.value : 'db';
    const btn = document.getElementById('btn-scan-setups');
    _setupsLoading(true, `Scanning ${_uniLabel(universe)} for setups…`);
    if (btn) btn.disabled = true;

    try {
        const data = await apiFetch(`${API}/setups?universe=${encodeURIComponent(universe)}`);
        setupsState.raw = data.results || [];
        setupsState.loaded = true;
        const ts = document.getElementById('setups-ts');
        if (ts) ts.textContent = `${data.found} setups · ${data.scanned} scanned · ${new Date().toLocaleTimeString()}`;
        renderSetups();
    } catch (e) {
        if (typeof toast === 'function') toast('Setup scan failed: ' + e.message, 'error');
        _setupsEmpty(true, `Scan failed: ${e.message}`);
    } finally {
        _setupsLoading(false);
        if (btn) btn.disabled = false;
    }
}

// ── S&P 500 fetch (reuses the scanner bulk-fetch pipeline) ──────────────
async function fetchSp500ForSetups() {
    const btn = document.getElementById('btn-setups-fetch');
    const statusEl = document.getElementById('setups-fetch-status');
    if (btn) btn.disabled = true;
    if (statusEl) statusEl.textContent = 'Starting S&P 500 fetch…';

    try {
        await apiFetch(`${API}/scanner/fetch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: false }),
        });
        if (statusEl) statusEl.textContent = 'Fetching… 0%';
        _pollSetupsFetch();
    } catch (e) {
        if (typeof toast === 'function') toast('Fetch failed: ' + e.message, 'error');
        if (statusEl) statusEl.textContent = 'Error: ' + e.message;
        if (btn) btn.disabled = false;
    }
}

function _pollSetupsFetch() {
    if (setupsState.fetchTimer) clearInterval(setupsState.fetchTimer);
    setupsState.fetchTimer = setInterval(async () => {
        try {
            const s = await apiFetch(`${API}/scanner/status`);
            const btn = document.getElementById('btn-setups-fetch');
            const statusEl = document.getElementById('setups-fetch-status');
            if (s.running) {
                if (statusEl) statusEl.textContent = `Fetching… ${s.progress}% (${s.done}/${s.total})`;
            } else {
                clearInterval(setupsState.fetchTimer);
                setupsState.fetchTimer = null;
                if (btn) btn.disabled = false;
                const sum = s.summary || {};
                if (statusEl) {
                    statusEl.textContent = sum.error
                        ? 'Error: ' + sum.error
                        : `Fetched — ${sum.success || 0} ok, ${sum.skipped || 0} skipped, ${sum.failed || 0} failed`;
                }
                if (typeof toast === 'function') toast('S&P 500 fetch complete — scanning', 'success');
                const uni = document.getElementById('setups-universe');
                if (uni) uni.value = 'db';
                loadSetups();
            }
        } catch (e) {
            clearInterval(setupsState.fetchTimer);
            setupsState.fetchTimer = null;
        }
    }, 1500);
}

// ── Filters ─────────────────────────────────────────────────────────────
function setSetupTypeFilter(t) {
    setupsState.typeFilter = t;
    document.querySelectorAll('.setups-type-btn').forEach(b =>
        b.classList.toggle('setups-toggle-on', b.dataset.type === t));
    renderSetups();
}

function setSetupDirFilter(d) {
    setupsState.dirFilter = d;
    document.querySelectorAll('.setups-dir-btn').forEach(b =>
        b.classList.toggle('setups-toggle-on', b.dataset.dir === d));
    renderSetups();
}

function _filtered() {
    let rows = setupsState.raw || [];
    if (setupsState.typeFilter !== 'all')
        rows = rows.filter(r => SETUP_FAMILY[r.setup] === setupsState.typeFilter);
    if (setupsState.dirFilter !== 'all')
        rows = rows.filter(r => r.direction === setupsState.dirFilter);
    const trigOnly = document.getElementById('setups-trigger-only');
    if (trigOnly && trigOnly.checked)
        rows = rows.filter(r => r.trigger);
    // sort
    const k = setupsState.sortKey, dir = setupsState.sortDir;
    rows = [...rows].sort((a, b) => {
        let va = a[k], vb = b[k];
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === 'string') return va.localeCompare(vb) * dir;
        return (va - vb) * dir;
    });
    return rows;
}

function _sortSetups(key) {
    setupsState.sortDir = setupsState.sortKey === key ? setupsState.sortDir * -1 : (key === 'symbol' ? 1 : -1);
    setupsState.sortKey = key;
    renderSetups();
}

// ── Render ──────────────────────────────────────────────────────────────
function renderSetups() {
    if (!setupsState.raw) { _setupsEmpty(true); return; }
    const rows = _filtered();

    // Summary chips (counts by setup, from the unfiltered raw set)
    _renderSummary();

    const thead = document.getElementById('setups-thead');
    const tbody = document.getElementById('setups-tbody');
    thead.innerHTML = '';
    tbody.innerHTML = '';

    if (!rows.length) { _setupsEmpty(true, 'No setups match the current filters.'); return; }
    _setupsEmpty(false);

    // Header
    const htr = document.createElement('tr');
    for (const col of SETUP_COLS) {
        const th = document.createElement('th');
        th.className = 'scan-th setups-th' + (col.num ? ' is-num' : '');
        th.textContent = col.label;
        if (setupsState.sortKey === col.key) {
            const arrow = document.createElement('span');
            arrow.className = 'scr-arrow';
            arrow.textContent = setupsState.sortDir === 1 ? ' ▲' : ' ▼';
            th.appendChild(arrow);
        }
        th.addEventListener('click', () => _sortSetups(col.key));
        htr.appendChild(th);
    }
    thead.appendChild(htr);

    // Body
    for (const row of rows) {
        tbody.appendChild(_buildSetupRow(row));
    }
}

function _buildSetupRow(row) {
    const tr = document.createElement('tr');
    tr.className = 'scan-row setups-row';

    for (const col of SETUP_COLS) {
        const td = document.createElement('td');
        td.className = 'scan-td' + (col.num ? ' is-num' : '');
        const val = row[col.key];

        if (col.key === 'symbol') {
            td.className += ' scan-td-sym';
            td.textContent = row.symbol;
            td.title = `Open ${row.symbol} chart`;
            td.addEventListener('click', () => {
                if (typeof selectSymbol === 'function') selectSymbol(row.symbol);
                if (typeof switchTab === 'function') switchTab('charts');
            });

        } else if (col.key === 'setup') {
            const badge = document.createElement('span');
            badge.className = 'setup-badge dir-' + row.direction + (row.trigger ? ' is-trig' : '');
            badge.textContent = row.setup_label || row.setup;
            td.appendChild(badge);

        } else if (col.key === 'direction') {
            td.className += ' dir-cell dir-' + row.direction;
            td.textContent = row.direction === 'up' ? '▲' : row.direction === 'down' ? '▼' : '◔';
            td.title = row.trigger ? 'Triggered' : 'Setting up';

        } else if (col.key === 'score') {
            const wrap = document.createElement('div');
            wrap.className = 'score-bar-wrap';
            const bar = document.createElement('div');
            bar.className = 'score-bar dir-' + row.direction;
            bar.style.width = Math.max(0, Math.min(100, val || 0)) + '%';
            const num = document.createElement('span');
            num.className = 'score-num';
            num.textContent = val != null ? val.toFixed(0) : '—';
            wrap.appendChild(bar);
            wrap.appendChild(num);
            td.appendChild(wrap);

        } else if (val == null) {
            td.textContent = '—';

        } else {
            td.textContent = col.fmt ? col.fmt(val) : val;
            const cls = _heatClass(col.heat, val);
            if (cls) td.className += ' ' + cls;
        }
        tr.appendChild(td);
    }
    return tr;
}

function _renderSummary() {
    const el = document.getElementById('setups-summary');
    if (!el) return;
    const raw = setupsState.raw || [];
    const counts = {};
    for (const r of raw) counts[r.setup] = (counts[r.setup] || 0) + 1;
    const order = ['BASE_BREAKOUT', 'BASE_BREAKDOWN', 'BASE_COILING',
                   'PARABOLIC_UP', 'PARABOLIC_DOWN', 'PARABOLIC_REVERSAL'];
    const labels = {
        BASE_BREAKOUT: 'Base breakout', BASE_BREAKDOWN: 'Base breakdown',
        BASE_COILING: 'Coiling', PARABOLIC_UP: 'Parabolic up',
        PARABOLIC_DOWN: 'Parabolic down', PARABOLIC_REVERSAL: 'Reversal',
    };
    const dirOf = {
        BASE_BREAKOUT: 'up', BASE_BREAKDOWN: 'down', BASE_COILING: 'watch',
        PARABOLIC_UP: 'up', PARABOLIC_DOWN: 'down', PARABOLIC_REVERSAL: 'down',
    };
    el.innerHTML = '';
    for (const k of order) {
        if (!counts[k]) continue;
        const chip = document.createElement('span');
        chip.className = 'setups-chip dir-' + dirOf[k];
        chip.textContent = `${labels[k]}: ${counts[k]}`;
        el.appendChild(chip);
    }
}

// ── Cell heat colouring ─────────────────────────────────────────────────
function _heatClass(kind, v) {
    if (v == null || !kind) return '';
    if (kind === 'signed') return v > 0.05 ? 'sc-s1' : v < -0.05 ? 'sc-b1' : 'sc-n';
    if (kind === 'rsi')    return v >= 70 ? 'sc-s2' : v <= 30 ? 'sc-b2' : 'sc-n';
    if (kind === 'squeeze') return v <= 20 ? 'sc-hi2' : v <= 40 ? 'sc-hi1' : 'sc-n';   // tight = highlighted
    if (kind === 'vol')    return v >= 2 ? 'sc-hi2' : v >= 1.5 ? 'sc-hi1' : 'sc-n';
    return '';
}

// ── UI helpers ──────────────────────────────────────────────────────────
function _setupsLoading(show, text) {
    const ov = document.getElementById('setups-loading');
    const tx = document.getElementById('setups-loading-text');
    if (tx && text) tx.textContent = text;
    if (ov) ov.style.display = show ? 'flex' : 'none';
}

function _setupsEmpty(show, text) {
    const el = document.getElementById('setups-empty');
    const tbl = document.querySelector('.setups-table-wrap');
    if (el) {
        el.style.display = show ? 'flex' : 'none';
        if (text) {
            const p = document.getElementById('setups-empty-text');
            if (p) p.innerHTML = text;
        }
    }
    if (tbl) tbl.style.display = show ? 'none' : 'block';
}

function _uniLabel(u) {
    return { db: 'the local DB', watchlist: 'your watchlist',
             library: 'the curated library', sp500: 'the S&P 500' }[u] || u;
}
