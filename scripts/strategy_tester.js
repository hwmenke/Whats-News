/**
 * strategy_tester.js — Strategy Tester tab
 *
 * Condition builder → API calls → LWC price chart with markers
 * + equity vs benchmark chart + metrics KPI row + trades table
 * + walk-forward fold table + optional Monte Carlo fan chart
 */

// ── State ──────────────────────────────────────────────────────
const stState = {
    freq:     'daily',
    result:   null,
    wfResult: null,
    priceChart:  null,
    equityChart: null,
    wfChart:     null,
    mcChart:     null,
    wfVisible:   false,
};

// ── Init ──────────────────────────────────────────────────────
function initStrategyTester() {
    if (typeof state !== 'undefined' && state.activeSymbol) {
        stState.symbol = state.activeSymbol;
    }
    if (typeof persistence !== 'undefined') {
        const saved = persistence.loadTab('strategy');
        if (saved?.freq) stSetFreq(saved.freq);
    }
}

// ── Frequency toggle ──────────────────────────────────────────
function stSetFreq(freq) {
    stState.freq = freq;
    document.querySelectorAll('.st-freq-btn').forEach(b =>
        b.classList.toggle('st-active', b.dataset.val === freq));
}

// ── Short-side toggle ─────────────────────────────────────────
function stToggleShort(enabled) {
    const el = document.getElementById('st-short-conditions');
    if (el) el.style.display = enabled ? '' : 'none';
}

function stToggleWfSettings() {
    const el = document.getElementById('st-wf-settings');
    if (!el) return;
    el.style.display = el.style.display === 'none' ? '' : 'none';
}

// ── Condition row builder ─────────────────────────────────────

const KIND_OPS = {
    kama_cross:       ['cross_above','cross_below'],
    price_kama_cross: ['cross_above','cross_below','above','below'],
    rsi_level:        ['cross_above','cross_below','above','below'],
    macd_cross:       ['cross_above_signal','cross_below_signal','line_above_signal','line_below_signal','hist_above_zero','hist_below_zero'],
    bb_touch:         ['close_above_upper','close_below_lower','close_above_mid','close_below_mid'],
    price_change:     ['gt','lt'],
    trend_regime:     ['long','short','flat'],
};

const KIND_PARAMS = {
    kama_cross:       [{key:'fast',label:'Fast',default:10},{key:'slow',label:'Slow',default:30}],
    price_kama_cross: [{key:'period',label:'Period',default:20}],
    rsi_level:        [{key:'period',label:'Period',default:14},{key:'level',label:'Level',default:30}],
    macd_cross:       [{key:'fast',label:'Fast',default:12},{key:'slow',label:'Slow',default:26},{key:'signal',label:'Signal',default:9}],
    bb_touch:         [{key:'window',label:'Window',default:20},{key:'num_std',label:'Std',default:2.0}],
    price_change:     [{key:'lookback',label:'Bars',default:5},{key:'pct',label:'Pct',default:0.0}],
    trend_regime:     [],
};

const KIND_LABELS = {
    kama_cross:       'KAMA Cross',
    price_kama_cross: 'Price × KAMA',
    rsi_level:        'RSI Level',
    macd_cross:       'MACD Cross',
    bb_touch:         'Bollinger Band',
    price_change:     'Price Change %',
    trend_regime:     'Trend Regime',
};

function stAddConditionRow(side, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    const row = document.createElement('div');
    row.className = 'st-cond-row';
    row.dataset.side = side;

    const kindSel = document.createElement('select');
    kindSel.className = 'st-cond-kind';
    for (const [k, label] of Object.entries(KIND_LABELS)) {
        const opt = document.createElement('option');
        opt.value = k; opt.textContent = label;
        kindSel.appendChild(opt);
    }

    const opSel = document.createElement('select');
    opSel.className = 'st-cond-op';

    const paramsDiv = document.createElement('div');
    paramsDiv.className = 'st-cond-params';

    const rmBtn = document.createElement('button');
    rmBtn.className = 'st-remove-btn';
    rmBtn.textContent = '✕';
    rmBtn.onclick = () => row.remove();

    function syncKind(kind) {
        // Ops
        opSel.innerHTML = '';
        for (const op of (KIND_OPS[kind] || [])) {
            const o = document.createElement('option');
            o.value = op; o.textContent = op.replace(/_/g, ' ');
            opSel.appendChild(o);
        }
        // Param inputs
        paramsDiv.innerHTML = '';
        for (const p of (KIND_PARAMS[kind] || [])) {
            const lbl = document.createElement('label');
            lbl.className = 'st-param-label';
            lbl.textContent = p.label + ' ';
            const inp = document.createElement('input');
            inp.type = 'number';
            inp.className = 'st-param-input';
            inp.value = p.default;
            inp.dataset.paramKey = p.key;
            inp.step = (p.default % 1 !== 0) ? '0.1' : '1';
            lbl.appendChild(inp);
            paramsDiv.appendChild(lbl);
        }
    }

    kindSel.addEventListener('change', () => syncKind(kindSel.value));
    syncKind(kindSel.value);

    row.appendChild(kindSel);
    row.appendChild(opSel);
    row.appendChild(paramsDiv);
    row.appendChild(rmBtn);
    container.appendChild(row);
}

function _readConditionRows(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return null;
    const rows = container.querySelectorAll('.st-cond-row');
    if (rows.length === 0) return null;

    const children = [];
    for (const row of rows) {
        const kind   = row.querySelector('.st-cond-kind')?.value;
        const op     = row.querySelector('.st-cond-op')?.value;
        if (!kind || !op) continue;
        const params = {};
        row.querySelectorAll('.st-param-input').forEach(inp => {
            params[inp.dataset.paramKey] = parseFloat(inp.value);
        });
        children.push({ type: 'leaf', kind, params, op });
    }
    if (children.length === 0) return null;
    if (children.length === 1) return children[0];
    return { type: 'group', logic: 'AND', children };
}

// ── Param grid builder ────────────────────────────────────────

function stAddParamGridRow() {
    const container = document.getElementById('st-param-grid-rows');
    if (!container) return;
    const row = document.createElement('div');
    row.className = 'st-param-grid-row';
    row.innerHTML =
        `<input type="text"   class="st-pg-key"    placeholder="e.g. rsi_level__period">` +
        `<input type="text"   class="st-pg-values" placeholder="e.g. 7,14,21">` +
        `<button class="st-remove-btn" onclick="this.parentElement.remove()">✕</button>`;
    container.appendChild(row);
}

function _readParamGrid() {
    const grid = {};
    document.querySelectorAll('.st-param-grid-row').forEach(row => {
        const key = row.querySelector('.st-pg-key')?.value.trim();
        const raw = row.querySelector('.st-pg-values')?.value.trim();
        if (!key || !raw) return;
        grid[key] = raw.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
    });
    return grid;
}

// ── Config builder ────────────────────────────────────────────
function stReadConfig() {
    return {
        entry_long:      _readConditionRows('st-entry-long-rows'),
        exit_long:       _readConditionRows('st-exit-long-rows'),
        entry_short:     _readConditionRows('st-entry-short-rows'),
        exit_short:      _readConditionRows('st-exit-short-rows'),
        allow_short:     document.getElementById('st-allow-short')?.checked || false,
        bar_delay:       parseInt(document.getElementById('st-bar-delay')?.value || '1', 10),
        commission_pct:  parseFloat(document.getElementById('st-commission')?.value || '0.05') / 100,
        slippage_pct:    parseFloat(document.getElementById('st-slippage')?.value  || '0.05') / 100,
        regime_filter:   document.getElementById('st-regime-filter')?.value || 'none',
    };
}

// ── Run backtest ──────────────────────────────────────────────
async function stRunBacktest() {
    const symbol = (typeof state !== 'undefined') ? state.activeSymbol : null;
    if (!symbol) { toast('Select a symbol first', 'warning'); return; }

    const config = stReadConfig();
    if (!config.entry_long) { toast('Add at least one Entry Long condition', 'warning'); return; }

    if (typeof persistence !== 'undefined') {
        persistence.saveTab('strategy', { freq: stState.freq });
    }

    _stSetLoading(true);

    try {
        const data = await apiFetch(`${API}/strategy/backtest`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ symbol, freq: stState.freq, config }),
        });
        stState.result = data;
        _stRenderResults(data);
        document.getElementById('btn-st-mc').style.display = '';
    } catch (e) {
        _stShowError(e.message);
    } finally {
        _stSetLoading(false);
    }
}

// ── Run walk-forward ──────────────────────────────────────────
async function stRunWalkForward() {
    const symbol = (typeof state !== 'undefined') ? state.activeSymbol : null;
    if (!symbol) { toast('Select a symbol first', 'warning'); return; }

    const config = stReadConfig();
    if (!config.entry_long) { toast('Add at least one Entry Long condition', 'warning'); return; }

    config.n_folds   = parseInt(document.getElementById('st-wf-folds')?.value  || '5', 10);
    config.train_pct = parseFloat(document.getElementById('st-wf-train-pct')?.value || '70') / 100;
    config.anchored  = document.getElementById('st-wf-anchored')?.checked || false;
    config.param_grid = _readParamGrid();

    _stSetLoading(true);

    try {
        const data = await apiFetch(`${API}/strategy/walk-forward`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ symbol, freq: stState.freq, config }),
        });
        stState.wfResult = data;
        _stRenderWalkForward(data);
    } catch (e) {
        _stShowError(e.message);
    } finally {
        _stSetLoading(false);
    }
}

// ── Monte Carlo ───────────────────────────────────────────────
async function stRunMonteCarlo() {
    if (!stState.result?.trades?.length) { toast('Run a backtest first', 'warning'); return; }
    try {
        const data = await apiFetch(`${API}/strategy/monte-carlo`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ trades: stState.result.trades, n_sim: 1000 }),
        });
        _stRenderMonteCarlo(data);
    } catch (e) {
        toast('Monte Carlo error: ' + e.message, 'error');
    }
}

// ── Render results ────────────────────────────────────────────
function _stRenderResults(data) {
    document.getElementById('st-empty').style.display   = 'none';
    document.getElementById('st-results').style.display = '';

    _stRenderMetrics(data.metrics, data.benchmark_metrics);
    _stRenderPriceChart(data);
    _stRenderEquityChart(data);
    _stRenderTradesTable(data.trades);
}

function _stRenderMetrics(m, bm) {
    const container = document.getElementById('st-metrics-row');
    if (!container) return;

    const fmt = (v, pct) => {
        if (v == null) return '—';
        return pct ? (v * 100).toFixed(2) + '%' : v.toFixed ? v.toFixed(4) : v;
    };
    const color = v => v == null ? '' : v > 0 ? 'st-kpi-pos' : v < 0 ? 'st-kpi-neg' : '';

    const metrics = [
        { label: 'Total Return', val: m.total_return,  pct: true },
        { label: 'CAGR',         val: m.cagr,          pct: true },
        { label: 'Sharpe',       val: m.sharpe,        pct: false },
        { label: 'Sortino',      val: m.sortino,       pct: false },
        { label: 'Max DD',       val: m.max_drawdown,  pct: true },
        { label: 'Calmar',       val: m.calmar,        pct: false },
        { label: 'Win Rate',     val: m.win_rate,      pct: true },
        { label: '# Trades',     val: m.n_trades,      pct: false },
        { label: 'Kelly ½',      val: m.kelly_half,    pct: true },
        { label: 'Exposure',     val: m.exposure_pct,  pct: true },
    ];

    container.innerHTML = metrics.map(({ label, val, pct }) =>
        `<div class="st-kpi">` +
        `<div class="st-kpi-label">${label}</div>` +
        `<div class="st-kpi-value ${color(val)}">${fmt(val, pct)}</div>` +
        (bm ? `<div class="st-kpi-bench">${fmt(bm[label.toLowerCase().replace(/ /g, '_')] ?? null, pct)}</div>` : '') +
        `</div>`
    ).join('');
}

function _stRenderPriceChart(data) {
    const container = document.getElementById('st-price-chart');
    if (!container || !data.dates?.length) return;

    // Destroy old instance
    if (stState.priceChart) { try { stState.priceChart.remove(); } catch (_) {} }

    const isDark = document.body.classList.contains('theme-light') === false;
    const chart = LightweightCharts.createChart(container, {
        width:  container.clientWidth || 700,
        height: 220,
        layout:      { background: { color: isDark ? '#0f172a' : '#fff' }, textColor: isDark ? '#94a3b8' : '#334155' },
        grid:        { vertLines: { color: isDark ? '#1e293b' : '#e2e8f0' }, horzLines: { color: isDark ? '#1e293b' : '#e2e8f0' } },
        rightPriceScale: { borderColor: isDark ? '#1e293b' : '#e2e8f0' },
        timeScale:       { borderColor: isDark ? '#1e293b' : '#e2e8f0', timeVisible: true },
    });

    const series = chart.addAreaSeries({
        lineColor:   '#3b82f6',
        topColor:    'rgba(59,130,246,0.15)',
        bottomColor: 'rgba(59,130,246,0)',
        lineWidth: 1,
    });

    const priceData = data.dates.map((d, i) => ({ time: d, value: data.price[i] }))
        .filter(p => p.value != null);
    series.setData(priceData);

    if (data.markers?.length) {
        const dedupedMarkers = _dedupeMarkers(data.markers);
        series.setMarkers(dedupedMarkers);
    }

    stState.priceChart = chart;
    new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth })).observe(container);
}

function _dedupeMarkers(markers) {
    // LWC requires markers to be sorted by time and unique per time+position
    const seen = new Set();
    const out  = [];
    for (const m of [...markers].sort((a, b) => a.time < b.time ? -1 : 1)) {
        const key = `${m.time}|${m.position}`;
        if (!seen.has(key)) { seen.add(key); out.push(m); }
    }
    return out;
}

function _stRenderEquityChart(data) {
    const container = document.getElementById('st-equity-chart');
    if (!container || !data.dates?.length) return;

    if (stState.equityChart) { try { stState.equityChart.remove(); } catch (_) {} }

    const isDark = document.body.classList.contains('theme-light') === false;
    const chart = LightweightCharts.createChart(container, {
        width:  container.clientWidth || 700,
        height: 180,
        layout:      { background: { color: isDark ? '#0f172a' : '#fff' }, textColor: isDark ? '#94a3b8' : '#334155' },
        grid:        { vertLines: { color: isDark ? '#1e293b' : '#e2e8f0' }, horzLines: { color: isDark ? '#1e293b' : '#e2e8f0' } },
        rightPriceScale: { borderColor: isDark ? '#1e293b' : '#e2e8f0' },
        timeScale:       { borderColor: isDark ? '#1e293b' : '#e2e8f0', timeVisible: true },
    });

    const strSeries = chart.addLineSeries({ color: '#22c55e', lineWidth: 2, title: 'Strategy' });
    const bmSeries  = chart.addLineSeries({ color: '#64748b', lineWidth: 1, lineStyle: 2, title: 'B&H' });

    const eqData = data.dates.map((d, i) => ({ time: d, value: data.equity[i] })).filter(p => p.value != null);
    const bmData = data.dates.map((d, i) => ({ time: d, value: data.benchmark[i] })).filter(p => p.value != null);
    strSeries.setData(eqData);
    bmSeries.setData(bmData);

    stState.equityChart = chart;
    new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth })).observe(container);
}

function _stRenderTradesTable(trades) {
    const tbody = document.getElementById('st-trades-tbody');
    const badge = document.getElementById('st-trades-count');
    if (!tbody) return;
    if (badge) badge.textContent = `${trades.length}`;

    const fmtPct = v => v == null ? '—' : (v * 100).toFixed(2) + '%';
    const fmtDir = d => d === 1 ? '▲ L' : '▼ S';

    tbody.innerHTML = trades.slice(0, 200).map(t => {
        const cls = t.net_ret >= 0 ? 'st-trade-win' : 'st-trade-loss';
        return `<tr class="${cls}">` +
            `<td>${t.entry_date}</td>` +
            `<td>${t.exit_date}</td>` +
            `<td>${fmtDir(t.direction)}</td>` +
            `<td>${t.bars_held}</td>` +
            `<td>${fmtPct(t.gross_ret)}</td>` +
            `<td>${fmtPct(t.net_ret)}</td>` +
            `<td>${fmtPct(t.mfe)}</td>` +
            `<td>${fmtPct(t.mae)}</td>` +
            `</tr>`;
    }).join('');

    if (trades.length > 200) {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td colspan="8" style="text-align:center;color:var(--text-dim);font-size:11px;">…${trades.length - 200} more trades not shown</td>`;
        tbody.appendChild(tr);
    }
}

// ── Walk-forward rendering ────────────────────────────────────
function _stRenderWalkForward(data) {
    const section = document.getElementById('st-wf-section');
    if (section) section.style.display = '';
    stState.wfVisible = true;

    // Fold bar chart via Chart.js
    const container = document.getElementById('st-wf-fold-chart');
    if (container && data.folds?.length) {
        const labels = data.folds.map(f => `Fold ${f.fold}`);
        const isSharpe = data.folds.map(f => f.is_metric);
        const oosSharpe = data.folds.map(f => f.oos_metric);
        stState.wfChart = updateOrCreate('st.wf', container, {
            type: 'bar',
            data: {
                labels,
                datasets: [
                    { label: 'IS Sharpe',  data: isSharpe,  backgroundColor: 'rgba(59,130,246,0.7)' },
                    { label: 'OOS Sharpe', data: oosSharpe, backgroundColor: 'rgba(34,197,94,0.7)' },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'top', labels: { color: '#94a3b8' } } },
                scales: {
                    x: { ticks: { color: '#94a3b8' }, grid: { color: '#1e293b' } },
                    y: { ticks: { color: '#94a3b8' }, grid: { color: '#1e293b' } },
                },
            },
        });
    }

    // Param stability chips
    const stabEl = document.getElementById('st-wf-stability');
    if (stabEl && data.param_stability) {
        stabEl.innerHTML = '<strong>Param Stability (CV, lower = more stable):</strong> ' +
            Object.entries(data.param_stability).map(([k, v]) => {
                if (v == null) return '';
                const cls = v < 0.2 ? 'st-stability-good' : 'st-stability-bad';
                return `<span class="st-stability-chip ${cls}">${k}: ${v.toFixed(3)}</span>`;
            }).join('');
    }

    // Fold table
    const foldTable = document.getElementById('st-wf-fold-table');
    if (foldTable && data.folds?.length) {
        foldTable.innerHTML = `<table class="st-trades-table"><thead><tr>
            <th>Fold</th><th>Train</th><th>Test</th>
            <th>IS Sharpe</th><th>OOS Sharpe</th><th>OOS Return</th>
            <th>Best Params</th></tr></thead><tbody>` +
            data.folds.map(f =>
                `<tr>
                  <td>${f.fold}</td>
                  <td>${f.train_start}→${f.train_end}</td>
                  <td>${f.test_start}→${f.test_end}</td>
                  <td>${f.is_metric?.toFixed(3) ?? '—'}</td>
                  <td class="${(f.oos_metric ?? 0) >= 0 ? 'st-trade-win' : 'st-trade-loss'}">${f.oos_metric?.toFixed(3) ?? '—'}</td>
                  <td class="${(f.oos_return ?? 0) >= 0 ? 'st-trade-win' : 'st-trade-loss'}">${f.oos_return != null ? (f.oos_return * 100).toFixed(2) + '%' : '—'}</td>
                  <td style="font-size:10px;">${JSON.stringify(f.best_params)}</td>
                </tr>`
            ).join('') +
            '</tbody></table>';
    }

    // Combined metrics note
    if (data.combined_metrics) {
        const m = data.combined_metrics;
        toast(`Walk-Forward OOS: Sharpe ${m.sharpe?.toFixed(2) ?? '—'}, Return ${m.total_return != null ? (m.total_return * 100).toFixed(2) + '%' : '—'}`, 'info', 6000);
    }
}

// ── Monte Carlo rendering ─────────────────────────────────────
function _stRenderMonteCarlo(data) {
    const section = document.getElementById('st-mc-section');
    if (section) section.style.display = '';

    const container = document.getElementById('st-mc-chart');
    if (!container || !data.percentiles) return;
    const n = data.percentiles.p50.length;
    const labels = Array.from({ length: n }, (_, i) => i + 1);

    stState.mcChart = updateOrCreate('st.mc', container, {
        type: 'line',
        data: {
            labels,
            datasets: [
                { label: 'p95', data: data.percentiles.p95, borderColor: 'rgba(34,197,94,0.3)',  borderWidth:1, fill: false, pointRadius:0 },
                { label: 'p75', data: data.percentiles.p75, borderColor: 'rgba(34,197,94,0.6)',  borderWidth:1, fill: false, pointRadius:0 },
                { label: 'p50', data: data.percentiles.p50, borderColor: '#22c55e',               borderWidth:2, fill: false, pointRadius:0 },
                { label: 'p25', data: data.percentiles.p25, borderColor: 'rgba(239,68,68,0.6)',   borderWidth:1, fill: false, pointRadius:0 },
                { label: 'p5',  data: data.percentiles.p5,  borderColor: 'rgba(239,68,68,0.3)',   borderWidth:1, fill: false, pointRadius:0 },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: false,
            plugins: { legend: { position: 'top', labels: { color: '#94a3b8' } } },
            scales: {
                x: { display: false },
                y: { ticks: { color: '#94a3b8' }, grid: { color: '#1e293b' } },
            },
        },
    });
}

// ── Loading / error helpers ───────────────────────────────────
function _stSetLoading(on) {
    const loadEl    = document.getElementById('st-loading');
    const emptyEl   = document.getElementById('st-empty');
    const resultsEl = document.getElementById('st-results');
    const btnRun    = document.getElementById('btn-st-run');
    const btnWf     = document.getElementById('btn-st-wf');
    if (on) {
        if (loadEl)    loadEl.style.display    = '';
        if (emptyEl)   emptyEl.style.display   = 'none';
        if (resultsEl) resultsEl.style.display = 'none';
        if (btnRun) { btnRun.disabled = true;  btnRun.textContent = '⏳ Running…'; }
        if (btnWf)  { btnWf.disabled  = true;  btnWf.textContent  = '⏳ Running…'; }
    } else {
        if (loadEl) loadEl.style.display = 'none';
        if (btnRun) { btnRun.disabled = false; btnRun.textContent = '▶ Run Backtest'; }
        if (btnWf)  { btnWf.disabled  = false; btnWf.textContent  = '⚡ Walk-Forward'; }
    }
}

function _stShowError(msg) {
    const emptyEl = document.getElementById('st-empty');
    if (emptyEl) {
        emptyEl.style.display = '';
        emptyEl.innerHTML =
            `<div class="empty-icon">⚠</div>` +
            `<p>${msg}</p>`;
    }
}
