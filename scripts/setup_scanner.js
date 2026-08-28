/**
 * setup_scanner.js — Setup scanner UI (EP, Darvas, breakout queue, RSI alerts)
 */

let _setupFilter = null;
let _setupCatalog = {};
let _setupScanCursor = 0;

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

        tr.dataset.setups = JSON.stringify(row.setups || []);

        tr.innerHTML = `
            <td class="setup-sym">${row.symbol}</td>
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

async function loadSetupScan() {
    const loadEl = document.getElementById('setup-scan-loading');
    const btn = document.getElementById('btn-setup-scan');
    const meta = document.getElementById('setup-scan-meta');
    const universe = document.getElementById('chk-setup-universe')?.checked ?? true;

    if (loadEl) loadEl.style.display = 'flex';
    if (btn) { btn.disabled = true; btn.textContent = 'Scanning…'; }

    try {
        let url = `${API}/setups/scan?limit=300`;
        if (_setupFilter) url += `&setup=${encodeURIComponent(_setupFilter)}`;
        url += `&universe=${universe ? '1' : '0'}`;

        const data = await apiFetch(url);
        renderSetupScanTable(data.results || []);
        if (meta) {
            meta.textContent = `${data.count || 0} hits · scanned ${data.scanned || 0} symbols`;
        }
    } catch (e) {
        toast('Setup scan failed: ' + e.message, 'error');
    } finally {
        if (loadEl) loadEl.style.display = 'none';
        if (btn) { btn.disabled = false; btn.textContent = 'Scan setups'; }
    }
}

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
