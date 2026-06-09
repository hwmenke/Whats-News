/**
 * alerts_panel.js — Alert management panel + background polling
 *
 * Bell icon in topbar shows untriggered alert count.
 * Slide-in panel: view all alerts, create, delete, reset.
 * Polls /api/alerts/check every 60s and toasts on new triggers.
 */

let _alertsPollTimer = null;
let _alertsPanelOpen = false;

const _ALERT_FIELDS = [
    { value: 'price',       label: 'Price ($)' },
    { value: 'rsi_14',      label: 'RSI 14' },
    { value: 'kama10_pct',  label: 'KAMA 10 (% from)' },
    { value: 'kama20_pct',  label: 'KAMA 20 (% from)' },
    { value: 'kama50_pct',  label: 'KAMA 50 (% from)' },
];

// ── Badge ─────────────────────────────────────────────────────────────────────

async function _updateAlertBadge() {
    try {
        const alerts  = await apiFetch(`${API}/alerts`);
        const pending = alerts.filter(a => !a.triggered_at).length;
        const badge   = document.getElementById('alert-badge');
        if (!badge) return;
        badge.textContent  = pending;
        badge.style.display = pending > 0 ? '' : 'none';
    } catch (_) {}
}

// ── Panel toggle ──────────────────────────────────────────────────────────────

function toggleAlertsPanel() {
    const panel = document.getElementById('alerts-panel');
    if (!panel) return;
    _alertsPanelOpen = !_alertsPanelOpen;
    panel.classList.toggle('open', _alertsPanelOpen);
    if (_alertsPanelOpen) loadAlerts();
}

// ── Load + render alerts ──────────────────────────────────────────────────────

async function loadAlerts() {
    const listEl = document.getElementById('alerts-list');
    if (!listEl) return;
    listEl.innerHTML = '<div class="alp-loading"><span class="spinner"></span></div>';
    try {
        const alerts = await apiFetch(`${API}/alerts`);
        _renderAlerts(listEl, alerts);
        const pending = alerts.filter(a => !a.triggered_at).length;
        const badge   = document.getElementById('alert-badge');
        if (badge) { badge.textContent = pending; badge.style.display = pending > 0 ? '' : 'none'; }
    } catch (e) {
        listEl.innerHTML = `<div class="alp-empty">Failed: ${e.message}</div>`;
    }
}

function _renderAlerts(el, alerts) {
    if (!alerts.length) {
        el.innerHTML = '<div class="alp-empty">No alerts set. Add one above.</div>';
        return;
    }

    const rows = alerts.map(a => {
        const triggered = !!a.triggered_at;
        const date      = a.triggered_at ? a.triggered_at.slice(0, 10) : '';
        const statusCls = triggered ? 'alp-status-triggered' : 'alp-status-active';
        const statusTxt = triggered ? `✓ hit ${date}` : '● watching';
        const fieldLbl  = _ALERT_FIELDS.find(f => f.value === a.field)?.label || a.field;

        return `<div class="alp-row ${triggered ? 'alp-row-triggered' : ''}">
            <div class="alp-row-main">
                <strong class="alp-sym">${a.symbol}</strong>
                <span class="alp-cond">${fieldLbl} ${a.condition} ${a.threshold}</span>
            </div>
            <div class="alp-row-actions">
                <span class="alp-status ${statusCls}">${statusTxt}</span>
                ${triggered ? `<button class="btn btn-ghost btn-xs" onclick="resetAlert(${a.id})" title="Reset alert">↺</button>` : ''}
                <button class="btn btn-ghost btn-xs" onclick="deleteAlert(${a.id})" title="Delete alert">✕</button>
            </div>
        </div>`;
    }).join('');

    el.innerHTML = rows;
}

// ── CRUD ──────────────────────────────────────────────────────────────────────

async function createAlert() {
    const sym   = (document.getElementById('alert-symbol')?.value    || '').trim().toUpperCase();
    const field = document.getElementById('alert-field')?.value      || '';
    const cond  = document.getElementById('alert-condition')?.value  || '';
    const thr   = document.getElementById('alert-threshold')?.value  || '';

    if (!sym)   { toast('Symbol is required', 'warning'); return; }
    if (!thr)   { toast('Threshold is required', 'warning'); return; }

    try {
        await apiFetch(`${API}/alerts`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({ symbol: sym, field, condition: cond, threshold: parseFloat(thr) }),
        });
        // Clear form fields
        ['alert-symbol','alert-threshold'].forEach(id => {
            const el = document.getElementById(id); if (el) el.value = '';
        });
        if (sym && document.getElementById('jnl-symbol'))
            document.getElementById('alert-symbol').value = '';
        toast(`Alert set: ${sym} ${field} ${cond} ${thr}`, 'success', 2500);
        loadAlerts();
    } catch (e) {
        toastFromError(e, 'Alert');
    }
}

async function deleteAlert(id) {
    try {
        await apiFetch(`${API}/alerts/${id}`, { method: 'DELETE' });
        loadAlerts();
    } catch (e) {
        toastFromError(e, 'Alert');
    }
}

async function resetAlert(id) {
    try {
        await apiFetch(`${API}/alerts/${id}/reset`, { method: 'POST' });
        toast('Alert reset — watching again', 'info', 2000);
        loadAlerts();
    } catch (e) {
        toastFromError(e, 'Alert');
    }
}

// ── Background polling ────────────────────────────────────────────────────────

async function _pollAlertsCheck() {
    try {
        const result = await apiFetch(`${API}/alerts/check`, { method: 'POST' });
        if (result.triggered?.length) {
            result.triggered.forEach(a => {
                toast(`🔔 Alert: ${a.symbol} ${a.field} ${a.condition} ${a.threshold} (value: ${a.value ?? '—'})`,
                      'warning', 6000);
            });
            _updateAlertBadge();
            if (_alertsPanelOpen) loadAlerts();
        }
    } catch (_) {}
}

function startAlertPolling(intervalMs = 60000) {
    if (_alertsPollTimer) clearInterval(_alertsPollTimer);
    _pollAlertsCheck();                               // immediate check
    _alertsPollTimer = setInterval(_pollAlertsCheck, intervalMs);
}

// ── Pre-fill symbol from active symbol ───────────────────────────────────────

function _syncAlertSymbol() {
    const el = document.getElementById('alert-symbol');
    if (el && !el.value && typeof state !== 'undefined' && state.activeSymbol) {
        el.value = state.activeSymbol;
    }
}
