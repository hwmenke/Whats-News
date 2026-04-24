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
    watchlistFilter: '',
};

let statsCharts = {};

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
    const res = await fetch(url, opts);
    console.log(`<< API Response: ${res.status} ${res.statusText}`);
    let data;
    try { data = await res.json(); } catch (_) { data = null; }
    if (!res.ok) {
        const err    = new Error(data?.message || data?.error || `HTTP ${res.status}`);
        err.code     = data?.code   || 'HTTP_' + res.status;
        err.hint     = data?.hint   || null;
        err.status   = res.status;
        console.error('!! API Error:', err.code, err.message);
        throw err;
    }
    return data;
}

function toastFromError(err, prefix = '') {
    const base = prefix ? `${prefix}: ${err.message}` : err.message;
    const msg  = err.hint ? `${base} — ${err.hint}` : base;
    toast(msg, 'error');
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
            // re-fetch if symbol loaded so the API param changes
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
                toastFromError(e, 'KAMA');
            }
        }
    };

    btn.addEventListener('click', addPeriod);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') addPeriod(); });
}

// ── Symbol Watchlist ─────────────────────────────────────────
async function loadSymbols() {
    try {
        state.symbols = await apiFetch(`${API}/symbols`);
        renderSymbolList();
    } catch (e) {
        toastFromError(e, 'Symbols');
    }
}

function _moveWatchlist(delta) {
    const visible = state.symbols.filter(s => _matchesFilter(s, state.watchlistFilter));
    if (!visible.length) return;
    const idx = visible.findIndex(s => s.symbol === state.activeSymbol);
    const next = visible[(idx + delta + visible.length) % visible.length];
    selectSymbol(next.symbol);
}

// Watchlist filter helper
function _matchesFilter(symEntry, needle) {
    if (!needle) return true;
    const n = needle.toLowerCase();
    return symEntry.symbol.toLowerCase().includes(n) ||
           (symEntry.name   || '').toLowerCase().includes(n) ||
           (symEntry.sector || '').toLowerCase().includes(n);
}

// Display symbol — converts internal "A~B" store format to "A/B" for ratios
function _displaySymbol(sym) {
    return sym.includes('~') ? sym.replace('~', '/') : sym;
}

function renderSymbolList() {
    const list = document.getElementById('symbol-list');
    list.innerHTML = '';

    const visible = state.symbols.filter(s => _matchesFilter(s, state.watchlistFilter));
    const countEl = document.getElementById('watchlist-count');
    if (countEl) {
        countEl.textContent = state.watchlistFilter
            ? `${visible.length}/${state.symbols.length}`
            : (state.symbols.length ? `${state.symbols.length}` : '');
    }

    if (!state.symbols.length) {
        list.innerHTML = '<div style="padding:14px;color:var(--text-dim);font-size:12px;">No symbols yet.</div>';
        return;
    }
    if (!visible.length) {
        list.innerHTML = '<div style="padding:14px;color:var(--text-dim);font-size:12px;">No matches.</div>';
        return;
    }

    visible.forEach(sym => {
        const isRatio = sym.symbol.includes('~');
        const item = document.createElement('div');
        item.className = 'symbol-item' + (state.activeSymbol === sym.symbol ? ' active' : '');
        item.dataset.symbol = sym.symbol;

        const ticker = document.createElement('span');
        ticker.className = 'sym-ticker' + (isRatio ? ' sym-ticker-ratio' : '');
        ticker.textContent = _displaySymbol(sym.symbol);

        const lastFetch = document.createElement('span');
        lastFetch.className = 'sym-change';
        lastFetch.style.fontSize  = '10px';
        lastFetch.style.color     = 'var(--text-dim)';
        lastFetch.textContent = sym.last_fetch ? '⟳ ' + sym.last_fetch.slice(0, 10) : 'Not fetched';

        const removeBtn = document.createElement('span');
        removeBtn.className  = 'sym-remove';
        removeBtn.textContent = '×';
        removeBtn.title       = 'Remove';
        removeBtn.addEventListener('click', e => { e.stopPropagation(); removeSymbol(sym.symbol); });

        item.appendChild(ticker);
        item.appendChild(lastFetch);
        item.appendChild(removeBtn);
        item.addEventListener('click', () => selectSymbol(sym.symbol));
        list.appendChild(item);
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
        toastFromError(e, 'Add symbol');
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
        toastFromError(e, 'Remove symbol');
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
        if (!silent) toastFromError(e, symbol);
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
        if (state.activeSymbol) await loadChartData(state.activeSymbol);
    } catch (e) {
        toastFromError(e, 'Refresh');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '⟳ Refresh All';
    }
}

// ── Symbol selection & chart loading ─────────────────────────
async function selectSymbol(symbol) {
    state.activeSymbol = symbol;
    persistence.save({ activeSymbol: symbol });
    renderSymbolList();
    // Update header immediately with symbol name
    const sym = state.symbols.find(s => s.symbol === symbol);
    const headerEl = document.getElementById('sym-title');
    if (headerEl) headerEl.textContent = _displaySymbol(symbol);
    if (state.activeTab === 'charts') {
        await loadChartData(symbol);
    } else if (state.activeTab === 'stats') {
        await loadStatsData(symbol);
    } else if (state.activeTab === 'trend') {
        await loadAdaptiveTrendData(symbol);
    } else if (state.activeTab === 'regression') {
        // Regression tab: just update header; user clicks Run to trigger
        showRegressionArea();
    } else if (state.activeTab === 'swirl') {
        if (typeof swLoad === 'function') swLoad();
    }
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
            // If it's a NO_DATA error, try auto-fetching
            if (e.code === 'NO_DATA' || e.status === 404) {
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

        const last = ohlcv[ohlcv.length - 1];
        const prev = ohlcv[ohlcv.length - 2];
        updateSymbolHeader(symbol, last, prev);
    } catch (e) {
        toastFromError(e, 'Stats');
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
            if (e.code === 'NO_DATA' || e.status === 404) {
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
            }
            throw e;
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
    } catch (e) {
        toastFromError(e, 'Chart');
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

    const method  = trendState.method;
    const isBoth  = trendState.freq === 'both';
    const freqD   = 'daily';
    const freqW   = 'weekly';
    const freq    = isBoth ? freqD : trendState.freq;

    // Build trend URL — append custom params if set
    const _trendUrl = (f) => {
        let url = `${API}/adaptive-trend/${symbol}?freq=${f}&method=${method}`;
        if (trendState.params) {
            url += '&' + Object.entries(trendState.params)
                .map(([k, v]) => `${k}=${v}`).join('&');
        }
        return url;
    };

    try {
        // In "Both" mode fetch daily + weekly concurrently
        const fetches = isBoth
            ? [
                apiFetch(`${API}/ohlcv/${symbol}?freq=${freqD}`),
                apiFetch(_trendUrl(freqD)),
                apiFetch(`${API}/ohlcv/${symbol}?freq=${freqW}`),
                apiFetch(_trendUrl(freqW)),
              ]
            : [
                apiFetch(`${API}/ohlcv/${symbol}?freq=${freq}`),
                apiFetch(_trendUrl(freq)),
              ];

        let results = await Promise.all(fetches).catch(async e => {
            if (e.code === 'NO_DATA' || e.status === 404) {
                toast(`No data for ${symbol}. Downloading…`, 'info');
                const ok = await fetchSymbolData(symbol);
                if (!ok) throw e;
                await loadSymbols();
                return Promise.all(fetches);
            }
            throw e;
        });

        if (isBoth) {
            const [ohlcv, trendData, ohlcvW, trendDataW] = results;
            buildTrendCharts();
            buildWeeklyTrendCharts();
            loadTrendData(trendData, ohlcv);
            loadWeeklyTrendData(trendDataW, ohlcvW);

            const last = ohlcv[ohlcv.length - 1];
            const prev = ohlcv[ohlcv.length - 2];
            updateSymbolHeader(symbol, last, prev);
        } else {
            const [ohlcv, trendData] = results;
            buildTrendCharts();
            loadTrendData(trendData, ohlcv);

            const last = ohlcv[ohlcv.length - 1];
            const prev = ohlcv[ohlcv.length - 2];
            updateSymbolHeader(symbol, last, prev);
        }
    } catch (e) {
        toastFromError(e, 'Trend');
    } finally {
        if (loadingEl) loadingEl.style.display = 'none';
    }
}

// ── UI helpers ───────────────────────────────────────────────

const _AREA_DISPLAY = {
    'empty-state':       'flex',
    'chart-area':        'flex',
    'stats-area':        'block',
    'trend-area':        'flex',
    'scanner-area':      'flex',
    'data-manager-area': 'flex',
    'regression-area':   'flex',
    'strategy-area':     'flex',
    'swirl-area':        'flex',
    'portfolio-area':    'flex',
    'knn-area':          'flex',
    'regime-area':       'flex',
    'momentum-area':     'flex',
    'seasonality-area':  'flex',
    'factor-model-area': 'flex',
};

function _showOnly(activeId) {
    for (const [id, disp] of Object.entries(_AREA_DISPLAY)) {
        const el = document.getElementById(id);
        if (el) el.style.display = (id === activeId) ? disp : 'none';
    }
    const tabBar = document.querySelector('.tab-bar');
    if (tabBar) tabBar.style.display = (activeId === 'chart-area') ? '' : 'none';
}

function showEmptyState()      { _showOnly('empty-state'); }
function showChartArea()       { _showOnly('chart-area'); }

function showLoadingOverlay(show) {
    document.getElementById('chart-loading').style.display = show ? 'flex' : 'none';
}

// ── Tab Switching ─────────────────────────────────────────────
async function switchTab(tabId) {
    state.activeTab = tabId;
    persistence.save({ activeTab: tabId });

    // Update buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.id === `tab-${tabId}`);
    });

    if (tabId === 'charts') {
        showChartArea();
        if (state.activeSymbol) loadChartData(state.activeSymbol);
    } else if (tabId === 'stats') {
        showStatsArea();
        if (state.activeSymbol) loadStatsData(state.activeSymbol);
    } else if (tabId === 'trend') {
        showTrendArea();
        if (state.activeSymbol) loadAdaptiveTrendData(state.activeSymbol);
    } else if (tabId === 'scanner') {
        showScannerArea();
        loadScannerData();
    } else if (tabId === 'data-manager') {
        showDataManagerArea();
        initDataManager();
    } else if (tabId === 'regression') {
        showRegressionArea();
        if (typeof initRegression === 'function') initRegression();
    } else if (tabId === 'strategy') {
        showStrategyArea();
        if (typeof initStrategyTester === 'function') initStrategyTester();
    } else if (tabId === 'swirl') {
        showSwirlogramArea();
        if (typeof initSwirligram === 'function') initSwirligram();
    } else if (tabId === 'portfolio') {
        showPortfolioArea();
        if (typeof initPortfolioTester === 'function') initPortfolioTester();
    } else if (tabId === 'knn') {
        showKnnArea();
        if (typeof initKnnForecast === 'function') initKnnForecast();
    } else if (tabId === 'regime') {
        showRegimeArea();
        if (typeof initRegime === 'function') initRegime();
    } else if (tabId === 'momentum') {
        showMomentumArea();
        if (typeof initMomentumRanker === 'function') initMomentumRanker();
    } else if (tabId === 'seasonality') {
        showSeasonalityArea();
        if (typeof initSeasonality === 'function') initSeasonality();
    } else if (tabId === 'factor-model') {
        showFactorModelArea();
        if (typeof initFactorModel === 'function') initFactorModel();
    }
}

function showStatsArea()       { _showOnly('stats-area'); }
function showTrendArea()       { _showOnly('trend-area'); }
function showScannerArea()     { _showOnly('scanner-area'); }
function showDataManagerArea() { _showOnly('data-manager-area'); }
function showRegressionArea()  { _showOnly('regression-area'); }
function showStrategyArea()    { _showOnly('strategy-area'); }
function showSwirlogramArea()  { _showOnly('swirl-area'); }
function showPortfolioArea()   { _showOnly('portfolio-area'); }
function showKnnArea()         { _showOnly('knn-area'); }
function showRegimeArea()      { _showOnly('regime-area'); }
function showMomentumArea()    { _showOnly('momentum-area'); }
function showSeasonalityArea() { _showOnly('seasonality-area'); }
function showFactorModelArea() { _showOnly('factor-model-area'); }

// ── Ratio Symbol UI ───────────────────────────────────────────
function toggleRatioForm() {
    const form = document.getElementById('ratio-form');
    if (!form) return;
    const visible = form.style.display !== 'none';
    form.style.display = visible ? 'none' : 'flex';
    if (!visible) document.getElementById('ratio-sym-a')?.focus();
}

async function addRatioSymbol() {
    const symA = document.getElementById('ratio-sym-a')?.value.trim().toUpperCase();
    const symB = document.getElementById('ratio-sym-b')?.value.trim().toUpperCase();
    if (!symA || !symB) { toast('Enter both symbols for the ratio', 'warning'); return; }
    if (symA === symB)  { toast('Symbols must be different', 'warning'); return; }

    const btn = document.getElementById('btn-ratio-add');
    if (btn) btn.disabled = true;
    toast(`Computing ${symA}/${symB} ratio…`, 'info', 5000);

    try {
        const result = await apiFetch(`${API}/fetch-ratio`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ sym_a: symA, sym_b: symB }),
        });
        toast(`${symA}/${symB}: ${result.daily_rows} daily bars stored`, 'success');
        document.getElementById('ratio-sym-a').value = '';
        document.getElementById('ratio-sym-b').value = '';
        toggleRatioForm();
        await loadSymbols();
        selectSymbol(result.symbol);
    } catch (e) {
        toastFromError(e, 'Ratio');
    } finally {
        if (btn) btn.disabled = false;
    }
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

    // 1. RSI Deciles 1D
    statsCharts['rsi1d'] = updateOrCreate('stats.rsi1d', document.getElementById('chart-rsi-1d'), {
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
    statsCharts['kamaDist1d'] = updateOrCreate('stats.kamaDist1d', document.getElementById('chart-kama-dist-1d'), {
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
    statsCharts['rsi5d'] = updateOrCreate('stats.rsi5d', document.getElementById('chart-rsi-5d'), {
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
    statsCharts['kamaDist5d'] = updateOrCreate('stats.kamaDist5d', document.getElementById('chart-kama-dist-5d'), {
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
    statsCharts['dist'] = updateOrCreate('stats.dist', document.getElementById('chart-dist'), {
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
    statsCharts['season'] = updateOrCreate('stats.season', document.getElementById('chart-seasonality'), {
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
    statsCharts['kamaCross'] = updateOrCreate('stats.kamaCross', document.getElementById('chart-kama-cross'), {
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
    statsCharts['kamaCrossCounts'] = updateOrCreate('stats.kamaCrossCounts', document.getElementById('chart-kama-cross-counts'), {
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

// ── Boot ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    startClock();

    // Seed default KAMA periods
    DEFAULT_KAMA_PERIODS.forEach(p => addKamaPeriod(p));
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

    // Close bulk modal on Escape
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeBulkModal();
    });

    // Watchlist filter
    const wlSearch = document.getElementById('watchlist-search');
    if (wlSearch) {
        let _filterTimer = null;
        wlSearch.addEventListener('input', () => {
            clearTimeout(_filterTimer);
            _filterTimer = setTimeout(() => {
                state.watchlistFilter = wlSearch.value.trim();
                renderSymbolList();
            }, 150);
        });
        wlSearch.addEventListener('keydown', e => {
            if (e.key === 'Enter') {
                const visible = state.symbols.filter(s => _matchesFilter(s, state.watchlistFilter));
                if (visible.length) selectSymbol(visible[0].symbol);
            } else if (e.key === 'Escape') {
                wlSearch.value = '';
                state.watchlistFilter = '';
                renderSymbolList();
                wlSearch.blur();
            }
        });
    }

    // Keyboard shortcuts
    const TAB_ORDER = ['charts','stats','trend','scanner','data-manager','regression','strategy','swirl','portfolio','knn'];
    TAB_ORDER.forEach((id, i) =>
        registerShortcut({ key: String(i + 1), handler: () => switchTab(id), description: `Go to ${id}` })
    );
    registerShortcut({ key: 'j', handler: () => _moveWatchlist(+1), description: 'Next symbol' });
    registerShortcut({ key: 'k', handler: () => _moveWatchlist(-1), description: 'Previous symbol' });
    registerShortcut({ key: 'r', handler: () => { if (state.activeSymbol) switchTab(state.activeTab); }, description: 'Reload view' });
    registerShortcut({ key: '/', handler: () => document.getElementById('watchlist-search')?.focus(), description: 'Focus watchlist search' });
    registerShortcut({ key: '?', shift: true, handler: showShortcutsHelp, description: 'Show this help' });

    await loadSymbols();

    // Load regime badge async (non-blocking)
    if (typeof loadRegimeBadge === 'function') loadRegimeBadge('SPY');

    const saved = persistence.load();
    const savedSym = saved?.activeSymbol;
    const savedTab = saved?.activeTab || 'charts';

    // Restore active tab button highlight first
    const tabBtn = document.getElementById(`tab-${savedTab}`);
    if (tabBtn) {
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        tabBtn.classList.add('active');
    }
    state.activeTab = savedTab;

    // Restore symbol only if it's still in the watchlist
    const validSym = savedSym && state.symbols.find(s => s.symbol === savedSym);
    if (validSym) {
        await selectSymbol(savedSym);
    } else if (state.symbols.length && state.symbols[0].last_fetch) {
        await selectSymbol(state.symbols[0].symbol);
    } else {
        showEmptyState();
    }
});
