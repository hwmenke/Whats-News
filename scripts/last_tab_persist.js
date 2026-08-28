/**
 * last_tab_persist.js — persist last analysis tab (localStorage).
 * Wraps switchTab after app.js so reload restores charts / stats / knn / dist /
 * scanner if present. Invalid values fall back to charts.
 * Does not persist Review (news). Chart/Scan workspaces still override layout separately.
 * not a published rating.
 */
const LAST_TAB_KEY = 'whats-news-last-tab';
const LAST_TAB_ALLOWED = ['charts', 'stats', 'knn', 'dist'];
let _origSwitchTab = null;

function lastTabScannerPresent() {
    try {
        return !!(typeof document !== 'undefined' && document.getElementById
            && document.getElementById('tab-scanner'));
    } catch {
        return false;
    }
}

function isAllowedLastTab(tab) {
    const v = String(tab == null ? '' : tab).trim().toLowerCase();
    if (LAST_TAB_ALLOWED.indexOf(v) >= 0) return true;
    if (v === 'scanner' && lastTabScannerPresent()) return true;
    return false;
}

function normalizeLastTab(value) {
    const v = String(value == null ? '' : value).trim().toLowerCase();
    return isAllowedLastTab(v) ? v : 'charts';
}

function readLastTab() {
    try {
        const raw = localStorage.getItem(LAST_TAB_KEY);
        if (raw == null) return 'charts';
        return normalizeLastTab(raw);
    } catch {
        return 'charts';
    }
}

function writeLastTab(tab) {
    try {
        localStorage.setItem(LAST_TAB_KEY, normalizeLastTab(tab));
    } catch { /* ignore quota */ }
}

function persistLastTab(tabId) {
    if (!isAllowedLastTab(tabId)) return;
    writeLastTab(tabId);
}

function restoreLastTab() {
    const tab = readLastTab();
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    const fn = _origSwitchTab || (typeof g.switchTab === 'function' ? g.switchTab : null);
    if (typeof fn === 'function') {
        fn.call(g, tab, { keepWorkspace: true });
    } else if (typeof state !== 'undefined' && state) {
        state.activeTab = tab === 'scanner' ? 'charts' : tab;
    }
    return tab;
}

function wrapSwitchTab() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.switchTab !== 'function' || g.switchTab._lastTabPersistWrapped) return;
    const orig = g.switchTab;
    _origSwitchTab = orig;
    function switchTabPersist(tabId) {
        const result = orig.apply(this, arguments);
        persistLastTab(tabId);
        return result;
    }
    switchTabPersist._lastTabPersistWrapped = true;
    g.switchTab = switchTabPersist;
}

function wrapLoadSymbols() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.loadSymbols !== 'function' || g.loadSymbols._lastTabPersistWrapped) return;
    const orig = g.loadSymbols;
    async function loadSymbolsLastTab() {
        const result = await orig.apply(this, arguments);
        restoreLastTab();
        return result;
    }
    loadSymbolsLastTab._lastTabPersistWrapped = true;
    g.loadSymbols = loadSymbolsLastTab;
}

function bootLastTabPersist() {
    wrapSwitchTab();
    wrapLoadSymbols();
}

if (typeof document !== 'undefined' && document.addEventListener) {
    bootLastTabPersist();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootLastTabPersist);
    }
}
