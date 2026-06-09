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
    const data  = await apiFetch(`${API}/market-regime`);
    const score = data.score ?? 0;
    const label = data.regime || 'Unknown';
    const color = label.includes('Bull') ? 'var(--green)'
                : label.includes('Bear') ? 'var(--red)'
                : 'var(--yellow)';

    const components = data.components || {};
    const compRows = Object.entries(components).map(([k, v]) =>
        `<div class="regime-row">
            <span>${k}</span>
            <span style="color:${v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : 'var(--text-muted)'}">
                ${v > 0 ? '+' : ''}${v}
            </span>
        </div>`
    ).join('');

    return `
        <div style="display:flex;gap:16px;align-items:flex-start;flex-wrap:wrap;">
            <div class="regime-badge-lg" style="border-color:${color};color:${color};">
                <span class="regime-badge-label">${label}</span>
                <span class="regime-badge-score">Score: ${score}/10</span>
            </div>
            ${compRows ? `<div class="routine-regime-details">${compRows}</div>` : ''}
        </div>`;
}

async function _runJeffScan() {
    const data   = await apiFetch(`${API}/jeff-scan`);
    const setups = Array.isArray(data) ? data : (data.setups || []);
    if (!setups.length)
        return '<div class="routine-empty">No setups found today.</div>';

    const top  = setups.slice(0, 12);
    const rows = top.map(s => {
        const gateClass = (s.regime_gate || '') === 'pass' ? 'rc-text-green' : 'rc-text-red';
        const score = s.score != null ? Number(s.score).toFixed(0) : '—';
        return `<tr>
            <td><strong>${s.symbol}</strong></td>
            <td>${s.setup_type || s.setup || '—'}</td>
            <td>${score}</td>
            <td class="${gateClass}">${s.regime_gate || '—'}</td>
        </tr>`;
    }).join('');

    return `
        <div class="routine-summary">${setups.length} setups — <a href="#" onclick="switchTab('scanner');return false;">open scanner →</a></div>
        <table class="routine-table">
            <thead><tr><th>Symbol</th><th>Setup</th><th>Score</th><th>Regime</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

async function _runBreadth() {
    const data = await apiFetch(`${API}/breadth`);
    const items = [
        { label: 'Above KAMA-20', value: data.above_kama_20  != null ? `${data.above_kama_20}%`  : '—' },
        { label: 'Above KAMA-50', value: data.above_kama_50  != null ? `${data.above_kama_50}%`  : '—' },
        { label: '52-wk Highs',   value: data.new_highs      ?? '—' },
        { label: '52-wk Lows',    value: data.new_lows       ?? '—' },
        { label: 'Trending Up',   value: data.trending_up    ?? '—' },
        { label: 'Trending Down', value: data.trending_down  ?? '—' },
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
