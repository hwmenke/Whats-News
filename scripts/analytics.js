/**
 * analytics.js — Portfolio Analytics + R-Distribution Business Scorecard
 *
 * Section A: Dollar P&L analytics from positions table (equity curve, Sharpe, etc.)
 * Section B: R-multiple distribution from journal entries (business scorecard)
 */

let _analyticsChart = null;

function _anEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

function _anKpi(label, value, cls = '') {
    return `<div class="an-kpi"><div class="an-kpi-label">${label}</div><div class="an-kpi-value ${cls}">${value}</div></div>`;
}

function _anFmtPct(v) {
    return (v === null || v === undefined) ? '—' : (v * 100).toFixed(1) + '%';
}

function _anFmtNum(v, d = 2) {
    return (v === null || v === undefined) ? '—' : Number(v).toFixed(d);
}

// ── Section A: Dollar P&L ─────────────────────────────────────────────────────

async function _loadDollarAnalytics() {
    const kpis  = document.getElementById('analytics-kpis');
    const tbody = document.getElementById('analytics-trades');
    if (!kpis) return;
    kpis.innerHTML = '<div class="an-muted"><span class="spinner"></span> Computing…</div>';
    if (tbody) tbody.innerHTML = '';

    try {
        const d = await apiFetch(`${API}/analytics`);
        if (!d.trade_count) {
            kpis.innerHTML = '<div class="an-muted">No closed positions yet.</div>';
            if (_analyticsChart) { _analyticsChart.destroy(); _analyticsChart = null; }
            return;
        }
        const wr = d.win_rate;
        kpis.innerHTML = [
            _anKpi('Trades',       d.trade_count),
            _anKpi('Win Rate',     _anFmtPct(wr),              wr !== null && wr >= 0.5 ? 'an-pos' : 'an-neg'),
            _anKpi('Profit Factor',_anFmtNum(d.profit_factor)),
            _anKpi('Avg Win $',    _anFmtNum(d.avg_win),       'an-pos'),
            _anKpi('Avg Loss $',   _anFmtNum(d.avg_loss),      'an-neg'),
            _anKpi('Sharpe',       _anFmtNum(d.sharpe)),
            _anKpi('Max DD',       _anFmtPct(d.max_drawdown),  'an-neg'),
        ].join('');

        const ctx = document.getElementById('analytics-equity');
        if (ctx && window.Chart) {
            if (_analyticsChart) _analyticsChart.destroy();
            _analyticsChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: d.equity_curve.map(p => p.date),
                    datasets: [{
                        label: 'Cumulative P&L',
                        data: d.equity_curve.map(p => p.equity),
                        borderColor: '#3b82f6',
                        backgroundColor: 'rgba(59,130,246,0.12)',
                        fill: true, tension: 0.15, pointRadius: 0,
                    }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: { x: { ticks: { maxTicksLimit: 8 } } },
                },
            });
        }

        if (tbody) {
            tbody.innerHTML = d.trades.map(t => `
                <tr>
                    <td><strong>${_anEsc(t.symbol)}</strong></td>
                    <td>${_anEsc(t.date)}</td>
                    <td class="${t.pnl >= 0 ? 'an-pos' : 'an-neg'}">${_anFmtNum(t.pnl)}</td>
                    <td class="${t.pct >= 0 ? 'an-pos' : 'an-neg'}">${t.pct >= 0 ? '+' : ''}${_anFmtNum(t.pct)}%</td>
                </tr>`).join('');
        }
    } catch (e) {
        kpis.innerHTML = `<div class="an-muted">Failed: ${_anEsc(e.message || e)}</div>`;
    }
}

// ── Section B: R-Distribution Business Scorecard ──────────────────────────────

async function _loadRAnalytics() {
    const panel = document.getElementById('r-analytics-panel');
    if (!panel) return;
    panel.innerHTML = '<div class="an-muted"><span class="spinner"></span> Computing R-distribution…</div>';

    try {
        const d = await apiFetch(`${API}/r-analytics`);

        if (!d.count) {
            panel.innerHTML = '<div class="an-muted">No journal entries with stop_loss yet.<br>Add trades to the journal with a stop price to see R analytics.</div>';
            return;
        }

        const exp     = d.expectancy;
        const expCls  = exp > 0 ? 'an-pos' : 'an-neg';
        const wrCls   = d.win_rate >= 0.5 ? 'an-pos' : d.win_rate >= 0.3 ? 'an-warn' : 'an-neg';
        const slipMsg = d.avg_loss_slippage !== null
            ? (d.avg_loss_slippage < -0.05
                ? `<span class="an-neg">avg loss ${(d.avg_loss_slippage).toFixed(2)}R worse than −1R</span>`
                : `<span class="an-pos">losses near planned −1R (${d.avg_loss_slippage > 0 ? '+' : ''}${d.avg_loss_slippage.toFixed(2)}R avg)</span>`)
            : '';

        // Histogram bars
        const maxCount = Math.max(...d.histogram.map(b => b.count), 1);
        const histHtml = d.histogram.map(b => {
            const isLeft  = b.min < 0;
            const barW    = Math.round((b.count / maxCount) * 100);
            const barCls  = b.min >= 1 ? 'rh-bar-win' : b.max <= 0 ? 'rh-bar-loss' : 'rh-bar-scratch';
            return `<div class="rh-row">
                <span class="rh-label">${b.label}</span>
                <div class="rh-track">
                    <div class="rh-bar ${barCls}" style="width:${barW}%"></div>
                </div>
                <span class="rh-count">${b.count}</span>
                <span class="rh-pct">${b.pct}%</span>
            </div>`;
        }).join('');

        // Grade breakdown table
        const gradeRows = Object.entries(d.grade_stats || {}).map(([g, s]) => {
            const expCls = s.expectancy > 0 ? 'an-pos' : 'an-neg';
            return `<tr>
                <td>${g ? `<span class="sw-grade sw-grade-${g.toLowerCase()} sw-grade-sm">${g}</span>` : '—'}</td>
                <td>${s.count}</td>
                <td>${(s.win_rate * 100).toFixed(0)}%</td>
                <td>${s.avg_r > 0 ? '+' : ''}${s.avg_r.toFixed(2)}R</td>
                <td class="${expCls}">${s.expectancy > 0 ? '+' : ''}${s.expectancy.toFixed(3)}R</td>
            </tr>`;
        }).join('');

        panel.innerHTML = `
            <div class="an-section-header">R-Distribution Business Scorecard</div>

            <div class="an-kpis rh-kpis">
                ${_anKpi('Trades (R)',    d.count)}
                ${_anKpi('Win Rate',      (d.win_rate * 100).toFixed(1) + '%',  wrCls)}
                ${_anKpi('Avg Win',       '+' + d.avg_win_r.toFixed(2) + 'R',  'an-pos')}
                ${_anKpi('Avg Loss',      d.avg_loss_r.toFixed(2) + 'R',       'an-neg')}
                ${_anKpi('Payoff Ratio',  d.payoff_ratio ? d.payoff_ratio.toFixed(2) + '×' : '—')}
                ${_anKpi('Expectancy',    (exp > 0 ? '+' : '') + exp.toFixed(3) + 'R / trade', expCls)}
            </div>

            ${slipMsg ? `<div class="rh-slip-note">${slipMsg}</div>` : ''}

            <div class="rh-histogram">${histHtml}</div>

            ${gradeRows ? `
            <div class="an-section-header" style="margin-top:14px;">Performance by Setup Grade</div>
            <table class="rh-grade-table">
                <thead><tr><th>Grade</th><th>Trades</th><th>Win%</th><th>Avg R</th><th>Expectancy</th></tr></thead>
                <tbody>${gradeRows}</tbody>
            </table>` : ''}

            ${_renderLast100(d.last100, d.excursion)}
            ${_renderSetupStats(d.setup_stats || {})}
            ${_renderCompliance(d.compliance || {})}
            ${_renderRevGradeStats(d.rev_grade_stats || {})}
            ${_renderMistakeFreq(d.mistake_freq || [])}
        `;
    } catch (e) {
        panel.innerHTML = `<div class="an-muted">Failed: ${_anEsc(e.message || e)}</div>`;
    }
}

function _renderLast100(last100, excursion) {
    if (!last100 || !last100.count) return '';
    const exp    = last100.expectancy;
    const expCls = exp > 0 ? 'an-pos' : 'an-neg';
    const exc    = excursion || {};
    const excHtml = (exc.avg_mfe_r != null || exc.avg_mae_r != null) ? `
        <div class="rh-slip-note" style="margin-top:6px;">
            Excursion (${exc.count_mfe || 0} trades):
            avg MFE <span class="an-pos">+${(exc.avg_mfe_r ?? 0).toFixed(2)}R</span> ·
            avg MAE <span class="an-neg">${(exc.avg_mae_r ?? 0).toFixed(2)}R</span>
            — how much profit was available vs. heat taken
        </div>` : '';
    return `
        <div class="an-section-header" style="margin-top:14px;">100-Trade Review
            <span class="an-muted-inline">(last ${last100.count} closed trades)</span>
        </div>
        <div class="rh-expectancy-eq">
            E = ${(last100.win_rate * 100).toFixed(0)}% × ${last100.avg_win_r > 0 ? '+' : ''}${last100.avg_win_r.toFixed(2)}R
            &nbsp;−&nbsp; ${((1 - last100.win_rate) * 100).toFixed(0)}% × ${Math.abs(last100.avg_loss_r).toFixed(2)}R
            &nbsp;=&nbsp; <span class="${expCls}">${exp > 0 ? '+' : ''}${exp.toFixed(3)}R / trade</span>
        </div>
        ${excHtml}`;
}

function _renderSetupStats(stats) {
    const entries = Object.entries(stats).filter(([, s]) => s);
    if (!entries.length) return '';
    const rows = entries.map(([setup, s]) => `<tr>
        <td>${_anEsc(setup)}</td>
        <td>${s.count}</td>
        <td>${(s.win_rate * 100).toFixed(0)}%</td>
        <td class="${s.avg_r >= 0 ? 'an-pos' : 'an-neg'}">${s.avg_r > 0 ? '+' : ''}${s.avg_r.toFixed(2)}R</td>
    </tr>`).join('');
    return `
        <div class="an-section-header" style="margin-top:14px;">Performance by Setup Type</div>
        <table class="rh-grade-table">
            <thead><tr><th>Setup</th><th>Trades</th><th>Win%</th><th>Avg R</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

function _renderCompliance(compliance) {
    const RULES = [
        { key: 'lod',    label: 'LoD ≤ 0.6× ATR at entry' },
        { key: 'rvol',   label: 'RVOL ≥ 1.0× at entry' },
        { key: 'regime', label: 'Entered in BULL regime' },
    ];
    const cell = s => s
        ? `${s.count} · ${(s.win_rate * 100).toFixed(0)}% · <span class="${s.avg_r >= 0 ? 'an-pos' : 'an-neg'}">${s.avg_r > 0 ? '+' : ''}${s.avg_r.toFixed(2)}R</span>`
        : '—';
    const rows = RULES.map(rule => {
        const c = compliance[rule.key] || {};
        if (!c.pass && !c.fail) return '';
        return `<tr>
            <td>${rule.label}</td>
            <td>${cell(c.pass)}</td>
            <td>${cell(c.fail)}</td>
        </tr>`;
    }).filter(Boolean).join('');
    if (!rows) return '';
    return `
        <div class="an-section-header" style="margin-top:14px;">Rule Compliance
            <span class="an-muted-inline">(trades · win% · avg R)</span>
        </div>
        <table class="rh-grade-table">
            <thead><tr><th>Hard Rule</th><th>Followed</th><th>Violated</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

function _renderRevGradeStats(stats) {
    const entries = Object.entries(stats);
    if (!entries.length) return '';
    const rows = entries.map(([g, s]) => {
        const cls = (g === 'A+' || g === 'A') ? 'an-pos' : (g === 'D' || g === 'F') ? 'an-neg' : '';
        return `<tr>
            <td class="${cls}"><strong>${g}</strong></td>
            <td>${s.count}</td>
            <td>${(s.win_rate * 100).toFixed(0)}%</td>
            <td class="${s.avg_r >= 0 ? 'an-pos' : 'an-neg'}">${s.avg_r > 0 ? '+' : ''}${s.avg_r.toFixed(2)}R</td>
        </tr>`;
    }).join('');
    return `
        <div class="an-section-header" style="margin-top:14px;">Performance by Review Grade</div>
        <table class="rh-grade-table">
            <thead><tr><th>Grade</th><th>Trades</th><th>Win%</th><th>Avg R</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

function _renderMistakeFreq(freq) {
    if (!freq.length) return '';
    const maxCount = freq[0][1];
    const bars = freq.slice(0, 12).map(([tag, count]) => {
        const w = Math.round(count / maxCount * 100);
        return `<div class="rh-row">
            <span class="rh-label">${_anEsc(tag)}</span>
            <div class="rh-track"><div class="rh-bar rh-bar-loss" style="width:${w}%"></div></div>
            <span class="rh-count">${count}</span>
            <span class="rh-pct"></span>
        </div>`;
    }).join('');
    return `
        <div class="an-section-header" style="margin-top:14px;">Mistake Frequency</div>
        <div class="rh-histogram">${bars}</div>`;
}

// ── Entry point ───────────────────────────────────────────────────────────────

async function initAnalytics() {
    // Auto-fill missing MFE/MAE on closed trades from daily bars (idempotent)
    try {
        const r = await apiFetch(`${API}/journal/backfill-excursions`, { method: 'POST' });
        if (r && r.updated > 0) toast(`MFE/MAE computed for ${r.updated} closed trade${r.updated === 1 ? '' : 's'}`, 'info', 2500);
    } catch (_) {}
    await Promise.all([_loadDollarAnalytics(), _loadRAnalytics()]);
}
