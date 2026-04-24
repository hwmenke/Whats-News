/**
 * factor_model.js — Cross-Sectional Factor Model Analyzer UI
 *
 * Views:
 *   1. Exposure matrix: symbols × factors (beta heatmap)
 *   2. Alpha ranking: bar chart of annualised alpha
 *   3. Factor performance: cumulative return chart
 *   4. Individual drill-down: rolling betas + attribution for one symbol
 */

const fmState = {
    result:       null,
    selected:     null,   // symbol for drill-down
    lookback:     504,
    charts:       {},
};

const FM_FACTOR_COLORS = {
    market:    '#3b82f6',
    size:      '#22c55e',
    value:     '#f59e0b',
    duration:  '#06b6d4',
    commodity: '#f97316',
};

// ── Load ──────────────────────────────────────────────────────
async function loadFactorModel() {
    _fmSetLoading(true);
    try {
        const lookback = parseInt(document.getElementById('fm-lookback-input')?.value || '504');
        const data = await apiFetch(`${API}/factor-model?lookback=${lookback}`);
        fmState.result = data;
        _fmRenderAll(data);
    } catch (e) {
        toastFromError(e, 'Factor Model');
        _fmShowError(e.message);
    } finally {
        _fmSetLoading(false);
    }
}

// ── Render ────────────────────────────────────────────────────
function _fmRenderAll(data) {
    document.getElementById('fm-empty').style.display   = 'none';
    document.getElementById('fm-results').style.display = '';

    _fmRenderMissingWarning(data.missing_factors);
    _fmRenderExposureMatrix(data);
    _fmRenderAlphaRank(data);
    _fmRenderFactorPerf(data);

    // Auto drill-down to first symbol
    if (data.symbols?.length > 0 && !fmState.selected) {
        fmSelectSymbol(data.symbols[0], data);
    }
}

function _fmRenderMissingWarning(missing) {
    const el = document.getElementById('fm-missing-warn');
    if (!el) return;
    if (!missing?.length) { el.style.display = 'none'; return; }
    el.style.display = '';
    el.innerHTML = `⚠ Missing factor ETFs: ${missing.join(', ')} — add them to watchlist for full model`;
}

// ── Exposure matrix ───────────────────────────────────────────
function _fmRenderExposureMatrix(data) {
    const el = document.getElementById('fm-exposure-matrix');
    if (!el) return;

    const fnames  = data.factor_names || [];
    const labels  = data.factor_labels || {};
    const results = data.results || {};
    const symbols = data.symbols || [];

    function betaColor(v) {
        if (v == null) return 'var(--bg-card)';
        const t = Math.max(-2, Math.min(2, v)) / 2;
        if (t >= 0) return `rgba(59,130,246,${0.1 + t * 0.6})`;
        return `rgba(239,68,68,${0.1 + (-t) * 0.6})`;
    }

    const headerCols = fnames.map(f =>
        `<th class="fm-mx-th" style="color:${FM_FACTOR_COLORS[f]||'#94a3b8'}">${labels[f]||f}</th>`
    ).join('');

    const rows = symbols.map(sym => {
        const r      = results[sym] || {};
        const betas  = r.factor_betas || {};
        const betaCells = fnames.map(f => {
            const v   = betas[f];
            const bg  = betaColor(v);
            const txt = v != null ? v.toFixed(2) : '—';
            const col = v == null ? 'var(--text-dim)' : Math.abs(v) > 1.2 ? '#fff' : 'var(--text-primary)';
            return `<td class="fm-mx-td" style="background:${bg};color:${col}">${txt}</td>`;
        }).join('');

        const alpha   = r.alpha_ann;
        const alphaCol= alpha == null ? 'var(--text-dim)' : alpha > 0 ? 'var(--green)' : 'var(--red)';
        const alphaTxt= alpha != null ? (alpha >= 0 ? '+' : '') + (alpha * 100).toFixed(1) + '%' : '—';
        const r2Txt   = r.r2 != null ? (r.r2 * 100).toFixed(0) + '%' : '—';
        const pval    = r.alpha_pval;
        const sig     = pval != null && pval < 0.10 ? `<span class="fm-sig-dot" title="p=${pval.toFixed(3)}">*</span>` : '';

        return `<tr class="fm-mx-row" onclick="fmSelectSymbol('${sym}', null)" title="Drill into ${sym}">
          <td class="fm-mx-sym"><b>${sym}</b></td>
          ${betaCells}
          <td class="fm-mx-td" style="color:${alphaCol};font-weight:700">${alphaTxt}${sig}</td>
          <td class="fm-mx-td" style="color:var(--text-secondary)">${r2Txt}</td>
        </tr>`;
    }).join('');

    el.innerHTML = `
    <div class="fm-section-title">Factor Exposure Matrix <small style="color:var(--text-dim);font-weight:400">(click row → drill-down)</small></div>
    <div class="fm-mx-wrap">
      <table class="fm-mx-tbl">
        <thead><tr>
          <th class="fm-mx-th" style="text-align:left">Symbol</th>
          ${headerCols}
          <th class="fm-mx-th" style="color:#a78bfa">α Ann.</th>
          <th class="fm-mx-th">R²</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// ── Alpha ranking bar chart ────────────────────────────────────
function _fmRenderAlphaRank(data) {
    const canvas = document.getElementById('fm-alpha-chart');
    if (!canvas) return;

    const rank = (data.alpha_rank || []).slice(0, 20);
    const labels = rank.map(([sym]) => sym);
    const vals   = rank.map(([, a]) => a != null ? +(a * 100).toFixed(2) : 0);
    const colors = vals.map(v => v >= 0 ? 'rgba(34,197,94,0.7)' : 'rgba(239,68,68,0.7)');

    if (fmState.charts['alpha']) { try { fmState.charts['alpha'].destroy(); } catch(_) {} }

    fmState.charts['alpha'] = new Chart(canvas, {
        type: 'bar',
        data: { labels, datasets: [{ label: 'Annualised Alpha (%)', data: vals, backgroundColor: colors, borderWidth: 0 }] },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false, indexAxis: 'y',
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ctx => ` ${ctx.raw > 0 ? '+' : ''}${ctx.raw}% ann. alpha` } },
            },
            scales: {
                x: { ticks: { color: '#94a3b8', font: { size: 9 } }, grid: { color: '#1e293b' } },
                y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { display: false } },
            },
        },
    });
}

// ── Factor performance chart ───────────────────────────────────
function _fmRenderFactorPerf(data) {
    const canvas = document.getElementById('fm-factor-perf-chart');
    if (!canvas) return;

    const perf   = data.factor_perf || {};
    const labels = data.factor_labels || {};
    const datasets = Object.entries(perf).map(([f, series]) => ({
        label:       labels[f] || f,
        data:        series.values,
        labels:      series.dates,
        borderColor: FM_FACTOR_COLORS[f] || '#94a3b8',
        borderWidth: 1.5, pointRadius: 0, fill: false,
    }));
    if (!datasets.length) return;

    if (fmState.charts['perf']) { try { fmState.charts['perf'].destroy(); } catch(_) {} }

    fmState.charts['perf'] = new Chart(canvas, {
        type: 'line',
        data: { labels: Object.values(perf)[0]?.dates || [], datasets },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { display: true, position: 'top', labels: { color: '#94a3b8', font: { size: 9 }, boxWidth: 12 } } },
            scales: { x: { display: false }, y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#1e293b' } } },
        },
    });
}

// ── Drill-down ────────────────────────────────────────────────
function fmSelectSymbol(sym, data) {
    fmState.selected = sym;
    data = data || fmState.result;
    if (!data) return;

    const r = data.results?.[sym];
    if (!r) return;

    // Highlight row in matrix
    document.querySelectorAll('.fm-mx-row').forEach(row => {
        row.classList.toggle('fm-mx-selected', row.querySelector('b')?.textContent === sym);
    });

    // Update drill-down panel
    const panel = document.getElementById('fm-drilldown');
    if (!panel) return;
    panel.style.display = '';

    _fmRenderDrilldownHeader(sym, r);
    _fmRenderRollingBetas(r, data.factor_names, data.factor_labels);
    _fmRenderAttribution(r, data.factor_names, data.factor_labels);
}

function _fmRenderDrilldownHeader(sym, r) {
    const el = document.getElementById('fm-drill-header');
    if (!el) return;
    const alpha   = r.alpha_ann;
    const alphaCol= alpha == null ? 'var(--text-muted)' : alpha > 0 ? 'var(--green)' : 'var(--red)';
    const fmtPct  = v => v != null ? (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%' : '—';
    const sigStar = (r.alpha_pval != null && r.alpha_pval < 0.10) ? ' *' : '';

    const betaItems = Object.entries(r.factor_betas || {}).map(([f, b]) =>
        `<div class="fm-drill-beta"><span style="color:${FM_FACTOR_COLORS[f]||'#94a3b8'}">${f}</span> <b>${b?.toFixed(2)??'—'}</b></div>`
    ).join('');

    el.innerHTML = `
    <div class="fm-drill-sym">${sym} <span style="color:var(--text-dim);font-size:11px">${r.name||''}</span></div>
    <div class="fm-drill-stats">
      <div class="fm-drill-kpi"><div class="fm-dk-val" style="color:${alphaCol}">${fmtPct(alpha)}${sigStar}</div><div class="fm-dk-lbl">α Annualised</div></div>
      <div class="fm-drill-kpi"><div class="fm-dk-val">${r.alpha_tstat?.toFixed(2)??'—'}</div><div class="fm-dk-lbl">t-stat (α)</div></div>
      <div class="fm-drill-kpi"><div class="fm-dk-val">${r.alpha_pval?.toFixed(3)??'—'}</div><div class="fm-dk-lbl">p-value</div></div>
      <div class="fm-drill-kpi"><div class="fm-dk-val">${r.r2!=null?(r.r2*100).toFixed(0)+'%':'—'}</div><div class="fm-dk-lbl">R²</div></div>
      <div class="fm-drill-kpi"><div class="fm-dk-val">${fmtPct(r.total_ret)}</div><div class="fm-dk-lbl">Total Return</div></div>
    </div>
    <div class="fm-drill-betas">${betaItems}</div>`;
}

function _fmRenderRollingBetas(r, fnames, labels) {
    const canvas = document.getElementById('fm-rolling-beta-chart');
    if (!canvas || !r.rolling_dates?.length) return;

    const datasets = (fnames || []).filter(f => r.rolling_betas?.[f]?.length).map(f => ({
        label: labels?.[f] || f,
        data:  r.rolling_betas[f],
        borderColor: FM_FACTOR_COLORS[f] || '#94a3b8',
        borderWidth: 1.5, pointRadius: 0, fill: false,
    }));

    if (fmState.charts['rolling']) { try { fmState.charts['rolling'].destroy(); } catch(_) {} }
    fmState.charts['rolling'] = new Chart(canvas, {
        type: 'line',
        data: { labels: r.rolling_dates, datasets },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: { legend: { display: true, position: 'top', labels: { color: '#94a3b8', font: { size: 9 }, boxWidth: 12 } } },
            scales: { x: { display: false }, y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#1e293b' } } },
        },
    });
}

function _fmRenderAttribution(r, fnames, labels) {
    const el = document.getElementById('fm-attribution');
    if (!el) return;

    const contribs = r.factor_contribs || {};
    const total    = r.total_ret || 0;
    const alpha    = r.alpha_contrib || 0;
    const allItems = [
        ...Object.entries(contribs).map(([f, v]) => ({ label: labels?.[f] || f, value: v, color: FM_FACTOR_COLORS[f] || '#94a3b8' })),
        { label: 'Alpha', value: alpha, color: '#a78bfa' },
    ].filter(x => x.value != null && Math.abs(x.value) > 0.0001);

    const maxAbs = Math.max(...allItems.map(x => Math.abs(x.value))) || 1;
    const fmtPct = v => v != null ? (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%' : '—';

    const rows = allItems.map(item => {
        const barW   = Math.round(Math.abs(item.value) / maxAbs * 100);
        const barDir = (item.value || 0) >= 0 ? 'right' : 'left';
        const valCol = (item.value || 0) >= 0 ? 'var(--green)' : 'var(--red)';
        return `<div class="fm-attr-row">
          <span class="fm-attr-label" style="color:${item.color}">${item.label}</span>
          <div class="fm-attr-bar-bg">
            <div class="fm-attr-bar" style="width:${barW}%;background:${item.color}40;float:${barDir}"></div>
          </div>
          <span class="fm-attr-val" style="color:${valCol}">${fmtPct(item.value)}</span>
        </div>`;
    }).join('');

    el.innerHTML = `
    <div class="fm-section-title">Return Attribution <span style="color:var(--text-dim);font-size:10px;font-weight:400">Total: ${fmtPct(total)}</span></div>
    <div class="fm-attr-list">${rows || '<span style="color:var(--text-dim);font-size:11px">No attribution data</span>'}</div>`;
}

// ── Loading / error ────────────────────────────────────────────
function _fmSetLoading(on) {
    const btn    = document.getElementById('btn-fm-load');
    const loadEl = document.getElementById('fm-loading');
    if (on) {
        if (btn)    { btn.disabled = true;  btn.textContent = '⏳ Running…'; }
        if (loadEl) loadEl.style.display = 'flex';
    } else {
        if (btn)    { btn.disabled = false; btn.textContent = '▶ Run Model'; }
        if (loadEl) loadEl.style.display = 'none';
    }
}
function _fmShowError(msg) {
    const el = document.getElementById('fm-empty');
    if (el) { el.style.display = ''; el.innerHTML = `<div class="empty-icon">⚠</div><p>${msg}</p>`; }
    const res = document.getElementById('fm-results');
    if (res) res.style.display = 'none';
}

// ── Init ──────────────────────────────────────────────────────
function initFactorModel() {
    if (!fmState.result) loadFactorModel();
}
