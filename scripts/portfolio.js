/**
 * portfolio.js — Portfolio backtesting tab.
 *
 * Depends on: app.js (state, apiFetch, toast, API),
 *             strategy_tester.js (stAddConditionRow, _readConditionRows),
 *             chart_helpers.js (updateOrCreate)
 */

const ptState = {
    freq:    'daily',
    result:  null,
    charts:  {},
};

// ── Symbol list ───────────────────────────────────────────────
function ptRenderSymbolList() {
    const el = document.getElementById('pt-symbol-list');
    if (!el || typeof state === 'undefined') return;

    const symbols = state.symbols || [];
    el.innerHTML = symbols.map(s =>
        `<label class="pt-sym-item">
            <input type="checkbox" class="pt-sym-check" value="${s.symbol}"> ${s.symbol}
            ${s.name ? `<span class="pt-sym-name">${s.name}</span>` : ''}
         </label>`
    ).join('');
}

function ptGetSelectedSymbols() {
    return [...document.querySelectorAll('.pt-sym-check:checked')].map(c => c.value);
}

// ── Frequency toggle ──────────────────────────────────────────
function ptSetFreq(f) {
    ptState.freq = f;
    document.querySelectorAll('#portfolio-area .st-freq-btn').forEach(b => {
        b.classList.toggle('st-active', b.dataset.val === f);
    });
}

// ── Condition rows (reuse strategy_tester UI) ─────────────────
function ptAddConditionRow(containerId) {
    if (typeof stAddConditionRow === 'function') {
        stAddConditionRow(containerId);
    }
}

function ptReadConfig() {
    const entryLong  = typeof _readConditionRows === 'function' ? _readConditionRows('pt-entry-long-rows') : null;
    const exitLong   = typeof _readConditionRows === 'function' ? _readConditionRows('pt-exit-long-rows')  : null;
    const commission = parseFloat(document.getElementById('pt-commission')?.value || '0.05') / 100;
    const slippage   = parseFloat(document.getElementById('pt-slippage')?.value  || '0.05') / 100;
    const sizingEl   = document.querySelector('input[name="pt-sizing"]:checked');
    const sizing     = sizingEl ? sizingEl.value : 'vol_target';

    return { entryLong, exitLong, commission, slippage, sizing };
}

// ── Run portfolio backtest ────────────────────────────────────
async function ptRunBacktest() {
    const symbols = ptGetSelectedSymbols();
    if (!symbols.length) { toast('Select at least one symbol', 'warning'); return; }

    const { entryLong, exitLong, commission, slippage, sizing } = ptReadConfig();

    const config = { commission_pct: commission, slippage_pct: slippage };
    if (entryLong) config.entry_long = entryLong;
    if (exitLong)  config.exit_long  = exitLong;

    _ptSetLoading(true);
    try {
        const data = await apiFetch(`${API}/strategy/portfolio-backtest`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ symbols, freq: ptState.freq, config, sizing }),
        });
        ptState.result = data;
        _ptRenderResults(data);
    } catch (e) {
        _ptShowError(e.message + (e.hint ? ' — ' + e.hint : ''));
    } finally {
        _ptSetLoading(false);
    }
}

// ── Render results ────────────────────────────────────────────
function _ptRenderResults(data) {
    document.getElementById('pt-empty').style.display   = 'none';
    document.getElementById('pt-results').style.display = '';

    _ptRenderMetrics(data.metrics);
    _ptRenderEquityChart(data);
    _ptRenderLegChart(data);
    _ptRenderWeightChart(data);
    _ptRenderContribution(data.metrics.per_leg_contribution);
}

function _ptRenderMetrics(m) {
    const el = document.getElementById('pt-metrics-row');
    if (!el) return;
    const fmt = (v, pct, dec = 2) => {
        if (v == null) return '—';
        return pct ? (v * 100).toFixed(dec) + '%' : (typeof v === 'number' ? v.toFixed(dec) : v);
    };
    const c = v => v == null ? '' : v > 0 ? 'st-kpi-pos' : v < 0 ? 'st-kpi-neg' : '';
    const kpis = [
        { label: 'Total Return', val: m.total_return,      pct: true },
        { label: 'CAGR',         val: m.cagr,              pct: true },
        { label: 'Sharpe',       val: m.sharpe,            pct: false },
        { label: 'Vol (ann)',     val: m.vol_ann,           pct: true },
        { label: 'Max DD',       val: m.max_drawdown,      pct: true },
        { label: 'Turnover',     val: m.turnover_ann,      pct: true },
        { label: 'Avg Corr',     val: m.avg_pairwise_corr, pct: false, dec: 3 },
        { label: '# Symbols',    val: m.n_symbols,         pct: false, dec: 0 },
        { label: 'Overlap',      val: m.intersection_pct,  pct: true },
    ];
    el.innerHTML = kpis.map(({ label, val, pct, dec }) =>
        `<div class="st-kpi">` +
        `<div class="st-kpi-label">${label}</div>` +
        `<div class="st-kpi-value ${c(val)}">${fmt(val, pct, dec)}</div>` +
        `</div>`
    ).join('');
}

function _ptRenderEquityChart(data) {
    const canvas = document.getElementById('pt-equity-chart');
    if (!canvas || !data.dates?.length) return;
    ptState.charts['equity'] = updateOrCreate('pt.equity', canvas, {
        type: 'line',
        data: {
            labels: data.dates,
            datasets: [
                { label: 'Portfolio', data: data.equity,   borderColor: '#3b82f6', borderWidth: 2, pointRadius: 0, fill: false },
                { label: 'Benchmark', data: data.benchmark, borderColor: '#94a3b8', borderWidth: 1, borderDash: [4, 3], pointRadius: 0, fill: false },
            ],
        },
        options: _ptChartOpts(),
    });
}

function _ptRenderLegChart(data) {
    const canvas = document.getElementById('pt-leg-chart');
    if (!canvas || !data.dates?.length) return;
    const COLORS = ['#3b82f6','#22c55e','#f59e0b','#a855f7','#ef4444','#06b6d4','#f97316','#84cc16'];
    const syms = data.symbols || Object.keys(data.per_leg_equity || {});
    const datasets = syms.map((sym, i) => ({
        label:       sym,
        data:        (data.per_leg_equity?.[sym] || []).map(v => v == null ? null : v),
        borderColor: COLORS[i % COLORS.length],
        borderWidth: 1.5,
        pointRadius: 0,
        fill:        false,
        spanGaps:    false,
    }));
    ptState.charts['legs'] = updateOrCreate('pt.legs', canvas, {
        type: 'line',
        data: { labels: data.dates, datasets },
        options: _ptChartOpts(true),
    });
}

function _ptRenderWeightChart(data) {
    const canvas = document.getElementById('pt-weight-chart');
    if (!canvas || !data.dates?.length) return;
    const COLORS = ['#3b82f6','#22c55e','#f59e0b','#a855f7','#ef4444','#06b6d4','#f97316','#84cc16'];
    const syms = data.symbols || Object.keys(data.weights || {});
    const datasets = syms.map((sym, i) => ({
        label:           sym,
        data:            (data.weights?.[sym] || []).map(v => v == null ? null : v),
        borderColor:     COLORS[i % COLORS.length],
        backgroundColor: COLORS[i % COLORS.length] + '33',
        borderWidth:     1,
        pointRadius:     0,
        fill:            true,
        spanGaps:        false,
    }));
    ptState.charts['weights'] = updateOrCreate('pt.weights', canvas, {
        type: 'line',
        data: { labels: data.dates, datasets },
        options: { ..._ptChartOpts(true), plugins: { ..._ptChartOpts(true).plugins, tooltip: { mode: 'index' } } },
    });
}

function _ptRenderContribution(contrib) {
    const el = document.getElementById('pt-contribution-table');
    if (!el || !contrib) return;
    const rows = Object.entries(contrib).map(([sym, c]) =>
        `<tr>
            <td style="padding:4px 8px;color:var(--text-primary)">${sym}</td>
            <td style="padding:4px 8px;color:${c.contribution_pct >= 0 ? 'var(--green)' : 'var(--red)'};font-variant-numeric:tabular-nums">${(c.contribution_pct * 100).toFixed(1)}%</td>
            <td style="padding:4px 8px;color:var(--text-secondary);font-variant-numeric:tabular-nums">${(c.avg_weight * 100).toFixed(1)}%</td>
            <td style="padding:4px 8px;color:var(--text-secondary)">${c.n_trades}</td>
         </tr>`
    ).join('');
    el.innerHTML = `<div class="st-chart-label">Leg Contribution</div>
        <table style="font-size:11px;border-collapse:collapse;width:100%">
        <thead><tr>
            <th style="padding:4px 8px;text-align:left;color:var(--text-dim)">Symbol</th>
            <th style="padding:4px 8px;text-align:left;color:var(--text-dim)">Contribution</th>
            <th style="padding:4px 8px;text-align:left;color:var(--text-dim)">Avg Weight</th>
            <th style="padding:4px 8px;text-align:left;color:var(--text-dim)"># Trades</th>
        </tr></thead>
        <tbody>${rows}</tbody></table>`;
}

function _ptChartOpts(legend = false) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
            legend: { display: legend, position: 'top', labels: { color: '#94a3b8', font: { size: 10 } } },
        },
        scales: {
            x: { display: false },
            y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#1e293b' } },
        },
    };
}

// ── Loading / error helpers ───────────────────────────────────
function _ptSetLoading(on) {
    const loadEl    = document.getElementById('pt-loading');
    const emptyEl   = document.getElementById('pt-empty');
    const resultsEl = document.getElementById('pt-results');
    const btnRun    = document.getElementById('btn-pt-run');
    if (on) {
        if (loadEl)    loadEl.style.display    = '';
        if (emptyEl)   emptyEl.style.display   = 'none';
        if (resultsEl) resultsEl.style.display = 'none';
        if (btnRun)  { btnRun.disabled = true; btnRun.textContent = '⏳ Running…'; }
    } else {
        if (loadEl) loadEl.style.display = 'none';
        if (btnRun) { btnRun.disabled = false; btnRun.textContent = '▶ Run Portfolio'; }
    }
}

function _ptShowError(msg) {
    const el = document.getElementById('pt-empty');
    if (el) {
        el.style.display = '';
        el.innerHTML = `<div class="empty-icon">⚠</div><p>${msg}</p>`;
    }
}

// ── Init (called by switchTab) ────────────────────────────────
function initPortfolioTester() {
    ptRenderSymbolList();
}
