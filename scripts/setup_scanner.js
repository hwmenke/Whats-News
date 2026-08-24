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

/** Named scanner types → query / client filter presets */
const SCANNER_TYPES = [
    { id: 'all', label: 'All', blurb: 'Every hit' },
    { id: 'ep', label: 'EP', blurb: 'Gap + volume', setup: 'EP', badge: 'SB4' },
    { id: 'near_high', label: 'Near high', blurb: 'Breakout queue', setup: 'BREAKOUT_QUEUE' },
    { id: 'qulla', label: 'Qulla', blurb: 'Near high + vol', family: 'qullamaggie', setup: 'QULLA_BREAKOUT' },
    { id: 'darvas', label: 'Darvas', blurb: 'Box breakout', family: 'darvas', setup: 'DARVAS_BREAKOUT', badge: 'DB' },
    { id: 'stage2', label: 'Stage 2', blurb: 'Advancing', family: 'stage', stage: 2, badge: '2B' },
    { id: 'stage2a', label: 'Early 2A', blurb: 'Fresh Stage 2', setup: 'STAGE_2_EARLY', badge: '2A' },
    { id: 'minervini', label: 'Minervini', blurb: 'Trend Template', family: 'minervini', setup: 'MINERVINI_TT', badge: 'MM' },
    { id: 'stockbee', label: 'Stockbee', blurb: 'EP / RE / EMA', family: 'stockbee' },
    { id: 'rs_leaders', label: 'RS leaders', blurb: 'Top Book RS', max_rs: 30, min_rts: 70 },
    { id: 'rsi_ext', label: 'RSI extremes', blurb: 'OB or OS', setup: 'RSI_OB' },
    { id: 'vol_surge', label: 'Vol surge', blurb: '≥1.5× volume', setup: 'VOL_SURGE', min_vol: 1.5 },
    { id: 'dual_up', label: 'Dual up', blurb: 'D+W uptrend', dual_up: true, regime: 'uptrend' },
    { id: 'strike', label: 'Strike zone', blurb: 'Near pivot', strike: true, badge: '52W' },
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
    };
}

function applyScannerType(typeId) {
    _scannerType = typeId || 'all';
    const t = SCANNER_TYPES.find(x => x.id === _scannerType) || SCANNER_TYPES[0];

    _setupFamily = t.family || null;
    _setupStage = t.stage != null ? t.stage : null;
    _setupFilter = t.setup || null;
    _setupBadge = t.badge || null;

    // Seed advanced filter inputs from type defaults (only when empty-ish)
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
    // Always sync type-driven toggles
    if (t.min_vol != null) setIf('flt-min-vol', t.min_vol);
    if (t.max_rs != null) setIf('flt-max-rs', t.max_rs);
    if (t.min_rts != null) setIf('flt-min-rts', t.min_rts);
    if (t.regime) setIf('flt-regime', t.regime);
    if (t.strike != null) setIf('flt-strike', t.strike);
    if (t.dual_up != null) setIf('flt-dual-up', t.dual_up);

    // RSI extremes: client will also keep RSI_OS via post-filter
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
    SCANNER_TYPES.forEach(t => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'scanner-type-card' + (_scannerType === t.id ? ' selected' : '');
        btn.innerHTML = `<strong>${t.label}</strong><span>${t.blurb}</span>`;
        btn.title = t.blurb;
        btn.addEventListener('click', () => applyScannerType(t.id));
        wrap.appendChild(btn);
    });
}

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
        applyScannerType('all');
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

        tr.innerHTML = `
            <td class="setup-sym">${row.symbol}</td>
            <td class="setup-badges">${renderMethBadgesHtml(row)}</td>
            <td class="setup-stage ${stageCls}">${stageTxt}</td>
            <td class="setup-rts">${rts}</td>
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
        if (meta) {
            const typeBit = _scannerType && _scannerType !== 'all' ? ` · ${_scannerType}` : '';
            const badgeBit = _setupBadge ? ` · ${_setupBadge}` : '';
            const cacheBit = data.from_cache ? ' · cached' : ' · live';
            meta.textContent = `${data.count || 0} hits${typeBit}${badgeBit}${cacheBit} · scanned ${data.scanned || 0}`;
        }
        refreshMetricsStatus();
    } catch (e) {
        toast('Setup scan failed: ' + e.message, 'error');
    } finally {
        if (loadEl) loadEl.style.display = 'none';
        if (btn) { btn.disabled = false; btn.textContent = 'Scan'; }
    }
}

async function refreshMetricsStatus() {
    const el = document.getElementById('setup-metrics-status');
    if (!el) return;
    try {
        const s = await apiFetch(`${API}/metrics/status`);
        const pct = s.coverage_pct != null ? `${s.coverage_pct}%` : '—';
        el.textContent = `Cache ${s.cached || 0}/${s.universe || 0} (${pct})`;
        el.title = s.updated_at
            ? `Metrics updated ${s.updated_at}`
            : 'Run Precompute after archiving prices';
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
        const res = await apiFetch(`${API}/metrics/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workers: 8 }),
        });
        toast(`Cached ${res.ok || 0}/${res.total || 0} symbols`, 'success');
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
