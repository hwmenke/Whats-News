// ════════════════════════════════════════════════════════════
// performance.js — Performance tab (equity curve, expectancy, R-dist)
// ════════════════════════════════════════════════════════════

let _perfCharts = { equity: null, dist: null };

function pf(v, dp = 2) { return (v === null || v === undefined) ? '—' : Number(v).toFixed(dp); }

async function loadPerformance() {
    let data;
    try { data = await apiFetch(`${API}/performance`); }
    catch (e) { toast(e.message, 'error'); return; }
    renderPerfOverall(data.overall);
    renderPerfSetup(data.by_setup);
    renderEquityChart(data.equity_curve);
    renderDistChart(data.distribution);
}

function renderPerfOverall(o) {
    const cls = v => v == null ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));
    const card = (label, val, c = '') =>
        `<div class="jr-stat ${c}"><div class="jr-stat-val">${val}</div><div class="jr-stat-lbl">${label}</div></div>`;
    document.getElementById('perf-overall').innerHTML =
        card('Closed Trades', o.count) +
        card('Win Rate', pf(o.win_rate, 1) + '%') +
        card('Expectancy', pf(o.expectancy_r) + 'R', cls(o.expectancy_r)) +
        card('Total R', pf(o.total_r) + 'R', cls(o.total_r)) +
        card('Max Drawdown', '-' + pf(o.max_drawdown_r) + 'R', 'neg') +
        card('Realized PnL', '$' + pf(o.total_pnl, 0), cls(o.total_pnl));
}

function renderPerfSetup(rows) {
    const t = document.getElementById('perf-setup-table');
    if (!rows || !rows.length) { t.innerHTML = '<tbody><tr><td style="padding:16px;color:#888;">No closed trades yet.</td></tr></tbody>'; return; }
    const cls = v => v == null ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));
    t.innerHTML = `<thead><tr><th>Setup</th><th>Trades</th><th>Win%</th><th>Expectancy</th><th>Avg R</th><th>Total R</th></tr></thead>`
        + '<tbody>' + rows.map(r => `<tr>
            <td><b>${r.setup}</b></td><td>${r.count}</td><td>${pf(r.win_rate, 0)}%</td>
            <td class="${cls(r.expectancy_r)}">${pf(r.expectancy_r)}R</td>
            <td class="${cls(r.avg_r)}">${pf(r.avg_r)}R</td>
            <td class="${cls(r.total_r)}">${pf(r.total_r)}R</td></tr>`).join('') + '</tbody>';
}

function renderEquityChart(curve) {
    const ctx = document.getElementById('perf-equity');
    if (_perfCharts.equity) _perfCharts.equity.destroy();
    _perfCharts.equity = new Chart(ctx, {
        type: 'line',
        data: {
            labels: curve.map((p, i) => i + 1),
            datasets: [{
                label: 'Cumulative R', data: curve.map(p => p.cum_r),
                borderColor: '#3b82f6', backgroundColor: 'rgba(59,130,246,.15)',
                fill: true, tension: 0.1, pointRadius: 0,
            }],
        },
        options: { plugins: { legend: { display: false } },
                   scales: { x: { display: false } } },
    });
}

function renderDistChart(dist) {
    const ctx = document.getElementById('perf-dist');
    if (_perfCharts.dist) _perfCharts.dist.destroy();
    _perfCharts.dist = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: dist.map(d => d.bucket),
            datasets: [{
                data: dist.map(d => d.count),
                backgroundColor: dist.map(d => d.bucket.includes('-') && d.bucket.startsWith('<') || d.bucket.includes('..-') || d.bucket === '-1..0R' ? '#ef4444' : '#22c55e'),
            }],
        },
        options: { plugins: { legend: { display: false } } },
    });
}
