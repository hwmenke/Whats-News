/**
 * desk_palette.js — Jump-to (`/`) and command palette (⌘K / Ctrl+K).
 * Jump never mutates the watchlist; Shift+Enter (or the Add row) adds.
 */

const PALETTE_COMMANDS = [
    { id: 'ws-scan', label: 'Workspace · Scan', hint: '1', run: () => applyWorkspace?.('scan') },
    { id: 'ws-chart', label: 'Workspace · Chart', hint: '2', run: () => applyWorkspace?.('chart') },
    { id: 'ws-review', label: 'Workspace · Review', hint: '3', run: () => applyWorkspace?.('review') },
    { id: 'tab-scanner', label: 'Open Scanner', hint: '', run: () => switchTab?.('scanner') },
    { id: 'tab-charts', label: 'Open Charts', hint: '', run: () => switchTab?.('charts') },
    { id: 'tab-data', label: 'Open Data', hint: '', run: () => switchTab?.('data-manager') },
    { id: 'lists', label: 'Smart lists', hint: '', run: () => openSmartListsModal?.() },
    { id: 'positions', label: 'Positions', hint: 'Shift+J', run: () => openJournal?.() },
    { id: 'guide', label: 'Desk guide', hint: '?', run: () => openDeskGuide?.(0) },
    { id: 'badges', label: 'Badge key', hint: '', run: () => openBadgeKey?.() },
    { id: 'focus', label: 'Toggle focus mode', hint: 'f', run: () => toggleFocusMode?.() },
    { id: 'pack-minervini', label: 'Chart pack · Minervini SMA 50/150/200', hint: '', run: () => applyMethodPack?.('minervini') },
    { id: 'pack-stockbee', label: 'Chart pack · Stockbee EMA 9/20', hint: '', run: () => applyMethodPack?.('stockbee') },
    { id: 'pack-qulla', label: 'Chart pack · Qulla EMA 10/21/50', hint: '', run: () => applyMethodPack?.('qulla') },
    { id: 'pack-brandt', label: 'Chart pack · Brandt risk box', hint: '', run: () => applyMethodPack?.('brandt') },
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
    if (!el) return;
    el.hidden = true;
    if (typeof disarmModalFocus === 'function') disarmModalFocus();
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
    if (typeof armModalFocus === 'function') armModalFocus(el);
    else requestAnimationFrame(() => input.focus());
}

function visibleSymbolCodes() {
    const list = document.getElementById('symbol-list');
    if (!list) return [];
    return [...list.querySelectorAll('.symbol-item[data-symbol]')]
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

    const visible = visibleSymbolCodes();
    const all = allWatchlistCodes();
    const seen = new Set();
    const pushSym = (code, where) => {
        if (seen.has(code)) return;
        if (q && !code.includes(q)) return;
        seen.add(code);
        rows.push({ kind: 'sym', id: code, label: code, hint: where, run: () => selectSymbol(code) });
    };
    visible.forEach(c => pushSym(c, 'visible'));
    all.forEach(c => pushSym(c, 'watchlist'));

    if (q && /^[A-Z.]{1,8}$/.test(q) && !seen.has(q)) {
        rows.push({
            kind: 'add',
            id: q,
            label: `Add ${q}`,
            hint: 'Shift+Enter only',
            run: () => addSymbolByCode?.(q),
        });
    }
    return rows.slice(0, 24);
}

function jumpToSymbol(code) {
    if (typeof applyWorkspace === 'function'
        && typeof state !== 'undefined'
        && state.activeTab !== 'charts'
        && state.activeTab !== 'review') {
        applyWorkspace('chart');
    }
    selectSymbol(code);
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
              data-idx="${i}" role="option" aria-selected="${i === _paletteIdx ? 'true' : 'false'}">
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
            jumpToSymbol(code);
            toast?.(`${code} already on the watchlist`, 'info');
            return;
        }
        closeDeskPalette();
        addSymbolByCode?.(code);
        return;
    }
    if (item.kind === 'add') {
        toast?.('Shift+Enter adds a ticker — Enter never mutates the list', 'info');
        return;
    }
    closeDeskPalette();
    if (item.kind === 'sym') jumpToSymbol(item.id);
    else item.run?.();
}

function initDeskPalette() {
    const overlay = document.getElementById('desk-palette');
    const input = document.getElementById('desk-palette-input');
    if (!overlay || !input) return;

    overlay.addEventListener('click', e => {
        if (e.target === overlay) closeDeskPalette();
    });
    input.addEventListener('input', () => {
        _paletteIdx = 0;
        renderPaletteResults(input.value);
    });
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

    document.getElementById('btn-badge-key')?.addEventListener('click', openBadgeKey);
}

function openBadgeKey() {
    const modal = document.getElementById('badge-key-modal');
    const body = document.getElementById('badge-key-body');
    if (!modal || !body) return;
    const cat = (typeof _badgeCatalog !== 'undefined' && _badgeCatalog) ? _badgeCatalog : {};
    const fallback = {
        KQ: { label: 'Qullamaggie', blurb: 'Near high + volume' },
        MM: { label: 'Minervini', blurb: 'Trend Template pass' },
        ON: { label: "O'Neil", blurb: 'Stage 2 + near high + Book RS' },
        DB: { label: 'Darvas', blurb: 'Close above box top' },
        SB4: { label: 'Stockbee 4%', blurb: 'Day or gap ≥4%' },
        SBW: { label: 'Stockbee 20% week', blurb: '5D return ≥20%' },
        SB9: { label: 'Stockbee 9/20', blurb: 'Close > EMA9 > EMA20' },
        '52W': { label: 'Near 52-week high', blurb: 'Within 25% of 52W high' },
        '2A': { label: 'Early Stage 2', blurb: 'Fresh breakout from base' },
        '2B': { label: 'Stage 2', blurb: 'Advancing (weekly SMA30)' },
        '97C': { label: '97 Club', blurb: 'Top Book RTS names' },
    };
    const codes = Object.keys(cat).length ? Object.keys(cat) : Object.keys(fallback);
    body.innerHTML = codes.map(code => {
        const meta = cat[code] || fallback[code] || { label: code, blurb: '' };
        return `<div class="badge-key-row">
          <span class="meth-badge">${code}</span>
          <div><strong>${meta.label || code}</strong><p>${meta.blurb || ''}</p></div>
        </div>`;
    }).join('');
    modal.style.display = 'flex';
    if (typeof armModalFocus === 'function') armModalFocus(modal);
}

function closeBadgeKey() {
    const modal = document.getElementById('badge-key-modal');
    if (modal) modal.style.display = 'none';
    if (typeof disarmModalFocus === 'function') disarmModalFocus();
}
