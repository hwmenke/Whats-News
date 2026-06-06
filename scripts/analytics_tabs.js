// ════════════════════════════════════════════════════════════
// analytics_tabs.js — lightweight UIs for Strategy Tester, KNN Forecast,
// Factor Model, Macro Regression (backends in mod_blueprints).
// ════════════════════════════════════════════════════════════

function _atFmt(v, dp = 2) { return (v === null || v === undefined) ? '—' : Number(v).toFixed(dp); }
function _atPct(v, dp = 1) { return (v === null || v === undefined) ? '—' : (Number(v) * 100).toFixed(dp) + '%'; }
function _atCls(v) { return v == null ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : '')); }
function _atNeedSymbol(elId) {
    if (state.activeSymbol) return false;
    document.getElementById(elId).innerHTML = '<p style="color:#888;padding:14px;">Select a symbol in the watchlist first.</p>';
    return true;
}

let _stEquityChart = null;

// ── Strategy Tester ──────────────────────────────────────────
async function loadStrategyTab() {
    if (_atNeedSymbol('st-body')) return;
    const body = document.getElementById('st-body');
    body.innerHTML = '<p style="color:#888;padding:14px;">Running backtest…</p>';
    let d;
    try {
        d = await apiFetch(`${API}/strategy/backtest`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: state.activeSymbol, freq: 'daily', config: {} }),
        });
    } catch (e) { body.innerHTML = `<p style="color:#e66;padding:14px;">${e.message}</p>`; return; }

    const m = d.metrics || {};
    const card = (label, val, cls = '') =>
        `<div class="jr-stat ${cls}"><div class="jr-stat-val">${val}</div><div class="jr-stat-lbl">${label}</div></div>`;
    body.innerHTML =
        `<div class="jr-stats-grid">
            ${card('CAGR', _atPct(m.cagr), _atCls(m.cagr))}
            ${card('Max DD', _atPct(m.max_drawdown), 'neg')}
            ${card('Profit Factor', _atFmt(m.profit_factor))}
            ${card('Expectancy', _atFmt(m.expectancy))}
            ${card('Trades', m.n_trades ?? '—')}
            ${card('Calmar', _atFmt(m.calmar))}
            ${card('Exposure', _atPct((m.exposure_pct ?? 0) / 100))}
            ${card('Kelly½', _atFmt(m.kelly_half))}
         </div>
         <div class="perf-card" style="margin-top:14px;"><h3>Strategy vs Benchmark (equity)</h3>
            <canvas id="st-equity" height="220"></canvas></div>`;

    if (_stEquityChart) _stEquityChart.destroy();
    const ctx = document.getElementById('st-equity');
    const ds = [{ label: 'Strategy', data: d.equity || [], borderColor: '#3b82f6', pointRadius: 0, tension: 0.1 }];
    if (d.benchmark) ds.push({ label: 'Benchmark', data: d.benchmark, borderColor: '#8b949e', pointRadius: 0, tension: 0.1, borderDash: [4, 4] });
    _stEquityChart = new Chart(ctx, {
        type: 'line',
        data: { labels: (d.dates || []).map((_, i) => i), datasets: ds },
        options: { plugins: { legend: { display: true } }, scales: { x: { display: false } } },
    });
}

// ── KNN Forecast ─────────────────────────────────────────────
async function loadKnnForecastTab() {
    if (_atNeedSymbol('kf-body')) return;
    const body = document.getElementById('kf-body');
    body.innerHTML = '<p style="color:#888;padding:14px;">Computing forecast…</p>';
    let d;
    try {
        d = await apiFetch(`${API}/knn-forecast/${state.activeSymbol}`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ freq: 'daily', k: 20 }),
        });
    } catch (e) { body.innerHTML = `<p style="color:#e66;padding:14px;">${e.message}</p>`; return; }

    const rows = (d.horizons || []).map(h => `<tr>
        <td><b>${h.horizon}d</b></td><td>${h.n}</td>
        <td class="${_atCls(h.bull_pct - 0.5)}">${_atPct(h.bull_pct)}</td>
        <td class="${_atCls(h.mean_ret)}">${_atPct(h.mean_ret)}</td>
        <td class="${_atCls(h.median)}">${_atPct(h.median)}</td>
        <td>${_atPct(h.q25)} / ${_atPct(h.q75)}</td>
        <td>${_atPct(h.confidence)}</td></tr>`).join('');
    body.innerHTML =
        `<p style="color:#888;">${d.k}-nearest analogs of ${d.symbol} (${d.n_train} train rows). Forward-return distribution by horizon:</p>
         <div class="scanner-table-wrap"><table class="scanner-table" style="width:100%;">
         <thead><tr><th>Horizon</th><th>n</th><th>Bull%</th><th>Mean</th><th>Median</th><th>Q25/Q75</th><th>Conf.</th></tr></thead>
         <tbody>${rows || '<tr><td>—</td></tr>'}</tbody></table></div>`;
}

// ── Factor Model ─────────────────────────────────────────────
async function loadFactorModelTab() {
    const body = document.getElementById('fm-body');
    body.innerHTML = '<p style="color:#888;padding:14px;">Loading factor model…</p>';
    let d;
    try { d = await apiFetch(`${API}/factor-model`); }
    catch (e) { body.innerHTML = `<p style="color:#e66;padding:14px;">${e.message}</p>`; return; }

    const rank = (d.alpha_rank || []).map((r, i) => `<tr>
        <td>${i + 1}</td><td><b>${r[0]}</b></td>
        <td class="${_atCls(r[1])}">${_atFmt(r[1], 3)}</td></tr>`).join('');
    const missing = (d.missing_factors && d.missing_factors.length)
        ? `<p style="color:var(--yellow);">Missing factor ETFs (fetch for full model): ${d.missing_factors.join(', ')}</p>` : '';
    body.innerHTML = missing +
        `<p style="color:#888;">Annualized alpha vs the factor set, ranked across your watchlist.</p>
         <div class="scanner-table-wrap"><table class="scanner-table" style="width:100%;">
         <thead><tr><th>#</th><th>Symbol</th><th>Alpha</th></tr></thead>
         <tbody>${rank || '<tr><td>—</td></tr>'}</tbody></table></div>`;
}

// ── Macro Regression ─────────────────────────────────────────
async function loadRegressionTab() {
    if (_atNeedSymbol('reg-body')) return;
    const body = document.getElementById('reg-body');
    body.innerHTML = '<p style="color:#888;padding:14px;">Running regression…</p>';
    let d;
    try { d = await apiFetch(`${API}/regression/${state.activeSymbol}`); }
    catch (e) {
        body.innerHTML = `<p style="color:#e66;padding:14px;">${e.message}</p>
            <p style="color:#888;">Macro regression needs factor ETFs (e.g. IWM, IWD, IWF, TLT, GLD) fetched into the watchlist.</p>`;
        return;
    }
    const betas = (d.factors || d.betas || []);
    const rows = Array.isArray(betas) ? betas.map(f => `<tr>
        <td><b>${f.name || f.factor}</b></td>
        <td class="${_atCls(f.beta ?? f.coef)}">${_atFmt(f.beta ?? f.coef, 3)}</td>
        <td>${_atFmt(f.t_stat ?? f.tstat, 2)}</td></tr>`).join('') : '';
    body.innerHTML =
        `<div class="jr-stats-grid">
            <div class="jr-stat"><div class="jr-stat-val">${_atFmt(d.r_squared ?? d.r2, 3)}</div><div class="jr-stat-lbl">R²</div></div>
            <div class="jr-stat"><div class="jr-stat-val">${d.n_obs ?? d.n ?? '—'}</div><div class="jr-stat-lbl">Obs</div></div>
         </div>
         <div class="scanner-table-wrap" style="margin-top:12px;"><table class="scanner-table" style="width:100%;">
         <thead><tr><th>Factor</th><th>Beta</th><th>t-stat</th></tr></thead>
         <tbody>${rows || '<tr><td colspan=3>No factor betas returned.</td></tr>'}</tbody></table></div>`;
}
