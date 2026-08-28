/**
 * alert_log_filter.js — compact Book drawer alert-log filter (localStorage).
 * Wraps renderAlertLog after app.js. Row click stays on renderAlertLog → selectSymbol.
 * not a published rating.
 */
const ALERT_LOG_FILTER_KEY = 'whats-news-alert-log-filter';

function readAlertLogFilter() {
    try {
        const raw = localStorage.getItem(ALERT_LOG_FILTER_KEY);
        return raw == null ? '' : String(raw);
    } catch {
        return '';
    }
}

function writeAlertLogFilter(value) {
    try {
        const text = value == null ? '' : String(value);
        if (text) localStorage.setItem(ALERT_LOG_FILTER_KEY, text);
        else localStorage.removeItem(ALERT_LOG_FILTER_KEY);
    } catch { /* ignore quota */ }
}

function persistAlertLogFilter() {
    const el = document.getElementById('alert-log-filter');
    writeAlertLogFilter(el ? el.value : '');
}

function restoreAlertLogFilter() {
    const el = document.getElementById('alert-log-filter');
    if (el) el.value = readAlertLogFilter();
    applyAlertLogFilter();
}

function alertLogFilterQuery() {
    return (document.getElementById('alert-log-filter')?.value || '').trim().toLowerCase();
}

function matchesAlertLogFilter(symbol, alertText, q) {
    const needle = String(q == null ? alertLogFilterQuery() : q).trim().toLowerCase();
    if (!needle) return true;
    const code = String(symbol || '').toLowerCase();
    const text = String(alertText || '').toLowerCase();
    return code.includes(needle) || text.includes(needle);
}

function applyAlertLogFilter() {
    const log = document.getElementById('alert-log');
    if (!log) return;
    const q = alertLogFilterQuery();
    const items = log.querySelectorAll('.alert-log-item');
    let visible = 0;
    items.forEach(item => {
        const symbol = item.dataset?.sym || '';
        const alertText = item.querySelector('.al-flag')?.textContent || '';
        const show = matchesAlertLogFilter(symbol, alertText, q);
        item.hidden = !show;
        if (show) visible += 1;
    });
    let hint = log.querySelector('.alert-log-filter-empty');
    if (items.length && !visible && q) {
        if (!hint) {
            hint = document.createElement('div');
            hint.className = 'alert-log-empty alert-log-filter-empty';
            hint.textContent = 'No matching alerts';
            log.appendChild(hint);
        }
    } else if (hint) {
        hint.remove();
    }
}

function bindAlertLogFilterUi() {
    const el = document.getElementById('alert-log-filter');
    if (el && !el._alertLogFilterBound) {
        el._alertLogFilterBound = true;
        el.addEventListener('input', () => {
            persistAlertLogFilter();
            applyAlertLogFilter();
        });
    }
}

function wrapRenderAlertLog() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.renderAlertLog !== 'function' || g.renderAlertLog._alertLogFilterWrapped) return;
    const orig = g.renderAlertLog;
    function renderAlertLogWithFilter() {
        orig.apply(this, arguments);
        applyAlertLogFilter();
    }
    renderAlertLogWithFilter._alertLogFilterWrapped = true;
    g.renderAlertLog = renderAlertLogWithFilter;
}

function wrapOpenBookDrawer() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.openBookDrawer !== 'function' || g.openBookDrawer._alertLogFilterWrapped) return;
    const orig = g.openBookDrawer;
    function openBookDrawerWithFilter() {
        restoreAlertLogFilter();
        return orig.apply(this, arguments);
    }
    openBookDrawerWithFilter._alertLogFilterWrapped = true;
    g.openBookDrawer = openBookDrawerWithFilter;
}

function bootAlertLogFilter() {
    wrapRenderAlertLog();
    wrapOpenBookDrawer();
    bindAlertLogFilterUi();
    restoreAlertLogFilter();
}

if (typeof document !== 'undefined' && document.addEventListener) {
    bootAlertLogFilter();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootAlertLogFilter);
    }
}
