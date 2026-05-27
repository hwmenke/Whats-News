/**
 * swing_widget.js — Adaptive Trend Widget
 *
 * Renders a sidebar panel inside #trend-area (and any tab that calls
 * initSwingWidget) showing live swing-data metrics + A/B/C grade for
 * the active symbol.  Automatically refreshes on symbol change via
 * the _extrasOnSymbolLoad hook.
 */

// ── State ──────────────────────────────────────────────────────────────────────
let _swGradeData = null;

// Called by _extrasOnSymbolLoad (chart_extras.js) on every symbol switch
function _swingWidgetOnSymbolLoad(symbol) {
    if (!symbol) return;
    const el = document.getElementById('swing-widget-panel');
    if (!el || el.offsetParent === null) return; // not visible — skip
    loadSwingWidget(symbol);
}

function initSwingWidget() {
    const sym = typeof state !== 'undefined' ? state.activeSymbol : null;
    if (sym) loadSwingWidget(sym);
}

async function loadSwingWidget(symbol) {
    const panel = document.getElementById('swing-widget-panel');
    if (!panel) return;

    panel.innerHTML = '<div class="sw-loading"><span class="spinner"></span></div>';
    try {
        const data = await apiFetch(`${API}/setup-grade/${encodeURIComponent(symbol)}`);
        _swGradeData = data;
        _renderSwingWidget(data);
    } catch (e) {
        panel.innerHTML = `<div class="sw-error">${e.message}</div>`;
    }
}

function _renderSwingWidget(d) {
    const panel = document.getElementById('swing-widget-panel');
    if (!panel) return;

    const gradeCls  = `sw-grade-${(d.grade || 'C').toLowerCase()}`;
    const extColor  = d.atr_mult_50ma > 4 ? 'var(--red)' : d.atr_mult_50ma > 2.5 ? 'var(--yellow)' : 'var(--green)';
    const rvolColor = d.rvol >= 1.5 ? 'var(--green)' : d.rvol >= 1.0 ? 'var(--text-primary)' : 'var(--red)';
    const lodColor  = d.lod_dist_atr > 0.6 ? 'var(--red)' : d.lod_dist_atr > 0.3 ? 'var(--yellow)' : 'var(--green)';
    const vcpColor  = d.vcp_score > 1.5 ? 'var(--green)' : d.vcp_score > 0.5 ? 'var(--yellow)' : 'var(--text-muted)';

    // Extension gauge: 0→6x, red zone at 4x
    const extPct     = Math.min(100, (d.atr_mult_50ma / 6) * 100);
    const extGaugePct= Math.max(0, extPct);

    // Pre-entry quick checks
    const checks = [
        { label: 'RVOL ≥ 1.0×',         pass: d.rvol >= 1.0 },
        { label: 'Not extended (< 4×)',  pass: d.atr_mult_50ma < 4.0 },
        { label: 'LoD tight (< 0.6 ATR)',pass: d.lod_dist_atr < 0.6 },
        { label: 'VCP / contraction',    pass: d.vcp_score > 0.5 },
        { label: 'Near 52W high',        pass: d.range_pos_52w >= 0.60 },
    ];
    const allPass    = checks.every(c => c.pass);
    const checkHtml  = checks.map(c =>
        `<div class="sw-check-row ${c.pass ? 'sw-chk-pass' : 'sw-chk-fail'}">
            <span class="sw-chk-icon">${c.pass ? '✓' : '✗'}</span>
            <span>${c.label}</span>
        </div>`
    ).join('');

    // Factor pills
    const factorHtml = (d.factors || []).map(f =>
        `<span class="sw-factor ${f.bull ? 'sw-factor-bull' : 'sw-factor-bear'}">${f.label}</span>`
    ).join('');

    panel.innerHTML = `
        <div class="sw-header">
            <span class="sw-sym">${d.symbol}</span>
            <span class="sw-grade ${gradeCls}">${d.grade}</span>
            <span class="sw-score-label">Score ${d.score}</span>
        </div>

        <div class="sw-metrics">
            <div class="sw-row"><span class="sw-label">ADR%</span>
                <span class="sw-val">${d.adr_pct?.toFixed(1) ?? '–'}%</span></div>
            <div class="sw-row"><span class="sw-label">ATR-14</span>
                <span class="sw-val">${d.atr_14?.toFixed(2) ?? '–'}</span></div>
            <div class="sw-row"><span class="sw-label">RVOL</span>
                <span class="sw-val" style="color:${rvolColor}">${d.rvol?.toFixed(1) ?? '–'}×</span></div>
            <div class="sw-row"><span class="sw-label">ATR×50MA</span>
                <span class="sw-val" style="color:${extColor}">${d.atr_mult_50ma?.toFixed(1) ?? '–'}×</span></div>
            <div class="sw-row"><span class="sw-label">LoD dist</span>
                <span class="sw-val" style="color:${lodColor}">${d.lod_dist_atr?.toFixed(2) ?? '–'} ATR</span></div>
            <div class="sw-row"><span class="sw-label">VCP</span>
                <span class="sw-val" style="color:${vcpColor}">${d.vcp_score?.toFixed(1) ?? '–'}</span></div>
            <div class="sw-row"><span class="sw-label">52W pos</span>
                <span class="sw-val">${((d.range_pos_52w || 0) * 100).toFixed(0)}%ile</span></div>
            ${d.ret_20d != null ? `<div class="sw-row"><span class="sw-label">20D ret</span>
                <span class="sw-val" style="color:${d.ret_20d >= 0 ? 'var(--green)' : 'var(--red)'}">
                    ${d.ret_20d >= 0 ? '+' : ''}${d.ret_20d.toFixed(1)}%</span></div>` : ''}
        </div>

        <div class="sw-ext-gauge-wrap">
            <div class="sw-ext-label">ATR Extension from 50-MA</div>
            <div class="sw-ext-track">
                <div class="sw-ext-fill" style="width:${extGaugePct.toFixed(1)}%; background:${extColor};"></div>
                <div class="sw-ext-limit"></div>
            </div>
            <div class="sw-ext-ticks"><span>0×</span><span>2×</span><span>4×⚠</span><span>6×</span></div>
        </div>

        <div class="sw-factors">${factorHtml}</div>

        <div class="sw-checks-header">Pre-Entry Quick Check</div>
        <div class="sw-checks">${checkHtml}</div>
        <div class="sw-checks-verdict ${allPass ? 'sw-verdict-go' : 'sw-verdict-wait'}">
            ${allPass ? '✓ Setup looks tradeable' : '⚠ Review flagged criteria'}
        </div>

        <button class="btn btn-ghost sw-refresh-btn" onclick="loadSwingWidget('${d.symbol}')">↻ Refresh</button>
    `;
}
