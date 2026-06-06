/**
 * market_regime.js — Market Regime Classifier UI
 *
 * Persistent regime badge in the top bar + full Regime tab with
 * history chart (LightweightCharts), per-regime stats table,
 * and recent transition timeline.
 */

const regimeState = {
    symbol: 'SPY',
    result: null,
    chart:  null,
    series: { price: null, regime: null },
};

// ── Topbar badge (auto-loads on page ready) ───────────────────
async function loadRegimeBadge(symbol) {
    symbol = (symbol || 'SPY').toUpperCase();
    regimeState.symbol = symbol;

    const badge     = document.getElementById('regime-badge');
    const iconEl    = document.getElementById('regime-badge-icon');
    const labelEl   = document.getElementById('regime-badge-label');
    if (!badge) return;

    try {
        const data = await apiFetch(`${API}/market-regime?symbol=${symbol}`);
        regimeState.result = data;

        const cur  = data.current;
        badge.style.background   = cur.bg  || 'rgba(100,116,139,0.15)';
        badge.style.borderColor  = cur.color + '60';
        badge.style.color        = cur.color;
        if (iconEl)  iconEl.textContent  = cur.icon  || '↔';
        if (labelEl) labelEl.textContent = cur.state || '—';
        badge.title = `Market Regime (${symbol}): ${cur.state} · ${cur.days_in} days · Score ${cur.score > 0 ? '+' : ''}${cur.score}`;

        // If regime tab is active, render full view
        if (document.getElementById('regime-area')?.style.display !== 'none') {
            _regimeRenderFull(data);
        }
    } catch (_) {
        if (labelEl) labelEl.textContent = 'N/A';
    }
}

// ── Tab init ──────────────────────────────────────────────────
function initRegime() {
    const sym = regimeState.symbol;
    if (regimeState.result) {
        _regimeRenderFull(regimeState.result);
    } else {
        loadRegimeFull(sym);
    }
}

async function loadRegimeFull(symbol) {
    symbol = (symbol || regimeState.symbol).toUpperCase();
    regimeState.symbol = symbol;
    _regimeSetLoading(true);
    try {
        const data = await apiFetch(`${API}/market-regime?symbol=${symbol}`);
        regimeState.result = data;
        _regimeRenderFull(data);
        // Also update badge
        loadRegimeBadge(symbol);
    } catch (e) {
        toastFromError(e, 'Regime');
        _regimeShowError(e.message);
    } finally {
        _regimeSetLoading(false);
    }
}

// ── Render ────────────────────────────────────────────────────
function _regimeRenderFull(data) {
    document.getElementById('regime-empty').style.display   = 'none';
    document.getElementById('regime-results').style.display = '';

    _regimeRenderHero(data.current);
    _regimeRenderHistory(data);
    _regimeRenderStats(data.regime_stats);
    _regimeRenderTransitions(data.transitions);
}

function _regimeRenderHero(cur) {
    const el = document.getElementById('regime-hero');
    if (!el) return;
    const score    = cur.score;
    const scoreStr = score > 0 ? `+${score}` : `${score}`;
    el.innerHTML = `
    <div class="rg-hero-badge" style="color:${cur.color};background:${cur.bg};border-color:${cur.color}60">
      <span class="rg-hero-icon">${cur.icon}</span>
      <span class="rg-hero-state">${cur.state}</span>
    </div>
    <div class="rg-hero-meta">
      <div class="rg-hero-stat"><span class="rg-hero-sl">Score</span><span class="rg-hero-sv" style="color:${cur.color}">${scoreStr}</span></div>
      <div class="rg-hero-stat"><span class="rg-hero-sl">Days in regime</span><span class="rg-hero-sv">${cur.days_in}</span></div>
      <div class="rg-hero-stat"><span class="rg-hero-sl">As of</span><span class="rg-hero-sv">${cur.date}</span></div>
    </div>`;
}

function _regimeRenderHistory(data) {
    const canvas = document.getElementById('regime-price-chart');
    if (!canvas) return;

    // Destroy & rebuild LWC chart
    if (regimeState.chart) {
        try { regimeState.chart.remove(); } catch (_) {}
        regimeState.chart = null;
    }

    const rows   = data.history || [];
    if (!rows.length) return;

    regimeState.chart = LightweightCharts.createChart(canvas, {
        layout: { background: { color: '#0d1117' }, textColor: '#8b949e', fontFamily: "'JetBrains Mono',monospace", fontSize: 10 },
        grid:   { vertLines: { color: '#1c2230' }, horzLines: { color: '#1c2230' } },
        rightPriceScale: { borderColor: '#30363d' },
        timeScale: { borderColor: '#30363d', timeVisible: true, secondsVisible: false },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        width:  canvas.clientWidth  || 800,
        height: canvas.clientHeight || 220,
        handleScroll: true, handleScale: true,
    });

    // Background fills by regime
    const META = data.regime_meta || {};
    const bgSeries = regimeState.chart.addHistogramSeries({
        priceScaleId: 'left', color: 'transparent',
        priceLineVisible: false, lastValueVisible: false,
    });
    regimeState.chart.applyOptions({ leftPriceScale: { visible: false } });

    bgSeries.setData(rows.filter(r => r.close).map(r => {
        const m   = META[r.state] || {};
        const col = (m.color || '#94a3b8') + '25';
        return { time: r.date, value: 1, color: col };
    }));

    // Price line
    const priceSeries = regimeState.chart.addLineSeries({
        color: '#60a5fa', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true,
    });
    priceSeries.setData(rows.filter(r => r.close).map(r => ({ time: r.date, value: r.close })));

    // Entry markers for regime changes
    const markers = [];
    let prev = null;
    rows.forEach(r => {
        if (r.state !== prev && r.state && r.close) {
            const m = META[r.state] || {};
            markers.push({
                time: r.date, position: 'aboveBar',
                color: m.color || '#94a3b8',
                shape: 'circle', text: r.state.split(' ')[0],
                size: 0,
            });
            prev = r.state;
        }
    });
    priceSeries.setMarkers(markers);
    regimeState.chart.timeScale().fitContent();

    // Resize observer
    const obs = new ResizeObserver(() => {
        if (regimeState.chart) {
            try { regimeState.chart.resize(canvas.clientWidth, canvas.clientHeight); } catch (_) {}
        }
    });
    obs.observe(canvas);
}

const _REGIME_ORDER = ["BULL STRONG", "BULL", "CHOP", "BEAR", "CRASH"];

function _regimeRenderStats(stats) {
    const el = document.getElementById('regime-stats-table');
    if (!el || !stats) return;

    const rows = _REGIME_ORDER.map(state => {
        const s   = stats[state] || {};
        const m   = { "BULL STRONG": {color:"#22c55e"}, "BULL": {color:"#4ade80"},
                      "CHOP": {color:"#94a3b8"}, "BEAR": {color:"#f87171"}, "CRASH": {color:"#ef4444"} };
        const col = m[state]?.color || '#94a3b8';
        const fmt = v => v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';
        const fmtHit = v => v == null ? '—' : Math.round(v * 100) + '%';
        const fmtDays = v => v == null || v === 0 ? '—' : v.toLocaleString();
        const pctTime = s.pct_of_time != null ? Math.round(s.pct_of_time * 100) + '%' : '—';

        return `<tr class="rg-stat-row">
          <td class="rg-st-td"><span class="rg-state-dot" style="background:${col}"></span>${state}</td>
          <td class="rg-st-td">${fmtDays(s.n_days)} <small style="color:var(--text-dim)">(${pctTime})</small></td>
          <td class="rg-st-td" style="color:${(s.fwd5_mean||0)>0?'var(--green)':'var(--red)'}">${fmt(s.fwd5_mean)}</td>
          <td class="rg-st-td">${fmtHit(s.fwd5_hit_rate)}</td>
          <td class="rg-st-td" style="color:${(s.fwd20_mean||0)>0?'var(--green)':'var(--red)'}">${fmt(s.fwd20_mean)}</td>
          <td class="rg-st-td">${fmtHit(s.fwd20_hit_rate)}</td>
        </tr>`;
    }).join('');

    el.innerHTML = `
    <div class="rg-section-title">Historical Per-Regime Statistics</div>
    <table class="rg-stats-tbl">
      <thead><tr>
        <th class="rg-st-th">Regime</th>
        <th class="rg-st-th">Days</th>
        <th class="rg-st-th">5d Mean Ret</th>
        <th class="rg-st-th">5d Hit Rate</th>
        <th class="rg-st-th">20d Mean Ret</th>
        <th class="rg-st-th">20d Hit Rate</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function _regimeRenderTransitions(transitions) {
    const el = document.getElementById('regime-transitions');
    if (!el || !transitions?.length) return;
    const META = { "BULL STRONG":"#22c55e","BULL":"#4ade80","CHOP":"#94a3b8","BEAR":"#f87171","CRASH":"#ef4444" };
    const pills = [...transitions].reverse().map(t =>
        `<div class="rg-trans-pill" style="border-color:${META[t.state]||'#94a3b8'}40;color:${META[t.state]||'#94a3b8'}">
           <span class="rg-trans-date">${t.date}</span>
           <span class="rg-trans-state">${t.state}</span>
         </div>`
    ).join('<span class="rg-trans-arrow">←</span>');

    el.innerHTML = `<div class="rg-section-title">Recent Regime Transitions</div>
                    <div class="rg-transitions">${pills}</div>`;
}

// ── Loading / error ───────────────────────────────────────────
function _regimeSetLoading(on) {
    const loadEl = document.getElementById('regime-loading');
    if (loadEl) loadEl.style.display = on ? 'flex' : 'none';
}
function _regimeShowError(msg) {
    const el = document.getElementById('regime-empty');
    if (el) { el.style.display = ''; el.innerHTML = `<div class="empty-icon">⚠</div><p>${msg}</p>`; }
    const res = document.getElementById('regime-results');
    if (res) res.style.display = 'none';
}
