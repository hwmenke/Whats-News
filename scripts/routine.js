/**
 * routine.js — Morning Routine master dashboard
 * Component cards that surface daily workflow steps in one view.
 */

const ROUTINE_COMPONENTS = [
    {
        id:   'data-refresh',
        name: 'Data Refresh',
        icon: '⟳',
        desc: 'Pull latest OHLCV from Yahoo Finance for all watchlist symbols.',
        run:  _runDataRefresh,
    },
    {
        id:   'market-regime',
        name: 'Market Regime',
        icon: '🌡',
        desc: 'Score market regime (bull / neutral / bear) from SPY trend + breadth.',
        run:  _runMarketRegime,
    },
    {
        id:   'jeff-scan',
        name: 'Jeff Scanner',
        icon: '🔍',
        desc: 'Run the Jeff Sun setup scanner across your watchlist.',
        run:  _runJeffScan,
    },
    {
        id:   'breadth',
        name: 'Watchlist Breadth',
        icon: '📊',
        desc: 'Count symbols above KAMA, new highs, new lows, and trend direction.',
        run:  _runBreadth,
    },
    {
        id:   'signals',
        name: 'Active Signals',
        icon: '🔔',
        desc: 'List currently-triggered alerts and new setup signals.',
        run:  _runSignals,
    },
    {
        id:   'what-changed',
        name: 'What Changed',
        icon: '📋',
        desc: 'Highlight symbols with notable price moves, volume spikes, or MA crossovers today.',
        run:  _runWhatChanged,
    },
];

const _ROUTINE_KEY = 'routine_settings_v1';

function _loadRoutineSettings() {
    try {
        const saved   = JSON.parse(localStorage.getItem(_ROUTINE_KEY) || '{}');
        const allIds  = ROUTINE_COMPONENTS.map(c => c.id);
        const enabled = saved.enabled || allIds;
        const order   = saved.order   || allIds;
        // Include any newly-added components not yet in saved order
        allIds.forEach(id => { if (!order.includes(id)) order.push(id); });
        return { enabled: new Set(enabled), order };
    } catch (_) {
        const allIds = ROUTINE_COMPONENTS.map(c => c.id);
        return { enabled: new Set(allIds), order: allIds };
    }
}

function saveRoutineSettings(settings) {
    try {
        localStorage.setItem(_ROUTINE_KEY, JSON.stringify({
            enabled: [...settings.enabled],
            order:   settings.order,
        }));
    } catch (_) {}
}

let _routineSettings = null;

function initRoutine() {
    _routineSettings = _loadRoutineSettings();
    const area = document.getElementById('routine-area');
    if (!area) return;
    _renderRoutineArea(area);
}

function _routineDate() {
    return new Date().toLocaleDateString('en-US', {
        weekday: 'long', month: 'long', day: 'numeric', year: 'numeric',
    });
}

function _renderRoutineArea(area) {
    const s       = _routineSettings;
    const ordered = s.order
        .map(id => ROUTINE_COMPONENTS.find(c => c.id === id))
        .filter(Boolean);
    // Include any components not yet in persisted order
    ROUTINE_COMPONENTS.forEach(c => {
        if (!ordered.find(o => o.id === c.id)) ordered.push(c);
    });
    const visible = ordered.filter(c => s.enabled.has(c.id));

    const cards = visible.length
        ? visible.map(_buildComponentCard).join('')
        : '<div class="routine-empty-state">No components enabled. <a href="#" onclick="switchTab(\'settings\');return false;">Open Settings →</a></div>';

    area.innerHTML = `
        <div class="routine-container">
            <div class="routine-header">
                <div>
                    <h2 class="feat-title" style="margin:0;">Morning Routine</h2>
                    <div class="routine-subtitle">${_routineDate()}</div>
                </div>
                <div style="display:flex;gap:8px;align-items:center;">
                    <button class="btn btn-ghost btn-sm" onclick="switchTab('settings')" title="Configure components">⚙</button>
                    <button class="btn btn-primary" id="btn-run-all-routine" onclick="runAllRoutine()">▶ Run All</button>
                </div>
            </div>
            <div class="routine-cards" id="routine-cards">${cards}</div>
        </div>`;
}

function _buildComponentCard(comp) {
    return `
        <div class="routine-card" id="rc-card-${comp.id}">
            <div class="routine-card-header">
                <span class="routine-card-icon">${comp.icon}</span>
                <span class="routine-card-name">${comp.name}</span>
                <span class="routine-card-status" id="rc-status-${comp.id}">idle</span>
                <button class="btn btn-ghost btn-sm" onclick="runComponent('${comp.id}')">Run</button>
            </div>
            <div class="routine-card-desc">${comp.desc}</div>
            <div class="routine-card-output" id="rc-output-${comp.id}"></div>
        </div>`;
}

async function runComponent(id) {
    const comp     = ROUTINE_COMPONENTS.find(c => c.id === id);
    if (!comp) return;
    const statusEl = document.getElementById(`rc-status-${id}`);
    const outputEl = document.getElementById(`rc-output-${id}`);
    const card     = document.getElementById(`rc-card-${id}`);
    if (!statusEl || !outputEl) return;

    statusEl.textContent = 'running…';
    statusEl.className   = 'routine-card-status running';
    outputEl.innerHTML   = '<div class="routine-loading"><span class="spinner"></span> Fetching…</div>';
    if (card) card.classList.add('card-running');

    try {
        const html = await comp.run();
        outputEl.innerHTML   = html || '<div class="routine-empty">No data returned.</div>';
        statusEl.textContent = '✓ done';
        statusEl.className   = 'routine-card-status done';
    } catch (e) {
        outputEl.innerHTML   = `<div class="routine-error">✗ ${e.message}</div>`;
        statusEl.textContent = 'error';
        statusEl.className   = 'routine-card-status error';
    } finally {
        if (card) card.classList.remove('card-running');
    }
}

async function runAllRoutine() {
    const btn = document.getElementById('btn-run-all-routine');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Running…'; }
    const s = _routineSettings || _loadRoutineSettings();
    for (const id of s.order) {
        if (s.enabled.has(id)) await runComponent(id);
    }
    if (btn) { btn.disabled = false; btn.textContent = '▶ Run All'; }
    toast('Routine complete', 'success', 2000);
}

// ── Component runners ─────────────────────────────────────────────────────────

async function _runDataRefresh() {
    const results = await apiFetch(`${API}/refresh`, { method: 'POST' });
    if (!Array.isArray(results) || !results.length)
        return '<div class="routine-empty">No symbols to refresh.</div>';

    const ok  = results.filter(r => !r.error).length;
    const bad = results.filter(r =>  r.error).length;
    const rows = results.map(r => {
        const good = !r.error;
        const detail = good
            ? `${r.daily_rows ?? '?'}d / ${r.weekly_rows ?? '?'}w bars`
            : r.error;
        return `<tr>
            <td><strong>${r.symbol}</strong></td>
            <td class="${good ? 'rc-text-green' : 'rc-text-red'}">${good ? '✓' : '✗'}</td>
            <td style="color:var(--text-muted)">${detail}</td>
        </tr>`;
    }).join('');

    return `
        <div class="routine-summary">${ok} updated${bad ? `, ${bad} failed` : ''}</div>
        <table class="routine-table">
            <thead><tr><th>Symbol</th><th></th><th>Detail</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

async function _runMarketRegime() {
    const data    = await apiFetch(`${API}/market-regime`);
    const cur     = data.current || {};
    const score   = cur.score ?? 0;
    const label   = cur.state || 'Unknown';
    const color   = label.toLowerCase().includes('bull') ? 'var(--green)'
                  : label.toLowerCase().includes('bear') ? 'var(--red)'
                  : 'var(--yellow)';

    const stats   = data.regime_stats || {};
    const statRows = Object.entries(stats).map(([state, s]) =>
        `<div class="regime-row">
            <span>${state}</span>
            <span style="color:var(--text-muted)">${s.count ?? 0}d</span>
        </div>`
    ).join('');

    const daysIn  = cur.days_in != null ? `${cur.days_in}d in state` : '';

    return `
        <div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;">
            <div class="regime-badge-lg" style="border-color:${color};color:${color};">
                <span class="regime-badge-label">${label}</span>
                <span class="regime-badge-score">Score: ${score}/10</span>
                ${daysIn ? `<span class="regime-badge-days">${daysIn}</span>` : ''}
            </div>
            ${statRows ? `<div class="routine-regime-details">${statRows}</div>` : ''}
        </div>`;
}

async function _runJeffScan() {
    const data   = await apiFetch(`${API}/jeff-scan`);
    const all    = Array.isArray(data) ? data : (data.rows || []);
    // Sort by opportunity score (grade quality + readiness + RS + trigger proximity)
    const graded = all.filter(r => r.grade && !r.error)
                      .sort((a, b) => (b.opp_score ?? 0) - (a.opp_score ?? 0));
    if (!graded.length)
        return '<div class="routine-empty">No graded setups found. Run a data refresh first.</div>';

    const nA = graded.filter(r => r.grade === 'A').length;
    const nB = graded.filter(r => r.grade === 'B').length;
    const top  = graded.slice(0, 12);
    const rows = top.map(s => {
        const g     = (s.grade || '').toLowerCase();
        const gCls  = g === 'a' ? 'rc-text-green' : g === 'b' ? '' : 'rc-text-red';
        const tStat = s.trigger_status || '—';
        const tCls  = tStat === 'AT' ? 'rc-text-green' : tStat === 'NEAR' ? 'rc-text-amber' : '';
        const tTxt  = tDist => tDist != null ? `${tStat} +${tDist}%` : tStat;
        return `<tr>
            <td><strong>${s.symbol}</strong></td>
            <td class="${gCls}">${s.grade || '—'}</td>
            <td style="color:var(--text-muted)">${s.opp_score ?? '—'}</td>
            <td style="color:var(--text-muted)">${s.readiness ?? '—'}/5</td>
            <td class="${tCls}">${tTxt(s.trigger_dist_pct)}</td>
        </tr>`;
    }).join('');

    const errCount = all.filter(r => r.error).length;
    const errNote  = errCount ? ` · ${errCount} no data` : '';
    return `
        <div class="routine-summary">${graded.length} setups (${nA}A · ${nB}B)${errNote} — <a href="#" onclick="switchTab('scanner');setScanMode('jeff');return false;">open scanner →</a></div>
        <table class="routine-table">
            <thead><tr><th>Symbol</th><th>Grade</th><th>Opp</th><th>Ready</th><th>Trigger</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

async function _runBreadth() {
    const data = await apiFetch(`${API}/breadth`);
    const items = [
        { label: 'Above 20-MA',  value: data.pct_above_20ma  != null ? `${data.pct_above_20ma}%`  : '—' },
        { label: 'Above 50-MA',  value: data.pct_above_50ma  != null ? `${data.pct_above_50ma}%`  : '—' },
        { label: 'Above 200-MA', value: data.pct_above_200ma != null ? `${data.pct_above_200ma}%` : '—' },
        { label: '52-wk Highs',  value: data.new_highs       ?? '—' },
        { label: '52-wk Lows',   value: data.new_lows        ?? '—' },
        { label: 'A/D Ratio',    value: data.ad_ratio        != null ? data.ad_ratio.toFixed(2) : '—' },
    ];
    return `<div class="breadth-grid">${items.map(i =>
        `<div class="breadth-item">
            <div class="breadth-val">${i.value}</div>
            <div class="breadth-lbl">${i.label}</div>
        </div>`
    ).join('')}</div>`;
}

async function _runSignals() {
    const data    = await apiFetch(`${API}/signals`);
    const signals = Array.isArray(data) ? data : (data.signals || []);
    if (!signals.length)
        return '<div class="routine-empty">No active signals.</div>';

    const rows = signals.slice(0, 15).map(s => `<tr>
        <td><strong>${s.symbol}</strong></td>
        <td>${s.signal_type || s.type || '—'}</td>
        <td style="color:var(--text-muted)">${s.date || s.triggered_at || '—'}</td>
    </tr>`).join('');

    return `
        <div class="routine-summary">${signals.length} signals</div>
        <table class="routine-table">
            <thead><tr><th>Symbol</th><th>Signal</th><th>Date</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

async function _runWhatChanged() {
    const stats = await apiFetch(`${API}/symbols/quick-stats`);
    if (!Array.isArray(stats) || !stats.length)
        return '<div class="routine-empty">No data available.</div>';

    const notable = stats.filter(s =>
        s.chg != null || s.vol_ratio != null
    );
    if (!notable.length)
        return '<div class="routine-empty">Fetch data first to see daily changes.</div>';

    const movers = notable.filter(s => s.chg != null && Math.abs(s.chg) >= 2)
        .sort((a, b) => Math.abs(b.chg) - Math.abs(a.chg));
    const vols   = notable.filter(s => s.vol_ratio != null && s.vol_ratio >= 2)
        .sort((a, b) => b.vol_ratio - a.vol_ratio);

    let html = '';

    if (movers.length) {
        const rows = movers.slice(0, 10).map(s => {
            const cls = s.chg >= 0 ? 'rc-text-green' : 'rc-text-red';
            return `<tr>
                <td><strong>${s.symbol}</strong></td>
                <td class="${cls}">${s.chg >= 0 ? '+' : ''}${s.chg.toFixed(2)}%</td>
                <td style="color:var(--text-muted)">${s.price != null ? '$' + s.price.toFixed(2) : '—'}</td>
                <td style="color:var(--text-muted)">${s.rsi14 != null ? 'RSI ' + s.rsi14 : '—'}</td>
            </tr>`;
        }).join('');
        html += `<div class="routine-summary">Big Movers (≥2%): ${movers.length}</div>
            <table class="routine-table"><thead><tr><th>Symbol</th><th>Change</th><th>Price</th><th>RSI</th></tr></thead>
            <tbody>${rows}</tbody></table>`;
    } else {
        html += '<div class="routine-empty">No symbols moved ≥2% today.</div>';
    }

    if (vols.length) {
        const rows = vols.slice(0, 8).map(s =>
            `<tr>
                <td><strong>${s.symbol}</strong></td>
                <td style="color:#f97316">${s.vol_ratio.toFixed(1)}× avg vol</td>
                <td class="${(s.chg||0) >= 0 ? 'rc-text-green' : 'rc-text-red'}">${s.chg != null ? (s.chg >= 0 ? '+' : '') + s.chg.toFixed(2) + '%' : '—'}</td>
            </tr>`
        ).join('');
        html += `<div class="routine-summary" style="margin-top:12px">Volume Spikes (≥2× avg): ${vols.length}</div>
            <table class="routine-table"><thead><tr><th>Symbol</th><th>Volume</th><th>Change</th></tr></thead>
            <tbody>${rows}</tbody></table>`;
    }

    return html || '<div class="routine-empty">No notable changes today.</div>';
}

// ── CSV export utility (used by settings tab and elsewhere) ───────────────────

function exportTableToCSV(tableId, filename) {
    const table = typeof tableId === 'string'
        ? document.getElementById(tableId) || document.querySelector(tableId)
        : tableId;
    if (!table) { toast('Table not found for export', 'warning'); return; }

    const rows = [...table.querySelectorAll('tr')].map(row =>
        [...row.querySelectorAll('th,td')]
            .map(cell => `"${(cell.innerText || '').replace(/"/g, '""').trim()}"`)
            .join(',')
    );
    const csv  = rows.join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = Object.assign(document.createElement('a'), { href: url, download: filename || 'export.csv' });
    a.click();
    URL.revokeObjectURL(url);
    toast(`Exported ${filename || 'export.csv'}`, 'success', 2000);
}
