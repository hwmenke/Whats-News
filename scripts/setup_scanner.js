/**
 * setup_scanner.js — Named setups board + methodology badges
 * (KQ / MM / SB4 / SBW / SB9 / DB / ON / 2A / 2B …)
 */

let _setupFilter = null;
let _setupFamily = null;
let _setupStage = null;
let _setupBadge = null;
let _scannerType = 'all';
let _setupCatalog = {};
let _setupFamilies = {};
let _badgeCatalog = {};
let _familyCounts = {};
let _stageCounts = {};
let _badgeCounts = {};
let _lastSetupResults = [];
let _setupSort = { key: 'setup_score', dir: -1 };
let _setupRowIdx = -1;
let _setupChromeOpen = false;
let _setupFiltersOpen = false;

/** Named scanner types → query / client filter presets */
const SCANNER_TYPES = [
    { id: 'all', label: 'All', blurb: 'Every hit', group: 'flow' },
    { id: 'ep', label: 'EP', blurb: 'Gap + volume', setup: 'EP', badge: 'SB4', group: 'flow' },
    { id: 'near_high', label: 'Near high', blurb: 'Breakout queue', setup: 'BREAKOUT_QUEUE', group: 'flow' },
    { id: 'vol_surge', label: 'Vol surge', blurb: '≥1.5× volume', setup: 'VOL_SURGE', min_vol: 1.5, group: 'flow' },
    { id: 'coil', label: 'Tight coil', blurb: 'Near high + dry vol', setup: 'TIGHT_COIL', group: 'flow' },
    { id: 'pullback', label: 'Pullback', blurb: 'Uptrend vs KAMA20', setup: 'PULLBACK_EMA', group: 'flow' },
    { id: 'qulla', label: 'Qulla', blurb: 'Near high + vol', family: 'qullamaggie', setup: 'QULLA_BREAKOUT', group: 'method' },
    { id: 'darvas', label: 'Darvas', blurb: 'Box breakout', family: 'darvas', setup: 'DARVAS_BREAKOUT', badge: 'DB', group: 'method' },
    { id: 'minervini', label: 'Minervini', blurb: 'Trend Template', family: 'minervini', setup: 'MINERVINI_TT', badge: 'MM', group: 'method' },
    { id: 'stockbee', label: 'Stockbee', blurb: 'EP / RE / EMA', family: 'stockbee', group: 'method' },
    { id: 'stage2', label: 'Stage 2', blurb: 'Advancing', family: 'stage', stage: 2, group: 'method' },
    { id: 'stage2a', label: 'Early 2A', blurb: 'Fresh Stage 2', setup: 'STAGE_2_EARLY', badge: '2A', group: 'method' },
    { id: 'rs_leaders', label: 'Book RS leaders', blurb: 'Top Book RS', max_rs: 30, min_rts: 70, group: 'quality' },
    { id: 'dual_up', label: 'Dual up', blurb: 'D+W uptrend', dual_up: true, regime: 'uptrend', group: 'quality' },
    { id: 'strike', label: 'Strike zone', blurb: 'Near pivot', strike: true, badge: '52W', group: 'quality' },
    { id: 'rsi_ext', label: 'RSI extremes', blurb: 'OB or OS', setup: 'RSI_OB', group: 'quality' },
];

const SCANNER_GROUPS = [
    { id: 'flow', label: 'Flow' },
    { id: 'method', label: 'Method' },
    { id: 'quality', label: 'Quality' },
];

function collectAdvFilters() {
    const num = id => {
        const el = document.getElementById(id);
        if (!el || el.value === '' || el.value == null) return null;
        const v = parseFloat(el.value);
        return Number.isFinite(v) ? v : null;
    };
    return {
        min_change: num('flt-min-change'),
        max_change: num('flt-max-change'),
        min_vol: num('flt-min-vol'),
        max_rs: num('flt-max-rs'),
        min_rts: num('flt-min-rts'),
        regime: document.getElementById('flt-regime')?.value || '',
        strike: !!document.getElementById('flt-strike')?.checked,
        dual_up: !!document.getElementById('flt-dual-up')?.checked,
        liquid: document.getElementById('flt-liquid') ? !!document.getElementById('flt-liquid').checked : true,
        min_price: num('flt-min-price'),
        min_dollar_vol: (() => {
            const v = num('flt-min-dv');
            return v == null ? null : v * 1e6;
        })(),
    };
}

function resetTypeDrivenFilters(t) {
    const setIf = (id, val) => {
        const el = document.getElementById(id);
        if (!el) return;
        if (val == null || val === false || val === '') {
            if (el.type === 'checkbox') el.checked = false;
            else el.value = '';
            return;
        }
        if (el.type === 'checkbox') el.checked = !!val;
        else el.value = val;
    };
    setIf('flt-min-vol', t.min_vol);
    setIf('flt-max-rs', t.max_rs);
    setIf('flt-min-rts', t.min_rts);
    setIf('flt-regime', t.regime || '');
    setIf('flt-strike', t.strike || false);
    setIf('flt-dual-up', t.dual_up || false);
}

function applyScannerType(typeId) {
    _scannerType = typeId || 'all';
    const t = SCANNER_TYPES.find(x => x.id === _scannerType) || SCANNER_TYPES[0];

    _setupFamily = t.family || null;
    _setupStage = t.stage != null ? t.stage : null;
    _setupFilter = t.setup || null;
    _setupBadge = t.badge || null;

    resetTypeDrivenFilters(t);

    renderScannerTypeCards();
    renderSetupFamilyCards();
    renderSetupStagePills();
    renderSetupBadgePills();
    renderSetupFilterPills();
    loadSetupScan();
}

function renderScannerTypeCards() {
    const wrap = document.getElementById('scanner-type-cards');
    if (!wrap) return;
    wrap.innerHTML = '';
    SCANNER_GROUPS.forEach(g => {
        const types = SCANNER_TYPES.filter(t => t.group === g.id);
        if (!types.length) return;
        const lab = document.createElement('span');
        lab.className = 'overlay-section-label scanner-group-label';
        lab.textContent = g.label;
        wrap.appendChild(lab);
        types.forEach(t => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'scanner-type-card compact' + (_scannerType === t.id ? ' selected' : '');
            btn.innerHTML = `<strong>${t.label}</strong><span class="scanner-type-blurb">${t.blurb}</span>`;
            btn.title = t.blurb;
            btn.addEventListener('click', () => applyScannerType(t.id));
            wrap.appendChild(btn);
        });
    });
}

let _setupScannerBound = false;

async function initSetupScanner() {
    try {
        const data = await apiFetch(`${API}/setups/families`);
        _setupCatalog = data.setups || {};
        _setupFamilies = data.families || {};
        _badgeCatalog = data.badges || {};
        renderScannerTypeCards();
        renderSetupFamilyCards();
        renderSetupStagePills();
        renderSetupBadgePills();
        renderSetupFilterPills();
    } catch (e) {
        try {
            const data = await apiFetch(`${API}/setups/catalog`);
            _setupCatalog = data.setups || {};
            renderScannerTypeCards();
            renderSetupFilterPills();
        } catch (e2) {
            console.warn('Setup catalog failed:', e2);
        }
    }
    if (_setupScannerBound) {
        refreshMetricsStatus();
        return;
    }
    _setupScannerBound = true;
    document.getElementById('btn-metrics-refresh')?.addEventListener('click', refreshMetricsCache);
    document.getElementById('btn-setup-filters-apply')?.addEventListener('click', () => loadSetupScan());
    document.getElementById('btn-setup-filters-clear')?.addEventListener('click', () => {
        ['flt-min-change', 'flt-max-change', 'flt-min-vol', 'flt-max-rs', 'flt-min-rts'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        const reg = document.getElementById('flt-regime');
        if (reg) reg.value = '';
        const st = document.getElementById('flt-strike');
        if (st) st.checked = false;
        const du = document.getElementById('flt-dual-up');
        if (du) du.checked = false;
        const liq = document.getElementById('flt-liquid');
        if (liq) liq.checked = true;
        ['flt-min-price', 'flt-min-dv'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        applyScannerType('all');
    });
    document.getElementById('btn-setup-chrome')?.addEventListener('click', () => {
        _setupChromeOpen = !_setupChromeOpen;
        const el = document.getElementById('setup-chrome');
        if (el) el.hidden = !_setupChromeOpen;
        const btn = document.getElementById('btn-setup-chrome');
        if (btn) btn.textContent = _setupChromeOpen ? 'More ▴' : 'More ▾';
    });
    document.getElementById('btn-setup-filters-toggle')?.addEventListener('click', () => {
        _setupFiltersOpen = !_setupFiltersOpen;
        const el = document.getElementById('setup-adv-filters');
        if (el) el.hidden = !_setupFiltersOpen;
        const btn = document.getElementById('btn-setup-filters-toggle');
        if (btn) btn.textContent = _setupFiltersOpen ? 'Filters ▴' : 'Filters ▾';
    });
    document.querySelectorAll('#setup-scan-table thead th[data-sort]').forEach(th => {
        th.style.cursor = 'pointer';
        th.addEventListener('click', () => {
            const key = th.dataset.sort;
            if (_setupSort.key === key) _setupSort.dir *= -1;
            else _setupSort = { key, dir: key === 'symbol' || key === 'badges' ? 1 : -1 };
            renderSetupScanTable(_lastSetupResults);
        });
    });
    refreshMetricsStatus();
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
        _setupBadge = null;
        _scannerType = 'all';
        resetTypeDrivenFilters({});
        renderSetupFamilyCards();
        renderSetupStagePills();
        renderSetupBadgePills();
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
            _setupBadge = null;
            _scannerType = 'all';
            resetTypeDrivenFilters({});
            if (id !== 'stage') _setupStage = null;
            renderSetupFamilyCards();
            renderSetupStagePills();
            renderSetupBadgePills();
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
            _scannerType = 'all';
            resetTypeDrivenFilters({});
            if (st != null) _setupFamily = 'stage';
            renderSetupFamilyCards();
            renderSetupStagePills();
            loadSetupScan();
        });
        wrap.appendChild(btn);
    });
}

function renderSetupBadgePills() {
    const wrap = document.getElementById('setup-badge-pills');
    if (!wrap) return;
    wrap.innerHTML = '';
    wrap.style.display = 'flex';

    const label = document.createElement('span');
    label.className = 'overlay-section-label';
    label.textContent = 'Badges';
    wrap.appendChild(label);

    const all = document.createElement('button');
    all.type = 'button';
    all.className = 'ind-pill setup-pill' + (!_setupBadge ? ' setup-pill-on' : '');
    all.textContent = 'All';
    all.addEventListener('click', () => {
        _setupBadge = null;
        renderSetupBadgePills();
        loadSetupScan();
    });
    wrap.appendChild(all);

    const order = ['KQ', 'MM', 'ON', 'DB', 'SB4', 'SBW', 'SB9', '52W', '2A', '2B', '97C'];
    order.forEach(code => {
        const meta = _badgeCatalog[code];
        if (!meta && !Object.keys(_badgeCatalog).length) {
            // catalog not loaded yet — still show codes
        } else if (!meta) {
            return;
        }
        const btn = document.createElement('button');
        btn.type = 'button';
        const n = _badgeCounts[code];
        const tone = (meta && meta.tone) || 'def';
        btn.className = `ind-pill setup-pill meth-badge tone-${tone}` + (_setupBadge === code ? ' setup-pill-on' : '');
        btn.textContent = code + (n != null ? ` ${n}` : '');
        btn.title = meta ? `${code}: ${meta.label} — ${meta.blurb}` : code;
        btn.addEventListener('click', () => {
            _setupBadge = code;
            _setupFilter = null;
            _scannerType = 'all';
            resetTypeDrivenFilters({});
            renderSetupBadgePills();
            renderSetupFilterPills();
            loadSetupScan();
        });
        wrap.appendChild(btn);
    });

    if (_setupBadge) {
        const apply = document.createElement('button');
        apply.type = 'button';
        apply.className = 'btn btn-primary btn-sm setup-badge-apply';
        apply.textContent = `Apply ${_setupBadge} as list →`;
        apply.title = 'Save & apply a smart list for this badge';
        apply.addEventListener('click', () => applyBadgeAsSmartList(_setupBadge));
        wrap.appendChild(apply);
    }
}

function applyBadgeAsSmartList(code) {
    const meta = _badgeCatalog[code] || { label: code, blurb: '' };
    const list = {
        id: `badge_${code.toLowerCase()}_${Date.now()}`,
        name: `${code} · ${meta.label || code}`,
        scope: document.getElementById('chk-setup-universe')?.checked ? 'with_data' : 'desk',
        match: 'all',
        rules: [{ field: 'badge', op: 'has_badge', value: code }],
    };
    try {
        const raw = JSON.parse(localStorage.getItem('whats-news-smart-lists') || '[]');
        const lists = Array.isArray(raw) ? raw : [];
        // Replace prior list with same badge name prefix
        const filtered = lists.filter(l => !(l.name || '').startsWith(`${code} ·`));
        filtered.unshift(list);
        localStorage.setItem('whats-news-smart-lists', JSON.stringify(filtered.slice(0, 40)));
        localStorage.setItem('whats-news-active-smart-list', list.id);
        if (typeof loadSmartListsFromStorage === 'function') loadSmartListsFromStorage();
        if (typeof setActiveSmartListId === 'function') setActiveSmartListId(list.id);
        if (typeof applySmartListById === 'function') {
            applySmartListById(list.id);
        } else if (typeof openSmartListsModal === 'function') {
            openSmartListsModal();
            toast(`${code} list saved — open Lists to apply`, 'success');
            return;
        }
        toast(`${code} watchlist applied (${meta.label || code})`, 'success');
        if (typeof renderSmartListPills === 'function') renderSmartListPills();
    } catch (e) {
        toast('Could not save badge list: ' + e.message, 'error');
    }
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

function renderMethBadgesHtml(row) {
    const parts = [];
    (row.badges || []).forEach(b => {
        parts.push(`<span class="meth-badge tone-${b.tone}" title="${b.title || b.label}">${b.id}</span>`);
    });
    if (row.rts != null) {
        parts.push(`<span class="meth-rts" title="Book Relative Trend Strength (from Book RS)">${row.rts}</span>`);
    }
    if (row.strike_zone) {
        parts.push(`<span class="meth-sz" title="Strike zone — near 20D high / pivot">SZ</span>`);
    }
    return parts.join('') || '—';
}

function sortSetupResults(results) {
    const { key, dir } = _setupSort;
    const copy = results.slice();
    copy.sort((a, b) => {
        let va = a[key];
        let vb = b[key];
        if (key === 'badges') {
            va = (a.badge_codes || []).length;
            vb = (b.badge_codes || []).length;
        }
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        if (typeof va === 'string') return va.localeCompare(vb) * dir;
        return (va - vb) * dir;
    });
    return copy;
}

function highlightSetupRow(idx) {
    const rows = document.querySelectorAll('#setup-scan-tbody .setup-scan-row');
    rows.forEach((tr, i) => tr.classList.toggle('setup-row-on', i === idx));
    if (idx >= 0 && rows[idx]) {
        rows[idx].scrollIntoView({ block: 'nearest' });
    }
}

function moveSetupRow(delta) {
    if (!_lastSetupResults.length) return false;
    const n = _lastSetupResults.length;
    if (_setupRowIdx < 0) _setupRowIdx = 0;
    else _setupRowIdx = (_setupRowIdx + delta + n) % n;
    highlightSetupRow(_setupRowIdx);
    return true;
}

function openSetupRow() {
    const sorted = sortSetupResults(_lastSetupResults);
    if (!sorted.length) return false;
    if (_setupRowIdx < 0 || _setupRowIdx >= sorted.length) _setupRowIdx = 0;
    const row = sorted[_setupRowIdx];
    if (!row) return false;
    highlightSetupRow(_setupRowIdx);
    if (typeof applyWorkspace === 'function') applyWorkspace('chart');
    else switchTab('charts');
    selectSymbol(row.symbol);
    return true;
}

function isScannerTabOpen() {
    const area = document.getElementById('scanner-area');
    return area && area.style.display !== 'none';
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
        _setupRowIdx = -1;
        return;
    }
    if (empty) empty.style.display = 'none';
    if (table) table.style.display = 'table';

    const sorted = sortSetupResults(results);
    document.querySelectorAll('#setup-scan-table thead th[data-sort]').forEach(th => {
        th.classList.toggle('sort-on', th.dataset.sort === _setupSort.key);
        th.dataset.dir = th.dataset.sort === _setupSort.key ? (_setupSort.dir > 0 ? 'asc' : 'desc') : '';
    });

    sorted.forEach((row, idx) => {
        const tr = document.createElement('tr');
        tr.className = 'setup-scan-row';
        tr.dataset.symbol = row.symbol;
        tr.dataset.idx = String(idx);

        const stageCls = row.stage ? `stage-${row.stage}` : '';
        let stageTxt = '—';
        if ((row.badge_codes || []).includes('2A')) stageTxt = '2A';
        else if ((row.badge_codes || []).includes('2B')) stageTxt = '2B';
        else if (row.stage_label) stageTxt = row.stage_label.replace('Stage ', 'S');
        else if (row.stage) stageTxt = `S${row.stage}`;

        const chg = row.change_pct != null
            ? `${row.change_pct >= 0 ? '+' : ''}${row.change_pct.toFixed(1)}%`
            : '—';
        const chgCls = row.change_pct >= 0 ? 'positive' : 'negative';
        const rs = row.rs_rank_21d != null ? `#${row.rs_rank_21d}/${row.rs_n ?? '—'}` : '—';
        const dist = row.dist_20d_high_pct != null ? `${row.dist_20d_high_pct.toFixed(1)}%` : '—';
        const vol = row.vol_ratio_5_20 != null ? row.vol_ratio_5_20.toFixed(2) : '—';
        const rts = row.rts != null ? row.rts : '—';
        const atr = row.atr_pct != null ? `${row.atr_pct.toFixed(1)}%` : '—';
        const stop = row.stop_long_1_5atr != null ? row.stop_long_1_5atr.toFixed(2) : '—';
        const rBox = row.r_to_box != null ? ` · ${row.r_to_box}R` : '';

        tr.innerHTML = `
            <td class="setup-sym">${row.symbol}</td>
            <td class="setup-badges">${renderMethBadgesHtml(row)}</td>
            <td class="setup-stage ${stageCls}">${stageTxt}</td>
            <td class="setup-rts">${rts}</td>
            <td class="${chgCls}">${chg}</td>
            <td>${rs}</td>
            <td>${dist}</td>
            <td>${vol}</td>
            <td class="setup-atr" title="ATR% of price">${atr}</td>
            <td class="setup-stop" title="1.5×ATR stop${rBox}">${stop}</td>
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
            _setupRowIdx = idx;
            highlightSetupRow(idx);
            switchTab('charts');
            selectSymbol(row.symbol);
        });

        tbody.appendChild(tr);
    });
    if (_setupRowIdx >= sorted.length) _setupRowIdx = sorted.length - 1;
    if (_setupRowIdx >= 0) highlightSetupRow(_setupRowIdx);
}

async function loadSetupScan() {
    const loadEl = document.getElementById('setup-scan-loading');
    const btn = document.getElementById('btn-setup-scan');
    const meta = document.getElementById('setup-scan-meta');
    const universe = document.getElementById('chk-setup-universe')?.checked ?? true;

    if (loadEl) loadEl.style.display = 'flex';
    if (btn) { btn.disabled = true; btn.textContent = 'Scanning…'; }

    try {
        let url = `${API}/setups/scan?limit=400`;
        if (_setupFilter) url += `&setup=${encodeURIComponent(_setupFilter)}`;
        if (_setupFamily) url += `&family=${encodeURIComponent(_setupFamily)}`;
        if (_setupStage != null) url += `&stage=${_setupStage}`;
        if (_setupBadge) url += `&badge=${encodeURIComponent(_setupBadge)}`;
        url += `&universe=${universe ? '1' : '0'}`;

        const adv = collectAdvFilters();
        if (adv.min_change != null) url += `&min_change=${adv.min_change}`;
        if (adv.max_change != null) url += `&max_change=${adv.max_change}`;
        if (adv.min_vol != null) url += `&min_vol=${adv.min_vol}`;
        if (adv.max_rs != null) url += `&max_rs=${adv.max_rs}`;
        if (adv.min_rts != null) url += `&min_rts=${adv.min_rts}`;
        if (adv.regime) url += `&regime=${encodeURIComponent(adv.regime)}`;
        if (adv.strike) url += `&strike=1`;
        if (adv.dual_up) url += `&dual_up=1`;
        if (adv.liquid) url += `&liquid=1`;
        else url += `&liquid=0`;
        if (adv.min_price != null) url += `&min_price=${adv.min_price}`;
        if (adv.min_dollar_vol != null) url += `&min_dollar_vol=${adv.min_dollar_vol}`;
        // RSI extremes type: include both OB and OS via special flag
        if (_scannerType === 'rsi_ext') url += `&rsi_extreme=1`;

        const data = await apiFetch(url);
        if (data.families) _setupFamilies = data.families;
        if (data.setup_catalog) _setupCatalog = data.setup_catalog;
        if (data.badge_catalog) _badgeCatalog = data.badge_catalog;
        _familyCounts = data.family_counts || {};
        _stageCounts = data.stage_counts || {};
        _badgeCounts = data.badge_counts || {};
        _lastSetupResults = data.results || [];
        renderScannerTypeCards();
        renderSetupFamilyCards();
        renderSetupStagePills();
        renderSetupBadgePills();
        renderSetupScanTable(_lastSetupResults);
        renderMarketContext(data.market_context);
        if (meta) {
            const typeBit = _scannerType && _scannerType !== 'all' ? ` · ${_scannerType}` : '';
            const badgeBit = _setupBadge ? ` · ${_setupBadge}` : '';
            const liqBit = adv.liquid ? ' · liquid' : '';
            const cache = data.cache || {};
            let cacheBit = data.from_cache ? ' · cached' : ' · live';
            if (cache.freshness === 'stale') cacheBit += ' · stale';
            if (cache.as_of) cacheBit += ` · as of ${String(cache.as_of).slice(0, 10)}`;
            meta.textContent = `${data.count || 0} hits${typeBit}${badgeBit}${liqBit}${cacheBit} · scanned ${data.scanned || 0}`;
        }
        const chip = document.getElementById('setup-liquid-chip');
        if (chip) {
            chip.hidden = !adv.liquid;
            chip.title = 'Filters ▾ → uncheck Liquid to include names under $5 or $20M ADV';
        }
        refreshMetricsStatus();
    } catch (e) {
        toast('Setup scan failed: ' + e.message, 'error');
        _lastSetupResults = [];
        renderSetupScanTable([]);
        const empty = document.getElementById('setup-scan-empty');
        if (empty) {
            empty.style.display = 'block';
            empty.innerHTML = `<div class="empty-icon">⚠️</div><p>Scan failed: ${e.message}</p><p>If the table is empty after archive, click <strong>Precompute</strong>.</p>`;
        }
    } finally {
        if (loadEl) loadEl.style.display = 'none';
        if (btn) { btn.disabled = false; btn.textContent = 'Scan'; }
    }
}

function renderMarketContext(ctx) {
    const strip = document.getElementById('market-context-strip');
    if (!strip) return;
    if (!ctx || !ctx.n) {
        strip.hidden = true;
        return;
    }
    strip.hidden = false;
    strip.classList.toggle('mc-stale', !!ctx.stale);
    const regime = document.getElementById('mc-regime');
    if (regime) {
        regime.textContent = `Book ${ctx.label || '—'}`;
        regime.className = `mc-regime mc-${ctx.regime || 'mixed'}`;
        regime.title = `${ctx.blurb || ''} ${ctx.honest || ''}`.trim();
    }
    const set = (id, label, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = `${label} ${val != null ? val.toFixed(0) + '%' : '—'}`;
    };
    set('mc-up', 'Uptrend', ctx.pct_uptrend);
    set('mc-dual', 'Daily+weekly up', ctx.pct_dual_up);
    set('mc-s2', 'Stage 2', ctx.pct_stage2);
    set('mc-ep', 'EP gap', ctx.pct_ep);
    set('mc-pos', 'Day up', ctx.pct_positive);
}

async function refreshMetricsStatus() {
    const el = document.getElementById('setup-metrics-status');
    if (!el) return;
    try {
        const s = await apiFetch(`${API}/metrics/status`);
        const pct = s.coverage_pct != null ? `${s.coverage_pct}%` : '—';
        const asOf = s.as_of ? String(s.as_of).slice(0, 10) : '';
        let txt = `Cache ${s.cached || 0}/${s.universe || 0} (${pct})`;
        if (asOf) txt += ` · ${asOf}`;
        if (s.freshness === 'stale') txt += ' · stale';
        el.textContent = txt;
        el.classList.toggle('cache-stale', s.freshness === 'stale');
        el.title = s.stale
            ? `Prices newer than cache (${s.bars_as_of}). Click Precompute.`
            : (s.updated_at ? `Metrics updated ${s.updated_at}` : 'Run Precompute after archiving prices');
    } catch {
        el.textContent = '';
    }
}

async function refreshMetricsCache() {
    const btn = document.getElementById('btn-metrics-refresh');
    const loadEl = document.getElementById('setup-scan-loading');
    if (btn) { btn.disabled = true; btn.textContent = 'Precomputing…'; }
    if (loadEl) {
        loadEl.style.display = 'flex';
        loadEl.innerHTML = '<span class="spinner"></span> Precomputing desk metrics…';
    }
    try {
        const res = await fetch(`${API}/metrics/refresh/stream`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workers: 8 }),
        });
        if (!res.ok || !res.body) {
            // Fallback to blocking POST
            const sync = await apiFetch(`${API}/metrics/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ workers: 8 }),
            });
            toast(`Cached ${sync.ok || 0}/${sync.total || 0} symbols`, 'success');
        } else {
            const reader = res.body.getReader();
            const dec = new TextDecoder();
            let buf = '';
            let last = null;
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buf += dec.decode(value, { stream: true });
                const parts = buf.split('\n\n');
                buf = parts.pop();
                for (const part of parts) {
                    const line = part.trim();
                    if (!line.startsWith('data:')) continue;
                    let ev;
                    try { ev = JSON.parse(line.slice(5).trim()); } catch { continue; }
                    if (ev.type === 'progress' && loadEl && ev.total) {
                        loadEl.innerHTML = `<span class="spinner"></span> Precomputing ${ev.done}/${ev.total} · ${ev.symbol || ''}`;
                    }
                    if (ev.type === 'done') last = ev;
                }
            }
            if (last && last.error) throw new Error(last.error);
            toast(`Cached ${(last && last.ok) || 0}/${(last && last.total) || 0} symbols`, 'success');
        }
        await refreshMetricsStatus();
        await loadSetupScan();
    } catch (e) {
        toast('Precompute failed: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Precompute'; }
        if (loadEl) {
            loadEl.style.display = 'none';
            loadEl.innerHTML = '<span class="spinner"></span> Scanning setups…';
        }
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
