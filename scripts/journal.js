// ════════════════════════════════════════════════════════════
// journal.js — Trade journal UI (PnL / R-multiple, sizing, screenshots)
// Reuses API, apiFetch, toast, state, captureMainChartDataURL from the app.
// ════════════════════════════════════════════════════════════

let jrSettings = { equity: 100000, risk_pct: 1.0 };
let jrView = 'open';

function jrFmt(v, dp = 2) {
    return (v === null || v === undefined) ? '—' : Number(v).toFixed(dp);
}
function jrEsc(s) {
    return String(s ?? '').replace(/[&<>"]/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

async function initJournal() {
    try {
        jrSettings = await apiFetch(`${API}/settings`);
    } catch (e) { /* defaults */ }
    document.getElementById('jr-equity').value = jrSettings.equity;
    document.getElementById('jr-risk').value   = jrSettings.risk_pct;
    if (!document.getElementById('f-entry-date').value) {
        document.getElementById('f-entry-date').value = new Date().toISOString().slice(0, 10);
    }
    if (state && state.activeSymbol && !document.getElementById('f-symbol').value) {
        document.getElementById('f-symbol').value = state.activeSymbol;
    }
    recomputeSizing();
    await loadJournalStats();
    await loadTrades(jrView);
}

async function saveJournalSettings() {
    const equity   = parseFloat(document.getElementById('jr-equity').value);
    const risk_pct = parseFloat(document.getElementById('jr-risk').value);
    try {
        jrSettings = await apiFetch(`${API}/settings`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ equity, risk_pct }),
        });
        toast('Settings saved', 'success');
        recomputeSizing();
        await loadJournalStats();
    } catch (e) { toast(e.message, 'error'); }
}

// ── Live position sizing (mirrors risk.position_size) ────────
function recomputeSizing() {
    const equity = parseFloat(document.getElementById('jr-equity').value) || jrSettings.equity;
    const risk   = parseFloat(document.getElementById('jr-risk').value)   || jrSettings.risk_pct;
    const entry  = parseFloat(document.getElementById('f-entry').value);
    const stop   = parseFloat(document.getElementById('f-stop').value);
    const box    = document.getElementById('jr-sizing');

    if (!entry || !stop || entry === stop) { box.innerHTML = ''; return; }
    const dollarRisk = equity * (risk / 100);
    const rps        = Math.abs(entry - stop);
    const shares     = Math.floor(dollarRisk / rps);
    const posVal     = shares * entry;
    const pctEq      = posVal / equity * 100;

    document.getElementById('f-shares').value = shares;
    const capWarn = pctEq > 30
        ? `<span class="neg">⚠ ${jrFmt(pctEq, 0)}% of equity — over 30% overnight cap</span>`
        : (pctEq > 20 ? `<span class="neg">⚠ ${jrFmt(pctEq, 0)}% of equity — above normal 20% size</span>` : '');
    box.innerHTML =
        `<span>1R risk <b>$${jrFmt(rps)}</b>/sh</span>` +
        `<span>Risk budget <b>$${jrFmt(dollarRisk, 0)}</b></span>` +
        `<span>Suggested <b>${shares}</b> sh</span>` +
        `<span>Position <b>$${jrFmt(posVal, 0)}</b></span>` +
        `<span>${jrFmt(pctEq, 1)}% of equity</span>` +
        capWarn;
}

function captureEntryChart() {
    const url = (typeof captureMainChartDataURL === 'function') ? captureMainChartDataURL() : null;
    if (!url) { toast('Open a chart first, then capture', 'error'); return; }
    document.getElementById('f-chart').value = url;
    const thumb = document.getElementById('f-chart-thumb');
    thumb.src = url; thumb.style.display = 'block';
    toast('Chart captured', 'success');
}

async function submitTrade() {
    const payload = {
        symbol:          document.getElementById('f-symbol').value,
        direction:       document.getElementById('f-direction').value,
        setup_type:      document.getElementById('f-setup').value,
        entry_price:     parseFloat(document.getElementById('f-entry').value),
        stop_price:      parseFloat(document.getElementById('f-stop').value),
        shares:          parseFloat(document.getElementById('f-shares').value),
        entry_date:      document.getElementById('f-entry-date').value,
        entry_time:      document.getElementById('f-entry-time').value,
        chart_entry_url: document.getElementById('f-chart').value,
        notes:           document.getElementById('f-notes').value,
        risk_pct:        parseFloat(document.getElementById('jr-risk').value),
        equity_at_entry: parseFloat(document.getElementById('jr-equity').value),
    };
    if (!payload.symbol || !payload.entry_price || !payload.stop_price) {
        toast('Symbol, entry and stop are required', 'error'); return;
    }
    try {
        await apiFetch(`${API}/journal/trades`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        toast('Trade added', 'success');
        ['f-symbol', 'f-setup', 'f-entry', 'f-stop', 'f-shares', 'f-chart', 'f-notes', 'f-entry-time']
            .forEach(id => document.getElementById(id).value = '');
        document.getElementById('f-chart-thumb').style.display = 'none';
        document.getElementById('jr-sizing').innerHTML = '';
        await loadJournalStats();
        await loadTrades('open');
        switchJournalView('open');
    } catch (e) { toast(e.message, 'error'); }
}

function switchJournalView(view) {
    jrView = view;
    document.getElementById('jr-stab-open').classList.toggle('trend-stab-active', view === 'open');
    document.getElementById('jr-stab-closed').classList.toggle('trend-stab-active', view === 'closed');
    loadTrades(view);
}

async function loadJournalStats() {
    let s;
    try { s = await apiFetch(`${API}/journal/stats`); } catch (e) { return; }
    const card = (label, val, cls = '') =>
        `<div class="jr-stat ${cls}"><div class="jr-stat-val">${val}</div><div class="jr-stat-lbl">${label}</div></div>`;
    const rcls = v => v == null ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));
    document.getElementById('jr-stats').innerHTML =
        card('Closed Trades', s.total_closed) +
        card('Batting Avg', jrFmt(s.batting_average, 1) + '%') +
        card('Expectancy', jrFmt(s.expectancy_r) + 'R', rcls(s.expectancy_r)) +
        card('Avg Win', jrFmt(s.avg_win_r) + 'R', 'pos') +
        card('Avg Loss', jrFmt(s.avg_loss_r) + 'R', 'neg') +
        card('Total R (closed)', jrFmt(s.total_r_closed) + 'R', rcls(s.total_r_closed)) +
        card('Total R (open)', jrFmt(s.total_r_open) + 'R', rcls(s.total_r_open)) +
        card('Total R (all)', jrFmt(s.total_r_all) + 'R', rcls(s.total_r_all)) +
        card('Realized PnL', '$' + jrFmt(s.total_pnl_usd, 0), rcls(s.total_pnl_usd)) +
        card('Open Positions', s.open_positions) +
        card('Portfolio Heat', s.portfolio_heat == null ? '—' : jrFmt(s.portfolio_heat, 1) + '%');
}

async function loadTrades(status) {
    let rows;
    try { rows = await apiFetch(`${API}/journal/trades?status=${status}`); }
    catch (e) { toast(e.message, 'error'); return; }
    const t = document.getElementById('jr-table');

    if (!rows.length) {
        t.innerHTML = `<tbody><tr><td style="padding:20px; text-align:center; color:#888;">No ${status} trades yet.</td></tr></tbody>`;
        return;
    }
    const isOpen = status === 'open';
    const head = `<thead><tr>
        <th>Symbol</th><th>Dir</th><th>Setup</th><th>Entry</th><th>Stop</th>
        <th>${isOpen ? 'Current' : 'Exit'}</th><th>% Move</th><th>R</th>
        <th>${isOpen ? 'Unreal PnL' : 'PnL'}</th><th>Result</th><th>Chart</th><th></th>
      </tr></thead>`;
    const rcls = v => v == null ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));
    const body = rows.map(r => {
        const px   = isOpen ? r.current_price : r.exit_price;
        const link = (u, lbl) => u ? `<a href="${jrEsc(u)}" target="_blank">${lbl}</a>` : '';
        const charts = link(r.chart_entry_url, '📷in') + ' ' + link(r.chart_exit_url, '📷out');
        const action = isOpen
            ? `<button class="btn btn-ghost btn-sm" onclick="promptClose(${r.id}, ${px || ''})">Close</button>`
            : `<button class="btn btn-ghost btn-sm" onclick="deleteTrade(${r.id})">✕</button>`;
        return `<tr>
            <td><b>${jrEsc(r.symbol)}</b></td>
            <td>${jrEsc(r.direction)}</td>
            <td>${jrEsc(r.setup_type)}</td>
            <td>${jrFmt(r.entry_price)}</td>
            <td>${jrFmt(r.stop_price)}</td>
            <td>${jrFmt(px)}</td>
            <td class="${rcls(r.pct_move)}">${jrFmt(r.pct_move, 1)}%</td>
            <td class="${rcls(r.r_multiple)}"><b>${jrFmt(r.r_multiple)}</b></td>
            <td class="${rcls(r.pnl)}">${r.pnl == null ? '—' : '$' + jrFmt(r.pnl, 0)}</td>
            <td>${jrEsc(r.result || '')}</td>
            <td>${charts}</td>
            <td>${action}</td>
        </tr>`;
    }).join('');
    t.innerHTML = head + `<tbody>${body}</tbody>`;
}

async function promptClose(id, suggested) {
    const v = prompt('Exit price:', suggested || '');
    if (v === null) return;
    const exit = parseFloat(v);
    if (!exit) { toast('Invalid exit price', 'error'); return; }
    let chartExit = '';
    if (confirm('Capture current chart as exit screenshot?')) {
        chartExit = (typeof captureMainChartDataURL === 'function') ? (captureMainChartDataURL() || '') : '';
    }
    try {
        await apiFetch(`${API}/journal/trades/${id}/close`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ exit_price: exit, chart_exit_url: chartExit }),
        });
        toast('Trade closed', 'success');
        await loadJournalStats();
        await loadTrades(jrView);
    } catch (e) { toast(e.message, 'error'); }
}

async function deleteTrade(id) {
    if (!confirm('Delete this trade?')) return;
    try {
        await apiFetch(`${API}/journal/trades/${id}`, { method: 'DELETE' });
        await loadJournalStats();
        await loadTrades(jrView);
    } catch (e) { toast(e.message, 'error'); }
}
