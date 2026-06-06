/**
 * social_insights.js — Social Trends v5 client renderers.
 *
 * Lightweight glue over the new /api/llm/* and /api/insights/* endpoints.
 * Lives alongside social_trends.js; nothing here owns global state beyond
 * a thin cache for the panels we render lazily.
 */

const insightsState = {
    narrativeLoaded: false,
    portfolioOpen:   false,
};

// ── ι · Daily narrative panel ─────────────────────────────────────────
async function loadInsightNarrative(force = false) {
    const el = document.getElementById('insight-narrative');
    if (!el) return;
    if (insightsState.narrativeLoaded && !force) return;
    insightsState.narrativeLoaded = true;
    el.innerHTML = `<div class="ins-loading"><span class="spinner-mini"></span>Generating today's read…</div>`;
    try {
        const d = await apiFetch(`${API}/llm/narrative`);
        el.innerHTML = `<div class="ins-narr-body">${escapeHtml(d.text)}</div>
            <div class="ins-narr-meta">${d.cached ? 'cached' : 'fresh'} · click ↻ to regenerate</div>`;
    } catch (e) {
        el.innerHTML = `<div class="ins-err">narrative unavailable: ${escapeHtml(e.message)}</div>`;
    }
}

function refreshInsightNarrative() { insightsState.narrativeLoaded = false; loadInsightNarrative(true); }

// ── ι · Trend explanation ('?' button on a card) ──────────────────────
async function explainTrend(term) {
    const m = ensureSocialModal();
    m.overlay.style.display = 'flex';
    m.title.textContent = `Why is "${term}" trending?`;
    m.body.innerHTML = `<div class="social-modal-loading">Asking the model…</div>`;
    try {
        const lc = await apiFetch(`${API}/insights/lifecycle/${encodeURIComponent(term)}`);
        const ex = await apiFetch(`${API}/llm/explain?term=${encodeURIComponent(term)}`);
        const arb = (await apiFetch(`${API}/insights/arbitrage`)).arbitrage.find(a => a.term === term);
        m.body.innerHTML = `
            <div class="ins-block">
              <div class="ins-block-label">Explanation</div>
              <div class="ins-narr-body">${escapeHtml(ex.text)}</div>
            </div>
            <div class="ins-block">
              <div class="ins-block-label">Lifecycle</div>
              <div><strong>${lc.archetype}</strong> — ${escapeHtml(lc.description)}.
                ${lc.half_life_days != null ? `Estimated half-life ~${lc.half_life_days}d.` : ''}</div>
            </div>
            ${arb ? `<div class="ins-block">
              <div class="ins-block-label">Search arbitrage</div>
              <div>Leader: <strong>${arb.leader}</strong> · bias ${arb.bias}</div>
            </div>` : ''}`;
    } catch (e) {
        m.body.innerHTML = `<div class="dd-err">${escapeHtml(e.message)}</div>`;
    }
}

// ── ι · Idea critique on demand ───────────────────────────────────────
async function critiqueIdea(ticker) {
    const m = ensureSocialModal();
    m.overlay.style.display = 'flex';
    m.title.textContent = `Why might ${ticker} be wrong?`;
    m.body.innerHTML = `<div class="social-modal-loading">Asking the sceptical desk…</div>`;
    try {
        const crit = await apiFetch(`${API}/llm/critique?ticker=${encodeURIComponent(ticker)}`);
        const risk = await apiFetch(`${API}/insights/risk/${encodeURIComponent(ticker)}`);
        const links = await apiFetch(`${API}/insights/trade-links/${encodeURIComponent(ticker)}`);
        const sec  = await apiFetch(`${API}/insights/sec/${encodeURIComponent(ticker)}`);
        const sz   = await apiFetch(`${API}/insights/position-size?ticker=${encodeURIComponent(ticker)}`);
        const flagsHtml = (risk.flags || []).map(f => `<span class="ins-flag">${escapeHtml(f)}</span>`).join(' ') || '<span class="ins-muted">no near-term flags</span>';
        const linksHtml = Object.entries(links.links || {})
            .map(([k,v]) => `<a href="${v}" target="_blank" rel="noopener" class="ins-link">${k}</a>`).join(' · ');
        m.body.innerHTML = `
            <div class="ins-block">
              <div class="ins-block-label">Contrarian read</div>
              <div class="ins-narr-body">${escapeHtml(crit.text)}</div>
            </div>
            <div class="ins-block"><div class="ins-block-label">Near-term flags</div>${flagsHtml}</div>
            <div class="ins-block">
              <div class="ins-block-label">Position size (using $10K)</div>
              <div>${escapeHtml(sz.note || '—')}</div>
            </div>
            <div class="ins-block">
              <div class="ins-block-label">Smart-money confirms?</div>
              <div>${sec.confirms ? '✓ recent SEC activity detected' : '— no recent SEC activity'} <span class="ins-muted">(${sec.note || ''})</span></div>
            </div>
            <div class="ins-block"><div class="ins-block-label">Trade ticket</div>${linksHtml}</div>
            <div class="ins-block">
              <button class="ind-pill" onclick="openScenarioBuilder('${ticker}')">▶ Open scenario builder</button>
            </div>`;
    } catch (e) {
        m.body.innerHTML = `<div class="dd-err">${escapeHtml(e.message)}</div>`;
    }
}

// ── μ · Portfolio exposure panel ──────────────────────────────────────
async function loadPortfolioExposure() {
    const el = document.getElementById('insight-portfolio');
    if (!el) return;
    el.innerHTML = `<div class="ins-loading"><span class="spinner-mini"></span>Crunching watchlist…</div>`;
    try {
        const d = await apiFetch(`${API}/insights/portfolio`);
        if (!(d.themes || []).length) {
            el.innerHTML = `<div class="ins-muted">No themed exposure yet — add tickers to your watchlist.</div>`;
            return;
        }
        const bars = d.themes.map(t => `
            <div class="ins-pf-row">
              <span class="ins-pf-theme" onclick="openThemeDrillDown('${t.theme.replace(/'/g,"\\'")}')">${escapeHtml(t.theme)}</span>
              <div class="ins-pf-bar"><div class="ins-pf-fill" style="width:${t.weight}%"></div></div>
              <span class="ins-pf-pct">${t.weight}%</span>
              <span class="ins-pf-tickers">${t.tickers.slice(0,4).join(' · ')}</span>
            </div>`).join('');
        const gaps = (d.coverage_gaps || []).slice(0, 6).map(g =>
            `<span class="ins-gap-chip" onclick="socialViewTicker('${g.top_play}')" title="${escapeHtml(g.theme)} — top play ${g.top_play}">${escapeHtml(g.theme)}</span>`
        ).join(' ');
        el.innerHTML = `
            <div class="ins-pf-list">${bars}</div>
            ${gaps ? `<div class="ins-pf-gaps"><span class="ins-block-label">Coverage gaps</span>${gaps}</div>` : ''}`;
    } catch (e) {
        el.innerHTML = `<div class="ins-err">${escapeHtml(e.message)}</div>`;
    }
}

// ── π · Streak + anomaly bar (ambient intelligence row) ───────────────
async function loadAmbientBar() {
    const el = document.getElementById('insight-ambient');
    if (!el) return;
    try {
        const [s, a] = await Promise.all([
            apiFetch(`${API}/insights/streaks`),
            apiFetch(`${API}/insights/anomalies`),
        ]);
        const streaks = (s.streaks || []).slice(0, 4).map(x =>
            `<span class="ins-pill ins-streak" title="Top-30 for ${x.days} consecutive days">🏃 ${escapeHtml(x.term)} · ${x.days}d</span>`).join('');
        const anoms = (a.anomalies || []).slice(0, 4).map(x =>
            `<span class="ins-pill ins-anom" title="Momentum ${x.momentum} vs theme baseline ${x.baseline} (z=${x.z})">⚡ ${escapeHtml(x.term)} · z=${x.z}</span>`).join('');
        const inner = (streaks || anoms)
            ? streaks + anoms
            : `<span class="ins-muted">Streaks &amp; anomalies will appear once daily snapshots accumulate.</span>`;
        el.innerHTML = inner;
    } catch (e) {
        el.innerHTML = '';
    }
}

// ── ξ · Heatmap (terms × momentum, colour-banded) ─────────────────────
async function loadHeatmap() {
    const el = document.getElementById('insight-heatmap');
    if (!el) return;
    if (!socialState.data) return;
    const trends = (socialState.data.trends || []).slice(0, 24);
    const buckets = (n) =>
        n >= 85 ? 'hm-5' : n >= 70 ? 'hm-4' : n >= 55 ? 'hm-3' : n >= 40 ? 'hm-2' : 'hm-1';
    el.innerHTML = trends.map(t =>
        `<div class="hm-cell ${buckets(t.momentum)}" title="${escapeHtml(t.term)} · momentum ${t.momentum}" onclick="explainTrend('${t.term.replace(/'/g,"\\'")}')">
           <span class="hm-term">${escapeHtml(t.term)}</span>
           <span class="hm-val">${t.momentum}</span>
         </div>`
    ).join('');
}

// ── ξ.3 · Theme rotation map (gained / lost attention vs N days ago) ──
async function loadRotationMap() {
    const el = document.getElementById('insight-rotation');
    if (!el) return;
    try {
        const d = await apiFetch(`${API}/insights/rotation?days=7`);
        const rows = (d.rotation || []).slice(0, 10);
        if (!rows.length) {
            el.innerHTML = `<div class="ins-muted">${escapeHtml(d.note || 'Rotation appears once you have multiple days of snapshots.')}</div>`;
            return;
        }
        el.innerHTML = `<div class="ins-block-label">Theme rotation · last 7d</div>` +
            rows.map(r => {
                const arrow = r.direction === 'rising' ? '▲' : r.direction === 'falling' ? '▼'
                            : r.direction === 'new' ? '🆕' : '·';
                const cls   = r.direction === 'rising' ? 'rot-up'
                            : r.direction === 'falling' ? 'rot-down'
                            : r.direction === 'new' ? 'rot-new' : 'rot-flat';
                const delta = r.delta == null ? '—' : (r.delta >= 0 ? '+' : '') + r.delta.toFixed(0);
                return `<div class="ins-rot-row ${cls}" onclick="openThemeDrillDown('${r.theme.replace(/'/g,"\\'")}')">
                  <span class="rot-arrow">${arrow}</span>
                  <span class="rot-theme">${escapeHtml(r.theme)}</span>
                  <span class="rot-delta">${delta}</span>
                </div>`;
            }).join('');
    } catch (e) { el.innerHTML = ''; }
}

// ── ο.2 · Scenario builder modal ──────────────────────────────────────
async function openScenarioBuilder(ticker) {
    const m = ensureSocialModal();
    m.overlay.style.display = 'flex';
    m.title.textContent = `Scenario · ${ticker}`;
    m.body.innerHTML = `
      <div class="ins-block">
        <div class="ins-block-label">Inputs</div>
        <label class="sc-label">Target momentum
          <input id="sc-target" class="sc-input" type="number" value="95" min="0" max="100">
        </label>
        <label class="sc-label">Beta (% per +10 mom)
          <input id="sc-beta" class="sc-input" type="number" step="0.05" value="0.30">
        </label>
        <button class="ind-pill" onclick="runScenario('${ticker}')">Project</button>
      </div>
      <div id="sc-result" class="ins-block"></div>`;
    runScenario(ticker);
}

async function runScenario(ticker) {
    const target = document.getElementById('sc-target')?.value || 95;
    const beta   = document.getElementById('sc-beta')?.value   || 0.30;
    const out    = document.getElementById('sc-result');
    if (!out) return;
    out.innerHTML = `<div class="ins-loading"><span class="spinner-mini"></span>Projecting…</div>`;
    try {
        const d = await apiFetch(`${API}/insights/scenario/${encodeURIComponent(ticker)}?target_mom=${target}&beta=${beta}`);
        if (d.error) { out.innerHTML = `<div class="dd-err">${escapeHtml(d.error)}</div>`; return; }
        const dirCls = d.implied_move >= 0 ? 'ret-up' : 'ret-down';
        out.innerHTML = `
          <div class="ins-block-label">Projection</div>
          <div class="sc-grid">
            <div><span class="ins-muted">Price now</span><div class="sc-val">$${d.price_now}</div></div>
            <div><span class="ins-muted">Momentum</span><div class="sc-val">${d.momentum_now} → ${d.momentum_target}</div></div>
            <div><span class="ins-muted">Implied move</span><div class="sc-val ${dirCls}">${d.implied_move >= 0 ? '+' : ''}${d.implied_move}%</div></div>
            <div><span class="ins-muted">Price target</span><div class="sc-val">$${d.price_target}</div></div>
          </div>
          <div class="ins-muted" style="margin-top:8px; font-size:11px;">${escapeHtml(d.assumption)}</div>`;
    } catch (e) {
        out.innerHTML = `<div class="dd-err">${escapeHtml(e.message)}</div>`;
    }
}

// ── ρ · Custom signal DSL panel ───────────────────────────────────────
const SIGNAL_EXAMPLES = [
    "catch_up > 50 and purity >= 0.7",
    "status == 'catch_up' and trend_momentum > 80",
    "in_watchlist and ret_20d < 0",
    "score > 70 and purity > 0.8",
];

async function runSignalDSL() {
    const inp = document.getElementById('signal-expr');
    const out = document.getElementById('signal-result');
    if (!inp || !out) return;
    const expr = inp.value.trim();
    if (!expr) { out.innerHTML = ''; return; }
    out.innerHTML = `<div class="ins-loading"><span class="spinner-mini"></span>Evaluating…</div>`;
    try {
        const d = await apiFetch(`${API}/insights/signal?expr=${encodeURIComponent(expr)}`);
        if (d.error) {
            out.innerHTML = `<div class="dd-err">${escapeHtml(d.error)}</div>`;
            return;
        }
        if (!d.matches.length) {
            out.innerHTML = `<div class="ins-muted">No matches.</div>`;
            return;
        }
        out.innerHTML = `<div class="ins-muted" style="font-size:10px; margin-bottom:4px;">${d.count} match${d.count === 1 ? '' : 'es'}</div>` +
            d.matches.slice(0, 10).map(m =>
                `<div class="ins-sig-match">
                   <span class="dd-sym" onclick="socialViewTicker('${m.ticker}')">${m.ticker}</span>
                   <span class="ins-muted">${escapeHtml(m.theme)}</span>
                   <span class="rot-delta">${m.score}</span>
                 </div>`).join('');
    } catch (e) {
        out.innerHTML = `<div class="dd-err">${escapeHtml(e.message)}</div>`;
    }
}

function setSignalExample(idx) {
    const inp = document.getElementById('signal-expr');
    if (inp) { inp.value = SIGNAL_EXAMPLES[idx % SIGNAL_EXAMPLES.length]; runSignalDSL(); }
}

// ── ρ · CSV export of the visible idea rows ───────────────────────────
function exportIdeasCSV() {
    if (!socialState.data) return;
    const cols = ['ticker','name','theme','purity_label','score','catch_up','ret_20d','status','trend_momentum'];
    const lines = ['# FinDash Social Trends idea export',
                   cols.join(',')];
    for (const i of socialState.data.ideas || []) {
        lines.push(cols.map(c => {
            const v = i[c] == null ? '' : String(i[c]).replace(/"/g, '""');
            return /[,"\n]/.test(v) ? `"${v}"` : v;
        }).join(','));
    }
    const blob = new Blob([lines.join('\n')], {type: 'text/csv'});
    const url  = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'findash-ideas.csv';
    document.body.appendChild(a); a.click(); a.remove();
    URL.revokeObjectURL(url);
}

// ── Utilities ─────────────────────────────────────────────────────────
function escapeHtml(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Refresh ambient + portfolio bars whenever the Social tab loads new data.
const _origRenderSocialTrendsV5 = renderSocialTrends;
renderSocialTrends = function (d) {
    _origRenderSocialTrendsV5(d);
    if (document.getElementById('insight-narrative')) {
        loadInsightNarrative();
        loadPortfolioExposure();
        loadAmbientBar();
        loadHeatmap();
        loadRotationMap();
    }
};
