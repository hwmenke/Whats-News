/**
 * desk_palette.js — Jump-to (`/`) and commands (⌘K / Ctrl+K).
 * Enter never mutates the watchlist; Shift+Enter or the Add row does.
 */

const PALETTE_COMMANDS = [
    { id: 'tab-charts', label: 'Open Charts', hint: '', run: () => switchTab?.('charts') },
    { id: 'tab-scanner', label: 'Open Scanner', hint: '', run: () => switchTab?.('scanner') },
    { id: 'tab-data', label: 'Open Data', hint: '', run: () => switchTab?.('data-manager') },
    { id: 'focus', label: 'Toggle focus mode', hint: 'f', run: () => toggleFocusMode?.() },
    { id: 'journal', label: 'Trade journal', hint: 'Shift+J', run: () => toggleJournal?.() },
    { id: 'book', label: 'Book scan drawer', hint: 'h', run: () => toggleBookDrawer?.() },
];

let _paletteMode = 'jump';
let _paletteItems = [];
let _paletteIdx = 0;

function isPaletteOpen() {
    const el = document.getElementById('desk-palette');
    return el && !el.hidden;
}

function closeDeskPalette() {
    const el = document.getElementById('desk-palette');
    if (el) el.hidden = true;
}

function openDeskPalette(mode = 'jump') {
    const el = document.getElementById('desk-palette');
    const input = document.getElementById('desk-palette-input');
    const title = document.getElementById('desk-palette-title');
    if (!el || !input) return;
    _paletteMode = mode === 'command' ? 'command' : 'jump';
    if (title) title.textContent = _paletteMode === 'command' ? 'Commands' : 'Jump to symbol';
    input.placeholder = _paletteMode === 'command'
        ? 'Filter commands or type a ticker…'
        : 'Jump to ticker — does not add';
    el.hidden = false;
    input.value = '';
    renderPaletteResults('');
    requestAnimationFrame(() => input.focus());
}

function visibleSymbolCodes() {
    const list = document.getElementById('symbol-list');
    if (!list) return [];
    return [...list.querySelectorAll('.symbol-item[data-symbol]')]
        .filter(el => !el.hidden)
        .map(el => el.dataset.symbol)
        .filter(Boolean);
}

function allWatchlistCodes() {
    return (state.symbols || []).map(s => s.symbol);
}

function paletteRows(query) {
    const q = (query || '').trim().toUpperCase();
    const rows = [];
    if (_paletteMode === 'command' || q.startsWith('>')) {
        const cq = q.replace(/^>/, '');
        PALETTE_COMMANDS.forEach(cmd => {
            if (!cq || cmd.label.toUpperCase().includes(cq) || cmd.id.toUpperCase().includes(cq)) {
                rows.push({ kind: 'cmd', id: cmd.id, label: cmd.label, hint: cmd.hint, run: cmd.run });
            }
        });
    }
    const seen = new Set();
    const pushSym = (code, where) => {
        if (seen.has(code)) return;
        if (q && !code.includes(q)) return;
        seen.add(code);
        rows.push({ kind: 'sym', id: code, label: code, hint: where, run: () => selectSymbol(code) });
    };
    visibleSymbolCodes().forEach(c => pushSym(c, 'visible'));
    allWatchlistCodes().forEach(c => pushSym(c, 'watchlist'));
    if (q && /^[A-Z.]{1,8}$/.test(q) && !seen.has(q)) {
        rows.push({
            kind: 'add',
            id: q,
            label: `Add ${q}`,
            hint: 'Shift+Enter only',
            run: () => addSymbolByCode?.(q) || (document.getElementById('new-symbol-input') && (document.getElementById('new-symbol-input').value = q, addSymbol())),
        });
    }
    return rows.slice(0, 24);
}

function renderPaletteResults(query) {
    const box = document.getElementById('desk-palette-results');
    if (!box) return;
    _paletteItems = paletteRows(query);
    if (_paletteIdx >= _paletteItems.length) _paletteIdx = 0;
    if (!_paletteItems.length) {
        box.innerHTML = '<div class="desk-palette-empty">No matches</div>';
        return;
    }
    box.innerHTML = _paletteItems.map((item, i) => `
      <button type="button" class="desk-palette-row${i === _paletteIdx ? ' active' : ''}"
              data-idx="${i}" role="option">
        <span class="desk-palette-label">${item.label}</span>
        <span class="desk-palette-meta">${item.hint || ''}</span>
      </button>
    `).join('');
    box.querySelectorAll('.desk-palette-row').forEach(btn => {
        btn.addEventListener('click', () => {
            const item = _paletteItems[Number(btn.dataset.idx)];
            runPaletteItem(Number(btn.dataset.idx), item?.kind === 'add');
        });
    });
}

function runPaletteItem(idx, addInstead) {
    const item = _paletteItems[idx];
    if (!item) return;
    if (addInstead) {
        const code = item.id;
        if (item.kind !== 'add' && item.kind !== 'sym') return;
        if (allWatchlistCodes().includes(code)) {
            closeDeskPalette();
            selectSymbol(code);
            toast?.(`${code} already on the watchlist`, 'info');
            return;
        }
        closeDeskPalette();
        if (typeof addSymbolByCode === 'function') addSymbolByCode(code);
        else {
            const input = document.getElementById('new-symbol-input');
            if (input) { input.value = code; addSymbol(); }
        }
        return;
    }
    if (item.kind === 'add') {
        toast?.('Shift+Enter adds a ticker — Enter never mutates the list', 'info');
        return;
    }
    closeDeskPalette();
    if (item.kind === 'sym') selectSymbol(item.id);
    else item.run?.();
}

function initDeskPalette() {
    const overlay = document.getElementById('desk-palette');
    const input = document.getElementById('desk-palette-input');
    if (!overlay || !input) return;
    overlay.addEventListener('click', e => { if (e.target === overlay) closeDeskPalette(); });
    input.addEventListener('input', () => { _paletteIdx = 0; renderPaletteResults(input.value); });
    input.addEventListener('keydown', e => {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            _paletteIdx = Math.min(_paletteItems.length - 1, _paletteIdx + 1);
            renderPaletteResults(input.value);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            _paletteIdx = Math.max(0, _paletteIdx - 1);
            renderPaletteResults(input.value);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            runPaletteItem(_paletteIdx, e.shiftKey);
        } else if (e.key === 'Escape') {
            e.preventDefault();
            closeDeskPalette();
        }
    });
    document.addEventListener('keydown', e => {
        const tag = (e.target && e.target.tagName) || '';
        const typing = tag === 'INPUT' || tag === 'TEXTAREA' || e.target?.isContentEditable;
        if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            if (isPaletteOpen() && _paletteMode === 'command') closeDeskPalette();
            else openDeskPalette('command');
            return;
        }
        if (typing) return;
        if (e.key === '/' && !e.metaKey && !e.ctrlKey && !e.altKey) {
            e.preventDefault();
            openDeskPalette('jump');
        }
    });
}

document.addEventListener('DOMContentLoaded', () => {
    if (typeof initDeskPalette === 'function') initDeskPalette();
});
