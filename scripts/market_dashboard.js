/**
 * market_dashboard.js — Market Dashboard tab
 *
 * Four sections:
 *   A) Breadth Gauges — % above 20/50/200 MA, A/D ratio, new highs/lows
 *   B) Regime Context — average ATR extension across watchlist
 *   C) Watchlist Strength Table — all symbols ranked by setup grade
 *   D) Daily Process Checklists — post-market and pre-market (localStorage)
 */

function initMarketDashboard() {
    _loadRiskPedal();
    _loadBreadth();
    _loadStrengthTable();
    _initDailyChecklists();
    _loadDiary();
    _initScreens();
    if (typeof initSector   === 'function') initSector();
    if (typeof initProcess  === 'function') initProcess();
}

// ── Risk Pedal ────────────────────────────────────────────────────────────────

async function _loadRiskPedal() {
    const banner = document.getElementById('dash-risk-pedal');
    if (!banner) return;
    try {
        const d = await apiFetch(`${API}/risk-pedal`);
        const meta = {
            green:  { icon: '🟢', label: 'GREEN — Normal Risk' },
            yellow: { icon: '🟡', label: 'YELLOW — Reduced Risk' },
            red:    { icon: '🔴', label: 'RED — Minimal Risk' },
        }[d.pedal] || { icon: '⚪', label: d.pedal };
        const facts = [
            d.regime_state ? `Regime: ${d.regime_state}` : '',
            d.breadth_pct20 != null ? `${d.breadth_pct20}% > 20-MA` : '',
            d.spy_ext != null ? `SPY ext ${d.spy_ext.toFixed(1)}× ATR` : '',
        ].filter(Boolean).join(' · ');
        banner.className = `risk-pedal-banner rp-${d.pedal}`;
        banner.style.display = '';
        banner.innerHTML = `
            <span class="rp-light">${meta.icon}</span>
            <span class="rp-label">${meta.label}</span>
            <span class="rp-facts">${facts}</span>
            <span class="rp-reason" title="${(d.reasons || []).join('\n')}">${(d.reasons || [])[0] || ''}</span>`;
    } catch (_) {
        banner.style.display = 'none';
    }
}

// ── Market Diary ──────────────────────────────────────────────────────────────

async function _loadDiary() {
    const c = document.getElementById('diary-history');
    if (!c) return;
    try {
        const entries = await apiFetch(`${API}/diary?limit=30`);
        if (!entries.length) {
            c.innerHTML = '<div class="feat-empty">No diary entries yet — save your first market read above.</div>';
            return;
        }
        const pedalIco = { green: '🟢', yellow: '🟡', red: '🔴' };
        const rows = entries.map(e => `
            <tr>
                <td>${e.date}</td>
                <td>${e.regime_state || '—'}</td>
                <td>${pedalIco[e.risk_pedal] || '—'}</td>
                <td>${e.breadth_pct20 != null ? e.breadth_pct20.toFixed(0) + '%' : '—'}</td>
                <td>${e.new_highs ?? '—'}/${e.new_lows ?? '—'}</td>
                <td class="diary-notes-cell">${_mdEsc(e.notes || '')}</td>
                <td><button class="btn btn-ghost btn-icon" title="Delete" onclick="_deleteDiary('${e.date}')">✕</button></td>
            </tr>`).join('');
        c.innerHTML = `
            <div class="feat-table-wrap">
            <table class="feat-table diary-table">
                <thead><tr><th>Date</th><th>Regime</th><th title="Risk pedal">Pedal</th><th title="% of watchlist above 20-MA">>20MA</th><th title="New 52-wk highs / lows">NH/NL</th><th>Notes</th><th></th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
            </div>`;
    } catch (e) {
        c.innerHTML = `<div class="feat-empty" style="color:var(--red);">${e.message}</div>`;
    }
}

async function _saveDiary() {
    const notes = document.getElementById('diary-notes')?.value || '';
    try {
        await apiFetch(`${API}/diary`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ notes }),
        });
        toast('Diary saved — context snapshotted', 'success');
        const el = document.getElementById('diary-notes');
        if (el) el.value = '';
        _loadDiary();
    } catch (e) {
        toastFromError(e, 'Diary');
    }
}

async function _deleteDiary(date) {
    try {
        await apiFetch(`${API}/diary/${date}`, { method: 'DELETE' });
        _loadDiary();
    } catch (e) {
        toastFromError(e, 'Diary');
    }
}

function _mdEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

// ── A) Breadth ────────────────────────────────────────────────────────────────

async function _loadBreadth() {
    const panel = document.getElementById('dash-breadth-panel');
    if (!panel) return;
    panel.innerHTML = '<div class="feat-loading"><span class="spinner"></span></div>';
    try {
        const d = await apiFetch(`${API}/breadth`);
        _renderBreadth(d);
    } catch (e) {
        panel.innerHTML = `<div class="feat-empty" style="color:var(--red);">${e.message}</div>`;
    }
}

function _renderBreadth(d) {
    const panel = document.getElementById('dash-breadth-panel');
    if (!panel) return;

    const adColor  = d.ad_ratio >= 2 ? 'var(--green)' : d.ad_ratio <= 0.5 ? 'var(--red)' : 'var(--text-primary)';
    const gauge = (pct, label) => {
        const color = pct >= 60 ? 'var(--green)' : pct >= 40 ? 'var(--yellow)' : 'var(--red)';
        return `<div class="dash-gauge-row">
            <span class="dash-gauge-label">${label}</span>
            <div class="dash-gauge-track">
                <div class="dash-gauge-fill" style="width:${pct.toFixed(0)}%; background:${color};"></div>
            </div>
            <span class="dash-gauge-val" style="color:${color}">${pct.toFixed(0)}%</span>
        </div>`;
    };

    panel.innerHTML = `
        <div class="dash-breadth-kpis">
            <div class="dash-kpi"><div class="dash-kpi-label">Universe</div><div class="dash-kpi-val">${d.total}</div></div>
            <div class="dash-kpi"><div class="dash-kpi-label">Advances</div><div class="dash-kpi-val" style="color:var(--green)">${d.advances}</div></div>
            <div class="dash-kpi"><div class="dash-kpi-label">Declines</div><div class="dash-kpi-val" style="color:var(--red)">${d.declines}</div></div>
            <div class="dash-kpi"><div class="dash-kpi-label">A/D Ratio</div><div class="dash-kpi-val" style="color:${adColor}">${d.ad_ratio?.toFixed(2)}</div></div>
            <div class="dash-kpi"><div class="dash-kpi-label">New 52W Highs</div><div class="dash-kpi-val" style="color:var(--green)">${d.new_highs}</div></div>
            <div class="dash-kpi"><div class="dash-kpi-label">New 52W Lows</div><div class="dash-kpi-val" style="color:var(--red)">${d.new_lows}</div></div>
        </div>
        <div class="dash-gauges">
            ${gauge(d.pct_above_20ma,  '% Above 20-MA')}
            ${gauge(d.pct_above_50ma,  '% Above 50-MA')}
            ${gauge(d.pct_above_200ma, '% Above 200-MA')}
        </div>
        <div class="dash-breadth-context">
            ${d.pct_above_50ma >= 70 ? '<span class="dash-regime-chip dash-regime-bull">Broad Uptrend</span>' :
              d.pct_above_50ma >= 50 ? '<span class="dash-regime-chip dash-regime-mix">Mixed Market</span>' :
              d.pct_above_50ma >= 30 ? '<span class="dash-regime-chip dash-regime-warn">Under Pressure</span>' :
                                       '<span class="dash-regime-chip dash-regime-bear">Broad Downtrend</span>'}
            ${d.new_highs > d.new_lows * 3 ? '<span class="dash-regime-chip dash-regime-bull">Expanding Leadership</span>' :
              d.new_lows  > d.new_highs * 3 ? '<span class="dash-regime-chip dash-regime-bear">Narrowing Leadership</span>' : ''}
        </div>
        ${_ewRow('EW vs CW (RSP/SPY)',  d.ew_cw)}
        ${_ewRow('EW vs CW (QQQE/QQQ)', d.qqqe_qqq)}`;
}

function _ewRow(label, r) {
    if (!r) return '';
    return `
        <div class="dash-ew-row">
            <span class="dash-ew-label">${label}</span>
            <span class="dash-ew-chg ${r.chg_20d >= 0 ? 'dash-ew-pos' : 'dash-ew-neg'}">
                ${r.chg_20d >= 0 ? '+' : ''}${r.chg_20d}% (20d)
            </span>
            <span class="dash-regime-chip ${
                r.signal === 'broadening' ? 'dash-regime-bull' :
                r.signal === 'narrowing'  ? 'dash-regime-bear' : 'dash-regime-mix'
            }">${r.signal.charAt(0).toUpperCase() + r.signal.slice(1)}</span>
        </div>`;
}

// ── C) Watchlist Strength Table ───────────────────────────────────────────────

async function _loadStrengthTable() {
    const panel = document.getElementById('dash-strength-table');
    if (!panel) return;
    panel.innerHTML = '<div class="feat-loading"><span class="spinner"></span></div>';
    try {
        const data = await apiFetch(`${API}/focus-pipeline`);
        _renderStrengthTable(data);
    } catch (e) {
        panel.innerHTML = `<div class="feat-empty" style="color:var(--red);">${e.message}</div>`;
    }
}

function _renderStrengthTable(pipeline) {
    const panel = document.getElementById('dash-strength-table');
    if (!panel) return;

    const all = ['focus', 'active', 'stalk', 'watchlist', 'back_watchlist']
        .flatMap(tier => (pipeline[tier] || []).map(s => ({ ...s, tier })));

    if (!all.length) {
        panel.innerHTML = '<div class="feat-empty">No symbols in watchlist.</div>';
        return;
    }

    const gradeOrder = { A: 0, B: 1, C: 2, '': 3 };
    all.sort((a, b) => (gradeOrder[a.setup_grade] ?? 3) - (gradeOrder[b.setup_grade] ?? 3));

    const tierMeta = { active: '⚡', focus: '🔥', stalk: '🎯', watchlist: '👁', back_watchlist: '🌙' };
    const rows = all.map(s => {
        const grade    = s.setup_grade || '—';
        const gradeCls = `sw-grade-${grade.toLowerCase()}`;
        const rvolCls  = s.rvol >= 1.5 ? 'proc-bull' : s.rvol >= 1.0 ? '' : s.rvol != null ? 'proc-bear' : '';
        const extCls   = s.atr_mult_50ma > 4 ? 'proc-bear' : s.atr_mult_50ma > 2.5 ? 'proc-warn' : 'proc-bull';
        return `<tr style="cursor:pointer" onclick="selectSymbol('${s.symbol}'); switchTab('charts')">
            <td><strong>${s.symbol}</strong></td>
            <td>${grade !== '—' ? `<span class="sw-grade ${gradeCls} sw-grade-sm">${grade}</span>` : '—'}</td>
            <td class="${rvolCls}">${s.rvol != null ? s.rvol.toFixed(1) + '×' : '—'}</td>
            <td class="${extCls}">${s.atr_mult_50ma != null ? s.atr_mult_50ma.toFixed(1) + '×' : '—'}</td>
            <td>${s.adr_pct != null ? s.adr_pct.toFixed(1) + '%' : '—'}</td>
            <td>${tierMeta[s.tier] || ''} ${s.tier}</td>
        </tr>`;
    }).join('');

    panel.innerHTML = `
        <table class="scanner-table">
            <thead><tr><th>Symbol</th><th>Grade</th><th>RVOL</th><th>ATR×50</th><th>ADR%</th><th>Tier</th></tr></thead>
            <tbody>${rows}</tbody>
        </table>`;
}

// ── D) Daily Process Checklists ───────────────────────────────────────────────

const _POST_MARKET_STEPS = [
    'Run all post-market screeners',
    'Remove illiquid / structurally weak names',
    'Check relative strength vs index, sector, group',
    'Check ATR extension from 50-MA (flag >4×)',
    'Check volatility contraction / VCP',
    'Mark actionable pivot / trigger level',
    'Define stop (invalidation) before entry',
    'Set price alerts',
    'Update stops on existing positions',
    'Finalize focus list for tomorrow',
];

const _PRE_MARKET_STEPS = [
    'Check index futures: gap, tone, direction',
    'Check scheduled macro data (CPI, NFP, FOMC…)',
    'Check earnings reports (pre- and post-market)',
    'Check sector / industry group strength',
    'Review breadth (new highs/lows, A/D)',
    'Check equal-weight vs cap-weight index divergence',
    'Identify focus-list names near alert levels',
    'Set or revise price alerts',
    'Review existing position stops',
    'Define max new positions allowed today (≤3)',
];

const _WEEKLY_REVIEW_STEPS = [
    'Refresh all screens; prune broken charts from watchlists',
    'Review Back Burner — any former leaders setting up again?',
    'Re-rank watchlist by RS, ADR and theme',
    'Review focus-list names that never triggered — why?',
    'Study the biggest winners you missed this week',
    'Study the biggest losses — rule break or bad luck?',
    'Check mistake frequency in Analytics — top recurring leak',
    'Check 100-trade expectancy and rule-compliance table',
    'Archive stale names; update screen thresholds',
    'Set risk posture for next week (pedal + size)',
];

const _STORAGE_KEY = 'dash_checklists';

function _initDailyChecklists() {
    _renderDailyChecklist('dash-post-mkt-checklist', _POST_MARKET_STEPS, 'post');
    _renderDailyChecklist('dash-pre-mkt-checklist',  _PRE_MARKET_STEPS,  'pre');
    _renderDailyChecklist('dash-weekly-checklist',   _WEEKLY_REVIEW_STEPS, 'weekly');
    _loadChecklistState();
}

function _renderDailyChecklist(containerId, steps, prefix) {
    const c = document.getElementById(containerId);
    if (!c) return;
    c.innerHTML = steps.map((step, i) => `
        <div class="dash-chk-row">
            <label class="chk-toggle">
                <input type="checkbox" id="dash-${prefix}-${i}" onchange="_saveDashChecklists()">
                <span class="chk-box"></span>
            </label>
            <span class="dash-chk-label">${step}</span>
        </div>`).join('') +
        `<div class="dash-chk-actions">
            <button class="btn btn-ghost btn-icon" onclick="_checkAllDash('${prefix}',${steps.length})">Check All</button>
            <button class="btn btn-ghost btn-icon" onclick="_clearDash('${prefix}',${steps.length})">Clear</button>
        </div>`;
}

const _CHECKLIST_STEPS = {
    post:   () => _POST_MARKET_STEPS,
    pre:    () => _PRE_MARKET_STEPS,
    weekly: () => _WEEKLY_REVIEW_STEPS,
};

function _saveDashChecklists() {
    const state = {};
    Object.entries(_CHECKLIST_STEPS).forEach(([prefix, steps]) => {
        for (let i = 0; i < steps().length; i++) {
            const cb = document.getElementById(`dash-${prefix}-${i}`);
            if (cb) state[`dash-${prefix}-${i}`] = cb.checked;
        }
    });
    try { localStorage.setItem(_STORAGE_KEY, JSON.stringify(state)); } catch (_) {}
}

function _loadChecklistState() {
    try {
        const raw = localStorage.getItem(_STORAGE_KEY);
        if (!raw) return;
        const s = JSON.parse(raw);
        Object.entries(s).forEach(([id, val]) => {
            const cb = document.getElementById(id);
            if (cb) cb.checked = val;
        });
    } catch (_) {}
}

function _checkAllDash(prefix, len) {
    for (let i = 0; i < len; i++) {
        const cb = document.getElementById(`dash-${prefix}-${i}`);
        if (cb) cb.checked = true;
    }
    _saveDashChecklists();
}

function _clearDash(prefix, len) {
    for (let i = 0; i < len; i++) {
        const cb = document.getElementById(`dash-${prefix}-${i}`);
        if (cb) cb.checked = false;
    }
    _saveDashChecklists();
}

function clearAllDashChecklists() {
    _clearDash('post',   _POST_MARKET_STEPS.length);
    _clearDash('pre',    _PRE_MARKET_STEPS.length);
    _clearDash('weekly', _WEEKLY_REVIEW_STEPS.length);
}

// ── EOD Screens ───────────────────────────────────────────────────────────────

const _SCREEN_DEFS = {
    high_adr:        { label: '⚡ High ADR',        desc: 'Highest average daily ranges — explosive movers' },
    pullback:        { label: '↩ Pullback',         desc: 'Strong uptrends resting on the 10/20-MA in quiet volume' },
    parabolic_short: { label: '🪂 Parabolic',        desc: 'Extreme upside extension — short / inverse-ETF candidates' },
    recent_ipo:      { label: '🌱 Recent IPO',       desc: 'Short price history — fresh listings building first bases' },
};
let _activeScreen = 'high_adr';

function _initScreens() {
    const chipBar = document.getElementById('screens-chips');
    if (!chipBar) return;
    chipBar.innerHTML = Object.entries(_SCREEN_DEFS).map(([name, m]) => `
        <button class="scan-mode-btn ${name === _activeScreen ? 'scan-mode-on' : ''}"
                data-screen="${name}" title="${m.desc}"
                onclick="_runScreen('${name}')">${m.label}</button>`).join('');
    _runScreen(_activeScreen);
}

async function _runScreen(name) {
    _activeScreen = name;
    document.querySelectorAll('#screens-chips .scan-mode-btn').forEach(b =>
        b.classList.toggle('scan-mode-on', b.dataset.screen === name));
    const c = document.getElementById('screens-results');
    if (!c) return;
    c.innerHTML = '<div class="feat-loading"><span class="spinner"></span></div>';
    try {
        const d    = await apiFetch(`${API}/screens/${name}`);
        const rows = d.rows || [];
        if (!rows.length) {
            c.innerHTML = `<div class="feat-empty">No matches — ${_SCREEN_DEFS[name].desc.toLowerCase()}.</div>`;
            return;
        }
        const extraHead = name === 'parabolic_short' ? '<th>5D %</th>'
                        : name === 'pullback'        ? '<th>30D %</th><th title="Distance to KAMA-20 in ATRs">→K20</th>'
                        : name === 'recent_ipo'      ? '<th>Bars</th><th>20D %</th>'
                        : '<th>20D %</th>';
        const body = rows.map(r => {
            const extCls = r.atr_mult_50ma > 4 ? 'proc-bear' : r.atr_mult_50ma > 2.5 ? 'proc-warn' : '';
            const extra  = name === 'parabolic_short'
                ? `<td class="${r.ret_5d >= 0 ? 'proc-bull' : 'proc-bear'}">${r.ret_5d > 0 ? '+' : ''}${r.ret_5d}%</td>`
                : name === 'pullback'
                ? `<td class="proc-bull">+${r.ret_30d}%</td><td>${r.dist_k20 != null ? r.dist_k20.toFixed(1) + '×' : '—'}${r.vol_dryup ? ' <span class="ep-flag-good" title="Volume dry-up">DU</span>' : ''}</td>`
                : name === 'recent_ipo'
                ? `<td>${r.bars}</td><td class="${(r.ret_20d || 0) >= 0 ? 'proc-bull' : 'proc-bear'}">${r.ret_20d != null ? (r.ret_20d > 0 ? '+' : '') + r.ret_20d + '%' : '—'}</td>`
                : `<td class="${(r.ret_20d || 0) >= 0 ? 'proc-bull' : 'proc-bear'}">${r.ret_20d != null ? (r.ret_20d > 0 ? '+' : '') + r.ret_20d + '%' : '—'}</td>`;
            return `<tr style="cursor:pointer" onclick="selectSymbol('${r.symbol}')">
                <td><strong data-hover-symbol="${r.symbol}">${r.symbol}</strong></td>
                <td class="jnl-muted-sm">${r.sector || '—'}</td>
                <td>${r.last_close != null ? r.last_close.toFixed(2) : '—'}</td>
                <td>${r.adr_pct != null ? r.adr_pct.toFixed(1) + '%' : '—'}</td>
                <td class="${extCls}">${r.atr_mult_50ma != null ? r.atr_mult_50ma.toFixed(1) + '×' : '—'}</td>
                ${extra}
            </tr>`;
        }).join('');
        c.innerHTML = `
            <div class="process-section-note" style="margin:4px 0 8px;">${_SCREEN_DEFS[name].desc} — ${rows.length} match${rows.length === 1 ? '' : 'es'}</div>
            <div class="feat-table-wrap">
            <table class="feat-table">
                <thead><tr><th>Symbol</th><th>Sector</th><th>Last</th><th>ADR%</th><th>ATR×50</th>${extraHead}</tr></thead>
                <tbody>${body}</tbody>
            </table>
            </div>`;
    } catch (e) {
        c.innerHTML = `<div class="feat-empty" style="color:var(--red);">${e.message}</div>`;
    }
}
