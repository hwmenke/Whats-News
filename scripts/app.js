/**
 * app.js — Financial Dashboard Application Logic
 * Manages watchlist, KAMA period UI, and dual-panel chart loading.
 */

const API = '/api';

// Default KAMA periods to show on first load
const DEFAULT_KAMA_PERIODS = [10, 20, 50];

// App state
let state = {
    symbols:         [],
    activeSymbol:    null,
    loading:         false,
    activeTab:       'charts',
    statsData:       null,
    watchlistSort:   'group_asc',
    watchlistFilter: 'all',
};

// Quick-stats cache: symbol → {price, chg, ret_5d, ret_1m, rsi14, vol_ratio, above_sma20}
let _wlStats = {};

let statsCharts = {};
let backtestEquityChart = null;
let scannerPollTimer = null;
let alertPollTimer = null;
let _closingPositionId = null;

// ── Toast system ─────────────────────────────────────────────
function toast(message, type = 'info', duration = 3500) {
    const container = document.getElementById('toast-container');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 300);
    }, duration);
}

// ── API helpers ──────────────────────────────────────────────
async function apiFetch(url, opts = {}) {
    console.log(`>> API Fetch: ${url}`, opts.method || 'GET');
    const res  = await fetch(url, opts);
    console.log(`<< API Response: ${res.status} ${res.statusText}`);
    const data = await res.json();
    if (!res.ok) {
        console.error('!! API Error:', data.error || `HTTP ${res.status}`);
        throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
}

// ── Clock ────────────────────────────────────────────────────
function startClock() {
    const el   = document.getElementById('market-time');
    const tick = () => {
        el.textContent = new Date().toLocaleString('en-US', {
            hour: '2-digit', minute: '2-digit', second: '2-digit',
            month: 'short', day: 'numeric', year: 'numeric',
            hour12: false,
        });
    };
    tick();
    setInterval(tick, 1000);
}

// ── KAMA period pills ─────────────────────────────────────────
function kamaApiParam() {
    return Object.keys(kamaPeriods).join(',') || '10';
}

function renderKamaPills() {
    const container = document.getElementById('kama-pills');
    container.innerHTML = '';
    Object.entries(kamaPeriods).forEach(([p, meta]) => {
        const pill = document.createElement('button');
        pill.className = 'ind-pill';
        pill.textContent = `KAMA ${p}`;
        pill.title = 'Click to toggle / right-click to remove';

        // Active style via inline border/color (dynamic colours)
        const applyStyle = () => {
            if (meta.active) {
                pill.style.background  = meta.color + '30';
                pill.style.borderColor = meta.color;
                pill.style.color       = meta.color;
            } else {
                pill.style.background  = '';
                pill.style.borderColor = '';
                pill.style.color       = '';
            }
        };
        applyStyle();

        pill.addEventListener('click', () => {
            toggleKamaPeriod(p);
            applyStyle();
        });

        pill.addEventListener('contextmenu', e => {
            e.preventDefault();
            removeKamaPeriod(p);
            renderKamaPills();
            saveKamaToStorage();
            if (state.activeSymbol) loadChartData(state.activeSymbol);
        });

        container.appendChild(pill);
    });
}

function setupKamaAddForm() {
    const input = document.getElementById('kama-period-input');
    const btn   = document.getElementById('btn-add-kama');

    const addPeriod = async () => {
        const val = parseInt(input.value, 10);
        if (!val || val < 2 || val > 500) {
            toast('KAMA period must be 2–500', 'warning');
            return;
        }
        if (kamaPeriods[String(val)]) {
            toast(`KAMA ${val} already shown`, 'info');
            input.value = '';
            return;
        }
        addKamaPeriod(val);
        renderKamaPills();
        saveKamaToStorage();
        input.value = '';

        // If data is already loaded, populate the new series immediately
        if (state.activeSymbol) {
            try {
                const [dailyInd, weeklyInd] = await Promise.all([
                    apiFetch(`${API}/indicators/${state.activeSymbol}?freq=daily&kama=${kamaApiParam()}`),
                    apiFetch(`${API}/indicators/${state.activeSymbol}?freq=weekly&kama=${kamaApiParam()}`),
                ]);
                loadIndicatorsToPanel('daily',  dailyInd);
                loadIndicatorsToPanel('weekly', weeklyInd);
            } catch (e) {
                toast('Failed to load new KAMA: ' + e.message, 'error');
            }
        }
    };

    btn.addEventListener('click', addPeriod);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') addPeriod(); });
}

// ── Sidebar toggle ────────────────────────────────────────────
function toggleSidebar() {
    const app = document.querySelector('.app');
    const btn = document.getElementById('btn-sidebar-toggle');
    if (!app) return;
    const collapsed = app.classList.toggle('sidebar-collapsed');
    if (btn) btn.textContent = collapsed ? '▶' : '☰';
    localStorage.setItem('sidebarCollapsed', collapsed ? '1' : '0');
}

// ── Symbol Watchlist ─────────────────────────────────────────
async function loadSymbols() {
    try {
        state.symbols = await apiFetch(`${API}/symbols`);
        renderSymbolList();
    } catch (e) {
        toast('Failed to load symbols: ' + e.message, 'error');
    }
}

// Load quick stats for all watchlist symbols from the DB-only endpoint.
// Runs in background on startup and after refreshAll.
async function loadQuickStats() {
    try {
        const rows = await apiFetch(`${API}/symbols/quick-stats`);
        _wlStats = {};
        for (const r of rows) _wlStats[r.symbol] = r;
        renderSymbolList();
    } catch (_) { /* non-fatal — badges just won't show */ }
}

function _liveFor(symbol) {
    // Merge quick-stats with scanner data; scanner wins when available
    const qs = _wlStats[symbol] || {};
    const sc = (typeof scannerState !== 'undefined' && Array.isArray(scannerState.data))
        ? scannerState.data.find(r => r.symbol === symbol) : null;
    return {
        price:       sc?.price       ?? qs.price       ?? null,
        chg:         sc?.chg         ?? qs.chg         ?? null,
        ret_5d:      qs.ret_5d       ?? null,
        ret_1m:      sc?.ret_1m      ?? qs.ret_1m      ?? null,
        rsi14:       sc?.d?.rsi_14   ?? qs.rsi14       ?? null,
        vol_ratio:   qs.vol_ratio    ?? null,
        above_sma20: qs.above_sma20  ?? null,
    };
}

// Parse sort value like "perf_1d_desc" → {key, dir}
function _parseSortVal(v) {
    const asc  = v.endsWith('_asc');
    const desc = v.endsWith('_desc');
    const key  = asc ? v.slice(0, -4) : desc ? v.slice(0, -5) : v;
    const dir  = asc ? 1 : -1;   // -1 = desc (big first), 1 = asc (small first)
    return { key, dir };
}

function renderSymbolList() {
    const list   = document.getElementById('symbol-list');
    const search = (document.getElementById('watchlist-search')?.value || '').trim().toUpperCase();
    list.innerHTML = '';

    if (!state.symbols.length) {
        list.innerHTML = '<div class="wl-empty">No symbols yet.<br><small>Type a ticker above and press +</small></div>';
        return;
    }

    // ── Filter ────────────────────────────────────────────────
    const filt = state.watchlistFilter || 'all';
    let visible = state.symbols.filter(sym => {
        if (search && !sym.symbol.includes(search) && !(sym.name || '').toUpperCase().includes(search)) return false;
        const L = _liveFor(sym.symbol);
        switch (filt) {
            case 'up':        return L.chg > 0;
            case 'down':      return L.chg < 0;
            case '1w_up':     return L.ret_5d > 2;
            case '1w_down':   return L.ret_5d < -2;
            case '1m_up':     return L.ret_1m > 5;
            case '1m_down':   return L.ret_1m < -5;
            case 'ob':        return L.rsi14 > 70;
            case 'os':        return L.rsi14 < 30;
            case 'bull_rsi':  return L.rsi14 >= 50 && L.rsi14 <= 70;
            case 'bear_rsi':  return L.rsi14 >= 30 && L.rsi14 < 50;
            case 'above_sma': return L.above_sma20 === true;
            case 'below_sma': return L.above_sma20 === false;
            case 'high_vol':  return L.vol_ratio > 2;
            default:          return true;
        }
    });

    // ── Sort ──────────────────────────────────────────────────
    const { key, dir } = _parseSortVal(state.watchlistSort || 'group_asc');

    const numSort = (fn) => visible.sort((a, b) => {
        const va = fn(a), vb = fn(b);
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        return (va - vb) * dir;
    });

    switch (key) {
        case 'alpha':   visible.sort((a, b) => a.symbol.localeCompare(b.symbol) * dir); break;
        case 'added':   visible.sort((a, b) => (a.added_at || '').localeCompare(b.added_at || '') * dir); break;
        case 'sector':  visible.sort((a, b) => ((a.sector || 'zzz').localeCompare(b.sector || 'zzz') || a.symbol.localeCompare(b.symbol)) * dir); break;
        case 'perf_1d': numSort(s => _liveFor(s.symbol).chg); break;
        case 'ret_5d':  numSort(s => _liveFor(s.symbol).ret_5d); break;
        case 'ret_1m':  numSort(s => _liveFor(s.symbol).ret_1m); break;
        case 'rsi14':   numSort(s => _liveFor(s.symbol).rsi14); break;
        case 'price':   numSort(s => _liveFor(s.symbol).price); break;
        case 'vol':     numSort(s => _liveFor(s.symbol).vol_ratio); break;
        // 'group': DB order (pre-sorted by group_tag, symbol)
    }

    // Count badge
    const countEl = document.getElementById('wl-count');
    if (countEl) countEl.textContent = visible.length < state.symbols.length
        ? `${visible.length} / ${state.symbols.length}` : `${state.symbols.length}`;

    if (!visible.length) {
        list.innerHTML = '<div class="wl-empty">No matches for current filter.</div>';
        return;
    }

    // ── Render ────────────────────────────────────────────────
    const showGroups = key === 'group' || key === 'sector';
    const groupKey   = sym => key === 'sector' ? (sym.sector || 'Other') : (sym.group_tag || '');

    let lastGroup = undefined;
    visible.forEach(sym => {
        if (showGroups) {
            const gk = groupKey(sym);
            if (gk !== lastGroup) {
                lastGroup = gk;
                if (gk) {
                    const hdr = document.createElement('div');
                    hdr.className   = 'sym-group-header';
                    hdr.textContent = gk;
                    list.appendChild(hdr);
                }
            }
        }

        const live = _liveFor(sym.symbol);
        const item = document.createElement('div');
        item.className = 'symbol-item' + (state.activeSymbol === sym.symbol ? ' active' : '');
        item.dataset.symbol = sym.symbol;

        // Ticker + anomaly badge
        const ticker = document.createElement('span');
        ticker.className = 'sym-ticker';
        ticker.textContent = sym.symbol;
        const anomalyFlags = _anomalyMap[sym.symbol];
        if (anomalyFlags?.length) {
            const badge = document.createElement('span');
            badge.className   = 'sym-anomaly-badge';
            badge.title       = anomalyFlags.map(f => f.label).join(', ');
            badge.textContent = '⚡';
            ticker.appendChild(badge);
        }
        item.appendChild(ticker);

        // Live mini badges — show the stat most relevant to current sort
        const miniRow = document.createElement('span');
        miniRow.className = 'sym-mini-row';

        const addBadge = (text, cls) => {
            const s = document.createElement('span');
            s.className   = cls;
            s.textContent = text;
            miniRow.appendChild(s);
        };

        if (live.chg != null)
            addBadge((live.chg >= 0 ? '+' : '') + live.chg.toFixed(1) + '%',
                     'sym-mini-chg ' + (live.chg >= 0 ? 'sym-mini-pos' : 'sym-mini-neg'));

        if (live.rsi14 != null)
            addBadge('RSI ' + live.rsi14.toFixed(0),
                     'sym-mini-rsi' + (live.rsi14 > 70 ? ' sym-mini-ob' : live.rsi14 < 30 ? ' sym-mini-os' : ''));

        // Show extra stat when sorted by something non-default
        if (key === 'ret_5d' && live.ret_5d != null)
            addBadge('1W ' + (live.ret_5d >= 0 ? '+' : '') + live.ret_5d.toFixed(1) + '%',
                     'sym-mini-chg ' + (live.ret_5d >= 0 ? 'sym-mini-pos' : 'sym-mini-neg'));
        if (key === 'ret_1m' && live.ret_1m != null)
            addBadge('1M ' + (live.ret_1m >= 0 ? '+' : '') + live.ret_1m.toFixed(1) + '%',
                     'sym-mini-chg ' + (live.ret_1m >= 0 ? 'sym-mini-pos' : 'sym-mini-neg'));
        if (key === 'vol' && live.vol_ratio != null)
            addBadge(live.vol_ratio.toFixed(1) + '×', 'sym-mini-rsi');
        if (key === 'price' && live.price != null)
            addBadge('$' + live.price.toLocaleString(), 'sym-mini-rsi');

        item.appendChild(miniRow);

        // Group tag badge — only in group mode
        if (key !== 'sector') {
            const tag = sym.group_tag || '';
            const tagBadge = document.createElement('span');
            tagBadge.className   = 'sym-tag';
            tagBadge.textContent = tag || '+ tag';
            tagBadge.title       = 'Click to set group';
            tagBadge.addEventListener('click', e => { e.stopPropagation(); startTagEdit(sym.symbol, tag, tagBadge); });
            item.appendChild(tagBadge);
        }

        const removeBtn = document.createElement('span');
        removeBtn.className   = 'sym-remove';
        removeBtn.textContent = '×';
        removeBtn.title       = 'Remove';
        removeBtn.addEventListener('click', e => { e.stopPropagation(); removeSymbol(sym.symbol); });
        item.appendChild(removeBtn);

        item.addEventListener('click', () => selectSymbol(sym.symbol));
        list.appendChild(item);
    });
}

function clearWatchlistSearch() {
    const inp = document.getElementById('watchlist-search');
    if (inp) { inp.value = ''; inp.focus(); }
    renderSymbolList();
}

function setWatchlistFilter(f) {
    state.watchlistFilter = f;
    const sel = document.getElementById('watchlist-filter');
    if (sel) sel.value = f;
    renderSymbolList();
}

function setWatchlistSort(v) {
    state.watchlistSort = v;
    const sel = document.getElementById('watchlist-sort');
    if (sel) sel.value = v;
    renderSymbolList();
}

function startTagEdit(symbol, currentTag, badgeEl) {
    const input = document.createElement('input');
    input.className   = 'sym-tag-input';
    input.value       = currentTag;
    input.placeholder = 'Group name…';
    input.maxLength   = 30;

    const parent = badgeEl.parentElement;
    parent.replaceChild(input, badgeEl);
    input.focus();
    input.select();

    const commit = async () => {
        const newTag = input.value.trim();
        try {
            await apiFetch(`${API}/symbols/${symbol}/group`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ group_tag: newTag }),
            });
            await loadSymbols();
        } catch (e) {
            toast('Group update failed: ' + e.message, 'error');
            input.replaceWith(badgeEl);
        }
    };

    input.addEventListener('blur',   commit);
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter')  { e.preventDefault(); input.blur(); }
        if (e.key === 'Escape') { input.replaceWith(badgeEl); }
    });
}

async function addSymbol() {
    const input = document.getElementById('new-symbol-input');
    const raw   = input.value.trim();
    if (!raw) return;

    // Multiple tickers (comma / space separated) → route to bulk modal
    const parts = raw.split(/[\s,;]+/).map(s => s.trim().toUpperCase()).filter(Boolean);
    if (parts.length > 1) {
        input.value = '';
        document.getElementById('bulk-symbols-input').value = parts.join('\n');
        openBulkModal();
        return;
    }

    const symbol = parts[0];
    input.disabled = true;
    try {
        await apiFetch(`${API}/symbols`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol }),
        });
        input.value = '';
        toast(`${symbol} added to watchlist`, 'success');
        await fetchSymbolData(symbol);
        await loadSymbols();
        selectSymbol(symbol);
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    } finally {
        input.disabled = false;
    }
}

async function removeSymbol(symbol) {
    try {
        await apiFetch(`${API}/symbols/${symbol}`, { method: 'DELETE' });
        toast(`${symbol} removed`, 'warning');
        if (state.activeSymbol === symbol) {
            state.activeSymbol = null;
            showEmptyState();
        }
        await loadSymbols();
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}

// ── Yahoo Finance fetch ───────────────────────────────────────
// silent=true suppresses per-symbol toasts (used during bulk import)
async function fetchSymbolData(symbol, silent = false) {
    console.log(`[App] Fetching data for ${symbol}...`);
    if (!silent) toast(`Downloading ${symbol} from Yahoo Finance…`, 'info', 5000);
    try {
        const res = await apiFetch(`${API}/fetch/${symbol}`, { method: 'POST' });
        console.log(`[App] Fetch complete for ${symbol}:`, res);
        if (!silent) toast(`${symbol}: ${res.daily_rows} daily / ${res.weekly_rows} weekly bars loaded`, 'success', 5000);
        return true;
    } catch (e) {
        console.error(`[App] Fetch failed for ${symbol}:`, e);
        if (!silent) toast(`${symbol} fetch failed: ` + e.message, 'error');
        return false;
    }
}

// ── Bulk Import ───────────────────────────────────────────────
function openBulkModal() {
    const modal = document.getElementById('bulk-modal');
    modal.style.display = 'flex';
    // Reset progress state from any previous run
    document.getElementById('bulk-progress').style.display        = 'none';
    document.getElementById('bulk-progress-fill').style.width     = '0%';
    document.getElementById('bulk-progress-label').style.color    = '';
    document.getElementById('btn-bulk-submit').disabled           = false;
    document.getElementById('bulk-symbols-input').disabled        = false;
    setTimeout(() => document.getElementById('bulk-symbols-input').focus(), 50);
}

function closeBulkModal() {
    // Only close if not in the middle of an import
    if (document.getElementById('btn-bulk-submit').disabled) return;
    document.getElementById('bulk-modal').style.display = 'none';
    document.getElementById('bulk-symbols-input').value = '';
    document.getElementById('bulk-progress').style.display = 'none';
}

async function bulkAddSymbols() {
    const raw = document.getElementById('bulk-symbols-input').value;

    // Parse: split on any combination of commas, semicolons, spaces, newlines
    // Validate: must start with a letter, 1-10 chars, only A-Z 0-9 . - ^
    const symbols = [...new Set(
        raw.split(/[\s,;\n\r]+/)
           .map(s => s.trim().toUpperCase())
           .filter(s => /^[A-Z][A-Z0-9.\-\^]{0,9}$/.test(s))
    )];

    if (!symbols.length) {
        toast('No valid ticker symbols found', 'warning');
        return;
    }

    const submitBtn  = document.getElementById('btn-bulk-submit');
    const textarea   = document.getElementById('bulk-symbols-input');
    const progressEl = document.getElementById('bulk-progress');
    const fillEl     = document.getElementById('bulk-progress-fill');
    const labelEl    = document.getElementById('bulk-progress-label');

    // Lock UI
    submitBtn.disabled  = true;
    textarea.disabled   = true;
    progressEl.style.display = 'block';
    labelEl.style.color = '';

    const existing = new Set(state.symbols.map(s => s.symbol));
    let added = 0, failed = 0, skipped = 0;
    const failedSymbols = [];

    for (let i = 0; i < symbols.length; i++) {
        const sym = symbols[i];

        // Update progress bar
        fillEl.style.width  = `${Math.round((i / symbols.length) * 100)}%`;
        labelEl.textContent = `${i + 1} / ${symbols.length}  ·  ${sym}`;

        if (existing.has(sym)) {
            skipped++;
            continue;
        }

        // Register symbol in DB (may already exist — ignore that error)
        try {
            await apiFetch(`${API}/symbols`, {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ symbol: sym }),
            });
        } catch (_) { /* already exists or other — still try data fetch */ }

        // Download market data
        const ok = await fetchSymbolData(sym, true);
        if (ok) {
            added++;
            existing.add(sym);
        } else {
            failed++;
            failedSymbols.push(sym);
        }
    }

    // Finalise progress bar
    fillEl.style.width = '100%';
    const parts = [
        added   ? `${added} added`   : null,
        skipped ? `${skipped} skipped` : null,
        failed  ? `${failed} failed`  : null,
    ].filter(Boolean);
    const summary = parts.join(', ');
    labelEl.textContent = `Done — ${summary}`;
    labelEl.style.color = failed ? 'var(--red)' : 'var(--green)';

    // Unlock UI
    submitBtn.disabled = false;
    textarea.disabled  = false;

    // Refresh sidebar
    await loadSymbols();

    // If something was added, select the first new one
    const firstNew = symbols.find(s => existing.has(s) && !state.symbols.find(x => x.symbol === s));
    if (added && !state.activeSymbol) selectSymbol(symbols[0]);

    // Toast summary
    toast(
        `Bulk import: ${summary}` + (failedSymbols.length ? ` (${failedSymbols.join(', ')})` : ''),
        failed ? 'warning' : 'success',
        6000
    );

    // Auto-close after 2 s if everything succeeded
    if (failed === 0) setTimeout(closeBulkModal, 2000);
}

async function refreshAll() {
    const btn = document.getElementById('btn-refresh-all');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Refreshing…';
    try {
        const results = await apiFetch(`${API}/refresh`, { method: 'POST' });
        results.forEach(r => {
            if (r.error) toast(`${r.symbol}: ${r.error}`, 'error');
            else toast(`${r.symbol}: updated`, 'success', 2000);
        });
        await loadSymbols();
        loadQuickStats();
        if (state.activeSymbol) await loadChartData(state.activeSymbol);
    } catch (e) {
        toast('Refresh failed: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '⟳ Refresh All';
    }
}

// ── Symbol selection & chart loading ─────────────────────────
async function selectSymbol(symbol) {
    state.activeSymbol = symbol;
    saveToLocalStorage();
    renderSymbolList();

    // Always update fundamentals + notes when switching symbols
    loadFundamentals(symbol);
    loadNotes(symbol);

    if (state.activeTab === 'charts') {
        await loadChartData(symbol);
    } else if (state.activeTab === 'stats') {
        await loadStatsData(symbol);
    } else if (state.activeTab === 'knn') {
        await loadKNN(symbol);
    } else if (state.activeTab === 'backtest') {
        updateSymbolHeader(symbol, null);
    } else if (state.activeTab === 'trend') {
        await loadAdaptiveTrendData(symbol);
    }
    // Scanner / portfolio tabs don't depend on the selected symbol

    // Phase 3 hook — fires after symbol load for crosshair, drawings, saved state
    if (typeof _p3OnSymbolLoad === 'function') _p3OnSymbolLoad(symbol);
}

async function loadStatsData(symbol) {
    if (!symbol) return;
    showStatsArea();
    showLoadingOverlay(true);
    updateSymbolHeader(symbol, null);

    try {
        const [ohlcv, stats] = await Promise.all([
            apiFetch(`${API}/ohlcv/${symbol}?freq=daily&limit=2`),
            apiFetch(`${API}/stats/${symbol}`),
        ]).catch(async e => {
            // If it's a 404/No data, try fetching
            if (e.message.includes('404') || e.message.includes('No data')) {
                toast(`No data for ${symbol}. Downloading…`, 'info');
                const ok = await fetchSymbolData(symbol);
                if (!ok) throw e;
                await loadSymbols();
                return Promise.all([
                    apiFetch(`${API}/ohlcv/${symbol}?freq=daily&limit=2`),
                    apiFetch(`${API}/stats/${symbol}`),
                ]);
            }
            throw e;
        });

        state.statsData = stats;
        renderStats(stats);
        // Show correlation section button so user can load it
        const corrSection = document.getElementById('correlation-section');
        if (corrSection) corrSection.style.display = 'block';

        const last = ohlcv[ohlcv.length - 1];
        const prev = ohlcv[ohlcv.length - 2];
        updateSymbolHeader(symbol, last, prev);
    } catch (e) {
        toast('Stats load failed: ' + e.message, 'error');
        // Clear old stats if error
        document.getElementById('stat-vol').textContent = '--';
        document.getElementById('stat-sharpe').textContent = '--';
        document.getElementById('stat-drawdown').textContent = '--';
        document.getElementById('stat-winrate').textContent = '--';
    } finally {
        showLoadingOverlay(false);
    }
}

async function loadChartData(symbol) {
    if (!symbol) return;
    state.loading = true;
    showChartArea();
    showLoadingOverlay(true);
    updateSymbolHeader(symbol, null);

    const kama = kamaApiParam();

    try {
        let [dailyOhlcv, weeklyOhlcv, dailyInd, weeklyInd] = await Promise.all([
            apiFetch(`${API}/ohlcv/${symbol}?freq=daily`),
            apiFetch(`${API}/ohlcv/${symbol}?freq=weekly`),
            apiFetch(`${API}/indicators/${symbol}?freq=daily&kama=${kama}`),
            apiFetch(`${API}/indicators/${symbol}?freq=weekly&kama=${kama}`),
        ]).catch(async e => {
            // No data yet — auto-fetch then retry
            toast(`No data for ${symbol}. Downloading…`, 'info');
            const ok = await fetchSymbolData(symbol);
            if (!ok) throw e;
            await loadSymbols();
            return Promise.all([
                apiFetch(`${API}/ohlcv/${symbol}?freq=daily`),
                apiFetch(`${API}/ohlcv/${symbol}?freq=weekly`),
                apiFetch(`${API}/indicators/${symbol}?freq=daily&kama=${kama}`),
                apiFetch(`${API}/indicators/${symbol}?freq=weekly&kama=${kama}`),
            ]);
        });

        initCharts();

        loadOHLCV('daily',  dailyOhlcv);
        loadOHLCV('weekly', weeklyOhlcv);
        loadIndicatorsToPanel('daily',  dailyInd);
        loadIndicatorsToPanel('weekly', weeklyInd);
        fitContent();

        const last = dailyOhlcv[dailyOhlcv.length - 1];
        const prev = dailyOhlcv[dailyOhlcv.length - 2];
        updateSymbolHeader(symbol, last, prev);

        if (typeof loadEarningsMarkers === 'function') loadEarningsMarkers(symbol);
    } catch (e) {
        toast('Chart load failed: ' + e.message, 'error');
        showEmptyState();
    } finally {
        state.loading = false;
        showLoadingOverlay(false);
    }
}

// ── Adaptive Trend loading ────────────────────────────────────
async function loadAdaptiveTrendData(symbol) {
    if (!symbol) return;
    showTrendArea();

    const loadingEl = document.getElementById('trend-loading');
    if (loadingEl) loadingEl.style.display = 'flex';
    updateSymbolHeader(symbol, null);

    const freq   = trendState.freq;
    const method = trendState.method;

    const cfg    = typeof trendConfig !== 'undefined' ? trendConfig : {};
    const cfgStr = Object.entries(cfg).map(([k,v]) => `${k}=${v}`).join('&');
    const trendUrl = `${API}/adaptive-trend/${symbol}?freq=${freq}&method=${method}&${cfgStr}`;

    try {
        let [ohlcv, trendData] = await Promise.all([
            apiFetch(`${API}/ohlcv/${symbol}?freq=${freq}`),
            apiFetch(trendUrl),
        ]).catch(async e => {
            if (e.message.includes('404') || e.message.includes('No data')) {
                toast(`No data for ${symbol}. Downloading…`, 'info');
                const ok = await fetchSymbolData(symbol);
                if (!ok) throw e;
                await loadSymbols();
                return Promise.all([
                    apiFetch(`${API}/ohlcv/${symbol}?freq=${freq}`),
                    apiFetch(trendUrl),
                ]);
            }
            throw e;
        });

        window._trendLastOhlcv = ohlcv;   // cache for sub-tab back-navigation
        buildTrendCharts();
        loadTrendData(trendData, ohlcv);

        const last = ohlcv[ohlcv.length - 1];
        const prev = ohlcv[ohlcv.length - 2];
        updateSymbolHeader(symbol, last, prev);
    } catch (e) {
        toast('Adaptive Trend load failed: ' + e.message, 'error');
    } finally {
        if (loadingEl) loadingEl.style.display = 'none';
    }
}

// ── UI helpers ───────────────────────────────────────────────
function showEmptyState() {
    document.getElementById('empty-state').style.display       = 'flex';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'none';
    ['news-area','sector-area','compare-area','signals-area',
     'journal-area','analytics-area','pair-area','mtf-area',
     'calendar-area','strategy-area'].forEach(id => {
        const el = document.getElementById(id); if (el) el.style.display = 'none';
    });
}

function showChartArea() {
    document.getElementById('empty-state').style.display = 'none';
    document.getElementById('chart-area').style.display  = 'flex';
}

function showLoadingOverlay(show) {
    document.getElementById('chart-loading').style.display = show ? 'flex' : 'none';
}

// ── Tab Switching ─────────────────────────────────────────────
async function switchTab(tabId) {
    state.activeTab = tabId;

    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.id === `tab-${tabId}`);
    });

    // Sync mobile bottom-nav active state
    document.querySelectorAll('.mbn-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
    });

    // Hide all content areas first
    ALL_AREAS.forEach(id => { const el = document.getElementById(id); if (el) el.style.display = 'none'; });
    document.querySelector('.tab-bar').style.display = 'none';

    if (tabId === 'charts') {
        showChartArea();
        if (state.activeSymbol) loadChartData(state.activeSymbol);
    } else if (tabId === 'stats') {
        showStatsArea();
        if (state.activeSymbol) loadStatsData(state.activeSymbol);
    } else if (tabId === 'knn') {
        document.getElementById('knn-area').style.display = 'block';
        if (state.activeSymbol) loadKNN(state.activeSymbol);
    } else if (tabId === 'backtest') {
        document.getElementById('backtest-area').style.display = 'block';
        if (state.activeSymbol) updateSymbolHeader(state.activeSymbol, null);
    } else if (tabId === 'trend') {
        showTrendArea();
        if (typeof renderTrendConfig === 'function') renderTrendConfig();
        if (state.activeSymbol) loadAdaptiveTrendData(state.activeSymbol);
    } else if (tabId === 'scanner') {
        showScannerArea();
        loadScannerData();
    } else if (tabId === 'data-manager') {
        showDataManagerArea();
        initDataManager();
    } else if (tabId === 'portfolio') {
        showPortfolioArea();
        loadPortfolio();
    } else if (tabId === 'news') {
        showArea('news-area');
        if (state.activeSymbol) loadNews(state.activeSymbol);
    } else if (tabId === 'sector') {
        showArea('sector-area');
        loadSectorHeatmap();
    } else if (tabId === 'compare') {
        showArea('compare-area');
        // Pre-fill active symbol if nothing entered
        const inp = document.getElementById('compare-symbols-input');
        if (inp && !inp.value && state.activeSymbol) inp.value = state.activeSymbol + ', ';
    } else if (tabId === 'signals') {
        showArea('signals-area');
        loadSignals();
    } else if (tabId === 'regime') {
        showArea('regime-area');
        loadRegime();
    } else if (tabId === 'journal') {
        showArea('journal-area');
        loadJournal();
    } else if (tabId === 'analytics') {
        showArea('analytics-area');
        loadPortfolioAnalytics();
    } else if (tabId === 'pair') {
        showArea('pair-area');
        const s1 = document.getElementById('pair-sym1');
        const s2 = document.getElementById('pair-sym2');
        if (s1 && !s1.value && state.activeSymbol) s1.value = state.activeSymbol;
    } else if (tabId === 'mtf') {
        showArea('mtf-area');
        const lbl = document.getElementById('mtf-sym-label');
        if (lbl) lbl.textContent = state.activeSymbol || '';
        if (state.activeSymbol) loadMultiTF(state.activeSymbol);
    } else if (tabId === 'calendar') {
        showArea('calendar-area');
        loadMacroCalendar();
    } else if (tabId === 'strategy') {
        showArea('strategy-area');
        loadStrategyLab();
    }
}

function showStatsArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('stats-area').style.display        = 'block';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'none';
    document.getElementById('portfolio-area').style.display    = 'none';
    document.querySelector('.tab-bar').style.display           = 'none';
}

function showPortfolioArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'none';
    document.getElementById('portfolio-area').style.display    = 'block';
    document.querySelector('.tab-bar').style.display           = 'none';
}

function showChartArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('chart-area').style.display        = 'flex';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'none';
    document.getElementById('portfolio-area').style.display    = 'none';
    document.querySelector('.tab-bar').style.display           = 'flex';
}

function showTrendArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'flex';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'none';
    document.querySelector('.tab-bar').style.display           = 'none';
}

function showScannerArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'flex';
    document.getElementById('data-manager-area').style.display = 'none';
    document.querySelector('.tab-bar').style.display           = 'none';
}

function showDataManagerArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'flex';
    document.querySelector('.tab-bar').style.display           = 'none';
}

// ── Stats Rendering ───────────────────────────────────────────
function renderStats(data) {
    const m = data.metrics;
    
    // Update KPI values
    const fmt = (v, pct = false) => {
        if (v === null || v === undefined || !Number.isFinite(v)) return '--';
        return pct ? (v * 100).toFixed(2) + '%' : v.toFixed(2);
    };
    const pctValue = v => (v !== null && Number.isFinite(v)) ? v * 100 : null;
    const pctColor = v => (v !== null && Number.isFinite(v) && v >= 0) ? '#22c55e' : '#ef4444';

    const kamaColors = {
        '10': '#3b82f6',
        '20': '#f97316',
        '50': '#a855f7',
    };
    const alignedDeciles = series => {
        const values = Array(10).fill(null);
        (series || []).forEach(point => {
            if (Number.isInteger(point.bin) && point.bin >= 0 && point.bin < 10) {
                values[point.bin] = pctValue(point.value);
            }
        });
        return values;
    };
    
    document.getElementById('stat-vol').textContent      = fmt(m.volatility, true);
    document.getElementById('stat-sharpe').textContent   = fmt(m.sharpe);
    document.getElementById('stat-drawdown').textContent = fmt(m.max_drawdown, true);
    document.getElementById('stat-winrate').textContent  = fmt(m.win_rate, true);

    // Common Chart.js options
    const baseChartOpts = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
            y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8b949e', font: { size: 10 } } },
            x: { grid: { display: false }, ticks: { color: '#8b949e', font: { size: 10 } } }
        }
    };
    const distanceChartOptions = {
        ...baseChartOpts,
        plugins: {
            legend: {
                display: true,
                labels: { color: '#8b949e', usePointStyle: true, boxWidth: 10 }
            }
        }
    };
    const crossChartOptions = {
        ...baseChartOpts,
        plugins: {
            legend: {
                display: true,
                labels: { color: '#8b949e', usePointStyle: true, boxWidth: 10 }
            }
        }
    };

    const destroy = (id) => { if (statsCharts[id]) statsCharts[id].destroy(); };

    // 1. RSI Deciles 1D
    destroy('rsi1d');
    statsCharts['rsi1d'] = new Chart(document.getElementById('chart-rsi-1d'), {
        type: 'bar',
        data: {
            labels: data.rsi_analysis.fwd_1d.map(d => `D${d.bin+1}`),
            datasets: [{
                label: 'Mean 1D Return',
                data: data.rsi_analysis.fwd_1d.map(d => pctValue(d.value)),
                backgroundColor: data.rsi_analysis.fwd_1d.map(d => pctColor(d.value)),
            }]
        },
        options: baseChartOpts
    });

    // 2b. Price vs KAMA distance deciles (1D)
    destroy('kamaDist1d');
    statsCharts['kamaDist1d'] = new Chart(document.getElementById('chart-kama-dist-1d'), {
        type: 'line',
        data: {
            labels: Array.from({ length: 10 }, (_, i) => `D${i + 1}`),
            datasets: Object.entries(data.kama_distance_analysis?.fwd_1d || {}).map(([period, points]) => ({
                label: `KAMA ${period}`,
                data: alignedDeciles(points),
                borderColor: kamaColors[period] || '#4facfe',
                backgroundColor: kamaColors[period] || '#4facfe',
                spanGaps: true,
                pointRadius: 3,
                pointHoverRadius: 5,
                borderWidth: 2,
                tension: 0.25,
            }))
        },
        options: distanceChartOptions
    });

    // 2. RSI Deciles 5D
    destroy('rsi5d');
    statsCharts['rsi5d'] = new Chart(document.getElementById('chart-rsi-5d'), {
        type: 'bar',
        data: {
            labels: data.rsi_analysis.fwd_5d.map(d => `D${d.bin+1}`),
            datasets: [{
                label: 'Mean 5D Return',
                data: data.rsi_analysis.fwd_5d.map(d => pctValue(d.value)),
                backgroundColor: data.rsi_analysis.fwd_5d.map(d => pctColor(d.value)),
            }]
        },
        options: baseChartOpts
    });

    // 2c. Price vs KAMA distance deciles (5D)
    destroy('kamaDist5d');
    statsCharts['kamaDist5d'] = new Chart(document.getElementById('chart-kama-dist-5d'), {
        type: 'line',
        data: {
            labels: Array.from({ length: 10 }, (_, i) => `D${i + 1}`),
            datasets: Object.entries(data.kama_distance_analysis?.fwd_5d || {}).map(([period, points]) => ({
                label: `KAMA ${period}`,
                data: alignedDeciles(points),
                borderColor: kamaColors[period] || '#4facfe',
                backgroundColor: kamaColors[period] || '#4facfe',
                spanGaps: true,
                pointRadius: 3,
                pointHoverRadius: 5,
                borderWidth: 2,
                tension: 0.25,
            }))
        },
        options: distanceChartOptions
    });

    // 3. Returns Distribution
    destroy('dist');
    statsCharts['dist'] = new Chart(document.getElementById('chart-dist'), {
        type: 'bar',
        data: {
            labels: data.distribution.map(d => (d.bin * 100).toFixed(1) + '%'),
            datasets: [{
                data: data.distribution.map(d => d.count),
                backgroundColor: 'rgba(79, 172, 254, 0.6)',
                borderColor: '#4facfe',
                borderWidth: 1,
                categoryPercentage: 1.0,
                barPercentage: 1.0
            }]
        },
        options: {
            ...baseChartOpts,
            scales: {
                ...baseChartOpts.scales,
                x: { ...baseChartOpts.scales.x, ticks: { ...baseChartOpts.scales.x.ticks, maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } }
            }
        }
    });

    // 4. Seasonality
    const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    destroy('season');
    statsCharts['season'] = new Chart(document.getElementById('chart-seasonality'), {
        type: 'bar',
        data: {
            labels: data.seasonality.map(d => monthNames[d.month-1]),
            datasets: [{
                data: data.seasonality.map(d => pctValue(d.value)),
                backgroundColor: data.seasonality.map(d => Number.isFinite(d.value) && d.value >= 0 ? 'rgba(34, 197, 94, 0.6)' : 'rgba(239, 68, 68, 0.6)'),
            }]
        },
        options: baseChartOpts
    });

    // 4b. KAMA cross forward returns
    destroy('kamaCross');
    statsCharts['kamaCross'] = new Chart(document.getElementById('chart-kama-cross'), {
        type: 'bar',
        data: {
            labels: (data.kama_cross_analysis || []).map(d => d.label),
            datasets: [
                {
                    label: '1D Fwd Return',
                    data: (data.kama_cross_analysis || []).map(d => pctValue(d.fwd_1d)),
                    backgroundColor: 'rgba(79, 172, 254, 0.65)',
                    borderColor: '#4facfe',
                    borderWidth: 1,
                },
                {
                    label: '5D Fwd Return',
                    data: (data.kama_cross_analysis || []).map(d => pctValue(d.fwd_5d)),
                    backgroundColor: 'rgba(249, 115, 22, 0.65)',
                    borderColor: '#f97316',
                    borderWidth: 1,
                }
            ]
        },
        options: crossChartOptions
    });

    // 4c. KAMA cross event counts
    destroy('kamaCrossCounts');
    statsCharts['kamaCrossCounts'] = new Chart(document.getElementById('chart-kama-cross-counts'), {
        type: 'bar',
        data: {
            labels: (data.kama_cross_analysis || []).map(d => d.label),
            datasets: [{
                label: '1D Event Count',
                data: (data.kama_cross_analysis || []).map(d => d.count_1d),
                backgroundColor: (data.kama_cross_analysis || []).map(d => d.direction === 'bull' ? 'rgba(34, 197, 94, 0.6)' : 'rgba(239, 68, 68, 0.6)'),
                borderColor: (data.kama_cross_analysis || []).map(d => d.direction === 'bull' ? '#22c55e' : '#ef4444'),
                borderWidth: 1,
            }]
        },
        options: baseChartOpts
    });
}

function updateSymbolHeader(symbol, last, prev) {
    document.getElementById('sym-title').textContent = symbol;
    const symInfo = state.symbols.find(s => s.symbol === symbol);
    document.getElementById('sym-subtitle').textContent = symInfo?.name || '';

    if (!last) {
        document.getElementById('sym-price').textContent   = '--';
        document.getElementById('sym-change-badge').textContent = '';
        ['open', 'high', 'low', 'close', 'volume'].forEach(k => {
            const el = document.getElementById(`ohlcv-${k}`);
            if (el) el.textContent = '--';
        });
        return;
    }

    const chg    = prev ? last.close - prev.close : 0;
    const chgPct = prev ? (chg / prev.close * 100).toFixed(2) : '0.00';
    const isPos  = chg >= 0;

    document.getElementById('sym-price').textContent = `$${last.close.toFixed(2)}`;

    const badge = document.getElementById('sym-change-badge');
    badge.textContent = `${isPos ? '+' : ''}${chg.toFixed(2)} (${isPos ? '+' : ''}${chgPct}%)`;
    badge.className   = `sym-change-badge ${isPos ? 'positive' : 'negative'}`;

    const fmt    = n => n?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '--';
    const fmtVol = n => (n != null) ? (n >= 1e9 ? (n / 1e9).toFixed(2) + 'B' : n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n.toLocaleString()) : '--';

    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set('ohlcv-open',   `$${fmt(last.open)}`);
    set('ohlcv-high',   `$${fmt(last.high)}`);
    set('ohlcv-low',    `$${fmt(last.low)}`);
    set('ohlcv-close',  `$${fmt(last.close)}`);
    set('ohlcv-volume', fmtVol(last.volume));
}

// ── KNN Functions ────────────────────────────────────────────
async function loadKNN(symbol) {
    document.getElementById('knn-loading').style.display = 'flex';
    try {
        const data = await apiFetch(`${API}/knn/${symbol}?k=15`);
        renderKNN(data);
    } catch (e) {
        toast('KNN failed: ' + e.message, 'error');
    } finally {
        document.getElementById('knn-loading').style.display = 'none';
    }
}

function renderKNN(data) {
    const fmt  = v => (v !== null && v !== undefined && Number.isFinite(v)) ? (v * 100).toFixed(2) + '%' : '--';
    const fmtF = (v, dec) => (v !== null && v !== undefined && Number.isFinite(v)) ? v.toFixed(dec) : '--';

    // Composite / confidence card
    const compEl = document.getElementById('knn-composite');
    const confEl = document.getElementById('knn-confidence');
    if (compEl) {
        const score = data.ensemble_score;
        if (score != null) {
            const col = score >= 15 ? '#22c55e' : score <= -15 ? '#ef4444' : 'var(--text-muted)';
            compEl.textContent = data.ensemble_label || '--';
            compEl.style.color = col;
            compEl.style.fontSize = '18px';
        } else {
            compEl.textContent = '--';
        }
    }
    if (confEl) {
        confEl.textContent = data.confidence != null
            ? `Confidence: ${(data.confidence * 100).toFixed(0)}%`
            : 'Confidence: --';
    }

    // Prediction KPI cards
    const horizons = { '1d': 'fwd_1d', '5d': 'fwd_5d', '20d': 'fwd_20d' };
    for (const [suffix, key] of Object.entries(horizons)) {
        const s = data.summary[key] || {};
        const winEl  = document.getElementById(`knn-win-${suffix}`);
        const meanEl = document.getElementById(`knn-mean-${suffix}`);
        if (winEl)  winEl.textContent  = s.positive_pct !== null && s.positive_pct !== undefined ? (s.positive_pct * 100).toFixed(1) + '%' : '--';
        if (meanEl) meanEl.textContent = 'Mean: ' + fmt(s.mean);
    }

    // Current features table
    const featureTbody = document.querySelector('#knn-feature-table tbody');
    if (featureTbody) {
        const featureLabels = {
            rsi14:        'RSI (14)',
            vol20_ann:    'Vol 20D Ann.',
            macd_hist:    'MACD Hist',
            cci_norm:     'CCI / 200',
            vol_ratio:    'Vol Ratio vs 20MA',
            kama_dist_10: 'Price vs KAMA10',
            kama_dist_20: 'Price vs KAMA20',
            kama_dist_50: 'Price vs KAMA50',
        };
        featureTbody.innerHTML = '';
        const cf = data.current_features || {};
        for (const [key, label] of Object.entries(featureLabels)) {
            const val = cf[key];
            const tr  = document.createElement('tr');
            tr.innerHTML = `<td>${label}</td><td>${fmtF(val, 4)}</td>`;
            featureTbody.appendChild(tr);
        }
    }

    // Neighbours table
    const nbTbody = document.querySelector('#knn-neighbors-table tbody');
    if (nbTbody) {
        nbTbody.innerHTML = '';
        (data.neighbors || []).forEach(n => {
            const tr = document.createElement('tr');
            const colorRet = v => {
                if (v === null || v === undefined || !Number.isFinite(v)) return '';
                return v >= 0 ? 'color:var(--green)' : 'color:var(--red)';
            };
            tr.innerHTML = `
                <td>${n.date}</td>
                <td>${fmtF(n.distance, 3)}</td>
                <td style="${colorRet(n.fwd_1d)}">${fmt(n.fwd_1d)}</td>
                <td style="${colorRet(n.fwd_5d)}">${fmt(n.fwd_5d)}</td>
                <td style="${colorRet(n.fwd_20d)}">${fmt(n.fwd_20d)}</td>
            `;
            nbTbody.appendChild(tr);
        });
    }
}

// ── KNN Sub-tab switching ─────────────────────────────────────
function switchKNNTab(tab) {
    ['lookalike', 'scan', 'wf', 'imp', 'clusters'].forEach(t => {
        const panel = document.getElementById(`knn-panel-${t}`);
        const btn   = document.getElementById(`knn-stab-${t}`);
        if (panel) panel.style.display = t === tab ? '' : 'none';
        if (btn)   btn.classList.toggle('knn-stab-active', t === tab);
    });
}

// ── KNN Clusters ──────────────────────────────────────────────
async function loadKNNClusters() {
    const loading  = document.getElementById('knn-cluster-loading');
    const statusEl = document.getElementById('knn-cluster-status');
    const n        = document.getElementById('knn-cluster-n')?.value || 4;
    if (loading)  loading.style.display = 'flex';
    if (statusEl) statusEl.textContent  = '';
    try {
        const data = await apiFetch(`${API}/knn/clusters?n=${n}`);
        if (data.error) { toast(data.error, 'warning'); return; }
        renderKNNClusters(data);
        if (statusEl) statusEl.textContent = `${data.total_symbols} symbols → ${data.n_clusters} clusters`;
    } catch (e) {
        toast('Clustering failed: ' + e.message, 'error');
    } finally {
        if (loading) loading.style.display = 'none';
    }
}

function renderKNNClusters(data) {
    const grid = document.getElementById('knn-cluster-grid');
    if (!grid) return;
    const clusters = data.clusters || [];
    grid.innerHTML = clusters.map(c => {
        const members = (c.members || []).map(s =>
            `<span class="cluster-chip" onclick="selectSymbol('${s}')">${s}</span>`
        ).join('');
        const cent = c.centroid || {};
        const rows = Object.values(cent).map(f =>
            `<div class="regime-meta-row"><span>${f.label}</span><span>${f.value != null ? f.value : '—'}</span></div>`
        ).join('');
        return `<div class="regime-cell">
            <div class="regime-badge" style="background:rgba(59,130,246,0.15); color:var(--accent-bright);">
                Cluster ${c.label} · ${c.member_count}
            </div>
            <div class="cluster-desc">${c.description}</div>
            <div class="cluster-members">${members}</div>
            <div class="regime-meta">${rows}</div>
        </div>`;
    }).join('');
}

// ── KNN Watchlist Scan ────────────────────────────────────────
async function loadKNNScan() {
    const loading  = document.getElementById('knn-scan-loading');
    const statusEl = document.getElementById('knn-scan-status');
    if (loading)  loading.style.display = 'flex';
    if (statusEl) statusEl.textContent  = '';
    try {
        const data = await apiFetch(`${API}/knn/scan?k=10`);
        renderKNNScan(data);
        if (statusEl) statusEl.textContent = `${data.length} symbols scanned`;
    } catch (e) {
        toast('KNN Scan failed: ' + e.message, 'error');
    } finally {
        if (loading) loading.style.display = 'none';
    }
}

function renderKNNScan(rows) {
    const tbody = document.getElementById('knn-scan-tbody');
    if (!tbody) return;
    const fmt  = v => (v != null && Number.isFinite(v)) ? (v * 100).toFixed(1) + '%' : '—';
    const fmtM = v => (v != null && Number.isFinite(v)) ? (v * 100).toFixed(2) + '%' : '—';
    const winCls = v => {
        if (v == null) return '';
        if (v >= 0.65) return 'style="color:var(--green);font-weight:600"';
        if (v <= 0.35) return 'style="color:var(--red);font-weight:600"';
        return '';
    };
    tbody.innerHTML = rows.map(r => {
        if (r.error) return `<tr><td><strong>${r.symbol}</strong></td><td colspan="7" style="color:var(--text-muted)">${r.error}</td></tr>`;
        return `<tr class="knn-scan-row" onclick="selectSymbol('${r.symbol}')">
            <td><strong>${r.symbol}</strong></td>
            <td ${winCls(r.fwd_1d_win)}>${fmt(r.fwd_1d_win)}</td>
            <td>${fmtM(r.fwd_1d_mean)}</td>
            <td ${winCls(r.fwd_5d_win)}>${fmt(r.fwd_5d_win)}</td>
            <td>${fmtM(r.fwd_5d_mean)}</td>
            <td ${winCls(r.fwd_20d_win)}>${fmt(r.fwd_20d_win)}</td>
            <td>${fmtM(r.fwd_20d_mean)}</td>
            <td style="color:var(--text-muted);font-size:11px">${r.as_of || '—'}</td>
        </tr>`;
    }).join('');
}

// ── KNN Walk-Forward Backtest ─────────────────────────────────
async function loadKNNWalkForward() {
    if (!state.activeSymbol) { toast('Select a symbol first', 'warn'); return; }
    const horizon  = document.getElementById('knn-wf-horizon')?.value  || 5;
    const step     = document.getElementById('knn-wf-step')?.value     || 21;
    const k        = document.getElementById('knn-wf-k')?.value        || 10;
    const loading  = document.getElementById('knn-wf-loading');
    const statusEl = document.getElementById('knn-wf-status');
    const results  = document.getElementById('knn-wf-results');

    if (loading)  { loading.style.display = 'flex'; }
    if (results)  { results.style.display = 'none'; }
    if (statusEl) { statusEl.textContent  = ''; }

    try {
        const url  = `${API}/knn/walk-forward/${state.activeSymbol}?horizon=${horizon}&step=${step}&k=${k}`;
        const data = await apiFetch(url);
        renderKNNWalkForward(data);
        if (statusEl) statusEl.textContent = `${data.n_total} eval points · accuracy ${(data.accuracy * 100).toFixed(1)}%`;
    } catch (e) {
        toast('Walk-forward failed: ' + e.message, 'error');
    } finally {
        if (loading) loading.style.display = 'none';
    }
}

function renderKNNWalkForward(data) {
    const results = document.getElementById('knn-wf-results');
    if (!results) return;
    results.style.display = '';

    // KPI row
    const kpiEl = document.getElementById('knn-wf-kpis');
    if (kpiEl) {
        const acc  = (data.accuracy * 100).toFixed(1);
        const accC = data.accuracy >= 0.55 ? '#22c55e' : data.accuracy <= 0.45 ? '#ef4444' : '#f59e0b';
        const lastEq = data.equity_curve?.length ? data.equity_curve[data.equity_curve.length - 1].equity : 0;
        const eqC    = lastEq >= 0 ? '#22c55e' : '#ef4444';
        kpiEl.innerHTML = `
            <div class="kpi-card prediction-card">
                <div class="kpi-label">Accuracy</div>
                <div class="kpi-value" style="color:${accC}">${acc}%</div>
                <div class="kpi-sub">${data.n_correct} / ${data.n_total} correct</div>
            </div>
            <div class="kpi-card prediction-card">
                <div class="kpi-label">Total Return</div>
                <div class="kpi-value" style="color:${eqC}">${lastEq >= 0 ? '+' : ''}${lastEq.toFixed(2)}%</div>
                <div class="kpi-sub">Horizon: ${data.horizon_days}D</div>
            </div>
            <div class="kpi-card prediction-card">
                <div class="kpi-label">Eval Points</div>
                <div class="kpi-value">${data.n_total}</div>
                <div class="kpi-sub">Symbol: ${data.symbol}</div>
            </div>
        `;
    }

    // Equity curve via canvas (simple line chart)
    const canvas = document.getElementById('knn-wf-chart');
    if (canvas && data.equity_curve?.length) {
        _drawEquityCurve(canvas, data.equity_curve);
    }

    // Detail table
    const tbody = document.getElementById('knn-wf-tbody');
    if (tbody) {
        tbody.innerHTML = (data.records || []).map(r => {
            const dirLabel = r.predicted === 1 ? '<span style="color:var(--green)">▲ Long</span>' : '<span style="color:var(--red)">▼ Short</span>';
            const actStyle = r.actual_ret >= 0 ? 'color:var(--green)' : 'color:var(--red)';
            const tick     = r.correct ? '✓' : '✗';
            const tickC    = r.correct ? 'color:var(--green)' : 'color:var(--red)';
            return `<tr>
                <td style="color:var(--text-muted);font-size:11px">${r.date}</td>
                <td>${dirLabel}</td>
                <td style="${r.pred_mean >= 0 ? 'color:var(--green)' : 'color:var(--red)'}">${r.pred_mean >= 0 ? '+' : ''}${r.pred_mean}%</td>
                <td style="${actStyle}">${r.actual_ret >= 0 ? '+' : ''}${r.actual_ret}%</td>
                <td style="${tickC};font-weight:700">${tick}</td>
            </tr>`;
        }).join('');
    }
}

function _drawEquityCurve(canvas, curve) {
    const ctx    = canvas.getContext('2d');
    const W      = canvas.offsetWidth || 600;
    const H      = canvas.height;
    canvas.width = W;
    ctx.clearRect(0, 0, W, H);

    const vals   = curve.map(p => p.equity);
    const minV   = Math.min(...vals);
    const maxV   = Math.max(...vals);
    const range  = maxV - minV || 1;
    const pad    = 20;

    const toX = i => pad + (i / (vals.length - 1)) * (W - pad * 2);
    const toY = v => H - pad - ((v - minV) / range) * (H - pad * 2);

    // Zero line
    ctx.strokeStyle = 'rgba(255,255,255,0.1)';
    ctx.lineWidth = 1;
    ctx.setLineDash([4, 4]);
    const y0 = toY(0);
    ctx.beginPath(); ctx.moveTo(pad, y0); ctx.lineTo(W - pad, y0); ctx.stroke();
    ctx.setLineDash([]);

    // Fill
    const lastY = toY(vals[vals.length - 1]);
    const fillColor = vals[vals.length - 1] >= 0 ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.12)';
    ctx.beginPath();
    ctx.moveTo(toX(0), y0);
    vals.forEach((v, i) => ctx.lineTo(toX(i), toY(v)));
    ctx.lineTo(toX(vals.length - 1), y0);
    ctx.closePath();
    ctx.fillStyle = fillColor;
    ctx.fill();

    // Line
    ctx.beginPath();
    ctx.strokeStyle = vals[vals.length - 1] >= 0 ? '#22c55e' : '#ef4444';
    ctx.lineWidth = 2;
    vals.forEach((v, i) => i === 0 ? ctx.moveTo(toX(i), toY(v)) : ctx.lineTo(toX(i), toY(v)));
    ctx.stroke();
}

// ── Scanner Custom Indicator Builder ─────────────────────────
const _customIndicators = [];   // [{name, type, period, period2, tf, values:{sym:val}}]

function toggleCustomIndBuilder() {
    const el = document.getElementById('custom-ind-builder');
    if (!el) return;
    el.style.display = el.style.display === 'none' ? '' : 'none';
}

async function addCustomIndicator() {
    const name    = document.getElementById('cib-name')?.value.trim()    || 'Custom';
    const type    = document.getElementById('cib-type')?.value           || 'rsi';
    const period  = parseInt(document.getElementById('cib-period')?.value || 14);
    const period2 = parseInt(document.getElementById('cib-period2')?.value) || null;
    const tf      = document.getElementById('cib-tf')?.value             || 'd';

    const symbols = scannerState.data?.map(r => r.symbol) || [];
    if (!symbols.length) { toast('Run scanner first', 'warn'); return; }

    const btn = document.querySelector('.cib-add');
    if (btn) { btn.disabled = true; btn.textContent = 'Computing…'; }
    try {
        const resp = await apiFetch(`${API}/scanner/custom-indicator`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbols, indicator: { type, period, period2, timeframe: tf } }),
        });
        const valMap = {};
        resp.forEach(r => { valMap[r.symbol] = r.value; });
        _customIndicators.push({ name, type, period, period2, tf, values: valMap });
        _renderCustomIndList();
        renderScannerTable();
        toast(`Added "${name}"`, 'success');
    } catch (e) {
        toast('Custom indicator failed: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '+ Add Column'; }
    }
}

function removeCustomIndicator(idx) {
    _customIndicators.splice(idx, 1);
    _renderCustomIndList();
    renderScannerTable();
}

function _renderCustomIndList() {
    const el = document.getElementById('cib-active');
    if (!el) return;
    if (!_customIndicators.length) { el.innerHTML = ''; return; }
    el.innerHTML = '<div class="cib-active-label">Active:</div>' +
        _customIndicators.map((ind, i) =>
            `<span class="cib-chip">${ind.name} <button onclick="removeCustomIndicator(${i})">✕</button></span>`
        ).join('');
}

// ── CSV Export ────────────────────────────────────────────────
function _downloadCSV(filename, rows) {
    // rows: array of arrays. Quote cells containing commas/quotes/newlines.
    const esc = v => {
        if (v == null) return '';
        const s = String(v);
        return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
    };
    const csv  = rows.map(r => r.map(esc).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function exportScannerCSV() {
    const data = (typeof scannerState !== 'undefined') ? scannerState.data : null;
    if (!data || !data.length) { toast('Run the scanner first', 'warning'); return; }

    // Header: fixed cols + visible group metrics (per timeframe) + custom
    const header = ['Symbol', 'Sector', 'Group', 'Score', 'Price', '1D%', '1M%'];
    const metricCols = [];
    if (typeof SCAN_GROUPS !== 'undefined') {
        for (const grp of SCAN_GROUPS) {
            if (!scannerState.visible[grp.id]) continue;
            for (const m of grp.metrics) {
                for (const tf of m.tfs) {
                    header.push(`${m.label} (${tf.toUpperCase()})`);
                    metricCols.push([tf, m.key]);
                }
            }
        }
    }
    const customs = (typeof _customIndicators !== 'undefined') ? _customIndicators : [];
    customs.forEach(ci => header.push(ci.name));

    const rows = [header];
    for (const r of data) {
        const score = (typeof _score === 'function') ? _score(r) : null;
        const row = [r.symbol, r.sector || '', r.group_tag || '',
                     score, r.price, r.chg, r.ret_1m];
        for (const [tf, key] of metricCols) row.push(r[tf]?.[key] ?? '');
        customs.forEach(ci => row.push(ci.values?.[r.symbol] ?? ''));
        rows.push(row);
    }
    _downloadCSV(`scanner_${new Date().toISOString().slice(0,10)}.csv`, rows);
    toast('Scanner CSV downloaded', 'success', 2000);
}

function exportKNNScanCSV() {
    const tbody = document.getElementById('knn-scan-tbody');
    if (!tbody || !tbody.children.length) { toast('Run the KNN scan first', 'warning'); return; }
    const rows = [['Symbol', '1D Win%', '1D Mean%', '5D Win%', '5D Mean%', '20D Win%', '20D Mean%', 'As Of']];
    for (const tr of tbody.querySelectorAll('tr')) {
        const cells = [...tr.querySelectorAll('td')].map(td => td.textContent.trim());
        if (cells.length) rows.push(cells);
    }
    _downloadCSV(`knn_scan_${new Date().toISOString().slice(0,10)}.csv`, rows);
    toast('KNN scan CSV downloaded', 'success', 2000);
}

// ── Backtest Functions ────────────────────────────────────────
async function loadBacktest(symbol) {
    const statusEl = document.getElementById('backtest-status');
    const btn      = document.getElementById('btn-run-backtest');
    const slider   = document.getElementById('train-pct-slider');
    const trainPct = slider ? (parseInt(slider.value, 10) / 100).toFixed(2) : '0.70';

    if (statusEl) statusEl.textContent = 'Running optimization…';
    if (btn) btn.disabled = true;
    try {
        const data = await apiFetch(`${API}/backtest/${symbol}?train_pct=${trainPct}`);
        renderBacktest(data);
        if (statusEl) statusEl.textContent = `Done — ${data.total_tested} combos tested (${data.train_bars} IS / ${data.oos_bars} OOS bars)`;
    } catch (e) {
        toast('Backtest failed: ' + e.message, 'error');
        if (statusEl) statusEl.textContent = 'Error: ' + e.message;
    } finally {
        if (btn) btn.disabled = false;
    }
}

function renderBacktest(data) {
    const fmt    = (v, dec = 2) => (v !== null && v !== undefined && Number.isFinite(v)) ? v.toFixed(dec) : '--';
    const fmtPct = v => (v !== null && v !== undefined && Number.isFinite(v)) ? (v * 100).toFixed(2) + '%' : '--';
    const colorV = v => (v !== null && v !== undefined && Number.isFinite(v) && v >= 0) ? 'color:#22c55e' : 'color:#ef4444';

    const best = data.best || {};
    const set  = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set('bt-sharpe',  fmt(best.is_sharpe ?? best.sharpe, 3));
    set('bt-annret',  fmtPct(best.is_ann_ret ?? best.ann_ret));
    set('bt-maxdd',   fmtPct(best.is_max_dd ?? best.max_dd));
    set('bt-winrate', fmtPct(best.is_win_rate ?? best.win_rate));
    set('bt-trades',  best.n_trades !== undefined ? String(best.n_trades) : '--');

    // Top 10 table
    const tbody = document.querySelector('#bt-results-table tbody');
    if (tbody) {
        tbody.innerHTML = '';
        (data.top10 || []).forEach((r, i) => {
            const tr = document.createElement('tr');
            if (i === 0) tr.style.background = 'rgba(59,130,246,0.08)';
            const sharpe = r.is_sharpe ?? r.sharpe;
            const annRet = r.is_ann_ret ?? r.ann_ret;
            const maxDd  = r.is_max_dd  ?? r.max_dd;
            const winRate= r.is_win_rate?? r.win_rate;
            tr.innerHTML = `
                <td>${r.label}</td>
                <td>${fmt(sharpe, 3)}</td>
                <td style="${colorV(annRet)}">${fmtPct(annRet)}</td>
                <td style="${colorV(maxDd ? -maxDd : null)}">${fmtPct(maxDd)}</td>
                <td>${r.n_trades}</td>
                <td>${fmtPct(winRate)}</td>
            `;
            tbody.appendChild(tr);
        });
    }

    // IS vs OOS comparison table
    const oosSection = document.getElementById('bt-oos-section');
    const oosTbody   = document.querySelector('#bt-oos-table tbody');
    const bmTbody    = document.querySelector('#bt-bm-table tbody');
    if (oosSection && best && oosTbody) {
        oosSection.style.display = 'block';
        const metrics = [
            ['Sharpe',      fmt(best.is_sharpe  ?? best.sharpe, 3),     fmt(best.oos_sharpe, 3)],
            ['Ann. Return', fmtPct(best.is_ann_ret ?? best.ann_ret),    fmtPct(best.oos_ann_ret)],
            ['Ann. Vol',    fmtPct(best.is_ann_vol ?? best.ann_vol),    fmtPct(best.oos_ann_vol)],
            ['Max DD',      fmtPct(best.is_max_dd  ?? best.max_dd),     fmtPct(best.oos_max_dd)],
            ['Win Rate',    fmtPct(best.is_win_rate ?? best.win_rate),  fmtPct(best.oos_win_rate)],
            ['Trades',      String(best.is_n_trades ?? best.n_trades ?? '--'), String(best.oos_n_trades ?? '--')],
        ];
        oosTbody.innerHTML = metrics.map(([label, is, oos]) =>
            `<tr><td>${label}</td><td>${is}</td><td>${oos}</td></tr>`
        ).join('');
    }
    if (bmTbody && data.benchmark) {
        const bm  = data.benchmark;
        const strat = best;
        const bmMetrics = [
            ['Sharpe',      fmt(strat.is_sharpe ?? strat.sharpe, 3),    fmt(bm.sharpe, 3)],
            ['Ann. Return', fmtPct(strat.is_ann_ret ?? strat.ann_ret),  fmtPct(bm.ann_ret)],
            ['Max DD',      fmtPct(strat.is_max_dd  ?? strat.max_dd),   fmtPct(bm.max_dd)],
        ];
        bmTbody.innerHTML = bmMetrics.map(([label, s, b]) =>
            `<tr><td>${label}</td><td>${s}</td><td>${b}</td></tr>`
        ).join('');
    }

    // Equity curve chart
    if (backtestEquityChart) {
        backtestEquityChart.destroy();
        backtestEquityChart = null;
    }
    const canvas = document.getElementById('chart-backtest-equity');
    if (canvas && data.equity_curve && data.equity_curve.length > 0) {
        const labels    = data.equity_curve.map(d => d.date);
        const strategy  = data.equity_curve.map(d => d.strategy);
        const benchmark = data.equity_curve.map(d => d.benchmark);
        backtestEquityChart = new Chart(canvas, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Strategy',
                        data: strategy,
                        borderColor: '#4facfe',
                        backgroundColor: 'rgba(79,172,254,0.08)',
                        borderWidth: 2,
                        pointRadius: 0,
                        tension: 0.1,
                        fill: true,
                    },
                    {
                        label: 'Buy & Hold',
                        data: benchmark,
                        borderColor: '#f97316',
                        backgroundColor: 'transparent',
                        borderWidth: 1.5,
                        borderDash: [5, 3],
                        pointRadius: 0,
                        tension: 0.1,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { display: true, labels: { color: '#8b949e', usePointStyle: true, boxWidth: 10 } },
                },
                scales: {
                    x: { grid: { display: false }, ticks: { color: '#8b949e', font: { size: 10 }, maxTicksLimit: 12 } },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8b949e', font: { size: 10 } } },
                },
            },
        });
    }
}

// ── Scanner Functions ─────────────────────────────────────────
async function fetchSP500() {
    const btn      = document.getElementById('btn-fetch-sp500');
    const statusEl = document.getElementById('scanner-fetch-status');
    if (btn) btn.disabled = true;
    if (statusEl) statusEl.textContent = 'Starting fetch…';

    try {
        await apiFetch(`${API}/scanner/fetch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: false }),
        });
        if (statusEl) statusEl.textContent = 'Fetching… 0%';
        pollScannerStatus();
    } catch (e) {
        toast('Fetch failed: ' + e.message, 'error');
        if (statusEl) statusEl.textContent = 'Error: ' + e.message;
        if (btn) btn.disabled = false;
    }
}

function pollScannerStatus() {
    if (scannerPollTimer) clearInterval(scannerPollTimer);
    scannerPollTimer = setInterval(async () => {
        try {
            const s      = await apiFetch(`${API}/scanner/status`);
            const btn    = document.getElementById('btn-fetch-sp500');
            const statusEl = document.getElementById('scanner-fetch-status');
            if (s.running) {
                if (statusEl) statusEl.textContent = `Fetching… ${s.progress}% (${s.done}/${s.total})`;
            } else {
                clearInterval(scannerPollTimer);
                scannerPollTimer = null;
                if (btn) btn.disabled = false;
                const sum = s.summary || {};
                if (statusEl) {
                    statusEl.textContent = sum.error
                        ? 'Error: ' + sum.error
                        : `Done — ${sum.success || 0} ok, ${sum.skipped || 0} skipped, ${sum.failed || 0} failed`;
                }
                toast('S&P 500 fetch complete', 'success');
            }
        } catch (e) {
            clearInterval(scannerPollTimer);
            scannerPollTimer = null;
        }
    }, 3000);
}

async function runScanner() {
    const btn       = document.getElementById('btn-run-scanner');
    const countEl   = document.getElementById('scanner-count');
    const filterSel = document.getElementById('scanner-signal-filter');
    const signal    = filterSel ? filterSel.value : '';

    if (btn) { btn.disabled = true; btn.textContent = 'Scanning…'; }
    if (countEl) countEl.textContent = '';

    try {
        let url = `${API}/scanner/run`;
        if (signal) url += `?signal=${encodeURIComponent(signal)}`;
        const results = await apiFetch(url);
        renderScannerTable(results);
        if (countEl) countEl.textContent = `${results.length} results`;
    } catch (e) {
        toast('Scanner failed: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Run Scanner'; }
    }
}

// renderScannerTable is defined in scanner.js (multi-timeframe version)

// ── Boot ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    startClock();
    initTheme();

    // Restore sidebar collapsed state
    if (localStorage.getItem('sidebarCollapsed') === '1') {
        const app = document.querySelector('.app');
        const btn = document.getElementById('btn-sidebar-toggle');
        if (app) app.classList.add('sidebar-collapsed');
        if (btn) btn.textContent = '▶';
    }

    // Restore focus mode
    if (localStorage.getItem('focusMode') === '1') {
        const main = document.querySelector('.main');
        const btn  = document.getElementById('btn-focus-mode');
        if (main) main.classList.add('focus-mode');
        if (btn)  btn.textContent = '⊞';
    }

    // Keyboard navigation
    document.addEventListener('keydown', _handleGlobalKeydown);

    // Restore KAMA periods from localStorage, fallback to defaults
    const savedKama = loadKamaFromStorage();
    (savedKama.length ? savedKama : DEFAULT_KAMA_PERIODS).forEach(p => addKamaPeriod(p));
    renderKamaPills();
    setupKamaAddForm();

    // BB pill
    const bbPill = document.getElementById('pill-bb');
    bbPill.addEventListener('click', () => {
        const on = toggleOverlay('bb');
        bbPill.classList.toggle('active-bb', on);
    });

    // Buttons
    document.getElementById('btn-add-symbol').addEventListener('click', addSymbol);
    document.getElementById('btn-bulk-add').addEventListener('click', openBulkModal);
    document.getElementById('btn-refresh-all').addEventListener('click', refreshAll);
    document.getElementById('new-symbol-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') addSymbol();
    });

    // Scanner buttons (optional — only present in legacy scanner UI)
    document.getElementById('btn-fetch-sp500')?.addEventListener('click', fetchSP500);
    document.getElementById('btn-run-scanner')?.addEventListener('click', runScanner);
    document.getElementById('scanner-signal-filter')?.addEventListener('change', runScanner);

    // Backtest button
    document.getElementById('btn-run-backtest').addEventListener('click', () => {
        if (state.activeSymbol) loadBacktest(state.activeSymbol);
        else toast('Select a symbol first', 'warning');
    });

    // Close modals on Escape
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') {
            closeBulkModal();
            closeAlertsModal();
            closeAddPositionModal();
            closeClosePositionModal();
        }
    });

    // Save notes on Ctrl+S
    document.addEventListener('keydown', e => {
        if ((e.ctrlKey || e.metaKey) && e.key === 's') {
            e.preventDefault();
            if (state.activeSymbol) saveNotes();
        }
    });

    await loadSymbols();
    loadQuickStats();   // background — no await, updates badges when ready

    // Restore last active symbol
    const savedSymbol = localStorage.getItem('activeSymbol');
    const toSelect = savedSymbol && state.symbols.find(s => s.symbol === savedSymbol)
        ? savedSymbol
        : (state.symbols.length && state.symbols[0].last_fetch ? state.symbols[0].symbol : null);

    if (toSelect) {
        selectSymbol(toSelect);
    } else {
        showEmptyState();
    }

    // Start alert polling (every 60s)
    checkAlerts();
    alertPollTimer = setInterval(checkAlerts, 60000);

    // Check auto-refresh status
    checkAutoRefreshStatus();
    setInterval(checkAutoRefreshStatus, 30000);

    // Anomaly badges (refresh every 10 min)
    refreshAnomalyBadges();
    setInterval(refreshAnomalyBadges, 600000);
});

// ── localStorage helpers ──────────────────────────────────────
function saveToLocalStorage() {
    try {
        if (state.activeSymbol) localStorage.setItem('activeSymbol', state.activeSymbol);
    } catch (_) {}
}

function saveKamaToStorage() {
    try {
        const periods = Object.keys(kamaPeriods).map(Number).filter(p => p > 0);
        localStorage.setItem('kamaPeriods', JSON.stringify(periods));
    } catch (_) {}
}

function loadKamaFromStorage() {
    try {
        const raw = localStorage.getItem('kamaPeriods');
        if (raw) {
            const arr = JSON.parse(raw);
            if (Array.isArray(arr) && arr.length) return arr;
        }
    } catch (_) {}
    return [];
}

// ── Fundamentals ──────────────────────────────────────────────
async function loadFundamentals(symbol) {
    const strip = document.getElementById('fundamentals-strip');
    if (!strip) return;
    try {
        const res = await apiFetch(`${API}/fundamentals/${symbol}`);
        if (!res || !res.data) { strip.style.display = 'none'; return; }
        renderFundamentals(strip, res.data);
    } catch (_) {
        strip.style.display = 'none';
    }
}

function renderFundamentals(strip, data) {
    const fmtN = (v, dec = 2) => (v !== null && v !== undefined && Number.isFinite(Number(v)))
        ? Number(v).toFixed(dec) : null;
    const fmtB = v => {
        const n = Number(v);
        if (!v || !isFinite(n)) return null;
        if (n >= 1e12) return (n / 1e12).toFixed(2) + 'T';
        if (n >= 1e9)  return (n / 1e9).toFixed(2) + 'B';
        if (n >= 1e6)  return (n / 1e6).toFixed(2) + 'M';
        return n.toLocaleString();
    };
    const fmtPct = v => (v !== null && v !== undefined && Number.isFinite(Number(v)))
        ? (Number(v) * 100).toFixed(2) + '%' : null;

    const chips = [
        ['P/E',   fmtN(data.trailingPE)],
        ['Fwd PE', fmtN(data.forwardPE)],
        ['P/B',   fmtN(data.priceToBook)],
        ['P/S',   fmtN(data.priceToSalesTrailing12Months)],
        ['Mkt Cap', fmtB(data.marketCap)],
        ['Beta',  fmtN(data.beta)],
        ['52w Hi', fmtN(data.fiftyTwoWeekHigh)],
        ['52w Lo', fmtN(data.fiftyTwoWeekLow)],
        ['Div',   fmtPct(data.dividendYield)],
        ['EPS',   fmtN(data.trailingEps)],
        ['Rev Gr', fmtPct(data.revenueGrowth)],
        ['Margin', fmtPct(data.profitMargins)],
        ['D/E',   fmtN(data.debtToEquity)],
        ['ROE',   fmtPct(data.returnOnEquity)],
    ].filter(([, v]) => v !== null);

    if (!chips.length) { strip.style.display = 'none'; return; }

    strip.innerHTML = chips.map(([label, value]) => `
        <div class="fund-chip" title="${label}">
          <span class="fund-chip-label">${label}</span>
          <span class="fund-chip-value">${value}</span>
        </div>
    `).join('');
    strip.style.display = 'flex';
}

// ── Notes ─────────────────────────────────────────────────────
function loadNotes(symbol) {
    const btn      = document.getElementById('btn-notes-toggle');
    const textarea = document.getElementById('sym-notes');
    const savedEl  = document.getElementById('notes-saved');
    const sym      = state.symbols.find(s => s.symbol === symbol);
    if (textarea)  textarea.value = sym?.notes || '';
    if (savedEl)   savedEl.textContent = '';
    if (btn)       btn.style.display = 'inline-flex';
    // Close panel when switching symbols
    const panel = document.getElementById('notes-panel');
    if (panel) panel.style.display = 'none';
}

function toggleNotesPanel() {
    const panel = document.getElementById('notes-panel');
    if (!panel) return;
    const open = panel.style.display === 'none';
    panel.style.display = open ? 'block' : 'none';
    if (open) document.getElementById('sym-notes')?.focus();
}

async function saveNotes() {
    if (!state.activeSymbol) return;
    const textarea = document.getElementById('sym-notes');
    const savedEl  = document.getElementById('notes-saved');
    const text     = textarea?.value ?? '';
    try {
        await apiFetch(`${API}/symbols/${state.activeSymbol}/notes`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notes: text }),
        });
        // Update local state so it persists without full reload
        const sym = state.symbols.find(s => s.symbol === state.activeSymbol);
        if (sym) sym.notes = text;
        if (savedEl) {
            savedEl.textContent = 'Saved ✓';
            setTimeout(() => { if (savedEl) savedEl.textContent = ''; }, 2000);
        }
    } catch (e) {
        toast('Failed to save notes: ' + e.message, 'error');
    }
}

// ── Alerts ────────────────────────────────────────────────────
function openAlertsModal() {
    const modal    = document.getElementById('alerts-modal');
    const symInput = document.getElementById('alert-symbol-input');
    if (!modal) return;
    modal.style.display = 'flex';
    if (symInput && state.activeSymbol) symInput.value = state.activeSymbol;
    requestNotificationPermission();
    loadAlerts();
}

function closeAlertsModal() {
    const modal = document.getElementById('alerts-modal');
    if (modal) modal.style.display = 'none';
}

async function loadAlerts() {
    const list = document.getElementById('alerts-list');
    if (!list) return;
    try {
        const alerts = await apiFetch(`${API}/alerts`);
        renderAlerts(list, alerts);
    } catch (_) {
        list.innerHTML = '<div style="color:var(--text-muted)">Could not load alerts.</div>';
    }
}

function renderAlerts(container, alerts) {
    if (!alerts || !alerts.length) {
        container.innerHTML = '<div style="color:var(--text-muted); padding:8px 0;">No alerts set.</div>';
        return;
    }
    container.innerHTML = alerts.map(a => {
        const triggered = a.triggered_at
            ? `<span class="alert-triggered">✓ triggered ${a.triggered_at.slice(0,10)}</span>`
            : `<span class="alert-untriggered">pending</span>`;
        return `
          <div class="alert-row">
            <span class="alert-row-sym">${a.symbol}</span>
            <span class="alert-row-desc">${a.field} ${a.condition} ${a.threshold}</span>
            ${triggered}
            <button class="btn btn-ghost btn-sm" onclick="deleteAlert(${a.id})" title="Delete">×</button>
          </div>`;
    }).join('');
}

async function addAlert() {
    const symbol    = document.getElementById('alert-symbol-input')?.value.trim().toUpperCase();
    const field     = document.getElementById('alert-field-select')?.value;
    const condition = document.getElementById('alert-cond-select')?.value;
    const threshold = parseFloat(document.getElementById('alert-threshold-input')?.value);

    if (!symbol || !field || !condition || isNaN(threshold)) {
        toast('Fill in all alert fields', 'warning');
        return;
    }
    try {
        await apiFetch(`${API}/alerts`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol, field, condition, threshold }),
        });
        document.getElementById('alert-symbol-input').value   = '';
        document.getElementById('alert-threshold-input').value = '';
        toast(`Alert added for ${symbol}`, 'success', 2500);
        loadAlerts();
        checkAlerts();
    } catch (e) {
        toast('Add alert failed: ' + e.message, 'error');
    }
}

async function deleteAlert(id) {
    try {
        await apiFetch(`${API}/alerts/${id}`, { method: 'DELETE' });
        loadAlerts();
        checkAlerts();
    } catch (e) {
        toast('Delete alert failed: ' + e.message, 'error');
    }
}

// Track alert IDs already surfaced as browser notifications this session
const _notifiedAlertIds = new Set();

function _notifyAlert(a) {
    const dir = a.condition === 'above' ? '↑' : '↓';
    const cur = (a.current_value != null) ? a.current_value : '';
    const title = `🔔 ${a.symbol} ${a.field} ${dir} ${a.threshold}`;
    const body  = cur !== '' ? `Current: ${cur}` : '';
    if ('Notification' in window && Notification.permission === 'granted') {
        try { new Notification(title, { body, tag: `alert-${a.id}` }); } catch (_) {}
    }
    // Always show an in-app toast as fallback
    toast(`${a.symbol}: ${a.field} ${a.condition} ${a.threshold}`, 'warning', 6000);
}

async function checkAlerts() {
    try {
        const res = await apiFetch(`${API}/alerts/check`, { method: 'POST' });
        // Endpoint may return an array (newly triggered) or {triggered:[...]}
        const fired = Array.isArray(res) ? res : (res.triggered || []);
        for (const a of fired) {
            if (a && a.id != null && !_notifiedAlertIds.has(a.id)) {
                _notifiedAlertIds.add(a.id);
                _notifyAlert(a);
            }
        }
        const triggered = fired.length;
        const badge     = document.getElementById('alerts-badge');
        if (!badge) return;
        if (triggered > 0) {
            badge.textContent    = String(triggered);
            badge.style.display  = 'inline-block';
        } else {
            badge.style.display = 'none';
        }
    } catch (_) {}
}

// Ask for browser notification permission (called on first alert creation)
function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission().then(p => {
            if (p === 'granted') toast('Browser notifications enabled for alerts', 'success', 3000);
        });
    }
}

// ── Portfolio ─────────────────────────────────────────────────
async function loadPortfolio() {
    try {
        // Ensure we have live quote prices for unrealised P&L
        if (typeof loadQuickStats === 'function' && Object.keys(_wlStats || {}).length === 0) {
            await loadQuickStats();
        }
        const positions = await apiFetch(`${API}/positions`);
        renderPortfolio(positions);
    } catch (e) {
        toast('Portfolio load failed: ' + e.message, 'error');
    }
}

function renderPortfolio(positions) {
    const open   = positions.filter(p => !p.closed_at);
    const closed = positions.filter(p =>  p.closed_at);

    const fmtPx = v => (v != null && isFinite(v)) ? `$${Number(v).toFixed(2)}` : '--';
    const fmtPnl = (qty, entry, exit) => {
        if (qty == null || entry == null || exit == null) return { pnl: null, pct: null };
        const pnl = (exit - entry) * qty;
        const pct = (exit - entry) / entry;
        return { pnl, pct };
    };

    // Compute live unrealised P&L per open position using cached quote prices
    let totalCost = 0, totalValue = 0;
    const openLive = open.map(p => {
        const live  = (typeof _liveFor === 'function') ? _liveFor(p.symbol) : {};
        const price = live.price ?? null;
        const cost  = p.entry_price * p.qty;
        const value = price != null ? price * p.qty : null;
        const pnl   = (price != null) ? (price - p.entry_price) * p.qty : null;
        const pct   = (price != null && p.entry_price) ? (price / p.entry_price - 1) : null;
        if (value != null) { totalCost += cost; totalValue += value; }
        return { ...p, price, value, pnl, pct };
    });

    // Open positions table
    const openTbody = document.getElementById('portfolio-open-tbody');
    if (openTbody) {
        openTbody.innerHTML = openLive.length ? openLive.map(p => {
            const color = p.pnl == null ? '' : p.pnl >= 0 ? 'color:#22c55e' : 'color:#ef4444';
            const mae = p.max_adverse_excursion;
            // Highlight deep drawdowns (worse than −8%)
            const ddColor = mae == null ? 'color:var(--text-muted)'
                          : mae <= -8 ? 'color:#ef4444; font-weight:700'
                          : 'color:#ef4444';
            const ddText  = mae != null ? mae.toFixed(2) + '%' : '--';
            const ddWarn  = (mae != null && mae <= -8) ? ' ⚠️' : '';
            return `
          <tr>
            <td><strong style="cursor:pointer;" onclick="selectSymbol('${p.symbol}')">${p.symbol}</strong></td>
            <td>${p.qty}</td>
            <td>${fmtPx(p.entry_price)}</td>
            <td>${fmtPx(p.price)}</td>
            <td style="${color}">${p.pnl != null ? (p.pnl >= 0 ? '+' : '') + '$' + p.pnl.toFixed(2) : '--'}</td>
            <td style="${color}">${p.pct != null ? (p.pct >= 0 ? '+' : '') + (p.pct * 100).toFixed(2) + '%' : '--'}</td>
            <td style="${ddColor}">${ddText}${ddWarn}</td>
            <td>${p.opened_at || '--'}</td>
            <td style="white-space:nowrap;">
              <button class="btn btn-ghost btn-sm" onclick="openClosePositionModal(${p.id})">Close</button>
              <button class="btn btn-ghost btn-sm" style="color:#ef4444" onclick="deletePosition(${p.id})">×</button>
            </td>
          </tr>`;
        }).join('')
          : '<tr><td colspan="9" style="color:var(--text-muted); text-align:center; padding:16px;">No open positions</td></tr>';
    }

    _renderPortfolioHeatmap(openLive);

    // Closed positions table
    const closedTbody = document.getElementById('portfolio-closed-tbody');
    if (closedTbody) {
        closedTbody.innerHTML = closed.length ? closed.map(p => {
            const { pnl, pct } = fmtPnl(p.qty, p.entry_price, p.exit_price);
            const color = (pnl != null && pnl >= 0) ? 'color:#22c55e' : 'color:#ef4444';
            return `<tr>
              <td><strong>${p.symbol}</strong></td>
              <td>${p.qty}</td>
              <td>${fmtPx(p.entry_price)}</td>
              <td>${fmtPx(p.exit_price)}</td>
              <td style="${color}">${pnl != null ? '$' + pnl.toFixed(2) : '--'}</td>
              <td style="${color}">${pct != null ? (pct * 100).toFixed(2) + '%' : '--'}</td>
              <td>${p.opened_at || '--'}</td>
              <td>${p.closed_at?.slice(0,10) || '--'}</td>
            </tr>`;
        }).join('')
        : '<tr><td colspan="8" style="color:var(--text-muted); text-align:center; padding:16px;">No closed positions</td></tr>';
    }

    // KPI summary (open positions, live)
    document.getElementById('port-open-count').textContent = String(open.length);
    const pnlEl    = document.getElementById('port-pnl');
    const pnlPctEl = document.getElementById('port-pnl-pct');
    if (totalValue > 0) {
        const totalPnl = totalValue - totalCost;
        const totalPct = totalCost > 0 ? totalPnl / totalCost : 0;
        const col      = totalPnl >= 0 ? '#22c55e' : '#ef4444';
        if (pnlEl)    { pnlEl.textContent    = (totalPnl >= 0 ? '+' : '') + '$' + totalPnl.toFixed(2); pnlEl.style.color = col; }
        if (pnlPctEl) { pnlPctEl.textContent = (totalPct >= 0 ? '+' : '') + (totalPct * 100).toFixed(2) + '%'; pnlPctEl.style.color = col; }
    } else {
        if (pnlEl)    { pnlEl.textContent = '--'; pnlEl.style.color = ''; }
        if (pnlPctEl) { pnlPctEl.textContent = '--'; pnlPctEl.style.color = ''; }
    }
}

function _renderPortfolioHeatmap(openLive) {
    const card = document.getElementById('portfolio-heatmap-card');
    const grid = document.getElementById('portfolio-heatmap');
    if (!card || !grid) return;

    const withValue = openLive.filter(p => p.value != null && p.value > 0);
    if (!withValue.length) { card.style.display = 'none'; return; }
    card.style.display = '';

    const maxValue = Math.max(...withValue.map(p => p.value));
    // P&L %-driven background colour
    const bg = pct => {
        if (pct == null) return 'var(--bg-secondary)';
        const clamped = Math.max(-0.1, Math.min(0.1, pct)); // ±10% saturates
        const intensity = Math.abs(clamped) / 0.1;
        return pct >= 0
            ? `rgba(34,197,94,${(0.15 + intensity * 0.55).toFixed(2)})`
            : `rgba(239,68,68,${(0.15 + intensity * 0.55).toFixed(2)})`;
    };

    grid.innerHTML = withValue
        .sort((a, b) => b.value - a.value)
        .map(p => {
            // flex-grow proportional to value so bigger positions take more space
            const grow = Math.max(1, Math.round(p.value / maxValue * 12));
            return `<div class="port-heat-cell" style="flex-grow:${grow}; background:${bg(p.pct)};"
                         onclick="selectSymbol('${p.symbol}')"
                         title="${p.symbol} — $${p.value.toFixed(0)} (${p.pct != null ? (p.pct*100).toFixed(2)+'%' : 'n/a'})">
                <span class="port-heat-sym">${p.symbol}</span>
                <span class="port-heat-pct">${p.pct != null ? (p.pct >= 0 ? '+' : '') + (p.pct*100).toFixed(1) + '%' : '--'}</span>
            </div>`;
        }).join('');
}

function openAddPositionModal() {
    const modal   = document.getElementById('add-position-modal');
    const dateInp = document.getElementById('pos-date-input');
    if (!modal) return;
    modal.style.display = 'flex';
    if (dateInp) dateInp.value = new Date().toISOString().slice(0, 10);
    if (state.activeSymbol) {
        const symInp = document.getElementById('pos-symbol-input');
        if (symInp) symInp.value = state.activeSymbol;
    }
}

function closeAddPositionModal() {
    const modal = document.getElementById('add-position-modal');
    if (modal) modal.style.display = 'none';
}

async function submitAddPosition() {
    const symbol     = document.getElementById('pos-symbol-input')?.value.trim().toUpperCase();
    const qty        = parseFloat(document.getElementById('pos-qty-input')?.value);
    const entryPrice = parseFloat(document.getElementById('pos-entry-input')?.value);
    const openedAt   = document.getElementById('pos-date-input')?.value;
    const notes      = document.getElementById('pos-notes-input')?.value.trim();

    if (!symbol || isNaN(qty) || isNaN(entryPrice)) {
        toast('Symbol, Qty and Entry Price are required', 'warning');
        return;
    }
    try {
        await apiFetch(`${API}/positions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol, qty, entry_price: entryPrice, opened_at: openedAt, notes }),
        });
        closeAddPositionModal();
        toast(`Position added: ${symbol}`, 'success');
        loadPortfolio();
    } catch (e) {
        toast('Add position failed: ' + e.message, 'error');
    }
}

function openClosePositionModal(posId) {
    _closingPositionId = posId;
    const modal   = document.getElementById('close-position-modal');
    const dateInp = document.getElementById('close-date-input');
    if (!modal) return;
    modal.style.display = 'flex';
    if (dateInp) dateInp.value = new Date().toISOString().slice(0, 10);
}

function closeClosePositionModal() {
    _closingPositionId = null;
    const modal = document.getElementById('close-position-modal');
    if (modal) modal.style.display = 'none';
}

async function confirmClosePosition() {
    const id        = _closingPositionId;
    const exitPrice = parseFloat(document.getElementById('close-exit-input')?.value);
    const closedAt  = document.getElementById('close-date-input')?.value;
    if (!id || isNaN(exitPrice)) { toast('Enter exit price', 'warning'); return; }
    try {
        await apiFetch(`${API}/positions/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ exit_price: exitPrice, closed_at: closedAt }),
        });
        closeClosePositionModal();
        toast('Position closed', 'success');
        loadPortfolio();
    } catch (e) {
        toast('Close position failed: ' + e.message, 'error');
    }
}

async function deletePosition(id) {
    if (!confirm('Delete this position?')) return;
    try {
        await apiFetch(`${API}/positions/${id}`, { method: 'DELETE' });
        toast('Position deleted', 'warning');
        loadPortfolio();
    } catch (e) {
        toast('Delete failed: ' + e.message, 'error');
    }
}

// ── Correlations ──────────────────────────────────────────────
async function loadCorrelations() {
    const section = document.getElementById('correlation-section');
    const heatmap = document.getElementById('correlation-heatmap');
    const btn     = document.getElementById('btn-load-correlations');
    if (!section || !heatmap) return;
    if (btn) btn.disabled = true;
    try {
        const data = await apiFetch(`${API}/correlations`);
        renderCorrelationHeatmap(heatmap, data);
        section.style.display = 'block';
    } catch (e) {
        toast('Correlations failed: ' + e.message, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

function renderCorrelationHeatmap(container, data) {
    const { symbols, matrix } = data;
    if (!symbols || !matrix) { container.innerHTML = '<div style="color:var(--text-muted)">No data.</div>'; return; }

    // Colour: -1 = red, 0 = neutral, +1 = green
    const cellColor = v => {
        if (v === null || !isFinite(v)) return 'background:#1c2230; color:var(--text-dim)';
        const r = v >= 0
            ? `rgba(34,197,94,${Math.abs(v).toFixed(2)})`
            : `rgba(239,68,68,${Math.abs(v).toFixed(2)})`;
        const text = Math.abs(v) > 0.5 ? '#fff' : 'var(--text-muted)';
        return `background:${r}; color:${text}`;
    };

    const th = (txt) => `<th>${txt}</th>`;
    const header = `<tr>${th('')}${symbols.map(s => th(s)).join('')}</tr>`;
    const rows   = symbols.map((sym, i) => {
        const cells = symbols.map((_, j) => {
            const v = matrix[i]?.[j];
            const fmt = (v === null || !isFinite(v)) ? '–' : v.toFixed(2);
            return `<td style="${cellColor(v)}">${fmt}</td>`;
        }).join('');
        return `<tr><td class="heatmap-label">${sym}</td>${cells}</tr>`;
    }).join('');

    container.innerHTML = `<table class="heatmap-table"><thead>${header}</thead><tbody>${rows}</tbody></table>`;
}

// ── Auto-refresh status ───────────────────────────────────────
async function checkAutoRefreshStatus() {
    try {
        const res = await apiFetch(`${API}/auto-refresh/status`);
        const dot = document.getElementById('auto-refresh-dot');
        if (!dot) return;
        if (res.enabled) {
            dot.style.display = 'inline-block';
            dot.title = `Auto-refresh enabled (${res.time || ''})`;
        } else {
            dot.style.display = 'none';
        }
    } catch (_) {}
}

// ── Focus mode ────────────────────────────────────────────────
function toggleFocusMode() {
    const main = document.querySelector('.main');
    const btn  = document.getElementById('btn-focus-mode');
    if (!main) return;
    const on = main.classList.toggle('focus-mode');
    if (btn) btn.textContent = on ? '⊞' : '⊟';
    localStorage.setItem('focusMode', on ? '1' : '0');
}

// ── Theme toggle ──────────────────────────────────────────────
function toggleTheme() {
    const html = document.documentElement;
    const next = html.dataset.theme === 'light' ? 'dark' : 'light';
    html.dataset.theme = next;
    localStorage.setItem('theme', next);
    const btn = document.getElementById('btn-theme');
    if (btn) btn.textContent = next === 'light' ? '☀️' : '🌙';
}

function initTheme() {
    const saved = localStorage.getItem('theme') || 'dark';
    document.documentElement.dataset.theme = saved;
    const btn = document.getElementById('btn-theme');
    if (btn) btn.textContent = saved === 'light' ? '☀️' : '🌙';
}

// ── Watchlist sort ────────────────────────────────────────────
// ── Keyboard navigation ───────────────────────────────────────
function _handleGlobalKeydown(e) {
    // Ignore when typing in inputs
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    const syms = state.symbols;
    const cur  = state.activeSymbol;
    const curIdx = cur ? syms.findIndex(s => s.symbol === cur) : -1;

    if (e.key === 'j' || e.key === 'ArrowDown') {
        // Next symbol
        if (curIdx < syms.length - 1) selectSymbol(syms[curIdx + 1].symbol);
    } else if (e.key === 'k' || e.key === 'ArrowUp') {
        // Previous symbol
        if (curIdx > 0) selectSymbol(syms[curIdx - 1].symbol);
    } else if (e.key === '/') {
        e.preventDefault();
        document.getElementById('new-symbol-input')?.focus();
    } else if (e.key === 'r') {
        openRiskModal();
    } else if (e.key === 'n') {
        switchTab('news');
    } else if (e.key === '\\') {
        toggleFocusMode();
    }
}

// ── Anomaly badges in watchlist ───────────────────────────────
let _anomalyMap = {};

async function refreshAnomalyBadges() {
    try {
        const anomalies = await apiFetch(`${API}/anomalies`);
        _anomalyMap = {};
        for (const a of anomalies) _anomalyMap[a.symbol] = a.flags;
        renderSymbolList();
    } catch (_) {}
}
