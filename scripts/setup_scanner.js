/**
 * setup_scanner.js — Named setups board
 * (Qullamaggie / Minervini / Stockbee / Darvas / Brandt / Stage)
 */

let _setupFilter = null;
let _setupFamily = null;
let _setupStage = null;
let _setupCatalog = {};
let _setupFamilies = {};
let _familyCounts = {};
let _stageCounts = {};

async function initSetupScanner() {
    try {
        const data = await apiFetch(`${API}/setups/families`);
        _setupCatalog = data.setups || {};
        _setupFamilies = data.families || {};
        renderSetupFamilyCards();
        renderSetupStagePills();
        renderSetupFilterPills();
    } catch (e) {
        // Fallback to catalog-only
        try {
            const data = await apiFetch(`${API}/setups/catalog`);
            _setupCatalog = data.setups || {};
            renderSetupFilterPills();
        } catch (e2) {
            console.warn('Setup catalog failed:', e2);
        }
    }
}

function renderSetupFamilyCards() {
    const wrap = document.getElementById('setup-family-cards');
    if (!wrap) return;
    wrap.innerHTML = '';

    const all = document.createElement('button');
    all.type = 'button';
    all.className = 'setup-family-card' + (!_setupFamily ? ' selected' : '');
    all.innerHTML = `<strong>All</strong><span>Every family</span>`;
    all.addEventListener('click', () => {
        _setupFamily = null;
        _setupStage = null;
        _setupFilter = null;
        renderSetupFamilyCards();
        renderSetupStagePills();
        renderSetupFilterPills();
        loadSetupScan();
    });
    wrap.appendChild(all);

    Object.entries(_setupFamilies).forEach(([id, meta]) => {
        const n = _familyCounts[id];
        const card = document.createElement('button');
        card.type = 'button';
        card.className = `setup-family-card tone-${id}` + (_setupFamily === id ? ' selected' : '');
        card.innerHTML = `
            <strong>${meta.label}</strong>
            <span>${meta.blurb}</span>
            ${n != null ? `<em>${n}</em>` : ''}`;
        card.addEventListener('click', () => {
            _setupFamily = id;
            _setupFilter = null;
            if (id !== 'stage') _setupStage = null;
            renderSetupFamilyCards();
            renderSetupStagePills();
            renderSetupFilterPills();
            loadSetupScan();
        });
        wrap.appendChild(card);
    });
}

function renderSetupStagePills() {
    const wrap = document.getElementById('setup-stage-pills');
    if (!wrap) return;
    wrap.innerHTML = '';
    if (_setupFamily && _setupFamily !== 'stage') {
        wrap.style.display = 'none';
        return;
    }
    wrap.style.display = 'flex';

    const label = document.createElement('span');
    label.className = 'overlay-section-label';
    label.textContent = 'Stage';
    wrap.appendChild(label);

    [null, 1, 2, 3, 4].forEach(st => {
        const btn = document.createElement('button');
        btn.type = 'button';
        const active = _setupStage === st || (st === null && _setupStage == null);
        btn.className = 'ind-pill setup-pill' + (active ? ' setup-pill-on' : '');
        const cnt = st != null ? _stageCounts[st] : null;
        btn.textContent = st == null ? 'All stages' : `S${st}` + (cnt != null ? ` (${cnt})` : '');
        btn.title = st == null ? 'Any stage' : ({
            1: 'Stage 1 · Basing',
            2: 'Stage 2 · Advancing',
            3: 'Stage 3 · Topping',
            4: 'Stage 4 · Declining',
        })[st];
        btn.addEventListener('click', () => {
            _setupStage = st;
            if (st != null) _setupFamily = 'stage';
            renderSetupFamilyCards();
            renderSetupStagePills();
            loadSetupScan();
        });
        wrap.appendChild(btn);
    });
}

function renderSetupFilterPills() {
    const wrap = document.getElementById('setup-filter-pills');
    if (!wrap) return;
    wrap.innerHTML = '';

    let tags = Object.keys(_setupCatalog);
    if (_setupFamily && _setupFamilies[_setupFamily]) {
        tags = _setupFamilies[_setupFamily].tags || tags;
    }

    const all = document.createElement('button');
    all.type = 'button';
    all.className = 'ind-pill setup-pill' + (!_setupFilter ? ' setup-pill-on' : '');
    all.textContent = 'All tags';
    all.addEventListener('click', () => {
        _setupFilter = null;
        renderSetupFilterPills();
        loadSetupScan();
    });
    wrap.appendChild(all);

    tags.forEach(id => {
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

        const fams = (row.families || []).map(f =>
            `<span class="setup-fam tone-${f}">${f}</span>`
        ).join(' ');

        const stageCls = row.stage ? `stage-${row.stage}` : '';
        const stageTxt = row.stage_label || (row.stage ? `S${row.stage}` : '—');

        const chg = row.change_pct != null
            ? `${row.change_pct >= 0 ? '+' : ''}${row.change_pct.toFixed(1)}%`
            : '—';
        const chgCls = row.change_pct >= 0 ? 'positive' : 'negative';
        const rs = row.rs_rank_21d != null ? `#${row.rs_rank_21d}/${row.rs_n ?? '—'}` : '—';
        const dist = row.dist_20d_high_pct != null ? `${row.dist_20d_high_pct.toFixed(1)}%` : '—';
        const vol = row.vol_ratio_5_20 != null ? row.vol_ratio_5_20.toFixed(2) : '—';

        tr.innerHTML = `
            <td class="setup-sym">${row.symbol}</td>
            <td class="setup-fams">${fams || '—'}</td>
            <td class="setup-stage ${stageCls}">${stageTxt}</td>
            <td class="setup-tags">${setups || '—'}</td>
            <td class="${chgCls}">${chg}</td>
            <td>${rs}</td>
            <td>${dist}</td>
            <td>${vol}</td>
            <td class="setup-actions">
                <button type="button" class="btn btn-ghost btn-sm setup-open" data-symbol="${row.symbol}">Chart</button>
                <button type="button" class="btn btn-ghost btn-sm setup-promote" data-symbol="${row.symbol}">+ Desk</button>
            </td>`;

        tr.querySelector('.setup-open').addEventListener('click', e => {
            e.stopPropagation();
            switchTab('charts');
            selectSymbol(row.symbol);
        });
        tr.querySelector('.setup-promote').addEventListener('click', async e => {
            e.stopPropagation();
            await promoteSymbolToDesk(row.symbol);
        });
        tr.addEventListener('click', () => {
            switchTab('charts');
            selectSymbol(row.symbol);
        });

        tbody.appendChild(tr);
    });
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
        if (_setupFamily) url += `&family=${encodeURIComponent(_setupFamily)}`;
        if (_setupStage != null) url += `&stage=${_setupStage}`;
        url += `&universe=${universe ? '1' : '0'}`;

        const data = await apiFetch(url);
        if (data.families) _setupFamilies = data.families;
        if (data.setup_catalog) _setupCatalog = data.setup_catalog;
        _familyCounts = data.family_counts || {};
        _stageCounts = data.stage_counts || {};
        renderSetupFamilyCards();
        renderSetupStagePills();
        renderSetupScanTable(data.results || []);
        if (meta) {
            meta.textContent = `${data.count || 0} hits · scanned ${data.scanned || 0}`;
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
