/**
 * app.js — Financial Dashboard Application Logic
 * Manages watchlist, API calls, symbol switching, and tab control.
 */

const API = 'http://localhost:8050/api';

// App state
let state = {
    symbols: [],
    activeSymbol: null,
    activeFreq: 'daily',   // 'daily' | 'weekly'
    ohlcvData: null,
    indData: null,
    loading: false,
};

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
    const res = await fetch(url, opts);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
}

// ── Clock ────────────────────────────────────────────────────
function startClock() {
    const el = document.getElementById('market-time');
    const tick = () => {
        const now = new Date();
        el.textContent = now.toLocaleString('en-US', {
            hour: '2-digit', minute: '2-digit', second: '2-digit',
            month: 'short', day: 'numeric', year: 'numeric',
            hour12: false,
        });
    };
    tick();
    setInterval(tick, 1000);
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

function renderSymbolList() {
    const list = document.getElementById('symbol-list');
    list.innerHTML = '';

    if (!state.symbols.length) {
        list.innerHTML = '<div style="padding:14px;color:var(--text-dim);font-size:12px;">No symbols yet.</div>';
        return;
    }

    state.symbols.forEach(sym => {
        const item = document.createElement('div');
        item.className = 'symbol-item' + (state.activeSymbol === sym.symbol ? ' active' : '');
        item.dataset.symbol = sym.symbol;

        const ticker = document.createElement('span');
        ticker.className = 'sym-ticker';
        ticker.textContent = sym.symbol;

        const lastFetch = document.createElement('span');
        lastFetch.className = 'sym-change';
        lastFetch.style.fontSize = '10px';
        lastFetch.style.color = 'var(--text-dim)';
        lastFetch.textContent = sym.last_fetch ? '⟳ ' + sym.last_fetch.slice(0, 10) : 'Not fetched';

        const removeBtn = document.createElement('span');
        removeBtn.className = 'sym-remove';
        removeBtn.textContent = '×';
        removeBtn.title = 'Remove';
        removeBtn.addEventListener('click', e => {
            e.stopPropagation();
            removeSymbol(sym.symbol);
        });

        item.appendChild(ticker);
        item.appendChild(lastFetch);
        item.appendChild(removeBtn);

        item.addEventListener('click', () => selectSymbol(sym.symbol));
        list.appendChild(item);
    });
}

async function addSymbol() {
    const input = document.getElementById('new-symbol-input');
    const symbol = input.value.trim().toUpperCase();
    if (!symbol) return;

    input.disabled = true;
    try {
        await apiFetch(`${API}/symbols`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol }),
        });
        input.value = '';
        toast(`${symbol} added to watchlist`, 'success');

        // Auto-fetch data for the new symbol
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

// ── Fetch data from Yahoo Finance ────────────────────────────
async function fetchSymbolData(symbol) {
    toast(`Downloading ${symbol} from Yahoo Finance…`, 'info');
    try {
        const res = await apiFetch(`${API}/fetch/${symbol}`, { method: 'POST' });
        toast(`${symbol}: ${res.daily_rows} daily / ${res.weekly_rows} weekly bars loaded`, 'success', 5000);
        return true;
    } catch (e) {
        toast(`${symbol} fetch failed: ` + e.message, 'error');
        return false;
    }
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
        toast('Refresh failed: ' + e.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '⟳ Refresh All';
    }
}

// ── Symbol selection & chart loading ─────────────────────────
async function selectSymbol(symbol) {
    state.activeSymbol = symbol;
    renderSymbolList(); // update active highlight

    // Check if we have data
    const existing = await apiFetch(`${API}/ohlcv/${symbol}?freq=${state.activeFreq}&limit=1`).catch(() => null);
    if (!existing || existing.error) {
        toast(`No data for ${symbol}. Downloading…`, 'info');
        const ok = await fetchSymbolData(symbol);
        if (!ok) return;
        await loadSymbols();
    }

    await loadChartData(symbol);
}

async function loadChartData(symbol) {
    if (!symbol) return;
    state.loading = true;
    showChartArea();
    showLoadingOverlay(true);
    updateSymbolHeader(symbol, null);

    try {
        const [ohlcv, indicators] = await Promise.all([
            apiFetch(`${API}/ohlcv/${symbol}?freq=${state.activeFreq}`),
            apiFetch(`${API}/indicators/${symbol}?freq=${state.activeFreq}`),
        ]);

        if (ohlcv.error) throw new Error(ohlcv.error);
        if (indicators.error) throw new Error(indicators.error);

        state.ohlcvData = ohlcv;
        state.indData = indicators;

        // Init charts (re-creates them to clear stale data)
        initCharts();
        loadOHLCV(ohlcv);
        loadIndicators(indicators);
        fitContent();

        // Update header with latest price
        const last = ohlcv[ohlcv.length - 1];
        const prev = ohlcv[ohlcv.length - 2];
        updateSymbolHeader(symbol, last, prev);
    } catch (e) {
        toast('Chart load failed: ' + e.message, 'error');
        showEmptyState();
    } finally {
        state.loading = false;
        showLoadingOverlay(false);
    }
}

// ── UI helpers ───────────────────────────────────────────────
function showEmptyState() {
    document.getElementById('empty-state').style.display = 'flex';
    document.getElementById('chart-area').style.display = 'none';
}

function showChartArea() {
    document.getElementById('empty-state').style.display = 'none';
    document.getElementById('chart-area').style.display = 'flex';
}

function showLoadingOverlay(show) {
    document.getElementById('chart-loading').style.display = show ? 'flex' : 'none';
}

function updateSymbolHeader(symbol, last, prev) {
    document.getElementById('sym-title').textContent = symbol;

    const symInfo = state.symbols.find(s => s.symbol === symbol);
    document.getElementById('sym-subtitle').textContent = symInfo?.name || '';

    if (!last) {
        document.getElementById('sym-price').textContent = '--';
        document.getElementById('sym-change-badge').textContent = '';
        ['open', 'high', 'low', 'close', 'volume'].forEach(k => {
            const el = document.getElementById(`ohlcv-${k}`);
            if (el) el.textContent = '--';
        });
        return;
    }

    const price = last.close.toFixed(2);
    const chg = prev ? last.close - prev.close : 0;
    const chgPct = prev ? (chg / prev.close * 100).toFixed(2) : '0.00';
    const isPos = chg >= 0;

    document.getElementById('sym-price').textContent = `$${price}`;

    const badge = document.getElementById('sym-change-badge');
    badge.textContent = `${isPos ? '+' : ''}${chg.toFixed(2)} (${isPos ? '+' : ''}${chgPct}%)`;
    badge.className = `sym-change-badge ${isPos ? 'positive' : 'negative'}`;

    const fmt = n => n?.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) ?? '--';
    const fmtVol = n => n ? (n >= 1e9 ? (n / 1e9).toFixed(2) + 'B' : n >= 1e6 ? (n / 1e6).toFixed(2) + 'M' : n.toLocaleString()) : '--';

    const ohlcvEl = document.getElementById('ohlcv-open'); if (ohlcvEl) ohlcvEl.textContent = `$${fmt(last.open)}`;
    const highEl = document.getElementById('ohlcv-high'); if (highEl) highEl.textContent = `$${fmt(last.high)}`;
    const lowEl = document.getElementById('ohlcv-low'); if (lowEl) lowEl.textContent = `$${fmt(last.low)}`;
    const closeEl = document.getElementById('ohlcv-close'); if (closeEl) closeEl.textContent = `$${fmt(last.close)}`;
    const volEl = document.getElementById('ohlcv-volume'); if (volEl) volEl.textContent = fmtVol(last.volume);
}

// ── Tab switching ────────────────────────────────────────────
function switchTab(freq) {
    state.activeFreq = freq;
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.freq === freq);
    });
    if (state.activeSymbol) loadChartData(state.activeSymbol);
}

// ── Indicator pills ──────────────────────────────────────────
function setupIndicatorPills() {
    document.querySelectorAll('.ind-pill').forEach(pill => {
        const key = pill.dataset.ind;
        // Reflect initial state
        if (activeOverlays[key]) pill.classList.add(`active-${key}`);

        pill.addEventListener('click', () => {
            const on = toggleOverlay(key);
            pill.classList.toggle(`active-${key}`, on);
        });
    });
}

// ── Enter key in symbol input ─────────────────────────────────
function handleSymbolInputKey(e) {
    if (e.key === 'Enter') addSymbol();
}

// ── Boot ──────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
    startClock();
    setupIndicatorPills();

    // Wire up buttons
    document.getElementById('btn-add-symbol').addEventListener('click', addSymbol);
    document.getElementById('btn-refresh-all').addEventListener('click', refreshAll);
    document.getElementById('new-symbol-input').addEventListener('keydown', handleSymbolInputKey);

    // Tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.freq));
    });

    // Load watchlist
    await loadSymbols();

    // Auto-select first symbol if any
    if (state.symbols.length) {
        const first = state.symbols[0];
        if (first.last_fetch) {
            selectSymbol(first.symbol);
        } else {
            showEmptyState();
        }
    } else {
        showEmptyState();
    }
});
