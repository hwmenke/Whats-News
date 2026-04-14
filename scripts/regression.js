/**
 * regression.js — Macro-factor regression tab
 *
 * Layout:
 *   Left panel (fixed)  — factor availability status + "Fetch Missing" button
 *   Right panel (flex)  — controls bar + results (R², feature bars, coef table)
 *
 * Workflow:
 *   1. Tab opens → initRegression() loads factor status
 *   2. User sets Freq / Horizon / Lookback and clicks ▶ Run
 *   3. runRegression() calls GET /api/regression/<symbol>
 *   4. renderRegressionResults() renders importance bars + coefficient table
 */

// ── State ─────────────────────────────────────────────────────
const regState = {
    freq:     'daily',
    horizon:  5,
    lookback: 504,
    data:     null,
    factors:  [],
};

const GROUP_LABELS = {
    equity:    'Broad Equity',
    rates:     'Rates & Credit',
    commodity: 'Commodities',
    vol:       'Volatility',
    sector:    'Sector ETFs',
    intl:      'International',
};

// ── Init ──────────────────────────────────────────────────────
async function initRegression() {
    await loadFactorStatus();
}

// ── Factor status ─────────────────────────────────────────────
async function loadFactorStatus() {
    try {
        const factors  = await apiFetch(`${API}/regression/factor-status`);
        regState.factors = factors;
        renderFactorList(factors);
    } catch (e) {
        const el = document.getElementById('reg-factor-list');
        if (el) el.innerHTML = `<div class="reg-error">Failed to load factor status: ${e.message}</div>`;
    }
}

function renderFactorList(factors) {
    const el = document.getElementById('reg-factor-list');
    if (!el) return;

    // Group factors
    const groups = {};
    factors.forEach(f => {
        if (!groups[f.group]) groups[f.group] = [];
        groups[f.group].push(f);
    });

    const available = factors.filter(f => f.available).length;
    const total     = factors.length;

    let html = `<div class="reg-factor-summary">${available} / ${total} available</div>`;

    for (const [grp, facs] of Object.entries(groups)) {
        html += `<div class="reg-factor-group-label">${GROUP_LABELS[grp] || grp}</div>`;
        html += '<div class="reg-factor-chips">';
        for (const f of facs) {
            const cls = f.available ? 'reg-factor-chip reg-factor-on' : 'reg-factor-chip reg-factor-off';
            html += `<span class="${cls}" title="${f.desc}">${f.label}</span>`;
        }
        html += '</div>';
    }
    el.innerHTML = html;
}

// ── Fetch missing macro factors ───────────────────────────────
async function fetchMissingFactors() {
    const btn = document.getElementById('btn-fetch-factors');
    if (btn) { btn.disabled = true; btn.textContent = '⏳ Fetching…'; }

    try {
        const factors = await apiFetch(`${API}/regression/factor-status`);
        const missing = factors.filter(f => !f.available);

        if (missing.length === 0) {
            toast('All macro factors already available', 'success');
            return;
        }

        toast(`Fetching ${missing.length} missing factor${missing.length > 1 ? 's' : ''}…`, 'info', 8000);
        let ok = 0, failed = 0;

        for (const f of missing) {
            try {
                // Register in watchlist (ignore 409/already-exists)
                await fetch(`${API}/symbols`, {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body:    JSON.stringify({ symbol: f.symbol }),
                });
                // Fetch OHLCV data
                const res = await fetch(`${API}/fetch/${encodeURIComponent(f.symbol)}`,
                    { method: 'POST' });
                if (res.ok) ok++;
                else        failed++;
            } catch (_) { failed++; }
        }

        toast(`${ok} fetched${failed ? `, ${failed} failed` : ''}`, ok > 0 ? 'success' : 'warning');
        await loadFactorStatus();
        if (typeof loadSymbols === 'function') await loadSymbols();
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '⬇ Fetch Missing Factors'; }
    }
}

// ── Run regression ────────────────────────────────────────────
async function runRegression() {
    const symbol = (typeof state !== 'undefined') ? state.activeSymbol : null;
    if (!symbol) {
        toast('Select a symbol first', 'warning');
        return;
    }

    const btn       = document.getElementById('btn-run-regression');
    const loadEl    = document.getElementById('reg-loading');
    const emptyEl   = document.getElementById('reg-empty');
    const resultsEl = document.getElementById('reg-results');

    if (btn)       { btn.disabled = true; btn.textContent = '⏳ Running…'; }
    if (loadEl)    loadEl.style.display = 'flex';
    if (emptyEl)   emptyEl.style.display = 'none';
    if (resultsEl) resultsEl.style.display = 'none';

    const url = `${API}/regression/${encodeURIComponent(symbol)}` +
                `?freq=${regState.freq}&horizon=${regState.horizon}&lookback=${regState.lookback}`;

    try {
        const data = await apiFetch(url);
        regState.data = data;
        renderRegressionResults(data);
        if (resultsEl) resultsEl.style.display = 'block';
    } catch (e) {
        if (emptyEl) {
            emptyEl.style.display = 'flex';
            emptyEl.innerHTML =
                `<div class="empty-icon">⚠</div>` +
                `<p>${e.message}</p>` +
                `<p style="font-size:11px;color:var(--text-dim);margin-top:6px;">` +
                `Make sure macro factors are fetched via the left panel first.</p>`;
        }
    } finally {
        if (loadEl) loadEl.style.display = 'none';
        if (btn)    { btn.disabled = false; btn.textContent = '▶ Run'; }
    }
}

// ── Render results ────────────────────────────────────────────
function renderRegressionResults(data) {
    // KPI row
    const fmt4 = v => (v != null && isFinite(v)) ? v.toFixed(4) : '—';
    const r2El    = document.getElementById('reg-r2');
    const adjR2El = document.getElementById('reg-adj-r2');
    const nObsEl  = document.getElementById('reg-n-obs');
    const nFeatEl = document.getElementById('reg-n-features');
    if (r2El)    r2El.textContent    = fmt4(data.r2);
    if (adjR2El) adjR2El.textContent = fmt4(data.adj_r2);
    if (nObsEl)  nObsEl.textContent  = data.n_obs    ?? '—';
    if (nFeatEl) nFeatEl.textContent = data.n_features ?? '—';

    // Colour R² — green if meaningful, otherwise muted
    if (r2El) {
        const r2v = data.r2 ?? 0;
        r2El.style.color = r2v > 0.05 ? 'var(--green)' : r2v > 0.02 ? 'var(--yellow)' : 'var(--text-muted)';
    }

    // Filter out intercept; sort by |t-stat| descending
    const coefs = (data.coefs || []).filter(c => c.name !== 'intercept');
    const sorted = [...coefs].sort((a, b) => Math.abs(b.t_stat ?? 0) - Math.abs(a.t_stat ?? 0));

    const maxT = sorted.length ? Math.abs(sorted[0].t_stat ?? 1) : 1;

    // ── Feature importance bars ───────────────────────────────
    const impEl = document.getElementById('reg-importance');
    if (impEl) {
        impEl.innerHTML = sorted.slice(0, 25).map(c => {
            const t   = c.t_stat ?? 0;
            const pct = (maxT > 0 ? Math.abs(t) / maxT * 100 : 0).toFixed(1);
            const sig = _sigStars(c.p_value);
            const cls = t > 0 ? 'reg-bar-pos' : 'reg-bar-neg';
            const tStr = (t >= 0 ? '+' : '') + t.toFixed(2);
            return `<div class="reg-bar-row">` +
                `<div class="reg-bar-name">${c.name}</div>` +
                `<div class="reg-bar-track"><div class="reg-bar ${cls}" style="width:${pct}%"></div></div>` +
                `<div class="reg-bar-tval">${tStr}</div>` +
                `<div class="reg-bar-sig">${sig}</div>` +
                `</div>`;
        }).join('');
    }

    // ── Coefficient table ─────────────────────────────────────
    const tbody = document.getElementById('reg-coef-tbody');
    if (tbody) {
        tbody.innerHTML = sorted.map(c => {
            const sig     = _sigStars(c.p_value);
            const pFmt    = c.p_value != null ? c.p_value.toFixed(3) : '—';
            const tFmt    = c.t_stat  != null ? (c.t_stat >= 0 ? '+' : '') + c.t_stat.toFixed(3) : '—';
            const coefFmt = c.coef    != null ? (c.coef   >= 0 ? '+' : '') + c.coef.toFixed(4) : '—';
            const seFmt   = c.se      != null ? c.se.toFixed(4) : '—';
            const rowCls  = Math.abs(c.t_stat ?? 0) > 1.96
                ? (c.t_stat > 0 ? 'reg-row-pos' : 'reg-row-neg') : '';
            return `<tr class="${rowCls}">` +
                `<td class="reg-td-name">${c.name}</td>` +
                `<td class="reg-td-mono">${coefFmt}</td>` +
                `<td class="reg-td-mono">${seFmt}</td>` +
                `<td class="reg-td-mono">${tFmt}</td>` +
                `<td class="reg-td-mono">${pFmt}</td>` +
                `<td class="reg-td-sig">${sig}</td>` +
                `</tr>`;
        }).join('');
    }

    // ── Factor summary note ───────────────────────────────────
    const noteEl = document.getElementById('reg-factor-note');
    if (noteEl) {
        const usedN = data.n_factors_used ?? '?';
        const fwd   = data.horizon ?? '?';
        const freq  = data.freq ?? '';
        noteEl.textContent =
            `${usedN} macro factors · ${fwd}-bar forward return · ` +
            `${data.n_obs} obs · standardised coefficients`;
    }
}

function _sigStars(p) {
    if (p == null) return '';
    if (p < 0.001) return '***';
    if (p < 0.01)  return '**';
    if (p < 0.05)  return '*';
    if (p < 0.10)  return '.';
    return '';
}

// ── Control selectors ─────────────────────────────────────────
function setRegFreq(freq) {
    regState.freq = freq;
    document.querySelectorAll('.reg-freq-btn').forEach(b =>
        b.classList.toggle('reg-active', b.dataset.val === freq));
}

function setRegHorizon(h) {
    regState.horizon = parseInt(h, 10);
    document.querySelectorAll('.reg-hor-btn').forEach(b =>
        b.classList.toggle('reg-active', b.dataset.val === String(h)));
}

function setRegLookback(lb) {
    regState.lookback = parseInt(lb, 10);
    document.querySelectorAll('.reg-lb-btn').forEach(b =>
        b.classList.toggle('reg-active', b.dataset.val === String(lb)));
}
