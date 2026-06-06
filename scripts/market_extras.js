// ════════════════════════════════════════════════════════════
// market_extras.js — RRG scatter, setup Alerts (notifications), Earnings
// ════════════════════════════════════════════════════════════

const _QUAD_COLOR = { leading: '#22c55e', improving: '#3b82f6', weakening: '#eab308', lagging: '#ef4444' };
let _rrgChart = null;

// ── RRG (relative-rotation graph) ────────────────────────────
async function loadRrgTab() {
    const body = document.getElementById('rrg-body');
    body.innerHTML = '<p style="color:#888;padding:14px;">Computing rotation…</p>';
    let d;
    try { d = await apiFetch(`${API}/rrg`); }
    catch (e) { body.innerHTML = `<p style="color:#e66;padding:14px;">${e.message}</p><p style="color:#888;">RRG needs weekly data for SPY + watchlist names.</p>`; return; }
    if (!d.symbols || !d.symbols.length) {
        body.innerHTML = `<p style="color:#888;padding:14px;">No symbols with enough weekly data vs ${d.benchmark}.</p>`;
        return;
    }
    body.innerHTML = `<p style="color:#888;">JdK relative-rotation vs <b>${d.benchmark}</b>. Right/up = leading.</p>
        <div class="perf-card"><canvas id="rrg-canvas" height="320"></canvas></div>`;
    const pts = d.symbols.map(s => ({ x: s.rs_ratio, y: s.rs_mom, label: s.symbol,
        backgroundColor: _QUAD_COLOR[s.quadrant] || '#8b949e' }));
    if (_rrgChart) _rrgChart.destroy();
    _rrgChart = new Chart(document.getElementById('rrg-canvas'), {
        type: 'scatter',
        data: { datasets: [{ data: pts, pointRadius: 7, pointHoverRadius: 9,
                 backgroundColor: pts.map(p => p.backgroundColor) }] },
        options: {
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: c => `${c.raw.label}: (${c.raw.x.toFixed(1)}, ${c.raw.y.toFixed(1)})` } },
            },
            scales: {
                x: { title: { display: true, text: 'RS-Ratio' }, suggestedMin: 96, suggestedMax: 104 },
                y: { title: { display: true, text: 'RS-Momentum' }, suggestedMin: 96, suggestedMax: 104 },
            },
        },
    });
}

// ── Setup Alerts (poll + browser notifications) ──────────────
let _alertSeen = new Set();
let _alertTimer = null;

async function loadAlertsTab() {
    renderAlertsControls();
    await refreshAlerts();
}

function renderAlertsControls() {
    const ctl = document.getElementById('alerts-controls');
    if (!ctl) return;
    const on = _alertTimer !== null;
    ctl.innerHTML = `
        <button class="btn btn-ghost" onclick="enableAlertNotifications()">🔔 Enable notifications</button>
        <button class="btn ${on ? 'btn-primary' : 'btn-ghost'}" onclick="toggleAlertPolling()">${on ? '⏸ Stop auto-scan' : '▶ Auto-scan (5m)'}</button>
        <button class="btn btn-ghost" onclick="refreshAlerts()">↻ Scan now</button>`;
}

function enableAlertNotifications() {
    if (!('Notification' in window)) { toast('Notifications not supported', 'warning'); return; }
    Notification.requestPermission().then(p => toast('Notifications ' + p, p === 'granted' ? 'success' : 'info'));
}

function toggleAlertPolling() {
    if (_alertTimer) { clearInterval(_alertTimer); _alertTimer = null; }
    else { _alertTimer = setInterval(refreshAlerts, 5 * 60 * 1000); refreshAlerts(); }
    renderAlertsControls();
}

async function refreshAlerts() {
    const body = document.getElementById('alerts-body');
    let d;
    try { d = await apiFetch(`${API}/alerts/scan`); }
    catch (e) { body.innerHTML = `<p style="color:#e66;padding:14px;">${e.message}</p>`; return; }

    // Fire notifications for newly-triggered names
    d.alerts.forEach(a => {
        const key = `${a.symbol}:${a.setup}`;
        if (!_alertSeen.has(key)) {
            _alertSeen.add(key);
            if ('Notification' in window && Notification.permission === 'granted') {
                new Notification(`${a.grade} setup: ${a.symbol}`, { body: `${a.setup} · score ${a.score}` });
            }
        }
    });

    if (!d.alerts.length) {
        body.innerHTML = `<p style="color:#888;padding:14px;">No A/A+ setups triggering right now.</p>`;
        return;
    }
    body.innerHTML = `<div class="scanner-table-wrap"><table class="scanner-table" style="width:100%;">
        <thead><tr><th>Symbol</th><th>Setup</th><th>Grade</th><th>Score</th><th>Price</th><th></th></tr></thead>
        <tbody>${d.alerts.map(a => `<tr>
            <td><b>${a.symbol}</b></td><td>${a.setup}</td>
            <td><span class="grade-badge ${a.grade === 'A+' ? 'g-aplus' : 'g-a'}">${a.grade}</span></td>
            <td>${a.score}</td><td>${a.price ?? '—'}</td>
            <td><button class="btn btn-ghost btn-sm" onclick="addToJournalFromScan('${a.symbol}','${a.setup}',${a.price || 0})">＋ Journal</button></td>
        </tr>`).join('')}</tbody></table></div>`;
}

// ── Earnings lookup (active symbol) ──────────────────────────
async function loadEarningsTab() {
    const body = document.getElementById('earnings-body');
    if (!state.activeSymbol) { body.innerHTML = '<p style="color:#888;padding:14px;">Select a symbol first.</p>'; return; }
    body.innerHTML = `<p style="color:#888;padding:14px;">Looking up earnings for ${state.activeSymbol}…</p>`;
    let d;
    try { d = await apiFetch(`${API}/earnings/${state.activeSymbol}`); }
    catch (e) { body.innerHTML = `<p style="color:#e66;padding:14px;">${e.message}</p>`; return; }
    if (!d.earnings_date) {
        body.innerHTML = `<p style="color:#888;padding:14px;">No earnings date available for ${d.symbol}. ${d.note || ''}</p>`;
        return;
    }
    const soon = d.days_until !== null && d.days_until >= 0 && d.days_until <= 7;
    body.innerHTML = `<div class="jr-stats-grid">
        <div class="jr-stat"><div class="jr-stat-val">${d.symbol}</div><div class="jr-stat-lbl">Symbol</div></div>
        <div class="jr-stat ${soon ? 'neg' : ''}"><div class="jr-stat-val">${d.earnings_date}</div><div class="jr-stat-lbl">Next Earnings</div></div>
        <div class="jr-stat ${soon ? 'neg' : ''}"><div class="jr-stat-val">${d.days_until ?? '—'}</div><div class="jr-stat-lbl">Days Until</div></div>
    </div>${soon ? '<p class="neg" style="padding:8px 4px;">⚠ Earnings within a week — binary risk on open positions; sizing/EP consideration.</p>' : ''}`;
}
