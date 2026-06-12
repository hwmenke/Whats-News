/**
 * seasonality.js — Calendar Seasonality Analysis UI
 *
 * Three views for the selected symbol:
 *   1. Monthly heatmap (calendar grid, each cell = avg monthly return)
 *   2. Month bar chart  (avg return by calendar month)
 *   3. Day-of-week + Quarterly bar charts
 *   4. Year × Month full heatmap (rows = years, cols = months)
 */

const seasState = {
    symbol: null,
    result: null,
    charts: {},
};

const MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const DOW_NAMES   = ['Mon','Tue','Wed','Thu','Fri'];

// ── Load ──────────────────────────────────────────────────────
async function loadSeasonality(symbol) {
    symbol = (symbol || (typeof state !== 'undefined' ? state.activeSymbol : null));
    if (!symbol) { toast('Select a symbol first', 'warning'); return; }

    seasState.symbol = symbol;
    _seasSetLoading(true);
    try {
        const data = await apiFetch(`${API}/seasonality/${symbol}`);
        seasState.result = data;
        _seasRenderAll(data);
    } catch (e) {
        toastFromError(e, 'Seasonality');
        _seasShowError(e.message);
    } finally {
        _seasSetLoading(false);
    }
}

// ── Render ────────────────────────────────────────────────────
function _seasRenderAll(data) {
    document.getElementById('seas-empty').style.display   = 'none';
    document.getElementById('seas-results').style.display = '';

    const sym = document.getElementById('seas-symbol-label');
    if (sym) sym.textContent = `${data.symbol} · ${data.n_years} years · ${data.n_monthly_obs} months`;

    _seasRenderHighlights(data.highlights);
    _seasRenderMonthBars(data.monthly_stats);
    _seasRenderDowBars(data.dow_stats);
    _seasRenderQuarterBars(data.quarterly_stats);
    _seasRenderHeatmap(data.heatmap, data.monthly_stats);
}

function _seasRenderHighlights(h) {
    const el = document.getElementById('seas-highlights');
    if (!el || !h) return;
    const fmtPct = v => v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
    el.innerHTML = `
      <div class="seas-hl"><span class="seas-hl-icon">🟢</span><span class="seas-hl-label">Best Month</span>
        <b style="color:var(--green)">${h.best_month}</b>
        <span style="color:var(--green);font-family:var(--font-mono)">${fmtPct(h.best_month_mean)}</span>
      </div>
      <div class="seas-hl"><span class="seas-hl-icon">🔴</span><span class="seas-hl-label">Worst Month</span>
        <b style="color:var(--red)">${h.worst_month}</b>
        <span style="color:var(--red);font-family:var(--font-mono)">${fmtPct(h.worst_month_mean)}</span>
      </div>
      <div class="seas-hl"><span class="seas-hl-icon">📅</span><span class="seas-hl-label">Best Day</span>
        <b style="color:var(--green)">${h.best_dow}</b>
      </div>
      <div class="seas-hl"><span class="seas-hl-icon">📅</span><span class="seas-hl-label">Worst Day</span>
        <b style="color:var(--red)">${h.worst_dow}</b>
      </div>`;
}

function _seasRenderMonthBars(monthly) {
    const canvas = document.getElementById('seas-month-chart');
    if (!canvas || !monthly?.length) return;

    const updateOrCreate = window.updateOrCreate;
    const labels = monthly.map(m => m.name);
    const means  = monthly.map(m => m.mean != null ? +(m.mean * 100).toFixed(2) : 0);
    const colors = means.map(v => v >= 0 ? 'rgba(34,197,94,0.75)' : 'rgba(239,68,68,0.75)');
    const borders= means.map(v => v >= 0 ? '#22c55e' : '#ef4444');

    seasState.charts['month'] = (updateOrCreate || _chartCreate)(
        'seas.month', canvas, {
            type: 'bar',
            data: { labels, datasets: [{ label: 'Avg Monthly Return', data: means, backgroundColor: colors, borderColor: borders, borderWidth: 1 }] },
            options: _seasBarOpts('Avg Monthly Return (%)', false),
        }
    );
}

function _seasRenderDowBars(dow) {
    const canvas = document.getElementById('seas-dow-chart');
    if (!canvas || !dow?.length) return;

    const updateOrCreate = window.updateOrCreate;
    const labels = dow.map(d => d.name);
    const means  = dow.map(d => d.mean != null ? +(d.mean * 100).toFixed(3) : 0);
    const colors = means.map(v => v >= 0 ? 'rgba(96,165,250,0.75)' : 'rgba(239,68,68,0.75)');

    seasState.charts['dow'] = (updateOrCreate || _chartCreate)(
        'seas.dow', canvas, {
            type: 'bar',
            data: { labels, datasets: [{ label: 'Avg Daily Return', data: means, backgroundColor: colors, borderWidth: 1 }] },
            options: _seasBarOpts('Avg Day-of-Week Return (%)', false),
        }
    );
}

function _seasRenderQuarterBars(quarterly) {
    const canvas = document.getElementById('seas-quarter-chart');
    if (!canvas || !quarterly?.length) return;

    const updateOrCreate = window.updateOrCreate;
    const labels = quarterly.map(q => q.name);
    const means  = quarterly.map(q => q.mean != null ? +(q.mean * 100).toFixed(2) : 0);
    const hit    = quarterly.map(q => q.hit_rate != null ? +(q.hit_rate * 100).toFixed(1) : 0);
    const colors = means.map(v => v >= 0 ? 'rgba(168,85,247,0.65)' : 'rgba(239,68,68,0.65)');

    seasState.charts['quarter'] = (updateOrCreate || _chartCreate)(
        'seas.quarter', canvas, {
            type: 'bar',
            data: {
                labels,
                datasets: [
                    { label: 'Avg Return', data: means, backgroundColor: colors, borderWidth: 1, yAxisID: 'y' },
                    { label: 'Hit Rate',   data: hit,   backgroundColor: 'rgba(250,204,21,0.3)', borderColor: '#fbbf24', borderWidth: 1, type: 'line', yAxisID: 'y2', pointRadius: 4 },
                ],
            },
            options: { ..._seasBarOpts('Quarterly (%)', true), scales: {
                x:  { ticks: { color: '#94a3b8' }, grid: { display: false } },
                y:  { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#1e293b' }, title: { display: true, text: 'Ret %', color: '#94a3b8', font: { size: 9 } } },
                y2: { position: 'right', ticks: { color: '#fbbf24', font: { size: 10 } }, grid: { display: false }, title: { display: true, text: 'Hit%', color: '#fbbf24', font: { size: 9 } } },
            }},
        }
    );
}

function _chartCreate(key, canvas, config) {
    return new Chart(canvas, config);
}

function _seasBarOpts(title, legend) {
    return {
        responsive: true, maintainAspectRatio: false, animation: false,
        plugins: {
            legend: { display: legend, labels: { color: '#94a3b8', font: { size: 10 } } },
            tooltip: { callbacks: { label: ctx => ` ${ctx.raw > 0 ? '+' : ''}${ctx.raw}%` } },
        },
        scales: {
            x: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } },
            y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#1e293b' } },
        },
    };
}

// ── Year × Month heatmap ──────────────────────────────────────
function _seasRenderHeatmap(heatmap, monthly_stats) {
    const el = document.getElementById('seas-heatmap');
    if (!el || !heatmap?.length) return;

    // Color scale: dark red → white → dark green  [-10%, +10%]
    function retColor(v) {
        if (v == null) return 'var(--bg-card)';
        const t    = Math.max(-1, Math.min(1, v / 0.10));   // clamp to ±10%
        if (t >= 0) {
            const g = Math.round(30 + t * 169);
            return `rgba(34,${g},94,${0.15 + t * 0.55})`;
        } else {
            const r = Math.round(200 + (-t) * 39);
            return `rgba(${r},68,68,${0.15 + (-t) * 0.55})`;
        }
    }

    const monthHeaders = MONTH_NAMES.map(m =>
        `<th class="seas-hm-th" style="text-align:center">${m}</th>`
    ).join('');

    // Avg row at bottom
    const avgRow = MONTH_NAMES.map((_, i) => {
        const m = monthly_stats.find(x => x.month === i + 1);
        const v = m?.mean;
        const pct = v != null ? (v * 100).toFixed(1) : '—';
        const col = retColor(v);
        const txt = v != null ? ((v >= 0 ? '+' : '') + pct + '%') : '—';
        return `<td class="seas-hm-td" style="background:${col};font-weight:700;font-size:10px">${txt}</td>`;
    }).join('');

    const rows = [...heatmap].reverse().map(yr => {
        const cells = MONTH_NAMES.map((_, i) => {
            const v   = yr.months[String(i + 1)];
            const col = retColor(v);
            const pct = v != null ? ((v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%') : '';
            const txt = v != null ? pct : '·';
            const textCol = v == null ? 'var(--text-dim)'
                          : Math.abs(v) > 0.06 ? '#fff' : 'var(--text-primary)';
            return `<td class="seas-hm-td" style="background:${col};color:${textCol}">${txt}</td>`;
        }).join('');

        const annV   = yr.annual;
        const annCol = retColor(annV);
        const annTxt = annV != null ? ((annV >= 0 ? '+' : '') + (annV * 100).toFixed(1) + '%') : '—';
        const annTxtCol = annV == null ? 'var(--text-dim)' : Math.abs(annV) > 0.10 ? '#fff' : 'var(--text-primary)';

        return `<tr>
          <td class="seas-hm-yr">${yr.year}</td>
          ${cells}
          <td class="seas-hm-ann" style="background:${annCol};color:${annTxtCol}">${annTxt}</td>
        </tr>`;
    }).join('');

    el.innerHTML = `
    <div class="seas-hm-title">Monthly Returns Heatmap</div>
    <div class="seas-hm-wrap">
      <table class="seas-hm-tbl">
        <thead><tr>
          <th class="seas-hm-th" style="text-align:left">Year</th>
          ${monthHeaders}
          <th class="seas-hm-th" style="text-align:center">Annual</th>
        </tr></thead>
        <tbody>
          ${rows}
          <tr>
            <td class="seas-hm-yr" style="color:var(--text-dim);font-size:9px">Avg</td>
            ${avgRow}
            <td class="seas-hm-td"></td>
          </tr>
        </tbody>
      </table>
    </div>`;
}

// ── Loading / error ───────────────────────────────────────────
function _seasSetLoading(on) {
    const loadEl = document.getElementById('seas-loading');
    if (loadEl) loadEl.style.display = on ? 'flex' : 'none';
}
function _seasShowError(msg) {
    const el = document.getElementById('seas-empty');
    if (el) { el.style.display = ''; el.innerHTML = `<div class="empty-icon">⚠</div><p>${msg}</p>`; }
    const res = document.getElementById('seas-results');
    if (res) res.style.display = 'none';
}

// ── Init ──────────────────────────────────────────────────────
function initSeasonality() {
    const sym = typeof state !== 'undefined' ? state.activeSymbol : null;
    if (sym && sym !== seasState.symbol) {
        loadSeasonality(sym);
    } else if (seasState.result) {
        _seasRenderAll(seasState.result);
    } else if (sym) {
        loadSeasonality(sym);
    }
}
