/**
 * process_tools.js — Trading Process tab
 *
 * Three panels:
 *   A) Focus Pipeline — 4-tier kanban (Watchlist → Stalk → Focus → Active)
 *   B) Pre-Entry Checklist — 11 items from the article, auto-evaluated where possible
 *   C) No-Trade Disqualifier — inverse checklist
 */

// ── Init ──────────────────────────────────────────────────────────────────────

function initProcess() {
    _loadPipeline();
    _initChecklist();
    _loadEntryPlanner();
}

// ═══════════════════════════════════════════════════════════════════════════════
// A) FOCUS PIPELINE
// ═══════════════════════════════════════════════════════════════════════════════

const _TIER_LABELS = {
    back_watchlist: { label: 'Back Burner', icon: '🌙', color: '#64748b' },
    watchlist:      { label: 'Watchlist',   icon: '👁',  color: '#8b949e' },
    stalk:          { label: 'Stalk List',  icon: '🎯',  color: '#f97316' },
    focus:          { label: 'Focus List',  icon: '🔥',  color: '#3b82f6' },
    active:         { label: 'Active',      icon: '⚡',  color: '#22c55e' },
};
const _TIER_ORDER = ['back_watchlist', 'watchlist', 'stalk', 'focus', 'active'];

async function _loadPipeline() {
    const container = document.getElementById('process-pipeline');
    if (!container) return;
    container.innerHTML = '<div class="feat-loading"><span class="spinner"></span></div>';
    try {
        const data = await apiFetch(`${API}/focus-pipeline`);
        _renderPipeline(data);
    } catch (e) {
        container.innerHTML = `<div class="feat-empty" style="color:var(--red);">${e.message}</div>`;
    }
}

function _renderPipeline(data) {
    const container = document.getElementById('process-pipeline');
    if (!container) return;

    const cols = _TIER_ORDER.map(tier => {
        const meta  = _TIER_LABELS[tier];
        const syms  = data[tier] || [];
        const cards = syms.map(s => _pipelineCard(s)).join('');
        return `
            <div class="pipeline-col" data-tier="${tier}">
                <div class="pipeline-col-header" style="border-top:3px solid ${meta.color};">
                    <span>${meta.icon} ${meta.label}</span>
                    <span class="pipeline-col-count">${syms.length}</span>
                </div>
                <div class="pipeline-cards" id="pipeline-cards-${tier}">${cards || '<div class="pipeline-empty">Drop symbols here</div>'}</div>
            </div>`;
    }).join('');

    container.innerHTML = `<div class="pipeline-grid">${cols}</div>`;
}

function _pipelineCard(s) {
    const grade    = s.setup_grade || '—';
    const gradeCls = grade === 'A' ? 'sw-grade-a' : grade === 'B' ? 'sw-grade-b' : grade === 'C' ? 'sw-grade-c' : '';
    const rvolCls  = s.rvol >= 1.5 ? 'proc-bull' : s.rvol >= 1.0 ? '' : 'proc-bear';
    const extCls   = s.atr_mult_50ma > 4 ? 'proc-bear' : s.atr_mult_50ma > 2.5 ? 'proc-warn' : 'proc-bull';
    const tiers    = _TIER_ORDER;
    const idx      = tiers.indexOf(s.tier);
    const prevTier = idx > 0 ? tiers[idx - 1] : null;
    const nextTier = idx < tiers.length - 1 ? tiers[idx + 1] : null;

    return `
        <div class="pipeline-card" data-symbol="${s.symbol}" onclick="selectSymbol('${s.symbol}')">
            <div class="pipeline-card-top">
                <strong class="pipeline-sym">${s.symbol}</strong>
                ${grade !== '—' ? `<span class="sw-grade ${gradeCls} sw-grade-sm">${grade}</span>` : ''}
            </div>
            <div class="pipeline-card-meta">
                ${s.sector ? `<span class="pipeline-sector">${s.sector}</span>` : ''}
                ${s.adr_pct != null ? `<span>ADR ${s.adr_pct.toFixed(1)}%</span>` : ''}
                ${s.rvol    != null ? `<span class="${rvolCls}">RVOL ${s.rvol.toFixed(1)}×</span>` : ''}
                ${s.atr_mult_50ma != null ? `<span class="${extCls}">ATR×${s.atr_mult_50ma.toFixed(1)}</span>` : ''}
            </div>
            <div class="pipeline-card-actions" onclick="event.stopPropagation()">
                ${prevTier ? `<button class="btn btn-ghost btn-icon pipeline-mv" title="Move to ${_TIER_LABELS[prevTier].label}"
                    onclick="moveTier('${s.symbol}','${prevTier}')">←</button>` : '<span></span>'}
                <button class="btn btn-ghost btn-icon pipeline-grade-btn" title="Refresh grade"
                    onclick="refreshGrade('${s.symbol}')">⟳</button>
                ${nextTier ? `<button class="btn btn-ghost btn-icon pipeline-mv" title="Move to ${_TIER_LABELS[nextTier].label}"
                    onclick="moveTier('${s.symbol}','${nextTier}')">→</button>` : '<span></span>'}
            </div>
        </div>`;
}

async function moveTier(symbol, tier) {
    try {
        await apiFetch(`${API}/symbols/${symbol}/tier`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tier }),
        });
        toast(`${symbol} → ${_TIER_LABELS[tier].label}`, 'success');
        _loadPipeline();
    } catch (e) {
        toastFromError(e, 'Pipeline');
    }
}

async function refreshGrade(symbol) {
    try {
        const data = await apiFetch(`${API}/setup-grade/${symbol}`);
        toast(`${symbol}: Grade ${data.grade} (score ${data.score})`, 'info');
        _loadPipeline();
    } catch (e) {
        toastFromError(e, 'Grade');
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// B) PRE-ENTRY CHECKLIST
// ═══════════════════════════════════════════════════════════════════════════════

const _ENTRY_CHECKS = [
    { id: 'chk-focus-list',   label: 'Name is on my focus list',                    auto: false },
    { id: 'chk-rvol',         label: 'RVOL is confirming (≥ 1.0×)',                  auto: 'rvol',     pass: d => d.rvol >= 1.0 },
    { id: 'chk-market',       label: 'Market context is supportive',                 auto: false },
    { id: 'chk-group',        label: 'Sector / group is supportive',                 auto: false },
    { id: 'chk-entry-level',  label: 'Entry is near planned level (not chasing)',    auto: false },
    { id: 'chk-lod',          label: 'LoD distance is acceptable (< 0.6 ATR)',       auto: 'lod',      pass: d => d.lod_dist_atr < 0.6 },
    { id: 'chk-extension',    label: 'ATR extension from 50-MA is acceptable (< 4×)',auto: 'ext',      pass: d => d.atr_mult_50ma < 4.0 },
    { id: 'chk-stop',         label: 'Stop loss level is clear',                     auto: false },
    { id: 'chk-size',         label: 'Position size is calculated correctly',        auto: false },
    { id: 'chk-process',      label: 'Entering because of process, not emotion',     auto: false },
    { id: 'chk-best',         label: 'Would take this if only one trade today',      auto: false },
];

const _NO_TRADE_CHECKS = [
    { id: 'nt-chasing',    label: 'Chasing — too far from pivot / trigger' },
    { id: 'nt-no-rvol',    label: 'No RVOL — volume not confirming' },
    { id: 'nt-extended',   label: 'Price too extended from 50-MA (> 4× ATR)' },
    { id: 'nt-macro',      label: 'Major macro data imminent (CPI, NFP, FOMC…)' },
    { id: 'nt-earnings',   label: 'Earnings are imminent' },
    { id: 'nt-illiquid',   label: 'Stock is illiquid / wide spread' },
    { id: 'nt-no-stop',    label: 'Stop is unclear' },
    { id: 'nt-not-focus',  label: 'Not on the focus list' },
    { id: 'nt-recover',    label: 'Trying to recover a recent loss' },
    { id: 'nt-bored',      label: 'Bored / FOMO — no real edge' },
];

let _chkSwingData = null;

function _initChecklist() {
    _renderEntryChecklist();
    _renderNoTradeChecklist();
    // Auto-evaluate with active symbol if available
    const sym = typeof state !== 'undefined' ? state.activeSymbol : null;
    if (sym) _autoEvalChecklist(sym);
}

function _renderEntryChecklist() {
    const c = document.getElementById('process-entry-checklist');
    if (!c) return;
    c.innerHTML = `
        <div class="chk-sym-row">
            <label>Symbol:</label>
            <input id="chk-symbol-input" type="text" class="feat-input" style="width:100px;"
                   placeholder="AAPL" autocomplete="off" spellcheck="false"
                   oninput="this.value=this.value.toUpperCase()"
                   onkeydown="if(event.key==='Enter')_autoEvalChecklist(this.value)" />
            <button class="btn btn-primary btn-icon" onclick="_autoEvalChecklist(document.getElementById('chk-symbol-input').value)">Evaluate</button>
        </div>
        <div id="entry-checks-list">
            ${_ENTRY_CHECKS.map(ch => `
                <div class="chk-item" id="${ch.id}-row">
                    <label class="chk-toggle">
                        <input type="checkbox" id="${ch.id}" onchange="_updateChecklistVerdict()">
                        <span class="chk-box"></span>
                    </label>
                    <span class="chk-label" id="${ch.id}-label">${ch.label}</span>
                    ${ch.auto ? `<span class="chk-auto-badge" id="${ch.id}-auto"></span>` : ''}
                </div>`).join('')}
        </div>
        <div id="entry-verdict" class="chk-verdict"></div>
    `;
    // Pre-fill symbol
    const sym = typeof state !== 'undefined' ? state.activeSymbol : null;
    const inp = document.getElementById('chk-symbol-input');
    if (inp && sym) inp.value = sym;
}

function _renderNoTradeChecklist() {
    const c = document.getElementById('process-notrade-checklist');
    if (!c) return;
    c.innerHTML = `
        <div class="chk-header-note">Check any that apply — if ANY are checked, do NOT trade.</div>
        ${_NO_TRADE_CHECKS.map(ch => `
            <div class="chk-item" id="${ch.id}-row">
                <label class="chk-toggle">
                    <input type="checkbox" id="${ch.id}" onchange="_updateNoTradeVerdict()">
                    <span class="chk-box chk-box-red"></span>
                </label>
                <span class="chk-label">${ch.label}</span>
            </div>`).join('')}
        <div id="notrade-verdict" class="chk-verdict"></div>
    `;
}

async function _autoEvalChecklist(symbol) {
    if (!symbol) return;
    const sym = symbol.toUpperCase();
    // Update input
    const inp = document.getElementById('chk-symbol-input');
    if (inp) inp.value = sym;
    try {
        _chkSwingData = await apiFetch(`${API}/swing-data/${sym}`);
        _applyAutoChecks(_chkSwingData);
    } catch (e) {
        toast('Could not load swing data: ' + e.message, 'warning');
    }
    _updateChecklistVerdict();
}

function _applyAutoChecks(d) {
    for (const ch of _ENTRY_CHECKS) {
        if (!ch.auto || !ch.pass) continue;
        const cb    = document.getElementById(ch.id);
        const badge = document.getElementById(`${ch.id}-auto`);
        if (!cb) continue;
        const result = ch.pass(d);
        cb.checked = result;
        if (badge) {
            badge.textContent = result ? '✓ auto' : '✗ auto';
            badge.className   = 'chk-auto-badge ' + (result ? 'chk-auto-pass' : 'chk-auto-fail');
        }
    }
}

function _updateChecklistVerdict() {
    const total  = _ENTRY_CHECKS.length;
    const passed = _ENTRY_CHECKS.filter(ch => document.getElementById(ch.id)?.checked).length;
    const v      = document.getElementById('entry-verdict');
    if (!v) return;
    const allPass = passed === total;
    v.className   = 'chk-verdict ' + (allPass ? 'chk-verdict-go' : passed >= 8 ? 'chk-verdict-warn' : 'chk-verdict-stop');
    v.textContent = allPass
        ? `✓ ALL ${total} CHECKS PASSED — EXECUTE`
        : passed >= 8
        ? `⚠ ${total - passed} item(s) not checked — REVIEW before executing`
        : `✗ ${total - passed} items outstanding — DO NOT TRADE`;
}

function _updateNoTradeVerdict() {
    const triggered = _NO_TRADE_CHECKS.filter(ch => document.getElementById(ch.id)?.checked).length;
    const v         = document.getElementById('notrade-verdict');
    if (!v) return;
    v.className   = 'chk-verdict ' + (triggered > 0 ? 'chk-verdict-stop' : 'chk-verdict-go');
    v.textContent = triggered > 0
        ? `✗ ${triggered} disqualifier(s) active — DO NOT TRADE`
        : '✓ No disqualifiers — trade is eligible';
}

// Reset all checkboxes
function resetProcessChecklists() {
    [..._ENTRY_CHECKS, ..._NO_TRADE_CHECKS].forEach(ch => {
        const cb = document.getElementById(ch.id);
        if (cb) cb.checked = false;
        const badge = document.getElementById(`${ch.id}-auto`);
        if (badge) { badge.textContent = ''; badge.className = 'chk-auto-badge'; }
    });
    _updateChecklistVerdict();
    _updateNoTradeVerdict();
}

// ═══════════════════════════════════════════════════════════════════════════════
// D) ENTRY PLANNER — pre-market action sheet for Focus/Active names
// ═══════════════════════════════════════════════════════════════════════════════

async function _loadEntryPlanner() {
    const container = document.getElementById('entry-planner');
    if (!container) return;
    container.innerHTML = '<div class="feat-loading"><span class="spinner"></span></div>';
    try {
        const data = await apiFetch(`${API}/trade-plans`);
        _renderEntryPlanner(data.rows || []);
    } catch (e) {
        container.innerHTML = `<div class="feat-empty" style="color:var(--red);">${e.message}</div>`;
    }
}

function _epFlags(r) {
    const f = r.flags || {};
    const chips = [];
    if (f.lod_too_far)     chips.push('<span class="ep-flag" title="LoD distance > 0.6× ATR — entry too far from intraday invalidation">LoD</span>');
    if (f.too_extended)    chips.push('<span class="ep-flag" title="More than 4× ATR above 50-MA — too extended for fresh entry">EXT</span>');
    if (f.ma200_declining) chips.push('<span class="ep-flag" title="200-day MA is declining — structural overhead">200↓</span>');
    if (f.low_rvol)        chips.push('<span class="ep-flag ep-flag-warn" title="RVOL below 1.0× — volume not confirming">RVOL</span>');
    if (r.pocket_pivot)    chips.push('<span class="ep-flag ep-flag-good" title="Pocket pivot — up-day volume beats every down-day volume of the last 10 sessions">PP</span>');
    if (r.vol_dryup)       chips.push('<span class="ep-flag ep-flag-good" title="Volume dry-up — supply contracting inside the base">DU</span>');
    const bad = f.lod_too_far || f.too_extended || f.low_rvol || f.ma200_declining;
    if (!bad && !chips.length) return '<span class="ep-flag-clear" title="No hard-rule violations">✓</span>';
    if (!bad) chips.unshift('<span class="ep-flag-clear" title="No hard-rule violations">✓</span>');
    return chips.join('');
}

function _renderEntryPlanner(rows) {
    const container = document.getElementById('entry-planner');
    if (!container) return;

    if (!rows.length) {
        container.innerHTML = `<div class="feat-empty">No Focus or Active symbols yet —
            promote names in the pipeline above to plan entries.</div>`;
        return;
    }

    const body = rows.map(r => {
        if (r.error) {
            return `<tr><td><strong>${r.symbol}</strong></td>
                <td colspan="8" class="jnl-muted">no data — fetch OHLCV first</td></tr>`;
        }
        const trig    = r.trigger_price != null ? r.trigger_price : '';
        const stop    = r.stop_price    != null ? r.stop_price    : '';
        const rps     = r.risk_per_sh   != null ? '$' + r.risk_per_sh.toFixed(2) : '—';
        const dist    = r.dist_to_trigger_pct != null
            ? `<span class="${Math.abs(r.dist_to_trigger_pct) <= 1 ? 'proc-bull' : ''}">${r.dist_to_trigger_pct > 0 ? '+' : ''}${r.dist_to_trigger_pct.toFixed(1)}%</span>`
            : '—';
        const tierIco = _TIER_LABELS[r.tier]?.icon || '';
        return `<tr data-ep-symbol="${r.symbol}">
            <td><strong data-hover-symbol="${r.symbol}">${r.symbol}</strong> ${tierIco}</td>
            <td>${r.last_close != null ? r.last_close.toFixed(2) : '—'}</td>
            <td><input type="number" step="any" class="feat-input feat-input-sm ep-input"
                 id="ep-trig-${r.symbol}" value="${trig}" placeholder="trigger" /></td>
            <td><input type="number" step="any" class="feat-input feat-input-sm ep-input"
                 id="ep-stop-${r.symbol}" value="${stop}" placeholder="stop" /></td>
            <td>${rps}</td>
            <td>${dist}</td>
            <td>${_epFlags(r)}</td>
            <td class="ep-actions">
                <button class="btn btn-ghost btn-icon" title="Save plan" onclick="_savePlan('${r.symbol}')">💾</button>
                <button class="btn btn-ghost btn-icon" title="Size it in Risk Calc" onclick="_planToRiskCalc('${r.symbol}')">🧮</button>
                ${r.has_plan ? `<button class="btn btn-ghost btn-icon" title="Delete plan" onclick="_deletePlan('${r.symbol}')">✕</button>` : ''}
            </td>
        </tr>`;
    }).join('');

    container.innerHTML = `
        <div class="feat-table-wrap">
        <table class="feat-table ep-table">
            <thead><tr>
                <th>Symbol</th><th>Last</th><th>Trigger $</th><th>Stop $</th>
                <th title="Risk per share = trigger − stop">R/share</th>
                <th title="Distance from last close to trigger">To Trigger</th>
                <th title="Hard-rule violations: LoD > 0.6 ATR, extension > 4× ATR, RVOL < 1">Flags</th><th></th>
            </tr></thead>
            <tbody>${body}</tbody>
        </table>
        </div>`;
}

async function _savePlan(symbol) {
    const trig = document.getElementById(`ep-trig-${symbol}`)?.value;
    const stop = document.getElementById(`ep-stop-${symbol}`)?.value;
    if (!trig && !stop) { toast('Enter a trigger or stop price first', 'warning'); return; }
    try {
        await apiFetch(`${API}/trade-plans`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                symbol,
                trigger_price: trig ? parseFloat(trig) : null,
                stop_price:    stop ? parseFloat(stop) : null,
            }),
        });
        toast(`Plan saved for ${symbol}`, 'success');
        _loadEntryPlanner();
    } catch (e) {
        toastFromError(e, 'Entry Planner');
    }
}

async function _deletePlan(symbol) {
    try {
        await apiFetch(`${API}/trade-plans/${symbol}`, { method: 'DELETE' });
        toast(`Plan removed for ${symbol}`, 'info');
        _loadEntryPlanner();
    } catch (e) {
        toastFromError(e, 'Entry Planner');
    }
}

function _planToRiskCalc(symbol) {
    const trig = parseFloat(document.getElementById(`ep-trig-${symbol}`)?.value);
    const stop = parseFloat(document.getElementById(`ep-stop-${symbol}`)?.value);
    window._jeffSizePrefill = {
        symbol,
        entry: Number.isFinite(trig) ? trig : null,
        stop:  Number.isFinite(stop) ? stop : null,
    };
    if (typeof selectSymbol === 'function') selectSymbol(symbol);
    switchTab('risk-calc');
}
