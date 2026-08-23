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
    tapeAlertsOnly: false,
    seenAlerts: new Set(),
};

let statsCharts = {};
let backtestEquityChart = null;
let scannerPollTimer = null;

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
        state.symbols = await apiFetch(`${API}/symbols`);
        renderSymbolList();
        refreshPortfolioTape(); // non-blocking enrich with % change
    } catch (e) {
        toast('Failed to load symbols: ' + e.message, 'error');
    }
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
    if (rs) metaBits += ` · RS#1 ${rs.symbol}`;
    if (data.correlation) {
        const c = data.correlation;
        metaBits += ` · ρ ${c.pair[0]}/${c.pair[1]} ${c.corr_30d} (${c.note})`;
    }
    if (data.group_rollup?.length) {
        const topG = data.group_rollup[0];
        metaBits += ` · grp ${topG.group} ${topG.avg_change_pct >= 0 ? '+' : ''}${topG.avg_change_pct}%`;
    }
    meta.textContent = metaBits;

    const tape = state.tapeAlertsOnly
        ? tapeAll.filter(r => r.alert)
        : tapeAll;

    chips.innerHTML = '';
    if (!tape.length) {
        chips.innerHTML = '<span style="color:var(--text-dim);font-size:11px;">No alerting names</span>';
    } else {
        tape.forEach(row => {
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
                <span class="tape-rs">RS ${row.rs_rank_21d ?? '—'}/${row.rs_n ?? '—'}${dw}</span>
                ${row.alert ? `<span class="tape-alert">${row.alert}</span>` : ''}
            `;
            chip.title = `D ${row.regime || ''} / W ${row.regime_weekly || ''} · RSI ${row.rsi14 ?? '—'}`;
            chip.addEventListener('click', () => selectSymbol(row.symbol));
            chips.appendChild(chip);
        });
    }

    renderRegimeHeatmap(data);
    renderAlertLog(data);
}

function renderRegimeHeatmap(data) {
    const panels = document.getElementById('pm-panels');
    const heat = document.getElementById('regime-heatmap');
    if (!panels || !heat) return;
    const rows = data.heatmap || [];
    if (!rows.length) {
        panels.style.display = 'none';
        return;
    }
    panels.style.display = 'grid';
    heat.innerHTML = '';
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

async function openBookNews() {
    const focus = state.portfolioMeta?.news_focus || state.portfolioMeta?.alerts || [];
    if (!focus.length) {
        toast('No alert/weak-RS names for book news yet', 'info');
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
        tagBadge.textContent = tag || '+ tag';
        tagBadge.title       = 'Click to set group';
        tagBadge.addEventListener('click', e => {
            e.stopPropagation();
            startTagEdit(sym.symbol, tag, tagBadge);
        });

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
    } else if (state.activeTab === 'news') {
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

// ── Tab Switching ─────────────────────────────────────────────
async function switchTab(tabId) {
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
    document.querySelector('.tab-bar').style.display           = 'none';

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
    } else if (tabId === 'scanner') {
        showScannerArea();
        loadScannerData();
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
    document.querySelector('.tab-bar').style.display           = 'none';
}

function showChartArea() {
    document.getElementById('empty-state').style.display       = 'none';
    document.getElementById('news-area').style.display         = 'none';
    document.getElementById('stats-area').style.display        = 'none';
    document.getElementById('knn-area').style.display          = 'none';
    document.getElementById('backtest-area').style.display     = 'none';
    document.getElementById('chart-area').style.display        = 'flex';
    document.getElementById('trend-area').style.display        = 'none';
    document.getElementById('scanner-area').style.display      = 'none';
    document.getElementById('data-manager-area').style.display = 'none';
    document.querySelector('.tab-bar').style.display           = 'flex';
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
    document.querySelector('.tab-bar').style.display           = 'none';
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
    document.querySelector('.tab-bar').style.display           = 'none';
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
    document.querySelector('.tab-bar').style.display           = 'none';
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
    document.querySelector('.tab-bar').style.display           = 'flex';
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
    loadPmDesk(symbol);
}

async function loadPmDesk(symbol) {
    const desk = document.getElementById('pm-desk');
    if (!desk || !symbol) return;
    try {
        const riskEl = document.getElementById('pm-risk-input');
        const risk = riskEl ? riskEl.value : 100;
        const snap = await apiFetch(`${API}/pm-desk/${symbol}?risk=${encodeURIComponent(risk)}`);
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
    if (snap.rs_rank_21d) atrEl.title = `RS #${snap.rs_rank_21d}/${snap.rs_n}`;

    const peer = document.getElementById('pm-peer');
    if (peer) {
        peer.textContent = snap.peer_etf || 'SPY';
        peer.title = snap.sector ? `Sector: ${snap.sector}` : 'Default peer';
    }

    const sizeEl = document.getElementById('pm-size');
    const size = snap.size || snap.size_risk_100;
    if (sizeEl && size?.shares != null) {
        sizeEl.textContent = `${size.shares} sh · $${size.notional}`;
        sizeEl.title = `Stop distance ${size.stop_distance} (1.5×ATR)`;
    } else if (sizeEl) {
        sizeEl.textContent = '—';
    }

    const stops = document.getElementById('pm-stops');
    if (snap.stop_long_1_5atr != null && snap.stop_short_1_5atr != null) {
        stops.textContent = `L ${snap.stop_long_1_5atr} · S ${snap.stop_short_1_5atr}`;
    } else {
        stops.textContent = '—';
    }
}

function copySetupCard() {
    const snap = state.portfolio[state.activeSymbol];
    if (!snap?.ready) {
        toast('No setup to copy — select a loaded symbol', 'warning');
        return;
    }
    const lines = [
        `${snap.symbol} setup @ ${snap.price}`,
        `Regime D/W: ${snap.regime} / ${snap.regime_weekly || 'n/a'} · vs KAMA20 ${snap.vs_kama20_pct ?? '—'}%`,
        `RSI14: ${snap.rsi14 ?? '—'} (${snap.rsi_zone})`,
        `5D / 21D: ${snap.ret_5d_pct ?? '—'}% / ${snap.ret_21d_pct ?? '—'}%`,
        snap.rs_rank_21d ? `RS rank 21D: #${snap.rs_rank_21d}/${snap.rs_n}` : null,
        snap.peer_etf ? `Peer ETF: ${snap.peer_etf}` : null,
        snap.size?.shares != null ? `Size @ $${snap.size.risk_dollars} risk: ${snap.size.shares} sh ($${snap.size.notional})` : null,
        `ATR%: ${snap.atr_pct ?? '—'} · stops 1.5×ATR L ${snap.stop_long_1_5atr} / S ${snap.stop_short_1_5atr}`,
        snap.alert ? `Alert: ${snap.alert}` : null,
        'Source: Whats-News PM Desk',
    ].filter(Boolean).join('\n');

    navigator.clipboard.writeText(lines).then(
        () => toast('Setup card copied', 'success'),
        () => toast('Clipboard failed', 'error')
    );
}

function moveSymbolSelection(delta) {
    if (!state.symbols.length) return;
    const codes = state.symbols.map(s => s.symbol);
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

function setupPmKeyboard() {
    document.addEventListener('keydown', e => {
        const tag = (e.target && e.target.tagName) || '';
        const typing = tag === 'INPUT' || tag === 'TEXTAREA' || e.target?.isContentEditable;
        if (typing) {
            if (e.key === 'Escape') e.target.blur();
            return;
        }
        if (e.key === 'j' || e.key === 'J') { e.preventDefault(); moveSymbolSelection(1); }
        else if (e.key === 'k' || e.key === 'K') { e.preventDefault(); moveSymbolSelection(-1); }
        else if (e.key === 'r' || e.key === 'R') {
            e.preventDefault();
            if (state.activeSymbol) fetchSymbolData(state.activeSymbol);
            else refreshAll();
        }
        else if (e.key === '/') {
            e.preventDefault();
            const input = document.getElementById('new-symbol-input');
            if (input) { input.focus(); input.select(); }
        }
        else if ((e.key === 'c' || e.key === 'C') && !e.metaKey && !e.ctrlKey) {
            e.preventDefault();
            copySetupCard();
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

    // Close bulk modal on Escape
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeBulkModal();
    });

    document.getElementById('pm-copy-setup')?.addEventListener('click', copySetupCard);
    document.getElementById('tape-alerts-only')?.addEventListener('change', e => {
        state.tapeAlertsOnly = !!e.target.checked;
        if (state.portfolioMeta) renderPortfolioTape(state.portfolioMeta);
    });
    document.getElementById('tape-book-news')?.addEventListener('click', openBookNews);
    document.getElementById('btn-preset-save')?.addEventListener('click', saveWatchlistPreset);
    document.getElementById('btn-preset-load')?.addEventListener('click', loadWatchlistPreset);
    document.getElementById('pm-risk-input')?.addEventListener('change', () => {
        if (state.activeSymbol) loadPmDesk(state.activeSymbol);
    });
    setupPmKeyboard();

    await loadSymbols();

    if (state.symbols.length && state.symbols[0].last_fetch) {
        selectSymbol(state.symbols[0].symbol);
    } else {
        showEmptyState();
    }
});
