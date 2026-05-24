/**
 * analytics.js — Portfolio / Trade Analytics
 * Fetches /api/analytics (computed from closed positions) and renders KPI
 * cards, an equity curve (Chart.js), and a closed-trade table.
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

async function initAnalytics() {
    const kpis = document.getElementById('analytics-kpis');
    const tbody = document.getElementById('analytics-trades');
    if (!kpis) return;
    kpis.innerHTML = '<div class="an-muted"><span class="spinner"></span> Computing…</div>';
    if (tbody) tbody.innerHTML = '';

    try {
        const d = await apiFetch(`${API}/analytics`);
        if (!d.trade_count) {
            kpis.innerHTML = '<div class="an-muted">No closed trades yet. Add and close positions to see analytics.</div>';
            if (_analyticsChart) { _analyticsChart.destroy(); _analyticsChart = null; }
            return;
        }
        const wr = d.win_rate;
        kpis.innerHTML = [
            _anKpi('Trades', d.trade_count),
            _anKpi('Win Rate', _anFmtPct(wr), wr !== null && wr >= 0.5 ? 'an-pos' : 'an-neg'),
            _anKpi('Profit Factor', _anFmtNum(d.profit_factor)),
            _anKpi('Avg Win', _anFmtNum(d.avg_win), 'an-pos'),
            _anKpi('Avg Loss', _anFmtNum(d.avg_loss), 'an-neg'),
            _anKpi('Sharpe', _anFmtNum(d.sharpe)),
            _anKpi('Max Drawdown', _anFmtPct(d.max_drawdown), 'an-neg'),
        ].join('');

        // Equity curve
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
        kpis.innerHTML = `<div class="an-muted">Failed to load: ${_anEsc(e.message || e)}</div>`;
    }
}
