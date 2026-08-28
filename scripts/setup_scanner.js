/**
 * setup_scanner.js — Setup scanner UI (EP, Darvas, breakout queue, RSI alerts)
 */

let _setupFilter = null;
let _setupCatalog = {};
let _setupScanCursor = 0;
const SETUP_SCAN_CACHE_TTL_MS = 60 * 1000;
const SETUP_SCAN_CACHE_KEY = 'whats-news-setup-scan';
let _setupScanCache = null;

async function initSetupScanner() {
    try {
        const data = await apiFetch(`${API}/setups/catalog`);
        _setupCatalog = data.setups || {};
        renderSetupFilterPills();
    } catch (e) {
        console.warn('Setup catalog failed:', e);
    }
}

function renderSetupFilterPills() {
    const wrap = document.getElementById('setup-filter-pills');
    if (!wrap) return;
    wrap.innerHTML = '';

    const all = document.createElement('button');
    all.type = 'button';
    all.className = 'ind-pill setup-pill' + (!_setupFilter ? ' setup-pill-on' : '');
    all.textContent = 'All';
    all.addEventListener('click', () => {
        _setupFilter = null;
        renderSetupFilterPills();
        loadSetupScan();
    });
    wrap.appendChild(all);

    Object.keys(_setupCatalog).forEach(id => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ind-pill setup-pill' + (_setupFilter === id ? ' setup-pill-on' : '');
        btn.textContent = id.replace(/_/g, ' ');
        btn.title = _setupCatalog[id] || id;
        btn.addEventListener('click', () => {
            _setupFilter = id;
            renderSetupFilterPills();
            loadSetupScan();
        });
        wrap.appendChild(btn);
    });
}

function formatSetupAdrChip(adr) {
    if (adr == null || !Number.isFinite(Number(adr))) return '';
    return `ADR ${Number(adr).toFixed(1)}%`;
}

function formatSetupRvolChip(rvol) {
    if (rvol == null || !Number.isFinite(Number(rvol))) return '';
    return `RVOL ${Number(rvol).toFixed(1)}\u00d7`;
}

function setupMetricChipsHtml(row) {
    const chips = [];
    const adrTxt = formatSetupAdrChip(row ? row.adr_pct : null);
    if (adrTxt) chips.push(`<span class="setup-metric-chip">${adrTxt}</span>`);
    const rvolTxt = formatSetupRvolChip(row ? row.vol_ratio_5_20 : null);
    if (rvolTxt) chips.push(`<span class="setup-metric-chip">${rvolTxt}</span>`);
    if (!chips.length) return '';
    return `<div class="setup-metric-chips">${chips.join('')}</div>`;
}

function renderSetupScanTable(results) {
    const tbody = document.getElementById('setup-scan-tbody');
    const empty = document.getElementById('setup-scan-empty');
    const table = document.getElementById('setup-scan-table');
    if (!tbody) return;

    tbody.innerHTML = '';
    if (!results || !results.length) {
        if (empty) empty.style.display = 'block';
        if (table) table.style.display = 'none';
        return;
    }
    if (empty) empty.style.display = 'none';
    if (table) table.style.display = 'table';

    results.forEach(row => {
        const tr = document.createElement('tr');
        tr.className = 'setup-scan-row';
        tr.dataset.symbol = row.symbol;

        const setups = (row.setups || []).map(s =>
            `<span class="setup-tag">${s}</span>`
        ).join('');

        const chg = row.change_pct != null
            ? `${row.change_pct >= 0 ? '+' : ''}${row.change_pct.toFixed(1)}%`
            : '—';
        const chgCls = row.change_pct >= 0 ? 'positive' : 'negative';

        const rs = row.rs_rank_21d != null ? `#${row.rs_rank_21d}/${row.rs_n ?? '—'}` : '—';
        const dist = row.dist_20d_high_pct != null
            ? `${row.dist_20d_high_pct.toFixed(1)}%`
            : '—';
        const vol = row.vol_ratio_5_20 != null
            ? row.vol_ratio_5_20.toFixed(2)
            : '—';
        const metricChips = setupMetricChipsHtml(row);

        tr.dataset.setups = JSON.stringify(row.setups || []);

        tr.innerHTML = `
            <td class="setup-sym">${row.symbol}${metricChips}</td>
            <td class="setup-tags">${setups || '—'}</td>
            <td class="${chgCls}">${chg}</td>
            <td>${rs}</td>
            <td>${dist}</td>
            <td>${vol}</td>
            <td>${row.regime || '—'}</td>
            <td class="setup-actions">
                <button type="button" class="btn btn-ghost btn-sm setup-open" data-symbol="${row.symbol}">Chart</button>
                <button type="button" class="btn btn-ghost btn-sm setup-promote" data-symbol="${row.symbol}">+ Desk</button>
            </td>`;

        tr.querySelector('.setup-open').addEventListener('click', e => {
            e.stopPropagation();
            openSetupOnChart(row);
        });
        tr.querySelector('.setup-promote').addEventListener('click', async e => {
            e.stopPropagation();
            await promoteSymbolToDesk(row.symbol);
        });
        tr.addEventListener('click', () => {
            openSetupOnChart(row);
        });

        tbody.appendChild(tr);
    });

    const current = (typeof state !== 'undefined' && state.activeSymbol) || '';
    if (current && tbody.querySelector(`tr[data-symbol="${current}"]`)) {
        highlightSetupRow(current);
    } else {
        const first = tbody.querySelector('tr.setup-scan-row');
        if (first) highlightSetupRow(first.dataset.symbol);
    }
}

function highlightSetupRow(symbol) {
    const rows = [...document.querySelectorAll('#setup-scan-tbody tr.setup-scan-row')];
    let idx = 0;
    rows.forEach((tr, i) => {
        const on = tr.dataset.symbol === symbol;
        tr.classList.toggle('setup-scan-selected', on);
        if (on) {
            idx = i;
            tr.scrollIntoView({ block: 'nearest' });
        }
    });
    _setupScanCursor = idx;
}

function moveSetupScanSelection(delta) {
    const rows = [...document.querySelectorAll('#setup-scan-tbody tr.setup-scan-row')];
    if (!rows.length) return;
    _setupScanCursor = Math.max(0, Math.min(rows.length - 1, (_setupScanCursor || 0) + delta));
    const tr = rows[_setupScanCursor];
    highlightSetupRow(tr.dataset.symbol);
}

function openSelectedSetupRow() {
    const rows = [...document.querySelectorAll('#setup-scan-tbody tr.setup-scan-row')];
    const tr = rows[_setupScanCursor] || rows[0];
    if (!tr) return;
    let setups = [];
    try { setups = JSON.parse(tr.dataset.setups || '[]'); } catch { setups = []; }
    openSetupOnChart({ symbol: tr.dataset.symbol, setups });
}

function openSetupOnChart(row) {
    // Apply Minervini SMA / Stockbee EMA packs from existing scanner tags.
    // Stay in Scan workspace so the hit list does not disappear.
    window._pendingChartPack = { symbol: row.symbol, setups: row.setups || [] };
    highlightSetupRow(row.symbol);
    if (typeof setWorkspace === 'function') {
        if (state.workspace !== 'scan') setWorkspace('scan', { skipChart: true });
    }
    selectSymbol(row.symbol);
}

window.highlightSetupRow = highlightSetupRow;
window.moveSetupScanSelection = moveSetupScanSelection;
window.openSelectedSetupRow = openSelectedSetupRow;

function setupScanCacheKey(filter, universe) {
    return `${filter || 'ALL'}|${universe ? '1' : '0'}`;
}

function applySetupScanPayload(data) {
    renderSetupScanTable((data && data.results) || []);
    const meta = document.getElementById('setup-scan-meta');
    if (meta) {
        meta.textContent = `${(data && data.count) || 0} hits · scanned ${(data && data.scanned) || 0} symbols`;
    }
}

function readSetupScanCache(key) {
    const now = Date.now();
    if (
        _setupScanCache
        && _setupScanCache.key === key
        && (now - _setupScanCache.ts) < SETUP_SCAN_CACHE_TTL_MS
        && _setupScanCache.data
    ) {
        return _setupScanCache.data;
    }
    try {
        const raw = sessionStorage.getItem(SETUP_SCAN_CACHE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (
            parsed
            && parsed.key === key
            && (now - parsed.ts) < SETUP_SCAN_CACHE_TTL_MS
            && parsed.data
        ) {
            _setupScanCache = parsed;
            return parsed.data;
        }
    } catch { /* quota / parse */ }
    return null;
}

function writeSetupScanCache(key, data) {
    const entry = { key, data, ts: Date.now() };
    _setupScanCache = entry;
    try {
        sessionStorage.setItem(SETUP_SCAN_CACHE_KEY, JSON.stringify(entry));
    } catch { /* quota */ }
}

async function loadSetupScan(opts) {
    const force = opts === true || (opts && opts.force === true);
    const allowStaleRows = !!(opts && opts.allowStaleRows);
    const loadEl = document.getElementById('setup-scan-loading');
    const btn = document.getElementById('btn-setup-scan');
    const universe = document.getElementById('chk-setup-universe')?.checked ?? true;
    const key = setupScanCacheKey(_setupFilter, universe);
    const tbody = document.getElementById('setup-scan-tbody');

    if (!force) {
        const cached = readSetupScanCache(key);
        if (cached) {
            if (!tbody || !tbody.children.length) applySetupScanPayload(cached);
            return;
        }
        // Reopening Scan keeps the last table; a filter change still refreshes.
        if (allowStaleRows && tbody && tbody.children.length) return;
    }

    if (loadEl) loadEl.style.display = 'flex';
    if (btn) { btn.disabled = true; btn.textContent = 'Scanning…'; }

    try {
        let url = `${API}/setups/scan?limit=300`;
        if (_setupFilter) url += `&setup=${encodeURIComponent(_setupFilter)}`;
        url += `&universe=${universe ? '1' : '0'}`;

        const data = await apiFetch(url);
        applySetupScanPayload(data);
        writeSetupScanCache(key, data);
    } catch (e) {
        toast('Setup scan failed: ' + e.message, 'error');
    } finally {
        if (loadEl) loadEl.style.display = 'none';
        if (btn) { btn.disabled = false; btn.textContent = 'Scan setups'; }
    }
}

window.loadSetupScan = loadSetupScan;

async function promoteSymbolToDesk(symbol) {
    try {
        const res = await apiFetch(`${API}/symbols/${encodeURIComponent(symbol)}/promote`, {
            method: 'POST',
        });
        if (res.promoted) {
            toast(`${symbol} added to desk`, 'success');
            await loadSymbols();
        } else {
            toast(`${symbol} already on desk or not found`, 'warning');
        }
    } catch (e) {
        toast('Promote failed: ' + e.message, 'error');
    }
}
