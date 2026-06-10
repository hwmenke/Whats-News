/**
 * risk_calc.js — R-based position sizer + 3-stop strategy calculator
 */

const _RC_KEY = 'risk_calc_prefs';
let _lastRiskCalcResult = null;

function initRiskCalc() {
    const sym = typeof state !== 'undefined' ? state.activeSymbol : null;
    const lbl = document.getElementById('rc-sym-label');
    if (lbl && sym) lbl.textContent = sym;

    // Restore persisted account size and risk %
    try {
        const saved = JSON.parse(localStorage.getItem(_RC_KEY) || '{}');
        const acctEl = document.getElementById('rc-account');
        const riskEl = document.getElementById('rc-risk-pct');
        if (acctEl && saved.account) acctEl.value = saved.account;
        if (riskEl && saved.risk_pct) riskEl.value = saved.risk_pct;
    } catch (_) {}

    // Consume a staged prefill from the Jeff scanner "Size it" action
    const pf = window._jeffSizePrefill;
    if (pf && pf.symbol === sym) {
        const entryEl = document.getElementById('rc-entry');
        const stopEl  = document.getElementById('rc-stop');
        if (entryEl && pf.entry != null) entryEl.value = pf.entry;
        if (stopEl  && pf.stop  != null) stopEl.value  = pf.stop;
        window._jeffSizePrefill = null;
        if (lbl && sym) lbl.textContent = sym;
        _calcPositionSize();
        _render3Stop();
        return;
    }

    if (sym) _riskPrefill(sym);
    _render3Stop();
}

function _saveRiskPrefs() {
    try {
        const acct = document.getElementById('rc-account')?.value;
        const risk = document.getElementById('rc-risk-pct')?.value;
        localStorage.setItem(_RC_KEY, JSON.stringify({ account: acct, risk_pct: risk }));
    } catch (_) {}
}

async function _riskPrefill(symbol) {
    try {
        const d = await apiFetch(`${API}/swing-data/${symbol}`);
        const entryEl = document.getElementById('rc-entry');
        const stopEl  = document.getElementById('rc-stop');
        if (entryEl && !entryEl.value) entryEl.value = d.last_close?.toFixed(2) || '';
        if (stopEl  && !stopEl.value  && d.atr_14 && d.last_close) {
            stopEl.value = (d.last_close - d.atr_14 * 1.5).toFixed(2);
        }
        _calcPositionSize();
    } catch (_) {}
}

// ── Position Sizer ────────────────────────────────────────────────────────────

async function _calcPositionSize() {
    _saveRiskPrefs();
    const g = id => document.getElementById(id)?.value;
    const account  = parseFloat(g('rc-account')  || '100000');
    const risk_pct = parseFloat(g('rc-risk-pct') || '0.5');
    const entry    = parseFloat(g('rc-entry')    || '0');
    const stop     = parseFloat(g('rc-stop')     || '0');

    if (!entry || !stop || stop >= entry) {
        const resEl = document.getElementById('rc-results');
        if (resEl) resEl.innerHTML = '<div class="rc-hint">Enter entry and stop prices above.</div>';
        return;
    }

    try {
        const symbol = (typeof state !== 'undefined' && state.activeSymbol) || undefined;
        const d = await apiFetch(`${API}/position-size`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account, risk_pct, entry, stop, symbol }),
        });
        _lastRiskCalcResult = { ...d, entry, stop };
        _renderPositionResults(d);
        _render3Stop(entry, stop, d.shares, d.dollar_risk);
    } catch (e) {
        document.getElementById('rc-results').innerHTML =
            `<div style="color:var(--red);">${e.message}</div>`;
    }
}

function _renderPositionResults(d) {
    const r = document.getElementById('rc-results');
    if (!r) return;
    r.innerHTML = `
        <div class="rc-grid">
            <div class="rc-kpi"><div class="rc-kpi-label">Shares</div><div class="rc-kpi-val">${d.shares.toLocaleString()}</div></div>
            <div class="rc-kpi"><div class="rc-kpi-label">Dollar Risk (1R)</div><div class="rc-kpi-val" style="color:var(--red);">$${d.dollar_risk.toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:0})}</div></div>
            <div class="rc-kpi"><div class="rc-kpi-label">Gross Exposure</div><div class="rc-kpi-val">$${d.gross_exp.toLocaleString('en-US',{minimumFractionDigits:0,maximumFractionDigits:0})}</div></div>
            <div class="rc-kpi"><div class="rc-kpi-label">% of Account</div><div class="rc-kpi-val">${d.pct_portfolio.toFixed(1)}%</div></div>
            <div class="rc-kpi"><div class="rc-kpi-label">Stop %</div><div class="rc-kpi-val" style="color:var(--red);">${d.stop_pct.toFixed(2)}%</div></div>
            <div class="rc-kpi"><div class="rc-kpi-label">Risk/Share</div><div class="rc-kpi-val">$${d.risk_per_sh.toFixed(2)}</div></div>
        </div>
        <div class="rc-targets">
            <div class="rc-target-row"><span class="rc-target-label">+1R</span><span>$${d.tp1_1r.toFixed(2)}</span></div>
            <div class="rc-target-row"><span class="rc-target-label">+3R</span><span style="color:var(--green)">$${d.tp2_3r.toFixed(2)}</span></div>
            <div class="rc-target-row"><span class="rc-target-label">+5R</span><span style="color:var(--green)">$${d.tp3_5r.toFixed(2)}</span></div>
            <div class="rc-target-row"><span class="rc-target-label">+10R</span><span style="color:var(--accent-bright)">$${d.tp4_10r.toFixed(2)}</span></div>
        </div>
        ${d.liq_pct_of_adv != null ? `
        <div class="rc-liq ${d.liq_warning ? 'rc-liq-warn' : ''}">
            Position = ${d.liq_pct_of_adv.toFixed(1)}% of avg daily $ volume
            (${(d.adv_dollar / 1e6).toFixed(1)}M ADV)
            ${d.liq_warning ? ' — above the ~2% liquidity cap, expect slippage' : ''}
        </div>` : ''}
        <div style="margin-top:12px;">
            <button class="btn btn-ghost btn-sm" onclick="_sendRiskToJournal()" title="Pre-fill Journal with these trade parameters">
                📋 Send to Journal
            </button>
        </div>`;
}

// ── 3-Stop Strategy ───────────────────────────────────────────────────────────

function _render3Stop(entry, stop, shares, dollarRisk) {
    const c = document.getElementById('rc-3stop-results');
    if (!c) return;

    if (!entry || !stop || stop >= entry) {
        c.innerHTML = '<div class="rc-hint">Calculate position size first to see 3-stop breakdown.</div>';
        return;
    }

    const riskPerSh  = entry - stop;
    const t1Stop     = entry - riskPerSh * 0.33;  // Tranche 1: early signal fail
    const t2Stop     = entry - riskPerSh * 0.67;  // Tranche 2: intraday level
    const t3Stop     = stop;                        // Tranche 3: full invalidation
    const sharesEa   = shares ? Math.round(shares / 3) : null;
    const avgLoss    = sharesEa && dollarRisk
        ? ((sharesEa * (entry - t1Stop)) + (sharesEa * (entry - t2Stop)) + (sharesEa * (entry - t3Stop)))
        : null;
    const fullLoss   = dollarRisk || null;
    const savings    = fullLoss && avgLoss ? fullLoss - avgLoss : null;

    c.innerHTML = `
        <div class="stop3-table">
            <div class="stop3-row stop3-header">
                <span>Tranche</span><span>Shares</span><span>Exit Price</span><span>Condition</span>
            </div>
            <div class="stop3-row">
                <span class="stop3-t stop3-t1">⅓</span>
                <span>${sharesEa ? sharesEa.toLocaleString() : '—'}</span>
                <span style="color:var(--red)">$${t1Stop.toFixed(2)}</span>
                <span>Early signal failure</span>
            </div>
            <div class="stop3-row">
                <span class="stop3-t stop3-t2">⅔</span>
                <span>${sharesEa ? sharesEa.toLocaleString() : '—'}</span>
                <span style="color:var(--red)">$${t2Stop.toFixed(2)}</span>
                <span>Key intraday level</span>
            </div>
            <div class="stop3-row">
                <span class="stop3-t stop3-t3">Full</span>
                <span>${sharesEa ? sharesEa.toLocaleString() : '—'}</span>
                <span style="color:var(--red)">$${t3Stop.toFixed(2)}</span>
                <span>Full structural invalidation</span>
            </div>
        </div>
        ${avgLoss != null ? `
        <div class="stop3-summary">
            <div class="stop3-stat"><span>Avg loss (3-stop):</span><span style="color:var(--red)">$${avgLoss.toLocaleString('en-US',{maximumFractionDigits:0})}</span></div>
            <div class="stop3-stat"><span>Full stop loss (1R):</span><span style="color:var(--red)">$${fullLoss.toLocaleString('en-US',{maximumFractionDigits:0})}</span></div>
            <div class="stop3-stat"><span>Expected saving:</span><span style="color:var(--green)">$${savings.toLocaleString('en-US',{maximumFractionDigits:0})}</span></div>
            <div class="stop3-note">Goal: avg loss ≈ −0.67R vs −1.0R with single stop</div>
        </div>` : ''}`;
}

// ── Journal handoff ───────────────────────────────────────────────────────────

function _sendRiskToJournal() {
    const sym = (typeof state !== 'undefined' && state.activeSymbol) || '';
    if (!sym) { toast('Select a symbol first', 'warning'); return; }
    const r = _lastRiskCalcResult;
    if (!r) { toast('Calculate position size first', 'warning'); return; }
    window._jeffJournalPrefill = {
        symbol:      sym,
        entry_price: r.entry,
        stop_loss:   r.stop,
        qty:         r.shares,
        setup:       '',
        thesis:      `Risk: $${r.dollar_risk?.toFixed(0)} · Exp: $${r.gross_exp?.toFixed(0)} · ${r.pct_portfolio?.toFixed(1)}% of account`,
    };
    switchTab('journal');
    toast(`Journal pre-filled for ${sym}`, 'info', 2000);
}
