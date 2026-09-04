/**
 * setup_scanner.js — Setup scanner UI (EP, Darvas, breakout queue, RSI alerts)
 */

let _setupFilter = null;
let _setupCatalog = {};
let _setupScanCursor = 0;
const SETUP_SCAN_CACHE_TTL_MS = 60 * 1000;
const SETUP_SCAN_CACHE_KEY = 'whats-news-setup-scan';
const SETUP_FILTERS_STORAGE_KEY = 'whats-news-setup-filters';
const SETUP_SORT_STORAGE_KEY = 'whats-news-setup-sort';
let _setupScanCache = null;
let _setupSort = 'scan';
let _setupScanRows = [];
let _qullaLens = 'all'; // all | qulla | ep | breakout | vol | adr

function currentSetupUniverse() {
    return document.getElementById('chk-setup-universe')?.checked ?? true;
}

function readSetupFilters() {
    try {
        const raw = localStorage.getItem(SETUP_FILTERS_STORAGE_KEY);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return null;
        let filter = parsed.filter;
        if (filter == null || filter === '' || filter === 'ALL') filter = null;
        else filter = String(filter);
        const universe = parsed.universe !== false;
        return { filter, universe };
    } catch {
        return null;
    }
}

function writeSetupFilters(filter, universe) {
    const payload = {
        filter: filter || null,
        universe: universe !== false,
    };
    try {
        localStorage.setItem(SETUP_FILTERS_STORAGE_KEY, JSON.stringify(payload));
    } catch { /* quota */ }
}

function persistSetupFilters() {
    writeSetupFilters(_setupFilter, currentSetupUniverse());
}

function restoreSetupFilters() {
    const saved = readSetupFilters();
    if (!saved) return null;
    _setupFilter = saved.filter;
    const el = document.getElementById('chk-setup-universe');
    if (el) el.checked = !!saved.universe;
    return saved;
}

function bindSetupUniverseToggle() {
    const el = document.getElementById('chk-setup-universe');
    if (!el || el._setupFiltersBound) return;
    el._setupFiltersBound = true;
    el.addEventListener('change', () => persistSetupFilters());
}

async function initSetupScanner() {
    // Restore filter + universe before the catalog fetch so a parallel
    // Scan reopen with allowStaleRows uses the last key (cache, not a forced scan).
    restoreSetupFilters();
    bindSetupUniverseToggle();
    bindSetupHitHighlight();
    restoreSetupSort();
    bindSetupSortControl();
    renderQullaPills();
    try {
        const data = await apiFetch(`${API}/setups/catalog`);
        _setupCatalog = data.setups || {};
        if (_setupFilter && !(_setupFilter in _setupCatalog)) {
            _setupFilter = null;
            persistSetupFilters();
        }
        renderSetupFilterPills();
    } catch (e) {
        console.warn('Setup catalog failed:', e);
    }
}

function isQullaRow(row) {
    const s = (row && row.setups) || [];
    return s.includes('EP') || s.includes('BREAKOUT_QUEUE') || s.includes('VOL_SURGE')
        || s.includes('NEAR_HIGH') || Number(row && row.adr_pct) >= 4;
}

function applyQullaLens(rows) {
    if (!_qullaLens || _qullaLens === 'all') return rows || [];
    return (rows || []).filter(row => {
        const s = row.setups || [];
        if (_qullaLens === 'qulla') return isQullaRow(row);
        if (_qullaLens === 'ep') return s.includes('EP');
        if (_qullaLens === 'breakout') return s.includes('BREAKOUT_QUEUE');
        if (_qullaLens === 'vol') return s.includes('VOL_SURGE');
        if (_qullaLens === 'high') return s.includes('NEAR_HIGH');
        if (_qullaLens === 'adr') return Number(row.adr_pct) >= 4;
        return true;
    });
}

function paintSetupTable() {
    renderSetupScanTable(sortedSetupScanRows(_setupScanRows, _setupSort));
}

function setQullaLens(id) {
    _qullaLens = id || 'all';
    if (typeof writeDeskPrefs === 'function') writeDeskPrefs({ qullaLens: _qullaLens });
    const wrap = document.getElementById('setup-qulla-pills');
    if (wrap) {
        wrap.querySelectorAll('.setup-pill').forEach(p => {
            p.classList.toggle('setup-pill-on', p.textContent && (
                (_qullaLens === 'all' && p.textContent.startsWith('All')) ||
                (_qullaLens === 'qulla' && p.textContent.startsWith('Qulla')) ||
                (_qullaLens === 'ep' && p.textContent === 'EP') ||
                (_qullaLens === 'breakout' && p.textContent === 'Breakout') ||
                (_qullaLens === 'vol' && p.textContent === 'VOL_SURGE') ||
                (_qullaLens === 'high' && p.textContent === 'NEAR_HIGH') ||
                (_qullaLens === 'adr' && p.textContent.startsWith('ADR'))
            ));
        });
    }
    applySetupScanSort();
}
window.setQullaLens = setQullaLens;

function renderQullaPills() {
    const wrap = document.getElementById('setup-qulla-pills');
    if (!wrap || wrap.dataset.ready) return;
    wrap.dataset.ready = '1';
    const specs = [
        ['all', 'All hits'],
        ['qulla', 'Qulla lens'],
        ['ep', 'EP'],
        ['breakout', 'Breakout'],
        ['vol', 'VOL_SURGE'],
        ['high', 'NEAR_HIGH'],
        ['adr', 'ADR≥4'],
    ];
    specs.forEach(([id, label]) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'ind-pill setup-pill' + (_qullaLens === id ? ' setup-pill-on' : '');
        btn.textContent = label;
        btn.title = id === 'qulla'
            ? 'EP / breakout / vol / near-high / ADR≥4 from our scanner — not Qullamaggie formulas'
            : label;
        btn.addEventListener('click', () => {
            _qullaLens = id;
            if (typeof writeDeskPrefs === 'function') writeDeskPrefs({ qullaLens: id });
            wrap.querySelectorAll('.setup-pill').forEach(p => p.classList.remove('setup-pill-on'));
            btn.classList.add('setup-pill-on');
            applySetupScanSort();
        });
        wrap.appendChild(btn);
    });
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
        persistSetupFilters();
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
            persistSetupFilters();
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
    results = applyQullaLens(results);
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
        const adr = row.adr_pct != null && Number.isFinite(Number(row.adr_pct))
            ? Number(row.adr_pct).toFixed(1)
            : '—';

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
            <td>${adr}</td>
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

    syncSetupHitHighlight(currentActiveSymbol());
}

// Client-side sort of already-fetched hit rows (ADR% / RVOL) — not a published rating.
function normalizeSetupSort(value) {
    const v = String(value == null ? '' : value).toLowerCase();
    if (v === 'adr' || v === 'rvol') return v;
    return 'scan';
}

function readSetupSort() {
    try {
        const raw = localStorage.getItem(SETUP_SORT_STORAGE_KEY);
        if (raw == null || raw === '') return null;
        return normalizeSetupSort(raw);
    } catch {
        return null;
    }
}

function writeSetupSort(sort) {
    try {
        localStorage.setItem(SETUP_SORT_STORAGE_KEY, normalizeSetupSort(sort));
    } catch { /* quota */ }
}

function persistSetupSort() {
    writeSetupSort(_setupSort);
}

function restoreSetupSort() {
    const saved = readSetupSort();
    _setupSort = saved || 'scan';
    syncSetupSortPills();
    return _setupSort;
}

function setupScanSortValue(row, key) {
    if (!row) return null;
    const raw = key === 'adr' ? row.adr_pct : row.vol_ratio_5_20;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
}

function sortedSetupScanRows(rows, sort) {
    const list = Array.isArray(rows) ? rows.slice() : [];
    const mode = normalizeSetupSort(sort);
    if (mode === 'scan' || !list.length) return list;
    return list
        .map((row, i) => ({ row, i }))
        .sort((a, b) => {
            const va = setupScanSortValue(a.row, mode);
            const vb = setupScanSortValue(b.row, mode);
            const aMissing = va == null;
            const bMissing = vb == null;
            if (aMissing && bMissing) return a.i - b.i;
            if (aMissing) return 1;
            if (bMissing) return -1;
            if (vb !== va) return vb - va;
            return a.i - b.i;
        })
        .map(item => item.row);
}

function applySetupScanSort() {
    renderSetupScanTable(sortedSetupScanRows(_setupScanRows, _setupSort));
}

function syncSetupSortPills() {
    const wrap = document.getElementById('setup-sort-pills');
    if (!wrap || !wrap.querySelectorAll) return;
    wrap.querySelectorAll('[data-setup-sort]').forEach(btn => {
        const on = String(btn.getAttribute('data-setup-sort') || '') === _setupSort;
        btn.classList.toggle('setup-sort-on', on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
}

function setSetupSort(sort) {
    _setupSort = normalizeSetupSort(sort);
    persistSetupSort();
    syncSetupSortPills();
    applySetupScanSort();
}

function bindSetupSortControl() {
    const wrap = document.getElementById('setup-sort-pills');
    if (!wrap || wrap._setupSortBound) return;
    wrap._setupSortBound = true;
    wrap.addEventListener('click', e => {
        const t = e && e.target;
        const btn = t && typeof t.closest === 'function'
            ? t.closest('[data-setup-sort]')
            : (t && t.getAttribute && t.getAttribute('data-setup-sort') != null ? t : null);
        if (!btn || (wrap.contains && !wrap.contains(btn))) return;
        setSetupSort(btn.getAttribute('data-setup-sort'));
    });
}

const SETUP_SCAN_ACTIVE_CLASS = 'setup-scan-active';

function currentActiveSymbol() {
    if (typeof state === 'undefined' || !state || state.activeSymbol == null || state.activeSymbol === '') {
        return '';
    }
    return String(state.activeSymbol);
}

function setupScanHitRows() {
    if (typeof document === 'undefined' || !document.querySelectorAll) return [];
    return [...document.querySelectorAll('#setup-scan-tbody tr.setup-scan-row')];
}

function symbolMatchesSetupRow(tr, symbol) {
    if (!tr || symbol == null || symbol === '') return false;
    return String(tr.dataset.symbol || '').toUpperCase() === String(symbol).toUpperCase();
}

function highlightSetupRow(symbol) {
    const rows = setupScanHitRows();
    let idx = -1;
    rows.forEach((tr, i) => {
        const on = symbolMatchesSetupRow(tr, symbol);
        tr.classList.toggle('setup-scan-selected', on);
        if (on) {
            idx = i;
            if (typeof tr.scrollIntoView === 'function') {
                tr.scrollIntoView({ block: 'nearest' });
            }
        }
    });
    if (idx >= 0) _setupScanCursor = idx;
}

function syncSetupHitHighlight(symbol) {
    const needle = (symbol == null || symbol === '') ? currentActiveSymbol() : String(symbol);
    const rows = setupScanHitRows();
    let foundIdx = -1;
    rows.forEach((tr, i) => {
        const on = symbolMatchesSetupRow(tr, needle);
        tr.classList.toggle(SETUP_SCAN_ACTIVE_CLASS, on);
        if (on) foundIdx = i;
    });
    if (foundIdx >= 0) {
        highlightSetupRow(rows[foundIdx].dataset.symbol);
        return true;
    }
    rows.forEach(tr => {
        tr.classList.remove('setup-scan-selected', SETUP_SCAN_ACTIVE_CLASS);
    });
    return false;
}

function bindSetupHitHighlight() {
    const root = typeof window !== 'undefined' ? window : globalThis;
    if (typeof root.selectSymbol === 'function' && !root.selectSymbol._setupHitBound) {
        const orig = root.selectSymbol;
        function wrapped(symbol) {
            const result = orig.apply(this, arguments);
            syncSetupHitHighlight(symbol);
            return result;
        }
        wrapped._setupHitBound = true;
        root.selectSymbol = wrapped;
    }
    if (typeof state !== 'undefined' && state && !state._setupHitHighlightBound) {
        let current = state.activeSymbol;
        Object.defineProperty(state, 'activeSymbol', {
            configurable: true,
            enumerable: true,
            get() { return current; },
            set(v) {
                current = v;
                syncSetupHitHighlight(v);
            },
        });
        state._setupHitHighlightBound = true;
    }
    syncSetupHitHighlight(currentActiveSymbol());
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
window.syncSetupHitHighlight = syncSetupHitHighlight;
window.bindSetupHitHighlight = bindSetupHitHighlight;
window.moveSetupScanSelection = moveSetupScanSelection;
window.openSelectedSetupRow = openSelectedSetupRow;
if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', bindSetupHitHighlight);
}

function setupScanCacheKey(filter, universe) {
    return `${filter || 'ALL'}|${universe ? '1' : '0'}`;
}

function applySetupScanPayload(data) {
    _setupScanRows = Array.isArray(data && data.results) ? data.results.slice() : [];
    renderSetupScanTable(sortedSetupScanRows(_setupScanRows, _setupSort));
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
    persistSetupFilters();
    const universe = currentSetupUniverse();
    const key = setupScanCacheKey(_setupFilter, universe);
    const tbody = document.getElementById('setup-scan-tbody');

    if (!force) {
        const cached = readSetupScanCache(key);
        if (cached) {
            if (!tbody || !tbody.children.length) applySetupScanPayload(cached);
            else syncSetupHitHighlight(currentActiveSymbol());
            return;
        }
        // Reopening Scan keeps the last table; a filter change still refreshes.
        if (allowStaleRows && tbody && tbody.children.length) {
            syncSetupHitHighlight(currentActiveSymbol());
            return;
        }
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
