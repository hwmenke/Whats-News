/**
 * desk_only_persist.js — persist sidebar Desk only checkbox (localStorage).
 * Wraps toggleDeskOnly / loadSymbols after app.js so reload keeps hiding univ:* names.
 * Does not rewrite tape-sort in app.js.
 * not a published rating.
 */
const DESK_ONLY_KEY = 'whats-news-desk-only';

function readDeskOnly() {
    try {
        const raw = localStorage.getItem(DESK_ONLY_KEY);
        if (raw == null) return true;
        return raw !== '0' && raw !== 'false';
    } catch {
        return true;
    }
}

function writeDeskOnly(checked) {
    try {
        localStorage.setItem(DESK_ONLY_KEY, checked ? '1' : '0');
    } catch { /* ignore quota */ }
}

function restoreDeskOnly() {
    const on = readDeskOnly();
    const el = document.getElementById('chk-desk-only');
    if (el) el.checked = !!on;
    if (typeof state !== 'undefined' && state) state.deskOnly = !!on;
    return on;
}

function wrapToggleDeskOnly() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.toggleDeskOnly !== 'function' || g.toggleDeskOnly._deskOnlyPersistWrapped) return;
    const orig = g.toggleDeskOnly;
    async function toggleDeskOnlyPersist(checked) {
        writeDeskOnly(!!checked);
        return orig.apply(this, arguments);
    }
    toggleDeskOnlyPersist._deskOnlyPersistWrapped = true;
    g.toggleDeskOnly = toggleDeskOnlyPersist;
}

function wrapLoadSymbols() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.loadSymbols !== 'function' || g.loadSymbols._deskOnlyPersistWrapped) return;
    const orig = g.loadSymbols;
    async function loadSymbolsDeskOnly() {
        restoreDeskOnly();
        return orig.apply(this, arguments);
    }
    loadSymbolsDeskOnly._deskOnlyPersistWrapped = true;
    g.loadSymbols = loadSymbolsDeskOnly;
}

function bootDeskOnlyPersist() {
    wrapToggleDeskOnly();
    wrapLoadSymbols();
    restoreDeskOnly();
}

if (typeof document !== 'undefined' && document.addEventListener) {
    bootDeskOnlyPersist();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootDeskOnlyPersist);
    }
}
