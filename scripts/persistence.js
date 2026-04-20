/**
 * persistence.js — Debounced localStorage save/restore for session state.
 *
 * Storage key: 'whatsnews.state.v1'
 * Schema:
 *   { version, activeSymbol, activeTab, tabs: { [tabId]: {...} } }
 */

const STORAGE_KEY    = 'whatsnews.state.v1';
const SCHEMA_VERSION = 1;

const persistence = {
    _timer: null,

    load() {
        try {
            const obj = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
            if (!obj || obj.version !== SCHEMA_VERSION) return null;
            return obj;
        } catch (_) { return null; }
    },

    save(patch) {
        clearTimeout(this._timer);
        this._timer = setTimeout(() => {
            try {
                const cur = this.load() || { version: SCHEMA_VERSION, tabs: {} };
                localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...cur, ...patch }));
            } catch (_) {}
        }, 250);
    },

    saveTab(tabId, tabState) {
        const cur = this.load() || { version: SCHEMA_VERSION, tabs: {} };
        cur.tabs        = cur.tabs || {};
        cur.tabs[tabId] = tabState;
        clearTimeout(this._timer);
        this._timer = setTimeout(() => {
            try { localStorage.setItem(STORAGE_KEY, JSON.stringify(cur)); } catch (_) {}
        }, 250);
    },

    loadTab(tabId) {
        return this.load()?.tabs?.[tabId] || null;
    },

    clear() { localStorage.removeItem(STORAGE_KEY); },
};
