/**
 * momentum_ranker.js — Cross-Sectional Momentum Ranking UI
 *
 * Table: all watchlist symbols ranked by composite momentum score.
 * Portfolio chart: top-tercile momentum strategy vs equal-weight.
 */

const momState = {
    result: null,
    sortCol: 'rank',
    sortAsc: true,
    chart: null,
};

const MOM_TIER_META = {
    STRONG:  { color: '#22c55e', bg: 'rgba(34,197,94,0.15)',   label: '▲ Strong' },
    LEADING: { color: '#86efac', bg: 'rgba(134,239,172,0.08)', label: '↑ Leading' },
    LAGGING: { color: '#fca5a5', bg: 'rgba(252,165,165,0.08)', label: '↓ Lagging' },
    WEAK:    { color: '#ef4444', bg: 'rgba(239,68,68,0.12)',   label: '▼ Weak' },
};

// ── Load ──────────────────────────────────────────────────────
async function loadMomentumRanks() {
    _momSetLoading(true);
    try {
        const data = await apiFetch(`${API}/momentum-rank`);
        momState.result = data;
        _momRenderResults(data);
    } catch (e) {
        toastFromError(e, 'Momentum');
        _momShowError(e.message);
    } finally {
        _momSetLoading(false);
    }
}

// ── Render ────────────────────────────────────────────────────
function _momRenderResults(data) {
    document.getElementById('mom-empty').style.display   = 'none';
    document.getElementById('mom-results').style.display = '';

    _momRenderSummary(data);
    _momRenderTable(data.rankings);
    _momRenderChart(data.portfolio);
}

function _momRenderSummary(data) {
    const el = document.getElementById('mom-summary');
    if (!el) return;
    const ranks  = data.rankings || [];
    const strong = ranks.filter(r => r.tier === 'STRONG').length;
    const weak   = ranks.filter(r => r.tier === 'WEAK').length;
    const port   = data.portfolio || {};
    const fmtPct = v => v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';

    el.innerHTML = `
      <div class="mom-kpi"><div class="mom-kpi-val" style="color:#22c55e">${strong}</div><div class="mom-kpi-lbl">Strong</div></div>
      <div class="mom-kpi"><div class="mom-kpi-val" style="color:#ef4444">${weak}</div><div class="mom-kpi-lbl">Weak</div></div>
      <div class="mom-kpi"><div class="mom-kpi-val">${data.n_symbols}</div><div class="mom-kpi-lbl">Symbols</div></div>
      <div class="mom-kpi-sep"></div>
      <div class="mom-kpi"><div class="mom-kpi-val" style="color:${(port.total_return_port||0)>=0?'var(--green)':'var(--red)'}">${fmtPct(port.total_return_port)}</div><div class="mom-kpi-lbl">Mom. Portfolio</div></div>
      <div class="mom-kpi"><div class="mom-kpi-val">${fmtPct(port.total_return_bench)}</div><div class="mom-kpi-lbl">Equal-Weight</div></div>`;
}

function _momRenderTable(rankings) {
    const el = document.getElementById('mom-table-body');
    if (!el) return;

    const fmtR = (v, dir = true) => {
        if (v == null) return '<span style="color:var(--text-dim)">—</span>';
        const pct = (v * 100).toFixed(1);
        const cls = v > 0 ? 'mom-ret-pos' : v < 0 ? 'mom-ret-neg' : '';
        return `<span class="${cls}">${v >= 0 ? '+' : ''}${pct}%</span>`;
    };

    el.innerHTML = (rankings || []).map(r => {
        const tier = MOM_TIER_META[r.tier] || {};
        const bar  = r.composite != null ? Math.min(100, Math.round(Math.abs(r.composite) / 2 * 100)) : 0;
        const barDir = (r.composite || 0) >= 0 ? 'right' : 'left';
        const barClr = (r.composite || 0) >= 0 ? '#22c55e' : '#ef4444';

        return `<tr class="mom-tr">
          <td class="mom-td mom-rank">${r.rank}</td>
          <td class="mom-td mom-symbol">
            <b>${r.symbol}</b>
            ${r.name ? `<span class="mom-name">${r.name}</span>` : ''}
          </td>
          <td class="mom-td">
            <span class="mom-tier-badge" style="color:${tier.color};background:${tier.bg}">${tier.label}</span>
          </td>
          <td class="mom-td">
            <div class="mom-score-wrap">
              <div class="mom-score-bar-bg">
                <div class="mom-score-bar" style="width:${bar}%;background:${barClr};float:${barDir}"></div>
              </div>
              <span class="mom-score-val">${r.composite != null ? (r.composite >= 0 ? '+' : '') + r.composite.toFixed(2) : '—'}</span>
            </div>
          </td>
          <td class="mom-td">${fmtR(r.ret_1m)}</td>
          <td class="mom-td">${fmtR(r.ret_3m)}</td>
          <td class="mom-td">${fmtR(r.ret_6m)}</td>
          <td class="mom-td">${fmtR(r.ret_12m_skip1m)}</td>
          <td class="mom-td" style="font-family:var(--font-mono);font-size:11px">${r.price != null ? r.price.toFixed(2) : '—'}</td>
          <td class="mom-td">${fmtR(r.chg1d)}</td>
        </tr>`;
    }).join('');
}

function _momRenderChart(portfolio) {
    const canvas = document.getElementById('mom-portfolio-chart');
    if (!canvas || !portfolio?.dates?.length) return;

    if (momState.chart) { try { momState.chart.destroy(); } catch(_) {} }

    momState.chart = new Chart(canvas, {
        type: 'line',
        data: {
            labels: portfolio.dates,
            datasets: [
                { label: 'Momentum (top tercile)', data: portfolio.portfolio,
                  borderColor: '#22c55e', borderWidth: 2, pointRadius: 0, fill: false },
                { label: 'Equal-Weight',            data: portfolio.benchmark,
                  borderColor: '#94a3b8', borderWidth: 1.5, borderDash: [4, 3], pointRadius: 0, fill: false },
            ],
        },
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: {
                legend: { display: true, position: 'top', labels: { color: '#94a3b8', font: { size: 10 } } },
            },
            scales: {
                x: { display: false },
                y: { ticks: { color: '#94a3b8', font: { size: 10 } }, grid: { color: '#1e293b' } },
            },
        },
    });
}

// ── Loading / error ───────────────────────────────────────────
function _momSetLoading(on) {
    const btn    = document.getElementById('btn-mom-load');
    const loadEl = document.getElementById('mom-loading');
    if (on) {
        if (btn)    { btn.disabled = true;  btn.textContent = '⏳ Ranking…'; }
        if (loadEl) loadEl.style.display = 'flex';
    } else {
        if (btn)    { btn.disabled = false; btn.textContent = '↻ Refresh'; }
        if (loadEl) loadEl.style.display = 'none';
    }
}
function _momShowError(msg) {
    const el = document.getElementById('mom-empty');
    if (el) { el.style.display = ''; el.innerHTML = `<div class="empty-icon">⚠</div><p>${msg}</p>`; }
    const res = document.getElementById('mom-results');
    if (res) res.style.display = 'none';
}

// ── Init ──────────────────────────────────────────────────────
function initMomentumRanker() {
    if (!momState.result) loadMomentumRanks();
}
