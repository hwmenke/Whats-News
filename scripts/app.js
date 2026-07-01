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
let backtestEquityChart = null;
let _ppLoaded = false;

// ── Data freshness banner ─────────────────────────────────────
function showFreshnessBanner(bannerId, latestDateStr, refreshCall) {
    const el = document.getElementById(bannerId);
    if (!el) return;
    if (!latestDateStr) { el.style.display = 'none'; return; }
    const latest   = new Date(latestDateStr);
    const today    = new Date(); today.setHours(0,0,0,0);
    const diffDays = Math.floor((today - latest) / 86400000);
    const dow      = today.getDay();
    const stale    = !(dow === 0 || dow === 6) && diffDays > 1;
    const label    = stale
        ? `<span class="dfb-stale">⚠ Data as of ${latestDateStr} — ${diffDays}d old</span>`
        : `<span class="dfb-fresh">✓ Data current as of ${latestDateStr}</span>`;
    el.innerHTML   = `<span class="dfb-label">${label}</span>` +
        (refreshCall ? `<button class="dfb-refresh" onclick="${refreshCall}">⟳ Refresh Data</button>` : '');
    el.style.display = 'flex';
    el.classList.toggle('fresh', !stale);
}

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
// ── UI preferences (accent / density / scale / tab visibility) ───────────────

const UI_PREFS_KEY = 'ui_prefs_v1';

function loadUiPrefs() {
    try { return JSON.parse(localStorage.getItem(UI_PREFS_KEY) || '{}'); }
    catch (_) { return {}; }
}

function saveUiPrefs(prefs) {
    try { localStorage.setItem(UI_PREFS_KEY, JSON.stringify(prefs)); } catch (_) {}
    applyUiPrefs();
}

function applyUiPrefs() {
    const p    = loadUiPrefs();
    const body = document.body;

    // Accent color — overrides the amber design tokens app-wide
    body.classList.remove('accent-blue', 'accent-green', 'accent-purple', 'accent-cyan');
    if (p.accent && p.accent !== 'amber') body.classList.add(`accent-${p.accent}`);

    // Density
    body.classList.toggle('ui-compact', p.density === 'compact');

    // UI scale (zoom is supported by all modern browsers incl. Firefox 126+)
    body.style.zoom = (p.scale && p.scale !== 100) ? String(p.scale / 100) : '';

    // Tab visibility
    const hidden = new Set(p.hiddenTabs || []);
    document.querySelectorAll('.tab-btn').forEach(btn => {
        const id = (btn.id || '').replace(/^tab-/, '');
        if (!id || id === 'charts' || id === 'settings') return;  // never hideable
        btn.style.display = hidden.has(id) ? 'none' : '';
    });
}

// ── Macro event proximity chip (status bar) ───────────────────────────────────

async function _loadMacroChip() {
    const el = document.getElementById('sb-macro');
    if (!el) return;
    try {
        const events = await apiFetch(`${API}/calendar?days_past=0&days_fwd=10`);
        const today  = new Date().toISOString().slice(0, 10);
        const next   = (events || []).find(e =>
            e.date >= today && e.importance >= 3 && e.category !== 'earnings');
        if (!next) { el.style.display = 'none'; return; }
        const days = Math.round((new Date(next.date) - new Date(today)) / 86400000);
        const txt  = days === 0 ? 'today' : `${days}d`;
        el.style.display = '';
        el.className = `sb-macro ${days <= 1 ? 'sb-macro-hot' : days <= 3 ? 'sb-macro-warn' : ''}`;
        el.innerHTML = `⚡ ${next.type} ${txt}`;
        el.title = `${next.label} — ${next.date}${next.approx ? ' (estimated)' : ''}. Click for calendar.`;
    } catch (_) {
        el.style.display = 'none';
    }
}

async function _loadOpenRiskBadge() {
    const el = document.getElementById('sb-open-risk');
    if (!el) return;
    try {
        const d = await apiFetch(`${API}/open-risk`);
        if (!d.open_count) { el.style.display = 'none'; return; }
        const fr   = d.total_float_r;
        const sign = fr >= 0 ? '+' : '';
        const cls  = fr >= 0 ? 'sb-risk-pos' : 'sb-risk-neg';
        el.style.display = '';
        el.innerHTML = `<span class="sb-label">OPEN</span>
            <span class="sb-item">${d.open_count}</span>
            <span class="sb-sep"></span>
            <span class="sb-label">ΣR</span>
            <span class="sb-item ${cls}" title="Floating R across ${d.open_count} open trade${d.open_count === 1 ? '' : 's'}">${sign}${fr.toFixed(1)}</span>`;
    } catch (_) {
        if (el) el.style.display = 'none';
    }
}

function setConnStatus(ok) {
    const dot = document.querySelector('.status-dot');
    if (dot) {
        dot.classList.toggle('offline', !ok);
        dot.title = ok ? 'Connected' : 'Server unreachable';
    }
    const conn = document.getElementById('sb-conn');
    if (conn) {
        conn.textContent = ok ? 'LIVE' : 'OFFLINE';
        conn.classList.toggle('sb-offline', !ok);
    }
}

async function apiFetch(url, opts = {}) {
    let res;
    try {
        res = await fetch(url, opts);
    } catch (e) {
        setConnStatus(false);
        const err  = new Error('Server unreachable');
        err.code   = 'NETWORK';
        err.hint   = 'Is the dashboard server running?';
        err.status = 0;
        throw err;
    }
    setConnStatus(true);
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
        const [syms, stats] = await Promise.all([
            apiFetch(`${API}/symbols`),
            apiFetch(`${API}/symbols/quick-stats`).catch(() => []),
        ]);
        const statsMap = Object.fromEntries((stats || []).map(s => [s.symbol, s]));
        state.symbols = syms.map(s => ({ ...s, ...(statsMap[s.symbol] || {}) }));
        state.symbolsLoaded = true;
        renderSymbolList();
        _refreshFreshnessBanners();
        if (typeof updateTickerTape  === 'function') updateTickerTape();
        if (typeof _sbSetSymbolCount === 'function') _sbSetSymbolCount(state.symbols.length);
    } catch (e) {
        toastFromError(e, 'Symbols');
    }
}

function _refreshFreshnessBanners() {
    const dates = state.symbols.map(s => s.last_fetch).filter(Boolean).sort();
    const latest = dates.length ? dates[dates.length - 1].slice(0, 10) : null;
    const rc = "document.getElementById('btn-refresh-all')?.click()";
    ['scanner-freshness','momentum-freshness','regime-freshness','dashboard-freshness']
        .forEach(id => showFreshnessBanner(id, latest, rc));
    if (typeof _sbSetFreshness === 'function') _sbSetFreshness(latest);
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
        if (sym.chg != null) item.classList.add(sym.chg >= 0 ? 'si-up' : 'si-down');
        item.dataset.symbol = sym.symbol;

        // Left column: ticker + sector / fetch date
        const left = document.createElement('div');
        left.className = 'si-col si-col-left';

        const ticker = document.createElement('span');
        ticker.className = 'sym-ticker' + (isRatio ? ' sym-ticker-ratio' : '');
        ticker.textContent = _displaySymbol(sym.symbol);
        left.appendChild(ticker);

        if (sym.sector && !isRatio) {
            const secChip = document.createElement('span');
            secChip.className = 'sym-sector-chip';
            secChip.textContent = sym.sector.length > 14 ? sym.sector.slice(0, 13) + '…' : sym.sector;
            secChip.title = sym.sector;
            left.appendChild(secChip);
        } else if (sym.last_fetch && sym.chg == null) {
            const fetchSpan = document.createElement('span');
            fetchSpan.className = 'sym-fetch-date';
            fetchSpan.textContent = sym.last_fetch.slice(0, 10);
            left.appendChild(fetchSpan);
        }

        // Middle: 20-bar sparkline
        if (Array.isArray(sym.spark) && sym.spark.length > 1 && typeof sparkSVG === 'function') {
            item.appendChild(left);
            item.appendChild(sparkSVG(sym.spark));
        } else {
            item.appendChild(left);
            const gap = document.createElement('span');
            gap.className = 'si-spark si-spark-empty';
            item.appendChild(gap);
        }

        // Right column: price + daily change
        const right = document.createElement('div');
        right.className = 'si-col si-col-right';

        if (sym.price != null) {
            const px = document.createElement('span');
            px.className = 'si-price';
            px.textContent = sym.price >= 1000 ? sym.price.toFixed(0) : sym.price.toFixed(2);
            right.appendChild(px);
        }
        if (sym.chg != null) {
            const chgSpan = document.createElement('span');
            chgSpan.className = 'sym-chg ' + (sym.chg >= 0 ? 'sym-chg-pos' : 'sym-chg-neg');
            chgSpan.textContent = (sym.chg >= 0 ? '+' : '') + sym.chg.toFixed(2) + '%';
            right.appendChild(chgSpan);
        }
        item.appendChild(right);

        const removeBtn = document.createElement('span');
        removeBtn.className  = 'sym-remove';
        removeBtn.textContent = '×';
        removeBtn.title       = 'Remove';
        removeBtn.addEventListener('click', e => { e.stopPropagation(); removeSymbol(sym.symbol); });

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
    const headerEl = document.getElementById('sym-title');
    if (headerEl) headerEl.textContent = _displaySymbol(symbol);
    if (typeof _extrasOnSymbolLoad === 'function') _extrasOnSymbolLoad(symbol);
    await TAB_DEFS[state.activeTab]?.onSymbol?.(symbol);
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
        updateSymbolHeader(symbol, last, prev, dailyOhlcv);
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
        // In "Both" mode fetch daily + weekly concurrently.
        // limit=1500 matches the adaptive-trend computation window — with the
        // default 500 the older trend markers fall outside the candle range
        // and lightweight-charts piles them up on the leftmost bar.
        const fetches = isBoth
            ? [
                apiFetch(`${API}/ohlcv/${symbol}?freq=${freqD}&limit=1500`),
                apiFetch(_trendUrl(freqD)),
                apiFetch(`${API}/ohlcv/${symbol}?freq=${freqW}&limit=1500`),
                apiFetch(_trendUrl(freqW)),
              ]
            : [
                apiFetch(`${API}/ohlcv/${symbol}?freq=${freq}&limit=1500`),
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
            updateSymbolHeader(symbol, last, prev, ohlcv);
        } else {
            const [ohlcv, trendData] = results;
            buildTrendCharts();
            loadTrendData(trendData, ohlcv);

            const last = ohlcv[ohlcv.length - 1];
            const prev = ohlcv[ohlcv.length - 2];
            updateSymbolHeader(symbol, last, prev, freq === 'daily' ? ohlcv : null);
        }
    } catch (e) {
        toastFromError(e, 'Trend');
    } finally {
        if (loadingEl) loadingEl.style.display = 'none';
    }
}

// ── UI helpers ───────────────────────────────────────────────

// Single source of truth for every tab: its content area, the display
// mode that area needs, what to run when the tab is shown, and (for
// symbol-driven tabs) what to run when the active symbol changes.
const TAB_DEFS = {
    'charts': {
        area: 'chart-area', display: 'flex',
        onShow:   () => state.activeSymbol ? loadChartData(state.activeSymbol) : showEmptyState(),
        onSymbol: sym => loadChartData(sym),
    },
    'stats': {
        area: 'stats-area', display: 'block',
        onShow:   () => state.activeSymbol ? loadStatsData(state.activeSymbol) : showEmptyState(),
        onSymbol: sym => loadStatsData(sym),
    },
    'trend': {
        area: 'trend-area', display: 'flex',
        onShow: () => {
            if (!state.activeSymbol) { showEmptyState(); return; }
            loadAdaptiveTrendData(state.activeSymbol);
            if (typeof initSwingWidget === 'function') initSwingWidget();
        },
        onSymbol: sym => loadAdaptiveTrendData(sym),
    },
    'scanner': {
        area: 'scanner-area', display: 'flex',
        onShow: () => (typeof initScanner === 'function') ? initScanner() : loadScannerData(),
    },
    'data-manager': { area: 'data-manager-area', display: 'flex', onShow: () => initDataManager() },
    'swirl': {
        area: 'swirl-area', display: 'flex',
        onShow:   () => { if (typeof initSwirligram === 'function') initSwirligram(); },
        onSymbol: () => { if (typeof swLoad === 'function') swLoad(); },
    },
    'portfolio':   { area: 'portfolio-area',   display: 'flex', onShow: () => { if (typeof initPortfolioTester === 'function') initPortfolioTester(); } },
    'regime':      { area: 'regime-area',      display: 'flex', onShow: () => { if (typeof initRegime === 'function') initRegime(); } },
    'momentum':    { area: 'momentum-area',    display: 'flex', onShow: () => { if (typeof initMomentumRanker === 'function') initMomentumRanker(); } },
    'vol-momentum': { area: 'vol-momentum-area', display: 'flex', onShow: () => { if (typeof initVolMomentum === 'function') initVolMomentum(); } },
    'seasonality': { area: 'seasonality-area', display: 'flex', onShow: () => { if (typeof initSeasonality === 'function') initSeasonality(); } },
    'newsletter':  { area: 'newsletter-area',  display: 'flex', onShow: () => { if (typeof initNewsletter === 'function') initNewsletter(); } },
    'news':        { area: 'news-area',        display: 'flex', onShow: () => { if (typeof initNews === 'function') initNews(); } },
    'sector':      { area: 'dashboard-area',    display: 'flex', onShow: () => { if (typeof initMarketDashboard === 'function') initMarketDashboard(); } },
    'calendar':    { area: 'calendar-area',    display: 'flex', onShow: () => { if (typeof initCalendar === 'function') initCalendar(); } },
    'journal':     { area: 'journal-area',     display: 'flex', onShow: () => { _switchJournalTab('log'); if (typeof initJournal === 'function') initJournal(); } },
    'analytics':   { area: 'journal-area',     display: 'flex', onShow: () => { _switchJournalTab('analytics'); if (typeof initAnalytics === 'function') initAnalytics(); } },
    'compare': {
        area: 'compare-area', display: 'flex',
        onShow:   () => { if (typeof initCompare === 'function') initCompare(); },
        onSymbol: () => { if (typeof runCompare === 'function') runCompare(); },
    },
    'mtf': {
        area: 'mtf-area', display: 'flex',
        onShow:   () => { if (typeof initMtf === 'function') initMtf(); },
        onSymbol: sym => { if (typeof loadMultiTF === 'function') loadMultiTF(sym); },
    },
    'process':   { area: 'dashboard-area', display: 'flex', onShow: () => { if (typeof initMarketDashboard === 'function') initMarketDashboard(); } },
    'risk-calc': { area: 'risk-calc-area', display: 'flex', onShow: () => { if (typeof initRiskCalc === 'function') initRiskCalc(); } },
    'dashboard': { area: 'dashboard-area', display: 'flex', onShow: () => { if (typeof initMarketDashboard === 'function') initMarketDashboard(); } },
    'routine':   { area: 'routine-area',   display: 'flex', onShow: () => { if (typeof initRoutine  === 'function') initRoutine();  } },
    'settings':  { area: 'settings-area',  display: 'flex', onShow: () => { if (typeof initSettings === 'function') initSettings(); } },
    'knn': {
        area: 'knn-area', display: 'block',
        onShow:   () => { if (state.activeSymbol) loadKNN(state.activeSymbol); },
        onSymbol: sym => loadKNN(sym),
    },
    'backtest': {
        area: 'backtest-area', display: 'block',
        onShow:   () => { if (state.activeSymbol) loadBacktest(state.activeSymbol); },
        onSymbol: sym => loadBacktest(sym),
    },
    'phase-plane': { area: 'phase-plane-area', display: 'flex', onShow: () => loadPhasePlane(false) },
    'social':      { area: 'social-area',      display: 'flex', onShow: () => { if (typeof loadSocialTrends === 'function') loadSocialTrends(); } },
};

function _showOnly(activeId) {
    const empty = document.getElementById('empty-state');
    if (empty) empty.style.display = (activeId === 'empty-state') ? 'flex' : 'none';
    for (const def of Object.values(TAB_DEFS)) {
        const el = document.getElementById(def.area);
        if (el) el.style.display = (def.area === activeId) ? def.display : 'none';
    }
    const tabBar = document.querySelector('.tab-bar');
    if (tabBar) tabBar.style.display = (activeId === 'chart-area') ? '' : 'none';
}

function showEmptyState()      { _showOnly('empty-state'); }
function showChartArea()       { _showOnly('chart-area'); }
function showStatsArea()       { _showOnly('stats-area'); }
function showTrendArea()       { _showOnly('trend-area'); }
function showScannerArea()     { _showOnly('scanner-area'); }
function showDataManagerArea() { _showOnly('data-manager-area'); }

// ── Sidebar collapse ──────────────────────────────────────────
function toggleSidebar() {
    const appEl = document.querySelector('.app');
    const btn   = document.getElementById('sidebar-collapse-btn');
    const hidden = appEl.classList.toggle('sidebar-hidden');
    if (btn) btn.textContent = hidden ? '›' : '‹';
    try { localStorage.setItem('sidebar_hidden', hidden ? '1' : '0'); } catch (_) {}
    // Fire a resize event after the CSS transition completes so ResizeObservers
    // on chart containers pick up the new width.
    setTimeout(() => window.dispatchEvent(new Event('resize')), 280);
}

function showLoadingOverlay(show) {
    document.getElementById('chart-loading').style.display = show ? 'flex' : 'none';
}

// ── Tab Switching ─────────────────────────────────────────────
async function switchTab(tabId) {
    const def = TAB_DEFS[tabId];
    if (!def) return;

    state.activeTab = tabId;
    persistence.save({ activeTab: tabId });

    document.querySelectorAll('.tab-btn').forEach(btn => {
        const active = btn.id === `tab-${tabId}`;
        btn.classList.toggle('active', active);
        // The nav scrolls horizontally — keep the active tab visible
        if (active) btn.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    });

    _showOnly(def.area);
    await def.onShow?.();
}

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
    const pctColor = v => (v !== null && Number.isFinite(v) && v >= 0) ? '#4DAF88' : '#E05252';

    const kamaColors = {
        '10': '#029FD5',
        '20': '#F68B42',
        '50': '#9B89C4',
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

    // Common Chart.js options — 538 style (font defaults set globally in chart_helpers.js)
    const baseChartOpts = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
            y: { grid: { color: 'rgba(255,255,255,0.06)' }, ticks: { color: '#9aafc4' } },
            x: { grid: { display: false }, ticks: { color: '#9aafc4' } }
        }
    };
    const distanceChartOptions = {
        ...baseChartOpts,
        plugins: {
            legend: {
                display: true,
                labels: { usePointStyle: true, boxWidth: 10 }
            }
        }
    };
    const crossChartOptions = {
        ...baseChartOpts,
        plugins: {
            legend: {
                display: true,
                labels: { usePointStyle: true, boxWidth: 10 }
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
    statsCharts['kamaDist1d'] = updateOrCreate('stats.kamaDist1d', document.getElementById('chart-kama-dist-1d'), {
        type: 'line',
        data: {
            labels: Array.from({ length: 10 }, (_, i) => `D${i + 1}`),
            datasets: Object.entries(data.kama_distance_analysis?.fwd_1d || {}).map(([period, points]) => ({
                label: `KAMA ${period}`,
                data: alignedDeciles(points),
                borderColor: kamaColors[period] || '#029FD5',
                backgroundColor: kamaColors[period] || '#029FD5',
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
    statsCharts['kamaDist5d'] = updateOrCreate('stats.kamaDist5d', document.getElementById('chart-kama-dist-5d'), {
        type: 'line',
        data: {
            labels: Array.from({ length: 10 }, (_, i) => `D${i + 1}`),
            datasets: Object.entries(data.kama_distance_analysis?.fwd_5d || {}).map(([period, points]) => ({
                label: `KAMA ${period}`,
                data: alignedDeciles(points),
                borderColor: kamaColors[period] || '#029FD5',
                backgroundColor: kamaColors[period] || '#029FD5',
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
    statsCharts['dist'] = updateOrCreate('stats.dist', document.getElementById('chart-dist'), {
        type: 'bar',
        data: {
            labels: data.distribution.map(d => (d.bin * 100).toFixed(1) + '%'),
            datasets: [{
                data: data.distribution.map(d => d.count),
                backgroundColor: 'rgba(2,159,213,0.55)',
                borderColor: '#029FD5',
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
    statsCharts['season'] = updateOrCreate('stats.season', document.getElementById('chart-seasonality'), {
        type: 'bar',
        data: {
            labels: data.seasonality.map(d => monthNames[d.month-1]),
            datasets: [{
                data: data.seasonality.map(d => pctValue(d.value)),
                backgroundColor: data.seasonality.map(d => Number.isFinite(d.value) && d.value >= 0 ? 'rgba(77,175,136,0.65)' : 'rgba(224,82,82,0.65)'),
            }]
        },
        options: baseChartOpts
    });

    // 4b. KAMA cross forward returns
    statsCharts['kamaCross'] = updateOrCreate('stats.kamaCross', document.getElementById('chart-kama-cross'), {
        type: 'bar',
        data: {
            labels: (data.kama_cross_analysis || []).map(d => d.label),
            datasets: [
                {
                    label: '1D Fwd Return',
                    data: (data.kama_cross_analysis || []).map(d => pctValue(d.fwd_1d)),
                    backgroundColor: 'rgba(2,159,213,0.60)',
                    borderColor: '#029FD5',
                    borderWidth: 1,
                },
                {
                    label: '5D Fwd Return',
                    data: (data.kama_cross_analysis || []).map(d => pctValue(d.fwd_5d)),
                    backgroundColor: 'rgba(246,139,66,0.60)',
                    borderColor: '#F68B42',
                    borderWidth: 1,
                }
            ]
        },
        options: crossChartOptions
    });

    // 4c. KAMA cross event counts
    statsCharts['kamaCrossCounts'] = updateOrCreate('stats.kamaCrossCounts', document.getElementById('chart-kama-cross-counts'), {
        type: 'bar',
        data: {
            labels: (data.kama_cross_analysis || []).map(d => d.label),
            datasets: [{
                label: '1D Event Count',
                data: (data.kama_cross_analysis || []).map(d => d.count_1d),
                backgroundColor: (data.kama_cross_analysis || []).map(d => d.direction === 'bull' ? 'rgba(77,175,136,0.65)' : 'rgba(224,82,82,0.65)'),
                borderColor: (data.kama_cross_analysis || []).map(d => d.direction === 'bull' ? '#4DAF88' : '#E05252'),
                borderWidth: 1,
            }]
        },
        options: baseChartOpts
    });
}

function updateSymbolHeader(symbol, last, prev, series) {
    document.getElementById('sym-title').textContent = _displaySymbol(symbol);
    const symInfo = state.symbols.find(s => s.symbol === symbol);
    document.getElementById('sym-subtitle').textContent = symInfo?.name || '';

    if (typeof renderRange52 === 'function') renderRange52(series);

    document.title = last
        ? `${_displaySymbol(symbol)} $${last.close.toFixed(2)} — FinDash`
        : `${_displaySymbol(symbol)} — FinDash`;

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

// ── Backtest Functions ────────────────────────────────────────
async function loadBacktest(symbol) {
    const statusEl = document.getElementById('backtest-status');
    const btn      = document.getElementById('btn-run-backtest');
    if (statusEl) statusEl.textContent = 'Running optimization…';
    if (btn) btn.disabled = true;
    try {
        const data = await apiFetch(`${API}/backtest/${symbol}`);
        renderBacktest(data);
        if (statusEl) statusEl.textContent = `Done — ${data.total_tested} combos tested`;
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

    const best = data.best || {};
    const set  = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set('bt-sharpe',  fmt(best.sharpe, 3));
    set('bt-annret',  fmtPct(best.ann_ret));
    set('bt-maxdd',   fmtPct(best.max_dd));
    set('bt-winrate', fmtPct(best.win_rate));
    set('bt-trades',  best.n_trades !== undefined ? String(best.n_trades) : '--');

    // Top 10 table
    const tbody = document.querySelector('#bt-results-table tbody');
    if (tbody) {
        tbody.innerHTML = '';
        (data.top10 || []).forEach((r, i) => {
            const tr = document.createElement('tr');
            if (i === 0) tr.style.background = 'rgba(59,130,246,0.08)';
            tr.innerHTML = `
                <td>${r.label}</td>
                <td>${fmt(r.sharpe, 3)}</td>
                <td>${fmtPct(r.ann_ret)}</td>
                <td>${fmtPct(r.max_dd)}</td>
                <td>${r.n_trades}</td>
                <td>${fmtPct(r.win_rate)}</td>
            `;
            tbody.appendChild(tr);
        });
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

// ── Phase Plane ───────────────────────────────────────────────
async function loadPhasePlane(forceRefresh = false) {
    if (_ppLoaded && !forceRefresh) return;

    const status  = document.getElementById('phase-plane-status');
    const loading = document.getElementById('phase-plane-loading');
    const imgWrap = document.getElementById('phase-plane-img-wrap');
    const img     = document.getElementById('phase-plane-img');

    status.textContent  = 'Loading…';
    loading.style.display  = 'flex';
    imgWrap.style.display  = 'none';

    // Fetch meta (KPI cards)
    try {
        const qs   = forceRefresh ? '?refresh=1' : '';
        const meta = await fetch(`/api/phase-plane/meta${qs}`).then(r => r.json());
        if (!meta.error) {
            document.getElementById('pp-vix').textContent  = meta.vix  ?? '--';
            document.getElementById('pp-nu').textContent   = meta.nu   ?? '--';
            document.getElementById('pp-rho').textContent  = meta.rho  ?? '--';
            document.getElementById('pp-nobs').textContent = meta.n_obs ?? '--';
            document.getElementById('pp-date').textContent = meta.date  ?? '--';
        }
    } catch (_) {}

    // Fetch image (slow — matplotlib render)
    try {
        const qs  = forceRefresh ? '?refresh=1' : '';
        const url = `/api/phase-plane/image${qs}&_=${Date.now()}`;
        img.onload = () => {
            loading.style.display = 'none';
            imgWrap.style.display = 'block';
            status.textContent    = `Last generated: ${new Date().toLocaleTimeString()}`;
            _ppLoaded = true;
        };
        img.onerror = () => {
            loading.style.display = 'none';
            status.textContent    = 'Error generating diagram.';
        };
        img.src = url;
    } catch (e) {
        loading.style.display = 'none';
        status.textContent    = `Error: ${e.message}`;
    }
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

    // Keyboard shortcuts — 1-9 then 0 for the ten most-used tabs
    const TAB_ORDER = ['charts','stats','trend','scanner','dashboard',
                       'journal','momentum','regime','portfolio','data-manager'];
    TAB_ORDER.forEach((id, i) =>
        registerShortcut({ key: String((i + 1) % 10), handler: () => switchTab(id), description: `Go to ${id}` })
    );
    registerShortcut({ key: 'j', handler: () => _moveWatchlist(+1), description: 'Next symbol' });
    registerShortcut({ key: 'k', handler: () => _moveWatchlist(-1), description: 'Previous symbol' });
    registerShortcut({ key: 'r', handler: () => { if (state.activeSymbol) switchTab(state.activeTab); }, description: 'Reload view' });
    registerShortcut({ key: '/', handler: () => document.getElementById('watchlist-search')?.focus(), description: 'Focus watchlist search' });
    registerShortcut({ key: '?', shift: true, handler: showShortcutsHelp, description: 'Show this help' });
    registerShortcut({ key: 'b', ctrl: true, handler: toggleSidebar, description: 'Toggle sidebar' });

    // Restore sidebar collapsed state
    try {
        if (localStorage.getItem('sidebar_hidden') === '1') {
            document.querySelector('.app')?.classList.add('sidebar-hidden');
            const btn = document.getElementById('sidebar-collapse-btn');
            if (btn) btn.textContent = '›';
        }
    } catch (_) {}

    await loadSymbols();

    // Start alert polling (60s interval, first check immediate)
    if (typeof startAlertPolling  === 'function') startAlertPolling(60000);
    // Init hover chart preview
    if (typeof initHoverPreview   === 'function') initHoverPreview();

    // Apply saved UI preferences (accent, density, scale, hidden tabs)
    applyUiPrefs();

    // Open-risk status bar widget (non-blocking)
    _loadOpenRiskBadge();
    setInterval(_loadOpenRiskBadge, 60_000);

    // Macro event proximity chip (refresh every 6h)
    _loadMacroChip();
    setInterval(_loadMacroChip, 6 * 3600_000);

    // Load regime badge async (non-blocking)
    if (typeof loadRegimeBadge === 'function') loadRegimeBadge('SPY');

    // Always-visible social top-movers banner (fire-and-forget, warms cache),
    // then refresh every 5 min so the strip stays current.
    if (typeof loadTopMovers === 'function') loadTopMovers();
    if (typeof startBannerAutoRefresh === 'function') startBannerAutoRefresh();

    const saved = persistence.load();
    const savedSym = saved?.activeSymbol;
    const savedTab = TAB_DEFS[saved?.activeTab] ? saved.activeTab : 'charts';

    // Restore symbol (without loading any view yet) only if still in the watchlist
    const validSym = savedSym && state.symbols.find(s => s.symbol === savedSym);
    if (validSym) {
        state.activeSymbol = savedSym;
    } else if (state.symbols.length && state.symbols[0].last_fetch) {
        state.activeSymbol = state.symbols[0].symbol;
    }

    if (state.activeSymbol) {
        renderSymbolList();
        const headerEl = document.getElementById('sym-title');
        if (headerEl) headerEl.textContent = _displaySymbol(state.activeSymbol);
        if (typeof _extrasOnSymbolLoad === 'function') _extrasOnSymbolLoad(state.activeSymbol);
    }

    // switchTab shows the saved tab's area and loads its data — previously a
    // saved non-chart tab restored the button highlight but left the empty
    // state on screen.
    await switchTab(savedTab);
});
