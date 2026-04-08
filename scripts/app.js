/**
 * app.js — Financial Dashboard Application Logic
 * Manages watchlist, KAMA period UI, and dual-panel chart loading.
 */

const API = '/api';

// Default KAMA periods to show on first load
const DEFAULT_KAMA_PERIODS = [10, 20, 50];

// App state
let state = {
    symbols:      [],
    activeSymbol: null,
    loading:      false,
    activeTab:    'charts',
    statsData:    null,
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
    const res  = await fetch(url, opts);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
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
                toast('Failed to load new KAMA: ' + e.message, 'error');
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
    const input  = document.getElementById('new-symbol-input');
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
    renderSymbolList();
    if (state.activeTab === 'charts') {
        await loadChartData(symbol);
    } else {
        await loadStatsData(symbol);
    }
}

async function loadStatsData(symbol) {
    if (!symbol) return;
    showStatsArea();
    showLoadingOverlay(true);
    updateSymbolHeader(symbol, null);

    try {
        // We still need OHLCV for the header price/change
        const [ohlcv, stats] = await Promise.all([
            apiFetch(`${API}/ohlcv/${symbol}?freq=daily&limit=2`),
            apiFetch(`${API}/stats/${symbol}`),
        ]);

        state.statsData = stats;
        renderStats(stats);
        
        const last = ohlcv[ohlcv.length - 1];
        const prev = ohlcv[ohlcv.length - 2];
        updateSymbolHeader(symbol, last, prev);
    } catch (e) {
        toast('Stats load failed: ' + e.message, 'error');
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
    document.getElementById('chart-area').style.display  = 'none';
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

    // Update buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.id === `tab-${tabId}`);
    });

    if (tabId === 'charts') {
        showChartArea();
        if (state.activeSymbol) loadChartData(state.activeSymbol);
    } else {
        showStatsArea();
        if (state.activeSymbol) loadStatsData(state.activeSymbol);
    }
}

function showStatsArea() {
    document.getElementById('empty-state').style.display = 'none';
    document.getElementById('chart-area').style.display  = 'none';
    document.getElementById('stats-area').style.display  = 'block';
    document.querySelector('.tab-bar').style.display     = 'none';
}

function showChartArea() {
    document.getElementById('empty-state').style.display = 'none';
    document.getElementById('stats-area').style.display  = 'none';
    document.getElementById('chart-area').style.display  = 'flex';
    document.querySelector('.tab-bar').style.display     = 'flex';
}

// ── Stats Rendering ───────────────────────────────────────────
function renderStats(data) {
    const m = data.metrics;
    
    // Update KPI values
    const fmt = (v, pct=false) => (v != null) ? (pct ? (v*100).toFixed(2)+'%' : v.toFixed(2)) : '--';
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

    const destroy = (id) => { if (statsCharts[id]) statsCharts[id].destroy(); };

    // 1. RSI Deciles 1D
    destroy('rsi1d');
    statsCharts['rsi1d'] = new Chart(document.getElementById('chart-rsi-1d'), {
        type: 'bar',
        data: {
            labels: data.rsi_analysis.fwd_1d.map(d => `D${d.bin+1}`),
            datasets: [{
                label: 'Mean 1D Return',
                data: data.rsi_analysis.fwd_1d.map(d => d.value * 100),
                backgroundColor: data.rsi_analysis.fwd_1d.map(d => d.value >= 0 ? '#22c55e' : '#ef4444'),
            }]
        },
        options: baseChartOpts
    });

    // 2. RSI Deciles 5D
    destroy('rsi5d');
    statsCharts['rsi5d'] = new Chart(document.getElementById('chart-rsi-5d'), {
        type: 'bar',
        data: {
            labels: data.rsi_analysis.fwd_5d.map(d => `D${d.bin+1}`),
            datasets: [{
                label: 'Mean 5D Return',
                data: data.rsi_analysis.fwd_5d.map(d => d.value * 100),
                backgroundColor: data.rsi_analysis.fwd_5d.map(d => d.value >= 0 ? '#22c55e' : '#ef4444'),
            }]
        },
        options: baseChartOpts
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
                data: data.seasonality.map(d => d.value * 100),
                backgroundColor: data.seasonality.map(d => d.value >= 0 ? 'rgba(34, 197, 94, 0.6)' : 'rgba(239, 68, 68, 0.6)'),
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
    document.getElementById('btn-refresh-all').addEventListener('click', refreshAll);
    document.getElementById('new-symbol-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') addSymbol();
    });

    await loadSymbols();

    if (state.symbols.length && state.symbols[0].last_fetch) {
        selectSymbol(state.symbols[0].symbol);
    } else {
        showEmptyState();
    }
});
