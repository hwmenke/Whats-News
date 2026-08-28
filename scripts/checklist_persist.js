/**
 * checklist_persist.js — persist process-tools checklist flags (localStorage).
 * Wraps syncChecklist (checklist toggle) after app.js so reload keeps
 * regime / stop / size / plan. Does not persist risk box prices.
 * not a published rating.
 */
const CHECKLIST_KEY = 'whats-news-checklist';
let _origSyncChecklist = null;

function emptyChecklist() {
    return { regime: false, stop: false, size: false, plan: false };
}

function normalizeChecklist(raw) {
    const src = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
    return {
        regime: !!src.regime,
        stop: !!src.stop,
        size: !!src.size,
        plan: !!src.plan,
    };
}

function readChecklist() {
    try {
        const raw = localStorage.getItem(CHECKLIST_KEY);
        if (raw == null) return emptyChecklist();
        return normalizeChecklist(JSON.parse(raw));
    } catch {
        return emptyChecklist();
    }
}

function writeChecklist(flags) {
    try {
        localStorage.setItem(CHECKLIST_KEY, JSON.stringify(normalizeChecklist(flags)));
    } catch { /* ignore quota */ }
}

function persistChecklist() {
    const flags = (typeof state !== 'undefined' && state) ? state.checklist : null;
    writeChecklist(flags);
}

function restoreChecklist() {
    const flags = readChecklist();
    const boxes = typeof document !== 'undefined' && document.querySelectorAll
        ? document.querySelectorAll('#pm-checklist input[type="checkbox"]')
        : [];
    boxes.forEach(box => {
        const key = box.dataset && box.dataset.check;
        if (!key) return;
        box.checked = !!flags[key];
    });
    if (typeof state !== 'undefined' && state) {
        state.checklist = {
            regime: !!flags.regime,
            stop: !!flags.stop,
            size: !!flags.size,
            plan: !!flags.plan,
        };
    }
    if (typeof _origSyncChecklist === 'function') {
        _origSyncChecklist.call(typeof globalThis !== 'undefined' ? globalThis : window);
    }
    return flags;
}

function wrapSyncChecklist() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.syncChecklist !== 'function' || g.syncChecklist._checklistPersistWrapped) return;
    const orig = g.syncChecklist;
    _origSyncChecklist = orig;
    function syncChecklistPersist() {
        const result = orig.apply(this, arguments);
        persistChecklist();
        return result;
    }
    syncChecklistPersist._checklistPersistWrapped = true;
    g.syncChecklist = syncChecklistPersist;
}

function bootChecklistPersist() {
    wrapSyncChecklist();
    restoreChecklist();
}

if (typeof document !== 'undefined' && document.addEventListener) {
    bootChecklistPersist();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootChecklistPersist);
    }
}
