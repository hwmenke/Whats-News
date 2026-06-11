/**
 * command_palette.js — ⌘K / Ctrl+K quick navigation
 *
 * Self-contained: builds its own overlay DOM on first open. Aggregates all
 * dashboard tabs (read from the .tab-btn nav) and watchlist symbols (from the
 * global `state`), then runs a simple fuzzy filter. Enter executes the
 * highlighted command (switchTab or selectSymbol).
 */
(function () {
    let overlay, input, listEl;
    let items = [];       // [{type,label,sub,run}]
    let filtered = [];
    let cursor = 0;

    function _esc(s) {
        return String(s ?? '').replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    function buildDom() {
        overlay = document.createElement('div');
        overlay.id = 'cmdk-overlay';
        overlay.className = 'cmdk-overlay';
        overlay.style.display = 'none';
        overlay.innerHTML = `
            <div class="cmdk-panel" role="dialog" aria-label="Command palette">
                <input id="cmdk-input" class="cmdk-input" type="text"
                       placeholder="Jump to a tab or symbol…" autocomplete="off" spellcheck="false" />
                <div id="cmdk-list" class="cmdk-list"></div>
                <div class="cmdk-foot"><span><kbd>↑</kbd><kbd>↓</kbd> navigate</span><span><kbd>↵</kbd> select</span><span><kbd>esc</kbd> close</span></div>
            </div>`;
        document.body.appendChild(overlay);
        input = overlay.querySelector('#cmdk-input');
        listEl = overlay.querySelector('#cmdk-list');

        overlay.addEventListener('mousedown', e => { if (e.target === overlay) close(); });
        input.addEventListener('input', () => { cursor = 0; render(); });
        input.addEventListener('keydown', onKey);
    }

    function collectItems() {
        const out = [];
        document.querySelectorAll('.tab-btn').forEach(btn => {
            const id = (btn.id || '').replace(/^tab-/, '');
            if (!id) return;
            const label = btn.textContent.trim().replace(/\s+/g, ' ');
            out.push({ type: 'Tab', label, sub: 'View', run: () => switchTab(id) });
        });
        const syms = (typeof state !== 'undefined' && Array.isArray(state.symbols)) ? state.symbols : [];
        syms.forEach(s => {
            const notes = s.notes ? ` · ${s.notes.slice(0, 40)}` : '';
            const sub   = [s.name, s.sector].filter(Boolean).join(' · ') + notes;
            out.push({
                type: 'Symbol',
                label: s.symbol,
                sub,
                run: () => {
                    if (typeof selectSymbol === 'function') selectSymbol(s.symbol);
                    if (typeof switchTab    === 'function') switchTab('charts');
                },
            });
            // Quick actions per symbol
            out.push({
                type: 'Action',
                label: `Alert ${s.symbol}`,
                sub: 'Set price alert at trigger',
                run: () => {
                    if (typeof selectSymbol === 'function') selectSymbol(s.symbol);
                    if (typeof toggleAlertsPanel === 'function') toggleAlertsPanel();
                },
            });
            out.push({
                type: 'Action',
                label: `Size ${s.symbol}`,
                sub: 'Open risk calculator',
                run: () => {
                    if (typeof selectSymbol === 'function') selectSymbol(s.symbol);
                    if (typeof switchTab    === 'function') switchTab('risk-calc');
                },
            });
        });

        // Global actions
        const globalActions = [
            { label: 'Scan All',         sub: 'Run watchlist scanner',     run: () => { if (typeof switchTab  === 'function') switchTab('scanner'); setTimeout(() => typeof runScan === 'function' && runScan(), 100); } },
            { label: 'Jeff Scanner',     sub: 'Jeff setup scan mode',      run: () => { if (typeof switchTab  === 'function') switchTab('scanner'); setTimeout(() => typeof setScanMode === 'function' && setScanMode('jeff'), 100); } },
            { label: 'Run All Routine',  sub: 'Morning routine all steps', run: () => { if (typeof switchTab  === 'function') switchTab('routine');  setTimeout(() => typeof runAllRoutine === 'function' && runAllRoutine(), 100); } },
            { label: 'Toggle Sidebar',   sub: 'Ctrl+B — show/hide watchlist', run: () => typeof toggleSidebar === 'function' && toggleSidebar() },
            { label: 'Keyboard Shortcuts', sub: '? — show all bindings',   run: () => typeof showShortcutsHelp === 'function' && showShortcutsHelp() },
        ];
        globalActions.forEach(a => out.push({ type: 'Action', ...a }));

        return out;
    }

    function score(item, q) {
        const hay = (item.label + ' ' + item.sub).toLowerCase();
        const needle = q.toLowerCase();
        if (!needle) return 1;
        if (item.label.toLowerCase().startsWith(needle)) return 3;
        if (hay.includes(needle)) return 2;
        // subsequence match
        let i = 0;
        for (const ch of hay) { if (ch === needle[i]) i++; if (i === needle.length) return 1; }
        return 0;
    }

    function render() {
        const q = input.value.trim();
        filtered = items
            .map(it => ({ it, s: score(it, q) }))
            .filter(x => x.s > 0)
            .sort((a, b) => b.s - a.s)
            .map(x => x.it)
            .slice(0, 50);
        if (cursor >= filtered.length) cursor = Math.max(0, filtered.length - 1);

        listEl.innerHTML = filtered.length
            ? filtered.map((it, i) => `
                <div class="cmdk-item ${i === cursor ? 'active' : ''}" data-i="${i}">
                    <span class="cmdk-kind cmdk-kind-${it.type.toLowerCase()}">${it.type}</span>
                    <span class="cmdk-label">${_esc(it.label)}</span>
                    <span class="cmdk-sub">${_esc(it.sub)}</span>
                </div>`).join('')
            : '<div class="cmdk-empty">No matches</div>';

        listEl.querySelectorAll('.cmdk-item').forEach(el => {
            el.addEventListener('mouseenter', () => { cursor = +el.dataset.i; highlight(); });
            el.addEventListener('click', () => exec());
        });
    }

    function highlight() {
        listEl.querySelectorAll('.cmdk-item').forEach((el, i) => el.classList.toggle('active', i === cursor));
    }

    function onKey(e) {
        if (e.key === 'ArrowDown') { e.preventDefault(); cursor = Math.min(cursor + 1, filtered.length - 1); highlight(); scrollToCursor(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); cursor = Math.max(cursor - 1, 0); highlight(); scrollToCursor(); }
        else if (e.key === 'Enter') { e.preventDefault(); exec(); }
        else if (e.key === 'Escape') { e.preventDefault(); close(); }
    }

    function scrollToCursor() {
        const el = listEl.querySelectorAll('.cmdk-item')[cursor];
        if (el) el.scrollIntoView({ block: 'nearest' });
    }

    function exec() {
        const it = filtered[cursor];
        if (!it) return;
        close();
        try { it.run(); } catch (_) {}
    }

    function open() {
        if (!overlay) buildDom();
        items = collectItems();
        cursor = 0;
        input.value = '';
        overlay.style.display = 'flex';
        render();
        setTimeout(() => input.focus(), 0);
    }

    function close() {
        if (overlay) overlay.style.display = 'none';
    }

    window.openCommandPalette = open;

    document.addEventListener('keydown', e => {
        if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            (overlay && overlay.style.display !== 'none') ? close() : open();
        }
    });
})();
