/**
 * setup_scanner.js — Setup scanner UI (EP, Darvas, breakout queue, RSI alerts)
 */

let _setupFilter = null;
let _setupCatalog = {};

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
}

function openSetupOnChart(row) {
    // Apply Minervini SMA / Stockbee EMA packs from existing scanner tags.
    window._pendingChartPack = { symbol: row.symbol, setups: row.setups || [] };
    switchTab('charts');
    selectSymbol(row.symbol);
}

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
