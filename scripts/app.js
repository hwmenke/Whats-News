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
    portfolio:    {},   // symbol -> snapshot
    portfolioMeta: null,
    tapeMode: 'all',   // 'all' | 'breakout' | 'alerts'
    seenAlerts: new Set(),
    deskOnly: true,    // sidebar: hide univ:* archive tickers
    checklist: { regime: false, stop: false, size: false, plan: false },
    stopMode: 'atr',   // 'atr' | 'box' | 'user'
    riskBox: null,     // last-applied { entry, stop, target } for the active symbol
    workspace: 'chart', // 'chart' | 'scan' | 'review'
};

const JOURNAL_KEY = 'whats-news-journal';
const PANES_KEY   = 'whats-news-panes';
const WORKSPACE_KEY = 'whats-news-workspace';
const LAST_SYMBOL_KEY = 'whats-news-last-symbol';
let journalFocusDate = null;

let statsCharts = {};
let backtestEquityChart = null;
let scannerPollTimer = null;
let lastFetchError = null;
let _chartLoadSeq = 0;

class ApiError extends Error {
    constructor(message, extras = {}) {
        super(message);
        this.name = 'ApiError';
        this.status = extras.status;
        this.code = extras.code;
        this.payload = extras.payload;
    }
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

function isYahooThrottle(err) {
    if (!err) return false;
    if (err.status === 429 || err.code === 'yahoo_throttle') return true;
    const payloadCode = err.payload && err.payload.code;
    if (payloadCode === 'yahoo_throttle') return true;
    const msg = String(err.message || err).toLowerCase();
    return /too many requests|rate.?limit|yahoo is rate-limiting|yfratelimit/.test(msg);
}

function showYahooThrottleBanner(symbol) {
    const banner = document.getElementById('yahoo-throttle-banner');
    if (!banner) return;
    const empty = document.getElementById('empty-state');
    const charts = document.getElementById('chart-area');
    if (empty) empty.style.display = 'none';
    if (charts) charts.style.display = 'flex';
    banner.hidden = false;
    banner.dataset.symbol = symbol || state.activeSymbol || '';
    const msg = document.getElementById('yahoo-throttle-message');
    if (msg) {
        const name = banner.dataset.symbol || 'this ticker';
        msg.textContent = `${name}: Yahoo is rate-limiting. Try again in a minute — the chart stays here instead of going blank.`;
    }
}

function hideYahooThrottleBanner() {
    const banner = document.getElementById('yahoo-throttle-banner');
    if (banner) {
        banner.hidden = true;
        delete banner.dataset.symbol;
    }
}

async function retryYahooFetch() {
    const banner = document.getElementById('yahoo-throttle-banner');
    const symbol = (banner && banner.dataset.symbol) || state.activeSymbol;
    if (!symbol) {
        toast('Pick a symbol first', 'warning');
        return;
    }
    const ok = await fetchSymbolData(symbol);
    if (ok) {
        hideYahooThrottleBanner();
        await loadChartData(symbol);
    }
}

function syncNewsSurfaceLabels(symbol) {
    const tab = document.getElementById('tab-news');
    if (tab) {
        tab.textContent = symbol ? `News · ${symbol}` : 'News · this ticker';
        tab.title = symbol
            ? `Headlines for ${symbol} only — Watchlist news is in the top bar`
            : 'Headlines for the selected ticker only — Watchlist news is in the top bar';
    }
    const title = document.getElementById('news-title');
    if (title) title.textContent = symbol ? `News for ${symbol}` : 'News for this ticker';
    const scope = document.getElementById('news-scope-label');
    if (scope) scope.textContent = symbol ? `${symbol} only` : 'Selected symbol only';
}

// ── API helpers ──────────────────────────────────────────────
async function apiFetch(url, opts = {}) {
    console.log(`>> API Fetch: ${url}`, opts.method || 'GET');
    const res  = await fetch(url, opts);
    console.log(`<< API Response: ${res.status} ${res.statusText}`);
    let data = {};
    try {
        data = await res.json();
    } catch {
        data = {};
    }
    if (!res.ok) {
        const err = new ApiError(data.error || `HTTP ${res.status}`, {
            status: res.status,
            code: data.code,
            payload: data,
        });
        console.error('!! API Error:', err.message);
        throw err;
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

// ── Sidebar toggle ────────────────────────────────────────────
function toggleSidebar() {
    const app = document.querySelector('.app');
    const btn = document.getElementById('btn-sidebar-toggle');
    if (!app) return;
    const collapsed = app.classList.toggle('sidebar-collapsed');
    if (btn) btn.textContent = collapsed ? '▶' : '☰';
}

// ── Symbol Watchlist ─────────────────────────────────────────
async function loadSymbols() {
    try {
        const url = state.deskOnly ? `${API}/symbols?desk=1` : `${API}/symbols`;
        state.symbols = await apiFetch(url);
        renderSymbolList();
        updateSidebarCount();
        refreshPortfolioTape(); // non-blocking enrich with % change
    } catch (e) {
        toast('Failed to load symbols: ' + e.message, 'error');
    }
}

function updateSidebarCount() {
    const el = document.getElementById('sidebar-symbol-count');
    if (!el) return;
    const n = state.symbols.length;
    el.textContent = state.deskOnly ? `${n} desk` : `${n} total`;
}

async function toggleDeskOnly(checked) {
    state.deskOnly = checked;
    await loadSymbols();
}

async function refreshPortfolioTape() {
    try {
        const data = await apiFetch(`${API}/portfolio/snapshot`);
        const map = {};
        (data.symbols || []).forEach(row => { map[row.symbol] = row; });
        state.portfolio = map;
        state.portfolioMeta = data;
        renderSymbolList();
        renderPortfolioTape(data);
        if (state.activeSymbol && map[state.activeSymbol]?.ready) {
            renderPmDesk(map[state.activeSymbol]);
        }
    } catch (e) {
        console.warn('Portfolio tape failed:', e);
    }
}

// Renders a single "Book RS #n/n" tag — never bare "RS" and never an
// industry-publication RS Rating (see METHODOLOGY_REVIEW.md: watchlist-relative only).
function bookRsLabel(row) {
    if (!row || row.rs_rank_21d == null) return 'Book RS —';
    return `Book RS #${row.rs_rank_21d}/${row.rs_n ?? '—'}`;
}

function renderPortfolioTape(data) {
    const bar = document.getElementById('portfolio-tape');
    const chips = document.getElementById('tape-chips');
    const meta = document.getElementById('tape-meta');
    if (!bar || !chips) return;

    const tapeAll = data.tape || [];
    if (!tapeAll.length) {
        bar.style.display = 'none';
        return;
    }
    bar.style.display = 'flex';

    // Toast newly appeared RSI alerts
    const alertSet = new Set(data.alerts || []);
    alertSet.forEach(sym => {
        if (!state.seenAlerts.has(sym)) {
            const row = (data.symbols || []).find(r => r.symbol === sym);
            toast(`${sym} ${row?.alert || 'ALERT'} · RSI ${row?.rsi14 ?? '—'}`, 'warning', 4500);
        }
    });
    state.seenAlerts = alertSet;

    const g = data.top_gainer;
    const l = data.top_loser;
    const rs = data.strongest_rs;
    let metaBits = `${data.ready_count}/${data.count} ready`;
    if (g) metaBits += ` · ↑ ${g.symbol} ${g.change_pct >= 0 ? '+' : ''}${g.change_pct}%`;
    if (l && l.symbol !== g?.symbol) metaBits += ` · ↓ ${l.symbol} ${l.change_pct}%`;
    if (rs) metaBits += ` · Book RS #1 ${rs.symbol}`;
    if (data.correlation) {
        const c = data.correlation;
        metaBits += ` · ρ ${c.pair[0]}/${c.pair[1]} ${c.corr_30d} (${c.note})`;
    }
    if (data.group_rollup?.length) {
        const topG = data.group_rollup[0];
        metaBits += ` · grp ${topG.group} ${topG.avg_change_pct >= 0 ? '+' : ''}${topG.avg_change_pct}%`;
    }
    meta.textContent = metaBits;

    chips.innerHTML = '';

    if (state.tapeMode === 'breakout') {
        renderBreakoutChips(data, chips);
    } else if (state.tapeMode === 'alerts') {
        renderAlertChips(data, chips);
    } else {
        renderAllChips(tapeAll, chips);
    }

    renderRegimeHeatmap(data);
    renderAlertLog(data);
}

function renderAllChips(tapeAll, chips) {
    if (!tapeAll.length) {
        chips.innerHTML = '<span style="color:var(--text-dim);font-size:11px;">No names yet</span>';
        return;
    }
    tapeAll.forEach(row => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'tape-chip' + (state.activeSymbol === row.symbol ? ' active' : '');
        const pos = (row.change_pct || 0) >= 0;
        const dw = row.regime_weekly && row.regime_weekly !== 'n/a'
            ? ` D:${row.regime?.[0] || '?'} W:${row.regime_weekly[0]}`
            : '';
        chip.innerHTML = `
            <span>${row.symbol}</span>
            <span class="tape-pct ${pos ? 'positive' : 'negative'}">${pos ? '+' : ''}${row.change_pct?.toFixed(1) ?? '—'}%</span>
            <span class="tape-rs">${bookRsLabel(row)}${dw}</span>
            ${row.alert ? `<span class="tape-alert">${row.alert}</span>` : ''}
        `;
        chip.title = `D ${row.regime || ''} / W ${row.regime_weekly || ''} · RSI ${row.rsi14 ?? '—'}`;
        chip.addEventListener('click', () => selectSymbol(row.symbol));
        chips.appendChild(chip);
    });
}

// Breakout chips — near-high + volume-confirmed names (Qullamaggie loop),
// with an EP flag and distance-from-high, shown when tape mode = "breakout".
function renderBreakoutChips(data, chips) {
    const queue = data.breakout_queue || [];
    if (!queue.length) {
        chips.innerHTML = '<span style="color:var(--text-dim);font-size:11px;">No breakout names</span>';
        return;
    }
    queue.forEach(row => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'tape-chip bq-chip' + (state.activeSymbol === row.symbol ? ' active' : '');
        const dist = row.dist_20d_high_pct;
        const distTxt = dist != null ? `${dist > 0 ? '+' : ''}${dist.toFixed(1)}% fr Hi` : '—';
        const volTxt = row.vol_ratio_5_20 != null ? `Vol ${row.vol_ratio_5_20.toFixed(1)}×` : '—';
        chip.innerHTML = `
            <span>${row.symbol}</span>
            <span class="tape-rs">${distTxt}</span>
            <span class="tape-rs">${volTxt}</span>
            ${row.is_ep ? '<span class="bq-ep-flag" title="Gap ≥4% on volume surge">EP</span>' : ''}
        `;
        chip.title = `${row.symbol} · ${distTxt} · ${volTxt}${row.gap_pct != null ? ` · gap ${row.gap_pct.toFixed(1)}%` : ''}`;
        chip.addEventListener('click', () => selectSymbol(row.symbol));
        chips.appendChild(chip);
    });
}

// Alerts chips — RSI overbought/oversold names only, shown when tape mode = "alerts".
function renderAlertChips(data, chips) {
    const alertRows = (data.tape || data.symbols || []).filter(r => r.alert);
    if (!alertRows.length) {
        chips.innerHTML = '<span style="color:var(--text-dim);font-size:11px;">No alerting names</span>';
        return;
    }
    alertRows.forEach(row => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'tape-chip' + (state.activeSymbol === row.symbol ? ' active' : '');
        chip.innerHTML = `
            <span>${row.symbol}</span>
            <span class="tape-alert">${row.alert}</span>
            <span class="tape-rs">RSI ${row.rsi14 ?? '—'}</span>
        `;
        chip.title = `${row.symbol} · ${row.alert} · RSI ${row.rsi14 ?? '—'}`;
        chip.addEventListener('click', () => selectSymbol(row.symbol));
        chips.appendChild(chip);
    });
}

function setPressed(el, on, className = 'active') {
    if (!el) return;
    el.classList.toggle(className, !!on);
    el.setAttribute('aria-pressed', on ? 'true' : 'false');
}

function setTapeMode(mode) {
    state.tapeMode = mode;
    document.querySelectorAll('.tape-mode-btn').forEach(btn => {
        setPressed(btn, btn.dataset.mode === mode);
    });
    if (state.portfolioMeta) renderPortfolioTape(state.portfolioMeta);
}

function renderRegimeHeatmap(data) {
    const heat = document.getElementById('regime-heatmap');
    const badge = document.getElementById('pm-panels-badge');
    if (badge) {
        const n = (data.alerts || []).length;
        badge.textContent = String(n);
        badge.style.display = n > 0 ? 'inline' : 'none';
    }
    if (heat) {
        const rows = data.heatmap || [];
        heat.innerHTML = '';
        if (!rows.length) {
            heat.innerHTML = '<div class="alert-log-empty">No symbols yet</div>';
        } else {
            rows.forEach(r => {
                const cell = document.createElement('button');
                cell.type = 'button';
                cell.className = 'heat-cell';
                cell.innerHTML = `
                  <span class="heat-sym">${r.symbol}</span>
                  <span class="heat-dots">
                    <span class="heat-dot ${r.regime || ''}" title="Daily ${r.regime || 'n/a'}"></span>
                    <span class="heat-dot ${r.regime_weekly || ''}" title="Weekly ${r.regime_weekly || 'n/a'}"></span>
                  </span>
                `;
                cell.title = `${r.symbol} D:${r.regime} W:${r.regime_weekly} · day ${r.change_pct ?? '—'}%`;
                cell.addEventListener('click', () => selectSymbol(r.symbol));
                heat.appendChild(cell);
            });
        }
    }
    renderThemeLeaders(data);
}

// Theme leaders — group rollup (avg day % by group_tag), shown in the book drawer.
function renderThemeLeaders(data) {
    const el = document.getElementById('theme-leaders');
    if (!el) return;
    const groups = data.group_rollup || [];
    if (!groups.length) {
        el.innerHTML = '<div class="alert-log-empty">No groups yet</div>';
        return;
    }
    el.innerHTML = groups.map(g => {
        const pos = (g.avg_change_pct || 0) >= 0;
        return `
          <div class="theme-leader-item">
            <span class="theme-leader-name">${g.group}</span>
            <span class="theme-leader-n">${g.n}</span>
            <span class="tape-pct ${pos ? 'positive' : 'negative'}">${pos ? '+' : ''}${g.avg_change_pct}%</span>
          </div>
        `;
    }).join('');
}

function renderAlertLog(data) {
    const log = document.getElementById('alert-log');
    if (!log) return;
    const alerts = (data.symbols || []).filter(r => r.alert);
    // Persist history in localStorage
    const key = 'wn_alert_log';
    let hist = [];
    try { hist = JSON.parse(localStorage.getItem(key) || '[]'); } catch { hist = []; }
    const now = new Date().toISOString();
    alerts.forEach(a => {
        const last = hist.find(h => h.symbol === a.symbol && h.alert === a.alert);
        if (!last || (Date.now() - new Date(last.at).getTime()) > 3600000) {
            hist.unshift({ symbol: a.symbol, alert: a.alert, rsi: a.rsi14, at: now });
        }
    });
    hist = hist.slice(0, 30);
    localStorage.setItem(key, JSON.stringify(hist));

    if (!hist.length) {
        log.innerHTML = '<div class="alert-log-empty">No RSI alerts yet</div>';
        return;
    }
    log.innerHTML = hist.slice(0, 12).map(h => `
      <div class="alert-log-item" data-sym="${h.symbol}">
        <span><span class="al-flag">${h.alert}</span> ${h.symbol} · RSI ${h.rsi ?? '—'}</span>
        <span style="color:var(--text-dim)">${(h.at || '').slice(11, 16)}Z</span>
      </div>
    `).join('');
    log.querySelectorAll('.alert-log-item').forEach(el => {
        el.addEventListener('click', () => selectSymbol(el.dataset.sym));
    });
}

// ── Book drawer (regime heatmap / alert log / theme leaders) ───────────
function openBookDrawer() {
    const drawer = document.getElementById('book-drawer');
    const backdrop = document.getElementById('book-drawer-backdrop');
    if (!drawer) return;
    closePmToolsPopover();
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    if (backdrop) backdrop.hidden = false;
}

function closeBookDrawer() {
    const drawer = document.getElementById('book-drawer');
    const backdrop = document.getElementById('book-drawer-backdrop');
    if (!drawer) return;
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    if (backdrop) backdrop.hidden = true;
}

function toggleBookDrawer() {
    const drawer = document.getElementById('book-drawer');
    if (!drawer) return;
    if (drawer.classList.contains('open')) closeBookDrawer();
    else openBookDrawer();
}

// ── Trade journal drawer (localStorage-backed) ─────────────────────────
function openJournal() {
    const drawer = document.getElementById('journal-drawer');
    if (!drawer) return;
    closePmToolsPopover();
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    renderJournal();
}

// Click-bar hook from charts.js subscribeClick. Daily uses the session date;
// weekly uses the week-ending date on the bar.
function onChartBarClick(payload) {
    const date = payload && payload.date ? String(payload.date).slice(0, 10) : '';
    if (!date) return;
    openJournalForDate(date, payload && payload.freq);
}

function openJournalForDate(date, freq) {
    const key = String(date || '').slice(0, 10);
    if (!key) return;
    journalFocusDate = key;
    openJournal();
    const dateEl = document.getElementById('journal-date');
    const noteEl = document.getElementById('journal-note');
    if (dateEl) dateEl.value = key;
    if (noteEl) {
        const week = freq === 'weekly' ? ' week-ending' : '';
        const sym = state.activeSymbol || '';
        noteEl.placeholder = [sym, key + week].filter(Boolean).join(' ');
        noteEl.focus();
    }
}

function closeJournal() {
    const drawer = document.getElementById('journal-drawer');
    if (!drawer) return;
    drawer.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
}

function toggleJournal() {
    const drawer = document.getElementById('journal-drawer');
    if (!drawer) return;
    if (drawer.classList.contains('open')) closeJournal();
    else openJournal();
}

function loadJournalEntries() {
    try {
        const raw = JSON.parse(localStorage.getItem(JOURNAL_KEY) || '[]');
        return Array.isArray(raw) ? raw : [];
    } catch {
        return [];
    }
}

function saveJournalEntries(entries) {
    localStorage.setItem(JOURNAL_KEY, JSON.stringify(entries));
}

function saveToJournal() {
    const snap = state.portfolio[state.activeSymbol];
    if (!snap?.ready) {
        toast('No setup to save — select a loaded symbol', 'warning');
        return;
    }
    const entry = {
        id: `${snap.symbol}-${Date.now()}`,
        symbol: snap.symbol,
        date: new Date().toISOString(),
        entry: state.riskBox?.entry ?? snap.price ?? null,
        stop: state.riskBox?.stop ?? snap.stop_long_1_5atr ?? null,
        target: state.riskBox?.target ?? null,
        r_multiple: computeRMultiple(),
        book_rs: bookRsLabel(snap),
        darvas_state: snap.darvas?.state || null,
        closed: false,
        result_r: null,
    };
    const entries = loadJournalEntries();
    entries.unshift(entry);
    saveJournalEntries(entries);
    renderJournal();
    toast(`${snap.symbol} setup saved to journal`, 'success');
}

function closeJournalEntry(id) {
    const entries = loadJournalEntries();
    const entry = entries.find(e => e.id === id);
    if (!entry) return;
    const input = prompt(`Close ${entry.symbol} — result in R-multiples:`, entry.result_r ?? '');
    if (input === null) return;
    const r = parseFloat(input);
    entry.closed = true;
    entry.result_r = Number.isFinite(r) ? r : null;
    saveJournalEntries(entries);
    renderJournal();
}

function deleteJournalEntry(id) {
    const entries = loadJournalEntries().filter(e => e.id !== id);
    saveJournalEntries(entries);
    renderJournal();
}

function saveJournalNote(ev) {
    if (ev) ev.preventDefault();
    const dateEl = document.getElementById('journal-date');
    const noteEl = document.getElementById('journal-note');
    const date = (dateEl && dateEl.value ? dateEl.value : journalFocusDate || '').slice(0, 10);
    const note = (noteEl && noteEl.value ? noteEl.value : '').trim();
    if (!date) {
        toast('Pick a date', 'warning');
        return;
    }
    if (!note) {
        toast('Add a one-line note', 'warning');
        return;
    }
    const symbol = state.activeSymbol || '—';
    const entry = {
        id: `${symbol}-${Date.now()}`,
        symbol,
        date,
        note,
        closed: false,
        result_r: null,
    };
    const entries = loadJournalEntries();
    entries.unshift(entry);
    saveJournalEntries(entries);
    journalFocusDate = date;
    if (noteEl) noteEl.value = '';
    renderJournal();
    toast(`${symbol} ${date} saved`, 'success');
}

function renderJournal() {
    const list = document.getElementById('journal-list');
    if (!list) return;
    const dateEl = document.getElementById('journal-date');
    if (dateEl && !dateEl.value) {
        dateEl.value = (journalFocusDate || new Date().toISOString().slice(0, 10));
    }
    const entries = loadJournalEntries();
    if (!entries.length) {
        list.innerHTML = '<div class="alert-log-empty">No setups saved yet</div>';
        return;
    }
    const focus = journalFocusDate || (dateEl && dateEl.value) || '';
    const fmt = v => (v == null ? '—' : `$${Number(v).toFixed(2)}`);
    const sorted = entries.slice().sort((a, b) => {
        const aHit = focus && String(a.date || '').slice(0, 10) === focus ? 0 : 1;
        const bHit = focus && String(b.date || '').slice(0, 10) === focus ? 0 : 1;
        return aHit - bHit;
    });
    list.innerHTML = sorted.map(e => {
        const d = (e.date || '').slice(0, 10);
        const focused = focus && d === focus;
        const noteLine = e.note
            ? `<span class="journal-note-text">${escapeHtml(e.note)}</span>`
            : `<span>Entry ${fmt(e.entry)} · Stop ${fmt(e.stop)} · Target ${fmt(e.target)}</span>
          <span>R ${e.r_multiple ?? '—'}${e.closed ? ` · Closed @ ${e.result_r ?? '—'}R` : ''}</span>`;
        return `
      <div class="journal-item ${e.closed ? 'journal-item-closed' : ''} ${focused ? 'journal-item-focus' : ''}" data-id="${e.id}" data-date="${d}">
        <div class="journal-item-head">
          <span class="journal-sym">${escapeHtml(e.symbol || '')}</span>
          <span class="journal-date">${d}</span>
        </div>
        <div class="journal-item-body">
          ${noteLine}
        </div>
        <div class="journal-item-actions">
          <button type="button" class="btn btn-ghost btn-sm journal-close-btn" data-id="${e.id}">${e.closed ? 'Edit result' : 'Close'}</button>
          <button type="button" class="btn btn-ghost btn-sm journal-del-btn" data-id="${e.id}">Delete</button>
        </div>
      </div>`;
    }).join('');
    list.querySelectorAll('.journal-close-btn').forEach(btn => {
        btn.addEventListener('click', () => closeJournalEntry(btn.dataset.id));
    });
    list.querySelectorAll('.journal-del-btn').forEach(btn => {
        btn.addEventListener('click', () => deleteJournalEntry(btn.dataset.id));
    });
    list.querySelector('.journal-item-focus')?.scrollIntoView({ block: 'nearest' });
}

// ── PM tools popover (risk box, checklist, copy/journal) ───────────────
function togglePmToolsPopover() {
    const pop = document.getElementById('pm-tools-popover');
    if (!pop) return;
    pop.hidden = !pop.hidden;
}

function closePmToolsPopover() {
    const pop = document.getElementById('pm-tools-popover');
    if (pop) pop.hidden = true;
}

// ── Checklist gate — copy/save only unlock once all 4 boxes are checked ─
function syncChecklist() {
    const boxes = document.querySelectorAll('#pm-checklist input[type="checkbox"]');
    boxes.forEach(box => { state.checklist[box.dataset.check] = box.checked; });
    const allChecked = Object.values(state.checklist).every(Boolean);
    const copyBtn = document.getElementById('pm-copy-setup');
    const saveBtn = document.getElementById('pm-save-journal');
    if (copyBtn) {
        copyBtn.disabled = !allChecked;
        copyBtn.title = allChecked ? 'Copy setup card' : 'Complete checklist first';
    }
    if (saveBtn) {
        saveBtn.disabled = !allChecked;
        saveBtn.title = allChecked ? 'Save to journal' : 'Complete checklist first';
    }
}

function computeRMultiple() {
    const entry = parseFloat(document.getElementById('pm-entry-input')?.value);
    const stop = parseFloat(document.getElementById('pm-stop-input')?.value);
    const target = parseFloat(document.getElementById('pm-target-input')?.value);
    if (!Number.isFinite(entry) || !Number.isFinite(stop) || !Number.isFinite(target)) return null;
    const risk = Math.abs(entry - stop);
    if (risk < 1e-9) return null;
    return Math.round(((target - entry) / risk) * 100) / 100;
}

function updateRMultiple() {
    const r = computeRMultiple();
    const el = document.getElementById('pm-r-mult');
    if (el) el.textContent = r != null ? `R ${r}` : 'R —';
}

function applyRiskBoxFromInputs() {
    const entry = parseFloat(document.getElementById('pm-entry-input')?.value);
    const stop = parseFloat(document.getElementById('pm-stop-input')?.value);
    const target = parseFloat(document.getElementById('pm-target-input')?.value);
    if (!Number.isFinite(entry) || !Number.isFinite(stop)) {
        toast('Enter entry and stop first', 'warning');
        return;
    }
    state.riskBox = { entry, stop, target: Number.isFinite(target) ? target : null };
    updateRMultiple();
    window.applyRiskBox?.(entry, stop, Number.isFinite(target) ? target : null);
    toast('Risk box drawn on daily + weekly', 'success');
}

async function openBookNews() {
    // news_focus is driven by breakout queue + top RS (strong names) —
    // never RSI OS/weak-RS. See METHODOLOGY_REVIEW.md must-not-do #3.
    const focus = state.portfolioMeta?.news_focus || [];
    if (!focus.length) {
        toast('No breakout/strong-RS names for book news yet', 'info');
        switchTab('news');
        return;
    }
    switchTab('news');
    const listEl = document.getElementById('news-list');
    const emptyEl = document.getElementById('news-empty');
    const loadingEl = document.getElementById('news-loading');
    if (loadingEl) loadingEl.style.display = 'flex';
    if (emptyEl) emptyEl.style.display = 'none';
    if (listEl) listEl.innerHTML = '';
    try {
        // Prefer focused symbols: fetch per-symbol and merge
        const batches = await Promise.all(
            focus.slice(0, 5).map(async sym => {
                try {
                    const data = await apiFetch(`${API}/news/${sym}`);
                    return (data.articles || []).map(a => ({ ...a, symbol: sym }));
                } catch {
                    return [];
                }
            })
        );
        const articles = batches.flat();
        const seen = new Set();
        const deduped = [];
        for (const a of articles) {
            const key = a.url || a.title;
            if (!key || seen.has(key)) continue;
            seen.add(key);
            deduped.push(a);
        }
        deduped.sort((a, b) => (b.publish_time || '').localeCompare(a.publish_time || ''));

        if (loadingEl) loadingEl.style.display = 'none';
        if (!deduped.length) {
            if (emptyEl) {
                emptyEl.style.display = 'flex';
                const p = emptyEl.querySelector('p');
                if (p) p.textContent = `No headlines for focus names: ${focus.join(', ')}`;
            }
            return;
        }
        // Reuse single-symbol news renderer if present
        if (typeof renderNewsArticles === 'function') {
            renderNewsArticles(deduped);
        } else if (listEl) {
            listEl.innerHTML = deduped.slice(0, 40).map(a => `
                <article class="news-item" style="padding:12px 0;border-bottom:1px solid var(--border);">
                  <div style="font-size:11px;color:var(--accent-bright);font-family:var(--font-mono);">${a.symbol || ''}</div>
                  <a href="${a.url || '#'}" target="_blank" rel="noopener" style="color:var(--text-primary);font-weight:600;text-decoration:none;">
                    ${a.title || 'Untitled'}
                  </a>
                  <div style="font-size:11px;color:var(--text-dim);margin-top:4px;">
                    via ${a.provider || 'Yahoo Finance'} · ${a.publish_time || ''}
                  </div>
                </article>
            `).join('');
        }
        toast(`Book news: ${focus.join(', ')}`, 'info');
    } catch (e) {
        if (loadingEl) loadingEl.style.display = 'none';
        toast('Book news failed: ' + e.message, 'error');
    }
}

function renderSymbolList() {
    const list = document.getElementById('symbol-list');
    list.innerHTML = '';
    const q = (document.getElementById('watchlist-filter')?.value || '').trim().toUpperCase();

    if (!state.symbols.length) {
        list.innerHTML = '<div style="padding:14px;color:var(--text-dim);font-size:12px;">No symbols yet.</div>';
        return;
    }

    // Group symbols by group_tag
    let lastGroup = undefined;
    state.symbols.forEach(sym => {
        const tag = sym.group_tag || '';

        // Render group header when group changes
        if (tag !== lastGroup) {
            lastGroup = tag;
            if (tag) {
                const hdr = document.createElement('div');
                hdr.className = 'sym-group-header';
                hdr.textContent = tag;
                list.appendChild(hdr);
            }
        }

        const item = document.createElement('div');
        item.className = 'symbol-item' + (state.activeSymbol === sym.symbol ? ' active' : '');
        item.dataset.symbol = sym.symbol;
        if (q && !sym.symbol.includes(q) && !(tag || '').toUpperCase().includes(q)) {
            item.hidden = true;
        }

        const ticker = document.createElement('span');
        ticker.className = 'sym-ticker';
        ticker.textContent = sym.symbol;

        const snap = state.portfolio[sym.symbol];
        const chgEl = document.createElement('span');
        chgEl.className = 'sym-change';
        if (snap?.ready && snap.change_pct != null) {
            const pos = snap.change_pct >= 0;
            chgEl.textContent = `${pos ? '+' : ''}${snap.change_pct.toFixed(1)}%`;
            chgEl.classList.add(pos ? 'positive' : 'negative');
            chgEl.title = snap.regime ? `Regime: ${snap.regime}` : '';
        } else {
            chgEl.textContent = snap?.error ? '—' : '…';
            chgEl.style.color = 'var(--text-dim)';
        }

        item.appendChild(ticker);
        item.appendChild(chgEl);

        if (snap?.rs_rank_21d) {
            const rs = document.createElement('span');
            rs.className = 'sym-rs';
            rs.textContent = `#${snap.rs_rank_21d}`;
            rs.title = `21D relative strength rank (${snap.rs_n} names)`;
            item.appendChild(rs);
        }
        if (snap?.alert) {
            const al = document.createElement('span');
            al.className = 'sym-alert';
            al.textContent = snap.alert;
            al.title = snap.alert === 'RSI_OB' ? 'RSI overbought' : 'RSI oversold';
            item.appendChild(al);
        }

        // Group tag badge (click to edit inline)
        const tagBadge = document.createElement('span');
        tagBadge.className   = 'sym-tag';
        const isUniverse = tag.startsWith('univ:');
        tagBadge.textContent = isUniverse ? tag.replace('univ:', 'idx:') : (tag || '+ tag');
        tagBadge.title       = isUniverse ? 'Archive index ticker — promote to desk' : 'Click to set group';
        if (!isUniverse) {
            tagBadge.addEventListener('click', e => {
                e.stopPropagation();
                startTagEdit(sym.symbol, tag, tagBadge);
            });
        }

        if (isUniverse) {
            const promoteBtn = document.createElement('span');
            promoteBtn.className = 'sym-promote';
            promoteBtn.textContent = '↑';
            promoteBtn.title = 'Promote to trading desk';
            promoteBtn.addEventListener('click', async e => {
                e.stopPropagation();
                await promoteSymbolToDesk(sym.symbol);
            });
            item.appendChild(promoteBtn);
        }

        const removeBtn = document.createElement('span');
        removeBtn.className  = 'sym-remove';
        removeBtn.textContent = '×';
        removeBtn.title       = 'Remove';
        removeBtn.addEventListener('click', e => { e.stopPropagation(); removeSymbol(sym.symbol); });

        item.appendChild(tagBadge);
        item.appendChild(removeBtn);
        item.addEventListener('click', () => selectSymbol(sym.symbol));
        list.appendChild(item);
    });
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

async function addSymbolByCode(code) {
    const input = document.getElementById('new-symbol-input');
    if (input) input.value = String(code || '').trim().toUpperCase();
    await addSymbol();
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
    lastFetchError = null;
    if (!silent) toast(`Downloading ${symbol} from Yahoo Finance…`, 'info', 5000);
    try {
        const res = await apiFetch(`${API}/fetch/${symbol}`, { method: 'POST' });
        console.log(`[App] Fetch complete for ${symbol}:`, res);
        hideYahooThrottleBanner();
        if (typeof forgetChartBundle === 'function') forgetChartBundle(symbol);
        if (!silent) toast(`${symbol}: ${res.daily_rows} daily / ${res.weekly_rows} weekly bars loaded`, 'success', 5000);
        return true;
    } catch (e) {
        console.error(`[App] Fetch failed for ${symbol}:`, e);
        lastFetchError = e;
        if (isYahooThrottle(e)) {
            showYahooThrottleBanner(symbol);
            if (!silent) toast('Yahoo is rate-limiting. Try again in a minute.', 'warning', 6000);
        } else if (!silent) {
            toast(`${symbol} fetch failed: ` + e.message, 'error');
        }
        return false;
    }
}

// ── Focus trap (bulk import + keyboard cheatsheet) ────────────
function trapFocusIn(root, e) {
    if (e.key !== 'Tab' || !root) return;
    const nodes = [...root.querySelectorAll(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )].filter(el => !el.disabled && el.getClientRects().length > 0);
    if (!nodes.length) {
        e.preventDefault();
        return;
    }
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
    }
}

function setAppInert(on) {
    const app = document.querySelector('.app');
    if (app) app.inert = !!on;
}

let _bulkPrevFocus = null;

function isBulkModalOpen() {
    const modal = document.getElementById('bulk-modal');
    return !!(modal && modal.style.display === 'flex');
}

function onBulkModalKeydown(e) {
    if (e.key === 'Escape') {
        if (!document.getElementById('btn-bulk-submit')?.disabled) {
            e.preventDefault();
            closeBulkModal();
        }
        return;
    }
    trapFocusIn(document.querySelector('#bulk-modal .bulk-modal-card'), e);
}

// ── Bulk Import ───────────────────────────────────────────────
function openBulkModal() {
    const modal = document.getElementById('bulk-modal');
    if (!modal) return;
    closeKbdHelp();
    _bulkPrevFocus = document.activeElement;
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden', 'false');
    setAppInert(true);
    // Reset progress state from any previous run
    document.getElementById('bulk-progress').style.display        = 'none';
    document.getElementById('bulk-progress-fill').style.width     = '0%';
    document.getElementById('bulk-progress-label').style.color    = '';
    document.getElementById('bulk-progress-label').textContent    = 'Starting…';
    const counts = document.getElementById('bulk-progress-counts');
    if (counts) counts.textContent = '';
    const log = document.getElementById('bulk-progress-log');
    if (log) log.innerHTML = '';
    document.getElementById('btn-bulk-submit').disabled           = false;
    document.getElementById('bulk-symbols-input').disabled        = false;
    modal.addEventListener('keydown', onBulkModalKeydown);
    setTimeout(() => document.getElementById('bulk-symbols-input').focus(), 50);
}

function closeBulkModal() {
    // Only close if not in the middle of an import
    if (document.getElementById('btn-bulk-submit')?.disabled) return;
    const modal = document.getElementById('bulk-modal');
    if (!modal || modal.style.display === 'none') return;
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
    modal.removeEventListener('keydown', onBulkModalKeydown);
    setAppInert(false);
    const input = document.getElementById('bulk-symbols-input');
    if (input) input.value = '';
    const progress = document.getElementById('bulk-progress');
    if (progress) progress.style.display = 'none';
    if (_bulkPrevFocus && typeof _bulkPrevFocus.focus === 'function') {
        _bulkPrevFocus.focus();
    }
    _bulkPrevFocus = null;
}

function appendBulkLog(symbol, status, detail) {
    const log = document.getElementById('bulk-progress-log');
    if (!log) return;
    const li = document.createElement('li');
    li.className = status;
    li.textContent = `${symbol}  —  ${detail}`;
    log.appendChild(li);
    log.scrollTop = log.scrollHeight;
}

function setBulkCounts(done, total, added, skipped, failed, paused) {
    const counts = document.getElementById('bulk-progress-counts');
    if (!counts) return;
    const bits = [`${done} / ${total}`];
    if (added) bits.push(`${added} fetched`);
    if (skipped) bits.push(`${skipped} skipped`);
    if (failed) bits.push(`${failed} failed`);
    if (paused) bits.push(`${paused} waiting`);
    counts.textContent = bits.join('  ·  ');
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
    const logEl      = document.getElementById('bulk-progress-log');

    submitBtn.disabled  = true;
    textarea.disabled   = true;
    progressEl.style.display = 'block';
    labelEl.style.color = '';
    if (logEl) logEl.innerHTML = '';

    const existing = new Set(state.symbols.map(s => s.symbol));
    const toFetch = [];
    let skipped = 0, added = 0, failed = 0, paused = 0;
    const failedSymbols = [];

    symbols.forEach(sym => {
        if (existing.has(sym)) {
            skipped++;
            appendBulkLog(sym, 'skip', 'already on watchlist');
        } else {
            toFetch.push(sym);
        }
    });

    labelEl.textContent = toFetch.length
        ? `Adding ${toFetch.length} ticker${toFetch.length === 1 ? '' : 's'} to the watchlist…`
        : 'Nothing new to add';
    setBulkCounts(0, symbols.length, 0, skipped, 0, 0);

    if (toFetch.length) {
        try {
            await apiFetch(`${API}/symbols`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbols: toFetch }),
            });
        } catch (_) {
            // Fall through — per-symbol register still happens below if needed
        }
        await loadSymbols();
        toFetch.forEach(s => existing.add(s));
    }

    let throttled = false;
    for (let i = 0; i < toFetch.length; i++) {
        const sym = toFetch[i];
        const done = skipped + i;
        fillEl.style.width = `${Math.round((done / symbols.length) * 100)}%`;
        labelEl.textContent = `Downloading ${sym} from Yahoo…  ${i + 1} / ${toFetch.length}`;
        setBulkCounts(done, symbols.length, added, skipped, failed, 0);
        appendBulkLog(sym, 'work', 'downloading from Yahoo…');

        try {
            await apiFetch(`${API}/symbols`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ symbol: sym }),
            });
        } catch (_) { /* already registered */ }

        const ok = await fetchSymbolData(sym, true);
        if (ok) {
            added++;
            appendBulkLog(sym, 'ok', 'history loaded');
        } else if (isYahooThrottle(lastFetchError)) {
            failed++;
            failedSymbols.push(sym);
            throttled = true;
            appendBulkLog(sym, 'pause', 'Yahoo is rate-limiting — stopped here');
            const leftover = toFetch.slice(i + 1);
            leftover.forEach(s => appendBulkLog(s, 'pause', 'waiting — fetch later'));
            paused = leftover.length;
            break;
        } else {
            failed++;
            failedSymbols.push(sym);
            appendBulkLog(sym, 'fail', lastFetchError?.message || 'fetch failed');
        }
    }

    fillEl.style.width = '100%';
    const parts = [
        added   ? `${added} fetched` : null,
        skipped ? `${skipped} skipped` : null,
        failed  ? `${failed} failed` : null,
        paused  ? `${paused} waiting` : null,
    ].filter(Boolean);
    const summary = parts.join(', ') || 'nothing to do';
    labelEl.textContent = throttled
        ? `Paused — Yahoo is rate-limiting. Try again in a minute.`
        : `Done — ${summary}`;
    labelEl.style.color = throttled ? 'var(--yellow)' : (failed ? 'var(--red)' : 'var(--green)');
    setBulkCounts(symbols.length, symbols.length, added, skipped, failed, paused);

    submitBtn.disabled = false;
    textarea.disabled  = false;

    await loadSymbols();
    if (added && !state.activeSymbol) selectSymbol(toFetch[0] || symbols[0]);

    toast(
        (throttled ? 'Yahoo rate-limit — ' : 'Bulk import: ') + summary
            + (failedSymbols.length ? ` (${failedSymbols.join(', ')})` : ''),
        throttled || failed ? 'warning' : 'success',
        6000
    );

    if (failed === 0 && !throttled) setTimeout(closeBulkModal, 2500);
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
// Neighbor prefetch: after a selection change, warm next/prev visible
// watchlist names so j/k chart switches reuse daily+weekly OHLCV + indicators.

let _prefetchGen = 0;
const _prefetchControllers = new Map();
const _chartPayloadCache = new Map();
const _inflightChartBundles = new Map();
const CHART_BUNDLE_CACHE_MAX = 12;

function chartBundleKey(symbol) {
    return `${String(symbol || '').toUpperCase()}|${kamaApiParam()}`;
}

function peekChartBundle(symbol) {
    return _chartPayloadCache.get(chartBundleKey(symbol)) || null;
}

function rememberChartBundle(symbol, bundle) {
    if (!symbol || !bundle) return;
    const key = chartBundleKey(symbol);
    if (_chartPayloadCache.has(key)) _chartPayloadCache.delete(key);
    _chartPayloadCache.set(key, bundle);
    while (_chartPayloadCache.size > CHART_BUNDLE_CACHE_MAX) {
        const oldest = _chartPayloadCache.keys().next().value;
        _chartPayloadCache.delete(oldest);
    }
}

function forgetChartBundle(symbol) {
    const prefix = `${String(symbol || '').toUpperCase()}|`;
    for (const key of [..._chartPayloadCache.keys()]) {
        if (key.startsWith(prefix)) _chartPayloadCache.delete(key);
    }
    for (const key of [..._inflightChartBundles.keys()]) {
        if (key.startsWith(prefix)) _inflightChartBundles.delete(key);
    }
    const code = String(symbol || '').toUpperCase();
    const ac = _prefetchControllers.get(code);
    if (ac) {
        ac.abort();
        _prefetchControllers.delete(code);
    }
}

function neighborVisibleSymbols(symbol) {
    const codes = (typeof visibleSymbolCodes === 'function' ? visibleSymbolCodes() : null) || [];
    if (!codes.length || !symbol) return [];
    const idx = codes.indexOf(symbol);
    if (idx < 0) return [];
    const neighbors = [];
    const prev = codes[(idx - 1 + codes.length) % codes.length];
    const next = codes[(idx + 1) % codes.length];
    if (prev && prev !== symbol) neighbors.push(prev);
    if (next && next !== symbol && next !== prev) neighbors.push(next);
    return neighbors;
}

function abortChartPrefetch(keepSymbol) {
    _prefetchGen += 1;
    const keep = keepSymbol ? String(keepSymbol).toUpperCase() : '';
    for (const [sym, ac] of [..._prefetchControllers.entries()]) {
        if (keep && String(sym).toUpperCase() === keep) continue;
        ac.abort();
        _prefetchControllers.delete(sym);
    }
}

async function fetchChartBundle(symbol, { signal } = {}) {
    const key = chartBundleKey(symbol);
    if (_inflightChartBundles.has(key)) {
        return _inflightChartBundles.get(key);
    }
    const kama = kamaApiParam();
    const opts = signal ? { signal } : {};
    const pending = Promise.all([
        apiFetch(`${API}/ohlcv/${symbol}?freq=daily`, opts),
        apiFetch(`${API}/ohlcv/${symbol}?freq=weekly`, opts),
        apiFetch(`${API}/indicators/${symbol}?freq=daily&kama=${kama}`, opts),
        apiFetch(`${API}/indicators/${symbol}?freq=weekly&kama=${kama}`, opts),
    ]).then(([dailyOhlcv, weeklyOhlcv, dailyInd, weeklyInd]) => ({
        dailyOhlcv, weeklyOhlcv, dailyInd, weeklyInd,
    }));
    _inflightChartBundles.set(key, pending);
    try {
        return await pending;
    } finally {
        if (_inflightChartBundles.get(key) === pending) _inflightChartBundles.delete(key);
    }
}

async function prefetchChartBundle(symbol, gen, signal) {
    if (peekChartBundle(symbol)) return;
    try {
        const bundle = await fetchChartBundle(symbol, { signal });
        if (gen !== _prefetchGen || (signal && signal.aborted)) return; // ignore stale prefetch
        rememberChartBundle(symbol, bundle);
    } catch (e) {
        if (e && (e.name === 'AbortError' || (signal && signal.aborted))) return; // ignore stale prefetch
        if (gen !== _prefetchGen) return; // ignore stale prefetch
        if (isYahooThrottle(e)) lastFetchError = e;
    }
}

function scheduleNeighborPrefetch(anchorSymbol) {
    abortChartPrefetch(anchorSymbol);
    if (!anchorSymbol) return;
    // j/k walk setup rows; do not prefetch-spam the universe
    if (state.workspace === 'scan') return;
    // Skip prefetch after a 429 so we do not pile onto Yahoo.
    if (isYahooThrottle(lastFetchError)) return;
    const neighbors = neighborVisibleSymbols(anchorSymbol);
    if (!neighbors.length) return;
    const gen = _prefetchGen;
    neighbors.forEach(sym => {
        const code = String(sym).toUpperCase();
        if (peekChartBundle(sym) || _prefetchControllers.has(code)) return;
        const ac = new AbortController();
        _prefetchControllers.set(code, ac);
        prefetchChartBundle(sym, gen, ac.signal).finally(() => {
            if (_prefetchControllers.get(code) === ac) _prefetchControllers.delete(code);
        });
    });
}

async function selectSymbol(symbol) {
    state.activeSymbol = symbol;
    try { if (symbol) localStorage.setItem(LAST_SYMBOL_KEY, symbol); } catch { /* ignore quota */ }
    renderSymbolList();
    if (state.workspace === 'scan' || state.activeTab === 'charts') {
        await loadChartData(symbol);
    } else {
        scheduleNeighborPrefetch(symbol);
        if (state.activeTab === 'news') {
            await loadNewsData(symbol);
        } else if (state.activeTab === 'stats') {
            await loadStatsData(symbol);
        } else if (state.activeTab === 'knn') {
            await loadKNN(symbol);
        } else if (state.activeTab === 'backtest') {
            // Backtest is triggered manually via the Run button; just update header
            updateSymbolHeader(symbol, null);
        } else if (state.activeTab === 'trend') {
            await loadAdaptiveTrendData(symbol);
        }
    }
    // Scanner tab doesn't depend on the selected symbol
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
                if (!ok) {
                    if (isYahooThrottle(lastFetchError)) throw lastFetchError;
                    throw e;
                }
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

// ── News Data Loading ─────────────────────────────────────
async function loadNewsData(symbol) {
    if (!symbol) return;
    showNewsArea();
    
    const loadingEl = document.getElementById('news-loading');
    const listEl = document.getElementById('news-list');
    const emptyEl = document.getElementById('news-empty');
    const errorEl = document.getElementById('news-error');
    
    // Show loading state
    if (loadingEl) loadingEl.style.display = 'flex';
    if (listEl) listEl.innerHTML = '';
    if (emptyEl) emptyEl.style.display = 'none';
    if (errorEl) errorEl.style.display = 'none';
    
    updateSymbolHeader(symbol, null);

    try {
        // Fetch news from API - returns { symbol, articles: [...], article_count, source } or { symbol, message, source } or { symbol, error, source }
        const data = await apiFetch(`${API}/news/${symbol}`);
        
        // Hide loading
        if (loadingEl) loadingEl.style.display = 'none';
        
        // Handle error response
        if (data.error) {
            if (errorEl) {
                errorEl.style.display = 'flex';
                const msgEl = document.getElementById('news-error-message');
                if (msgEl) msgEl.textContent = data.error;
            }
            toast('News error: ' + data.error, 'error');
            return;
        }
        
        // Check if we have articles
        if (!data.articles || data.articles.length === 0) {
            if (emptyEl) {
                emptyEl.style.display = 'flex';
                // If there's a message from the API, show it
                const emptyIcon = emptyEl.querySelector('.empty-icon');
                const emptyText = emptyEl.querySelector('p');
                if (emptyText && data.message) {
                    emptyText.textContent = data.message;
                }
            }
            return;
        }
        
        // Render news items
        renderNews(data.articles);
        
        // Also update header with latest price if available
        try {
            const ohlcv = await apiFetch(`${API}/ohlcv/${symbol}?freq=daily&limit=2`);
            if (ohlcv && ohlcv.length > 0) {
                const last = ohlcv[ohlcv.length - 1];
                const prev = ohlcv[ohlcv.length - 2];
                updateSymbolHeader(symbol, last, prev);
            }
        } catch (e) {
            // Ignore errors fetching price data for news tab
        }
        
    } catch (e) {
        if (loadingEl) loadingEl.style.display = 'none';
        if (errorEl) {
            errorEl.style.display = 'flex';
            const msgEl = document.getElementById('news-error-message');
            if (msgEl) msgEl.textContent = 'Failed to load news: ' + e.message;
        }
        toast('News load failed: ' + e.message, 'error');
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function renderNews(articles) {
    const listEl = document.getElementById('news-list');
    if (!listEl) return;
    
    listEl.innerHTML = '';
    
    articles.forEach(article => {
        const newsItem = document.createElement('div');
        newsItem.className = 'news-item';
        newsItem.addEventListener('click', () => {
            if (article.url) window.open(article.url, '_blank');
        });
        
        // No thumbnail in main's API format - it doesn't include images
        
        // Format publish_time (ISO string like "2026-08-21T10:00:00Z")
        let timeStr = '';
        if (article.publish_time) {
            try {
                const date = new Date(article.publish_time);
                if (!isNaN(date.getTime())) {
                    timeStr = date.toLocaleString('en-US', {
                        month: 'short',
                        day: 'numeric',
                        year: 'numeric',
                        hour: '2-digit',
                        minute: '2-digit'
                    });
                }
            } catch (e) {
                // If parsing fails, don't show time - never invent "2m ago"
                timeStr = '';
            }
        }
        
        // Create content div
        const contentDiv = document.createElement('div');
        contentDiv.className = 'news-item-content';
        
        // Headline (escaped)
        const headlineEl = document.createElement('h4');
        headlineEl.className = 'news-item-headline';
        headlineEl.textContent = article.title || 'No title';
        contentDiv.appendChild(headlineEl);
        
        // Meta (provider + time)
        const metaDiv = document.createElement('div');
        metaDiv.className = 'news-item-meta';
        
        const providerEl = document.createElement('span');
        providerEl.className = 'news-item-provider';
        providerEl.textContent = article.provider || 'Yahoo Finance';
        metaDiv.appendChild(providerEl);
        
        if (timeStr) {
            const timeEl = document.createElement('span');
            timeEl.className = 'news-item-time';
            timeEl.textContent = timeStr;
            metaDiv.appendChild(timeEl);
        }
        
        contentDiv.appendChild(metaDiv);
        newsItem.appendChild(contentDiv);
        listEl.appendChild(newsItem);
    });
}

async function loadChartData(symbol) {
    if (!symbol) return;
    const seq = ++_chartLoadSeq;
    scheduleNeighborPrefetch(symbol);
    const cached = peekChartBundle(symbol);
    state.loading = true;
    showChartArea();
    showLoadingOverlay(!cached);
    updateSymbolHeader(symbol, null);

    try {
        let dailyOhlcv, weeklyOhlcv, dailyInd, weeklyInd;
        if (cached) {
            rememberChartBundle(symbol, cached);
            ({ dailyOhlcv, weeklyOhlcv, dailyInd, weeklyInd } = cached);
        } else {
            let bundle;
            try {
                bundle = await fetchChartBundle(symbol);
            } catch (e) {
                if (e && e.name === 'AbortError') throw e;
                // No data yet — auto-fetch then retry
                toast(`No data for ${symbol}. Downloading…`, 'info');
                const ok = await fetchSymbolData(symbol);
                if (!ok) {
                    if (isYahooThrottle(lastFetchError)) {
                        throw lastFetchError;
                    }
                    throw e;
                }
                await loadSymbols();
                bundle = await fetchChartBundle(symbol);
            }
            rememberChartBundle(symbol, bundle);
            ({ dailyOhlcv, weeklyOhlcv, dailyInd, weeklyInd } = bundle);
        }

        if (seq !== _chartLoadSeq) return;

        initCharts();

        // Fresh symbol → clear any previously-drawn risk box so a stale
        // entry/stop/target from the last name doesn't linger on the chart.
        window.clearRiskBox?.();
        state.riskBox = null;
        ['pm-entry-input', 'pm-stop-input', 'pm-target-input'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        updateRMultiple();

        loadOHLCV('daily',  dailyOhlcv);
        loadOHLCV('weekly', weeklyOhlcv);
        loadIndicatorsToPanel('daily',  dailyInd);
        loadIndicatorsToPanel('weekly', weeklyInd);
        fitContent();
        const pending = window._pendingChartPack;
        if (pending && pending.symbol === symbol && typeof setChartPacksForSetups === 'function') {
            setChartPacksForSetups(pending.setups || []);
        }

        const last = dailyOhlcv[dailyOhlcv.length - 1];
        const prev = dailyOhlcv[dailyOhlcv.length - 2];
        updateSymbolHeader(symbol, last, prev);
        hideYahooThrottleBanner();
    } catch (e) {
        if (seq !== _chartLoadSeq) return;
        if (e && e.name === 'AbortError') return;
        if (isYahooThrottle(e) || isYahooThrottle(lastFetchError)) {
            showYahooThrottleBanner(symbol);
        } else {
            toast('Chart load failed: ' + e.message, 'error');
            showEmptyState();
        }
    } finally {
        if (seq === _chartLoadSeq && window._pendingChartPack && window._pendingChartPack.symbol === symbol) {
            window._pendingChartPack = null;
        }
        if (seq === _chartLoadSeq) {
            state.loading = false;
            showLoadingOverlay(false);
        }
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
                if (!ok) {
                    if (isYahooThrottle(lastFetchError)) throw lastFetchError;
                    throw e;
                }
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
    hideYahooThrottleBanner();
    document.getElementById('empty-state').style.display       = 'flex';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('news-area').style.display         = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'none';
    const pm = document.getElementById('pm-desk');
    if (pm) pm.style.display = 'none';

    const title = document.querySelector('#empty-state h2');
    const blurb = document.querySelector('#empty-state > p');
    const steps = document.querySelector('#empty-state .onboarding-steps');
    if (!state.symbols.length) {
        if (title) title.textContent = 'Welcome to Whats-News';
        if (blurb) blurb.textContent = 'Your local watchlist for charts, analysis, and real Yahoo Finance headlines.';
        if (steps) steps.style.display = '';
    } else {
        if (title) title.textContent = 'Pick a symbol';
        if (blurb) blurb.textContent = 'Click a ticker in the watchlist sidebar to load its chart and analysis.';
        if (steps) steps.style.display = 'none';
    }
}

function setConnectionStatus(ok, label) {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-label');
    if (dot) {
        dot.classList.toggle('ok', !!ok);
        dot.classList.toggle('bad', !ok);
        dot.title = label || (ok ? 'Connected' : 'Disconnected');
    }
    if (text) text.textContent = label || (ok ? 'Online' : 'Offline');
}

async function checkHealth() {
    try {
        const res = await fetch('/api/health');
        const data = await res.json();
        if (res.ok && data.ok) {
            const n = data.symbol_count ?? 0;
            setConnectionStatus(true, n ? `${n} symbols` : 'Online');
            return true;
        }
        setConnectionStatus(false, 'Server error');
        return false;
    } catch (e) {
        setConnectionStatus(false, 'Offline');
        return false;
    }
}

function showChartArea() {
    document.getElementById('empty-state').style.display = 'none';
    document.getElementById('chart-area').style.display  = 'flex';
}

function showLoadingOverlay(show) {
    document.getElementById('chart-loading').style.display = show ? 'flex' : 'none';
}

function syncWorkspacePills() {
    document.querySelectorAll('.workspace-btn').forEach(btn => {
        setPressed(btn, btn.dataset.workspace === state.workspace);
    });
}

function showScanSplit() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('news-area').style.display         = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('data-manager-area').style.display = 'none';
    document.getElementById('chart-area').style.display        = 'flex';
    document.getElementById('scanner-area').style.display      = 'flex';
    state.activeTab = 'charts';
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.id === 'tab-scanner' || btn.id === 'tab-charts');
    });
}

function applyReviewDrawerLayout(on) {
    const book = document.getElementById('book-drawer');
    const journal = document.getElementById('journal-drawer');
    const backdrop = document.getElementById('book-drawer-backdrop');
    if (backdrop) backdrop.hidden = true;
    if (book) {
        if (on) {
            book.classList.add('open');
            book.setAttribute('aria-hidden', 'false');
            book.style.transform = 'translateX(0)';
            book.style.right = '280px';
            book.style.zIndex = '220';
            book.style.width = '340px';
        } else {
            book.style.transform = '';
            book.style.right = '';
            book.style.zIndex = '';
            book.style.width = '';
        }
    }
    if (journal) {
        if (on) {
            journal.style.transform = 'translateX(0)';
            journal.style.width = '280px';
            journal.style.zIndex = '221';
        } else {
            journal.style.transform = '';
            journal.style.width = '';
            journal.style.zIndex = '';
        }
    }
}

function setWorkspace(id, opts = {}) {
    const next = id === 'scan' || id === 'review' ? id : 'chart';
    state.workspace = next;
    document.body.classList.toggle('workspace-scan', next === 'scan');
    document.body.classList.toggle('workspace-review', next === 'review');
    document.body.classList.toggle('workspace-chart', next === 'chart');
    syncWorkspacePills();
    try {
        localStorage.setItem(WORKSPACE_KEY, next === 'review' ? 'chart' : next);
    } catch { /* ignore quota */ }

    if (next === 'scan') {
        applyReviewDrawerLayout(false);
        showScanSplit();
        if (typeof initSetupScanner === 'function') initSetupScanner();
        loadSetupScan({ allowStaleRows: true });
        if (!opts.skipChart && state.activeSymbol) loadChartData(state.activeSymbol);
        requestAnimationFrame(() => window.resizeAllCharts?.());
        return next;
    }

    if (next === 'review') {
        switchTab('news', { keepWorkspace: true });
        openJournal();
        openBookDrawer();
        applyReviewDrawerLayout(true);
        return next;
    }

    applyReviewDrawerLayout(false);
    closeJournal();
    closeBookDrawer();
    if (!opts.fromTab) switchTab('charts', { keepWorkspace: true });
    requestAnimationFrame(() => window.resizeAllCharts?.());
    return next;
}

window.setWorkspace = setWorkspace;

// ── Tab Switching ─────────────────────────────────────────────
async function switchTab(tabId, opts = {}) {
    if (tabId === 'scanner') {
        setWorkspace('scan');
        return;
    }

    if (!opts.keepWorkspace) {
        state.workspace = 'chart';
        document.body.classList.remove('workspace-scan', 'workspace-review');
        document.body.classList.add('workspace-chart');
        syncWorkspacePills();
    }

    state.activeTab = tabId;

    // Update tab buttons
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.id === `tab-${tabId}`);
    });

    // Hide all content areas first
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('news-area').style.display         = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'none';

    if (tabId === 'charts') {
        showChartArea();
        if (state.activeSymbol) loadChartData(state.activeSymbol);
    } else if (tabId === 'news') {
        showNewsArea();
        if (state.activeSymbol) loadNewsData(state.activeSymbol);
    } else if (tabId === 'stats') {
        showStatsArea();
        if (state.activeSymbol) loadStatsData(state.activeSymbol);
    } else if (tabId === 'knn') {
        document.getElementById('knn-area').style.display = 'block';
        if (state.activeSymbol) loadKNN(state.activeSymbol);
    } else if (tabId === 'backtest') {
        document.getElementById('backtest-area').style.display = 'block';
        if (state.activeSymbol) {
            updateSymbolHeader(state.activeSymbol, null);
        }
    } else if (tabId === 'trend') {
        showTrendArea();
        if (typeof renderTrendConfig === 'function') renderTrendConfig();
        if (state.activeSymbol) loadAdaptiveTrendData(state.activeSymbol);
    } else if (tabId === 'data-manager') {
        showDataManagerArea();
        initDataManager();
    }
}

function showStatsArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('news-area').style.display         = 'none';
    document.getElementById('stats-area').style.display        = 'block';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'none';
}

function showChartArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('news-area').style.display         = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('chart-area').style.display        = 'flex';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      =
        state.workspace === 'scan' ? 'flex' : 'none';
    document.getElementById('data-manager-area').style.display = 'none';
}

function showTrendArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('news-area').style.display         = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'flex';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'none';
}

function showScannerArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('news-area').style.display         = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'flex';
    document.getElementById('data-manager-area').style.display = 'none';
}

function showDataManagerArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('news-area').style.display         = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'flex';
}

function showNewsArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('chart-area').style.display        = 'none';
    document.getElementById('news-area').style.display         = 'flex';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'none';
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
    syncNewsSurfaceLabels(symbol);

    if (!last) {
        document.getElementById('sym-price').textContent   = '--';
        document.getElementById('sym-change-badge').textContent = '';
        ['open', 'high', 'low', 'close', 'volume'].forEach(k => {
            const el = document.getElementById(`ohlcv-${k}`);
            if (el) el.textContent = '--';
        });
        const inlineEl = document.getElementById('ohlcv-inline');
        if (inlineEl) inlineEl.textContent = 'O — · H — · L — · C — · V —';
        loadPmDesk(symbol);
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

    const inlineEl = document.getElementById('ohlcv-inline');
    if (inlineEl) {
        inlineEl.textContent = `O $${fmt(last.open)} · H $${fmt(last.high)} · L $${fmt(last.low)} · C $${fmt(last.close)} · V ${fmtVol(last.volume)}`;
    }

    loadPmDesk(symbol);
}

async function loadPmDesk(symbol) {
    const desk = document.getElementById('pm-desk');
    if (!desk || !symbol) return;
    try {
        const riskEl = document.getElementById('pm-risk-input');
        const risk = riskEl ? riskEl.value : 100;
        const params = new URLSearchParams({ risk: risk ?? 100 });
        params.set('stop', state.stopMode);
        if (state.stopMode === 'user') {
            const stopPrice = document.getElementById('pm-stop-input')?.value;
            if (stopPrice) params.set('stop_price', stopPrice);
        }
        const targetVal = document.getElementById('pm-target-input')?.value;
        if (targetVal) params.set('target', targetVal);
        const snap = await apiFetch(`${API}/pm-desk/${symbol}?${params.toString()}`);
        state.portfolio[symbol] = { ...(state.portfolio[symbol] || {}), ...snap };
        renderPmDesk(snap);
    } catch (e) {
        desk.style.display = 'none';
    }
}

function renderPmDesk(snap) {
    const desk = document.getElementById('pm-desk');
    if (!desk || !snap?.ready) {
        if (desk) desk.style.display = 'none';
        return;
    }
    desk.style.display = 'flex';

    const regimeEl = document.getElementById('pm-regime');
    const d = snap.regime || '—';
    const w = snap.regime_weekly && snap.regime_weekly !== 'n/a' ? snap.regime_weekly : '—';
    regimeEl.textContent = `${d} / ${w}`;
    regimeEl.className = `pm-val regime-${snap.regime || 'n/a'}`;
    regimeEl.title = `Daily vs KAMA20 ${snap.vs_kama20_pct ?? '—'}% · Weekly ${snap.vs_kama20_weekly_pct ?? '—'}%`;

    const rsiEl = document.getElementById('pm-rsi');
    rsiEl.textContent = snap.rsi14 != null
        ? `${snap.rsi14} (${snap.rsi_zone})`
        : '—';
    rsiEl.className = `pm-val zone-${snap.rsi_zone || 'n/a'}`;

    const kamaEl = document.getElementById('pm-kama');
    if (snap.vs_kama20_pct != null) {
        const pos = snap.vs_kama20_pct >= 0;
        kamaEl.textContent = `${pos ? '+' : ''}${snap.vs_kama20_pct}%`;
        kamaEl.className = `pm-val ${pos ? 'positive' : 'negative'}`;
    } else {
        kamaEl.textContent = '—';
        kamaEl.className = 'pm-val';
    }

    const retEl = document.getElementById('pm-returns');
    const fmtR = v => v == null ? '—' : `${v >= 0 ? '+' : ''}${v}%`;
    retEl.textContent = `${fmtR(snap.ret_5d_pct)} / ${fmtR(snap.ret_21d_pct)}`;

    const atrEl = document.getElementById('pm-atr');
    atrEl.textContent = snap.atr_pct != null ? `${snap.atr_pct}%` : '—';

    const bookRsEl = document.getElementById('pm-book-rs');
    if (bookRsEl) {
        bookRsEl.textContent = bookRsLabel(snap);
        bookRsEl.title = 'Book RS (21D) — this watchlist’s 21-day return rank, not a published rating';
        bookRsEl.setAttribute('aria-label', `${bookRsLabel(snap)}, watchlist 21-day rank, not a published rating`);
    }

    const peer = document.getElementById('pm-peer');
    if (peer) {
        peer.textContent = snap.peer_etf || 'SPY';
        peer.title = snap.sector ? `Sector: ${snap.sector}` : 'Default peer';
    }

    const darvasEl = document.getElementById('pm-darvas');
    if (darvasEl) {
        const box = snap.darvas;
        if (box?.state) {
            darvasEl.textContent = `${box.state} ${box.bottom}–${box.top}`;
            darvasEl.title = `Box state — not a KAMA pattern. Since ${box.since || '—'} · target ${box.target ?? '—'}`;
        } else {
            darvasEl.textContent = '—';
        }
    }
    // Darvas box is structural/automatic (unlike the discretionary risk box) —
    // draw it whenever fresh PM desk data arrives, gated by the Box pill toggle.
    window.applyDarvasBox?.(snap.darvas || null);

    const sizeEl = document.getElementById('pm-size');
    const size = snap.size || snap.size_risk_100;
    if (sizeEl && size?.shares != null) {
        sizeEl.textContent = `${size.shares} sh · $${size.notional}`;
        sizeEl.title = `Stop distance ${size.stop_distance} (${size.stop_source || 'atr'})`;
    } else if (sizeEl) {
        sizeEl.textContent = '—';
    }

    const stops = document.getElementById('pm-stops');
    if (stops) {
        if (snap.stop_long_1_5atr != null && snap.stop_short_1_5atr != null) {
            stops.textContent = `L ${snap.stop_long_1_5atr} · S ${snap.stop_short_1_5atr}`;
        } else {
            stops.textContent = '—';
        }
    }

    // Pre-fill risk box inputs from the server-computed risk_box (entry/stop/target)
    // the first time we see them for this symbol, so the popover starts primed.
    if (snap.risk_box) {
        const entryInput = document.getElementById('pm-entry-input');
        const stopInput = document.getElementById('pm-stop-input');
        const targetInput = document.getElementById('pm-target-input');
        if (entryInput && !entryInput.value && snap.risk_box.entry != null) entryInput.value = snap.risk_box.entry;
        if (stopInput && !stopInput.value && snap.risk_box.stop != null) stopInput.value = snap.risk_box.stop;
        if (targetInput && !targetInput.value && snap.risk_box.target != null) targetInput.value = snap.risk_box.target;
        updateRMultiple();
    }
}

function copySetupCard() {
    const snap = state.portfolio[state.activeSymbol];
    if (!snap?.ready) {
        toast('No setup to copy — select a loaded symbol', 'warning');
        return;
    }
    const allChecked = Object.values(state.checklist).every(Boolean);
    const entry = parseFloat(document.getElementById('pm-entry-input')?.value);
    const stop = parseFloat(document.getElementById('pm-stop-input')?.value);
    const target = parseFloat(document.getElementById('pm-target-input')?.value);
    const r = computeRMultiple();
    const box = snap.darvas;

    const lines = [
        `${snap.symbol} setup @ ${snap.price}`,
        `Regime D/W: ${snap.regime} / ${snap.regime_weekly || 'n/a'} · vs KAMA20 ${snap.vs_kama20_pct ?? '—'}%`,
        `RSI14: ${snap.rsi14 ?? '—'} (${snap.rsi_zone})`,
        `5D / 21D: ${snap.ret_5d_pct ?? '—'}% / ${snap.ret_21d_pct ?? '—'}%`,
        `${bookRsLabel(snap)}`,
        snap.peer_etf ? `Peer ETF: ${snap.peer_etf}` : null,
        (Number.isFinite(entry) || Number.isFinite(stop) || Number.isFinite(target))
            ? `Risk box: entry ${Number.isFinite(entry) ? entry : '—'} · stop ${Number.isFinite(stop) ? stop : '—'} · target ${Number.isFinite(target) ? target : '—'} · R ${r ?? '—'}`
            : null,
        box?.state ? `Darvas: ${box.state} ${box.bottom}–${box.top} (since ${box.since || '—'})` : null,
        snap.size?.shares != null ? `Size @ $${snap.size.risk_dollars} risk: ${snap.size.shares} sh ($${snap.size.notional})` : null,
        `ATR%: ${snap.atr_pct ?? '—'} · stops 1.5×ATR L ${snap.stop_long_1_5atr} / S ${snap.stop_short_1_5atr}`,
        snap.alert ? `Alert: ${snap.alert}` : null,
        `Checklist: ${allChecked ? 'complete' : 'incomplete'}`,
        'Source: Whats-News PM Desk',
    ].filter(Boolean).join('\n');

    navigator.clipboard.writeText(lines).then(
        () => toast('Setup card copied', 'success'),
        () => toast('Clipboard failed', 'error')
    );
}

function moveSymbolSelection(delta) {
    const codes = (typeof visibleSymbolCodes === 'function' ? visibleSymbolCodes() : null)
        || (state.symbols || []).map(s => s.symbol);
    if (!codes.length) return;
    let idx = codes.indexOf(state.activeSymbol);
    if (idx < 0) idx = 0;
    else idx = (idx + delta + codes.length) % codes.length;
    selectSymbol(codes[idx]);
}

function saveWatchlistPreset() {
    const preset = {
        saved_at: new Date().toISOString(),
        symbols: state.symbols.map(s => ({
            symbol: s.symbol,
            group_tag: s.group_tag || '',
        })),
    };
    localStorage.setItem('wn_watchlist_preset', JSON.stringify(preset));
    toast(`Saved preset (${preset.symbols.length} symbols)`, 'success');
}

async function loadWatchlistPreset() {
    let preset;
    try {
        preset = JSON.parse(localStorage.getItem('wn_watchlist_preset') || 'null');
    } catch {
        preset = null;
    }
    if (!preset?.symbols?.length) {
        toast('No saved preset', 'warning');
        return;
    }
    const codes = preset.symbols.map(s => s.symbol);
    try {
        await apiFetch(`${API}/symbols`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbols: codes }),
        });
        for (const s of preset.symbols) {
            if (s.group_tag) {
                await apiFetch(`${API}/symbols/${s.symbol}/group`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ group_tag: s.group_tag }),
                });
            }
        }
        await loadSymbols();
        toast(`Loaded preset (${codes.length} symbols)`, 'success');
    } catch (e) {
        toast('Preset load failed: ' + e.message, 'error');
    }
}

function toggleFocusMode(force) {
    const on = force ?? !document.body.classList.contains('focus-mode');
    document.body.classList.toggle('focus-mode', on);
    setPressed(document.getElementById('pill-focus'), on);
    const chip = document.getElementById('focus-mode-chip');
    if (chip) chip.hidden = !on;
    toast(on ? 'Focus mode — press f to show the tape' : 'Tape restored', 'info', 2200);
    window.resizeAllCharts?.();
    return on;
}

function isKbdHelpOpen() {
    const el = document.getElementById('kbd-help');
    return !!(el && !el.hidden);
}

let _kbdHelpPrevFocus = null;

function onKbdHelpKeydown(e) {
    if (e.key === 'Escape' || e.key === '?') {
        e.preventDefault();
        closeKbdHelp();
        return;
    }
    trapFocusIn(document.querySelector('#kbd-help .kbd-help-card'), e);
}

function openKbdHelp() {
    const el = document.getElementById('kbd-help');
    const card = el?.querySelector('.kbd-help-card');
    if (!el) return;
    if (typeof closeDeskPalette === 'function') closeDeskPalette();
    _kbdHelpPrevFocus = document.activeElement;
    el.hidden = false;
    setAppInert(true);
    el.addEventListener('keydown', onKbdHelpKeydown);
    requestAnimationFrame(() => (card || el).focus());
}

function closeKbdHelp() {
    const el = document.getElementById('kbd-help');
    if (!el || el.hidden) return;
    el.hidden = true;
    el.removeEventListener('keydown', onKbdHelpKeydown);
    setAppInert(false);
    if (_kbdHelpPrevFocus && typeof _kbdHelpPrevFocus.focus === 'function') {
        _kbdHelpPrevFocus.focus();
    }
    _kbdHelpPrevFocus = null;
}

function toggleKbdHelp() {
    if (isKbdHelpOpen()) closeKbdHelp();
    else openKbdHelp();
}

function setupPmKeyboard() {
    document.addEventListener('keydown', e => {
        const tag = (e.target && e.target.tagName) || '';
        const typing = tag === 'INPUT' || tag === 'TEXTAREA' || e.target?.isContentEditable;
        if (typing) {
            if (e.key === 'Escape') e.target.blur();
            return;
        }
        if (typeof isPaletteOpen === 'function' && isPaletteOpen()) return;
        if (isBulkModalOpen()) return;
        if (isKbdHelpOpen()) {
            if (e.key === 'Escape' || e.key === '?') {
                e.preventDefault();
                closeKbdHelp();
            }
            return;
        }
        if (!e.metaKey && !e.ctrlKey && !e.altKey && (e.key === '1' || e.key === '2' || e.key === '3')) {
            e.preventDefault();
            setWorkspace(e.key === '1' ? 'chart' : e.key === '2' ? 'scan' : 'review');
            return;
        }
        if (state.workspace === 'scan' && !e.metaKey && !e.ctrlKey) {
            if (e.key === 'j' && !e.shiftKey) {
                e.preventDefault();
                window.moveSetupScanSelection?.(1);
                return;
            }
            if (e.key === 'k' && !e.shiftKey) {
                e.preventDefault();
                window.moveSetupScanSelection?.(-1);
                return;
            }
            if (e.key === 'Enter') {
                e.preventDefault();
                window.openSelectedSetupRow?.();
                return;
            }
        }
        // Shift+J → toggle trade journal drawer (plain j/k stay reserved for list nav).
        if (e.shiftKey && (e.key === 'J' || e.key === 'j')) {
            e.preventDefault();
            toggleJournal();
            return;
        }
        if (e.key === 'j') { e.preventDefault(); moveSymbolSelection(1); }
        else if (e.key === 'k' || e.key === 'K') { e.preventDefault(); moveSymbolSelection(-1); }
        else if (e.key === 'h' || e.key === 'H') { e.preventDefault(); toggleBookDrawer(); }
        else if (e.key === 'f') { e.preventDefault(); toggleFocusMode(); }
        else if (e.key === 'r' || e.key === 'R') {
            e.preventDefault();
            if (state.activeSymbol) fetchSymbolData(state.activeSymbol);
            else refreshAll();
        }
        else if (e.key === '?' || (e.shiftKey && e.key === '/')) {
            e.preventDefault();
            openKbdHelp();
        }
        else if (e.key === '/' && !e.shiftKey) {
            e.preventDefault();
            if (typeof openDeskPalette === 'function') openDeskPalette('jump');
            else {
                const input = document.getElementById('new-symbol-input');
                if (input) { input.focus(); input.select(); }
            }
        }
        else if (e.key === 'c' && !e.metaKey && !e.ctrlKey) {
            e.preventDefault();
            copySetupCard();
        }
        else if (e.key === 'Escape') {
            closeBookDrawer();
            closeJournal();
            closePmToolsPopover();
            closeKbdHelp();
            if (typeof closeDeskPalette === 'function') closeDeskPalette();
        }
    });
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
    await checkHealth();
    setInterval(checkHealth, 30000);

    // Seed default KAMA periods
    DEFAULT_KAMA_PERIODS.forEach(p => addKamaPeriod(p));
    renderKamaPills();
    setupKamaAddForm();

    // BB pill
    const bbPill = document.getElementById('pill-bb');
    bbPill.addEventListener('click', () => {
        const on = toggleOverlay('bb');
        bbPill.classList.toggle('active-bb', on);
        bbPill.setAttribute('aria-pressed', on ? 'true' : 'false');
    });

    // EP markers pill (gap ≥4% on volume surge) — on by default
    const epPill = document.getElementById('pill-ep-markers');
    epPill?.addEventListener('click', () => {
        const on = toggleOverlay('ep');
        epPill.classList.toggle('active-ep', on);
    });

    // EMA stack pills (10/21/50) — optional, off by default (Qullamaggie: beside KAMA, not instead of)
    document.querySelectorAll('[data-ema]').forEach(pill => {
        pill.addEventListener('click', () => {
            const p = pill.dataset.ema;
            const on = toggleEma(p);
            pill.classList.toggle('active-ema', on);
            pill.style.borderColor = on ? EMA_COLORS[p] : '';
            pill.style.color = on ? EMA_COLORS[p] : '';
            pill.style.background = on ? EMA_COLORS[p] + '20' : '';
        });
    });

    document.querySelectorAll('[data-chart-pack]').forEach(pill => {
        pill.addEventListener('click', () => {
            toggleChartPack(pill.dataset.chartPack);
        });
    });

    // Darvas box overlay pill — on by default (structural, not KAMA)
    const darvasPill = document.getElementById('pill-darvas');
    darvasPill?.addEventListener('click', () => {
        const on = toggleOverlay('darvas');
        darvasPill.classList.toggle('active-darvas', on);
    });

    // Indicator pane pills (RSI / MACD / Trend) — off by default, price-first.
    // Persisted to localStorage so the layout survives reloads.
    setupPaneToggles();

    // Focus mode pill — hides the portfolio tape for a chart-only view.
    document.getElementById('pill-focus')?.addEventListener('click', () => toggleFocusMode());
    document.getElementById('btn-yahoo-retry')?.addEventListener('click', retryYahooFetch);

    // Buttons
    document.getElementById('btn-add-symbol').addEventListener('click', addSymbol);
    document.getElementById('btn-bulk-add').addEventListener('click', openBulkModal);
    document.getElementById('btn-refresh-all').addEventListener('click', refreshAll);
    document.getElementById('chk-desk-only')?.addEventListener('change', e => {
        toggleDeskOnly(e.target.checked);
    });
    document.getElementById('watchlist-filter')?.addEventListener('input', () => renderSymbolList());
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

    // Close bulk modal on Escape (also trapped inside the dialog)
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeBulkModal();
    });

    // Tape mode segmented control — All / Breakout / Alerts
    document.querySelectorAll('.tape-mode-btn').forEach(btn => {
        btn.addEventListener('click', () => setTapeMode(btn.dataset.mode));
    });
    setTapeMode(state.tapeMode);

    document.getElementById('kbd-help')?.addEventListener('click', e => {
        if (e.target.id === 'kbd-help') closeKbdHelp();
    });
    document.getElementById('kbd-help-close')?.addEventListener('click', closeKbdHelp);
    document.getElementById('tape-book-news')?.addEventListener('click', openBookNews);

    // Book drawer (regime heatmap / alert log / theme leaders)
    document.getElementById('btn-book-drawer')?.addEventListener('click', toggleBookDrawer);
    document.getElementById('btn-book-drawer-close')?.addEventListener('click', closeBookDrawer);
    document.getElementById('book-drawer-backdrop')?.addEventListener('click', closeBookDrawer);

    // Trade journal drawer
    document.getElementById('btn-journal')?.addEventListener('click', toggleJournal);
    document.getElementById('btn-journal-close')?.addEventListener('click', closeJournal);
    document.getElementById('journal-compose')?.addEventListener('submit', saveJournalNote);

    // PM tools popover (risk box, stop mode, checklist, copy/journal)
    document.getElementById('btn-pm-tools')?.addEventListener('click', e => {
        e.stopPropagation();
        togglePmToolsPopover();
    });
    // Click outside the popover (and its trigger) closes it — it has no
    // backdrop, so without this it stays open and blocks the pills beneath it.
    document.addEventListener('click', e => {
        const pop = document.getElementById('pm-tools-popover');
        if (!pop || pop.hidden) return;
        if (pop.contains(e.target) || e.target.closest('#btn-pm-tools')) return;
        closePmToolsPopover();
    });

    ['pm-entry-input', 'pm-stop-input', 'pm-target-input'].forEach(id => {
        document.getElementById(id)?.addEventListener('input', updateRMultiple);
    });

    document.querySelectorAll('input[name="stop-mode"]').forEach(radio => {
        radio.addEventListener('change', e => {
            if (!e.target.checked) return;
            state.stopMode = e.target.value;
            if (state.activeSymbol) loadPmDesk(state.activeSymbol);
        });
    });

    document.getElementById('pm-apply-risk-box')?.addEventListener('click', applyRiskBoxFromInputs);

    document.querySelectorAll('#pm-checklist input[type="checkbox"]').forEach(box => {
        box.addEventListener('change', syncChecklist);
    });
    syncChecklist();

    document.getElementById('pm-copy-setup')?.addEventListener('click', copySetupCard);
    document.getElementById('pm-save-journal')?.addEventListener('click', saveToJournal);

    document.getElementById('btn-preset-save')?.addEventListener('click', saveWatchlistPreset);
    document.getElementById('btn-preset-load')?.addEventListener('click', loadWatchlistPreset);
    document.getElementById('pm-risk-input')?.addEventListener('change', () => {
        if (state.activeSymbol) loadPmDesk(state.activeSymbol);
    });
    setupPmKeyboard();

    document.querySelectorAll('.workspace-btn').forEach(btn => {
        btn.addEventListener('click', () => setWorkspace(btn.dataset.workspace));
    });
    syncWorkspacePills();

    await loadSymbols();

    const codes = (state.symbols || []).map(s => s.symbol).filter(Boolean);
    if (!codes.length) {
        showEmptyState();
    } else {
        let last = null;
        try { last = localStorage.getItem(LAST_SYMBOL_KEY); } catch { last = null; }
        const pick = (last && codes.includes(last)) ? last : codes[0];
        await selectSymbol(pick);
        let ws = 'chart';
        try { ws = localStorage.getItem(WORKSPACE_KEY) || 'chart'; } catch { ws = 'chart'; }
        if (ws === 'scan') setWorkspace('scan', { skipChart: true });
    }
});

// ── Indicator pane visibility (RSI / MACD / Trend) — persisted, price-first ──
function loadSavedPanes() {
    try {
        const raw = JSON.parse(localStorage.getItem(PANES_KEY) || '{}');
        return (raw && typeof raw === 'object') ? raw : {};
    } catch {
        return {};
    }
}

function savePane(name, visible) {
    const panes = loadSavedPanes();
    panes[name] = visible;
    localStorage.setItem(PANES_KEY, JSON.stringify(panes));
}

function setPaneVisible(name, visible) {
    if (typeof window.setIndicatorPane === 'function') {
        window.setIndicatorPane(name, visible);
    } else {
        document.querySelectorAll(`.pane-optional[data-pane="${name}"]`).forEach(el => { el.hidden = !visible; });
        document.querySelectorAll(`.chart-divider-${name}`).forEach(el => { el.hidden = !visible; });
        window.resizeAllCharts?.();
    }
    setPressed(document.getElementById(`pill-pane-${name}`), visible);
    savePane(name, visible);
}

function setupPaneToggles() {
    const panes = ['rsi', 'macd', 'trend'];
    const saved = loadSavedPanes();
    panes.forEach(name => {
        const pill = document.getElementById(`pill-pane-${name}`);
        if (!pill) return;
        pill.addEventListener('click', () => {
            const nowVisible = !pill.classList.contains('active');
            setPaneVisible(name, nowVisible);
        });
        // Default: all optional panes hidden (price-first) unless a prior
        // session explicitly turned one on.
        if (saved[name]) setPaneVisible(name, true);
    });
}
