/**
 * scan_on_tape.js — mark Scan hit rows whose ticker is already on the desk.
 * Wraps renderSetupScanTable after setup_scanner.js. Optional Hide tape (off by default).
 * Enter stays in Scan; Chart and + Desk keep working. not a published rating.
 */
const SCAN_HIDE_TAPE_KEY = 'whats-news-scan-hide-tape';
let hideTape = false;

function normalizeHideTape(value) {
    if (value === true || value === 1) return true;
    const s = String(value == null ? '' : value).trim().toLowerCase();
    return s === '1' || s === 'true';
}

function readHideTape() {
    try {
        const raw = localStorage.getItem(SCAN_HIDE_TAPE_KEY);
        if (raw == null || raw === '') return false;
        return normalizeHideTape(raw);
    } catch {
        return false;
    }
}

function writeHideTape(on) {
    try {
        localStorage.setItem(SCAN_HIDE_TAPE_KEY, on ? '1' : '0');
    } catch { /* ignore quota */ }
}

function persistHideTape() {
    writeHideTape(!!hideTape);
}

function restoreHideTape() {
    hideTape = readHideTape();
    syncHideTapeControl();
    markSetupRowsOnTape();
    return hideTape;
}

function deskTickerSet() {
    const set = new Set();
    const add = (code) => {
        const s = String(code == null ? '' : code).trim().toUpperCase();
        if (s) set.add(s);
    };
    const rows = (typeof state !== 'undefined' && state && Array.isArray(state.symbols))
        ? state.symbols
        : [];
    rows.forEach(row => {
        const tag = String((row && row.group_tag) || '');
        if (tag.toLowerCase().indexOf('univ:') === 0) return;
        add(row && row.symbol);
    });
    if (set.size) return set;
    if (typeof allWatchlistCodes === 'function') {
        const list = allWatchlistCodes() || [];
        list.forEach(add);
    }
    if (set.size) return set;
    if (typeof document !== 'undefined' && document.querySelectorAll) {
        document.querySelectorAll('#symbol-list .symbol-item[data-symbol]').forEach(el => {
            add(el && el.dataset && el.dataset.symbol);
        });
    }
    return set;
}

function rowSymbolCode(tr) {
    if (!tr || !tr.dataset) return '';
    return String(tr.dataset.symbol == null ? '' : tr.dataset.symbol).trim().toUpperCase();
}

function ensureTapeChip(tr, onDesk) {
    if (!tr || typeof tr.querySelector !== 'function') return;
    let chip = tr.querySelector('.setup-tape-chip');
    if (!onDesk) {
        if (chip && chip.parentNode) chip.parentNode.removeChild(chip);
        return;
    }
    if (chip) return;
    const doc = typeof document !== 'undefined' ? document : null;
    if (!doc || typeof doc.createElement !== 'function') return;
    chip = doc.createElement('span');
    chip.className = 'setup-tape-chip';
    chip.textContent = 'tape';
    chip.title = 'Already on the desk';
    const cell = tr.querySelector('.setup-sym');
    const metrics = cell && typeof cell.querySelector === 'function'
        ? cell.querySelector('.setup-metric-chips')
        : null;
    if (cell && metrics && typeof cell.insertBefore === 'function') {
        cell.insertBefore(chip, metrics);
    } else if (cell && typeof cell.appendChild === 'function') {
        cell.appendChild(chip);
    } else if (typeof tr.appendChild === 'function') {
        tr.appendChild(chip);
    }
}

function setupScanOnTapeRows() {
    if (typeof document === 'undefined' || !document.querySelectorAll) return [];
    return [...document.querySelectorAll('#setup-scan-tbody tr.setup-scan-row')];
}

function markSetupRowsOnTape() {
    const desk = deskTickerSet();
    const hide = !!hideTape;
    if (typeof document !== 'undefined' && document.body && document.body.classList) {
        document.body.classList.toggle('setup-hide-tape', hide);
    }
    setupScanOnTapeRows().forEach(tr => {
        const onDesk = desk.has(rowSymbolCode(tr));
        if (tr.classList && typeof tr.classList.toggle === 'function') {
            tr.classList.toggle('setup-on-tape', onDesk);
        }
        ensureTapeChip(tr, onDesk);
        tr.hidden = hide && onDesk;
    });
}

function syncHideTapeControl() {
    const btn = typeof document !== 'undefined'
        ? document.getElementById('btn-setup-hide-tape')
        : null;
    if (!btn) return;
    const on = !!hideTape;
    if (btn.classList && typeof btn.classList.toggle === 'function') {
        btn.classList.toggle('setup-hide-tape-on', on);
    }
    if (typeof btn.setAttribute === 'function') {
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    }
}

function setHideTape(on) {
    hideTape = !!on;
    persistHideTape();
    syncHideTapeControl();
    markSetupRowsOnTape();
}

function bindHideTapeUi() {
    const btn = typeof document !== 'undefined'
        ? document.getElementById('btn-setup-hide-tape')
        : null;
    if (!btn || btn._scanOnTapeBound) return;
    btn._scanOnTapeBound = true;
    btn.addEventListener('click', () => setHideTape(!hideTape));
}

function wrapRenderSetupScanTable() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.renderSetupScanTable !== 'function' || g.renderSetupScanTable._scanOnTapeWrapped) return;
    const orig = g.renderSetupScanTable;
    function renderSetupScanTableMarked() {
        const result = orig.apply(this, arguments);
        markSetupRowsOnTape();
        return result;
    }
    renderSetupScanTableMarked._scanOnTapeWrapped = true;
    g.renderSetupScanTable = renderSetupScanTableMarked;
}

function wrapLoadSymbols() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.loadSymbols !== 'function' || g.loadSymbols._scanOnTapeWrapped) return;
    const orig = g.loadSymbols;
    async function loadSymbolsThenMark() {
        const result = orig.apply(this, arguments);
        try {
            if (result && typeof result.then === 'function') await result;
        } finally {
            markSetupRowsOnTape();
        }
        return result;
    }
    loadSymbolsThenMark._scanOnTapeWrapped = true;
    g.loadSymbols = loadSymbolsThenMark;
}

function bootScanOnTape() {
    wrapRenderSetupScanTable();
    wrapLoadSymbols();
    bindHideTapeUi();
    restoreHideTape();
}

if (typeof document !== 'undefined' && document.addEventListener) {
    bootScanOnTape();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootScanOnTape);
    }
}
