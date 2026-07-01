/**
 * shortcuts.js — Global keyboard shortcut manager.
 *
 * registerShortcut({ key, ctrl, alt, shift, handler, description })
 * showShortcutsHelp() — renders a modal listing all bindings
 */

const _shortcuts = [];

function registerShortcut({ key, ctrl = false, alt = false, shift = false, handler, description }) {
    _shortcuts.push({ key, ctrl, alt, shift, handler, description });
}

function _shouldIgnore(e) {
    const tag = (e.target.tagName || '').toLowerCase();
    if (['input', 'textarea', 'select'].includes(tag)) return true;
    if (e.target.isContentEditable) return true;
    // Allow Escape through even inside modals so closeBulkModal works
    if (e.key === 'Escape') return false;
    const overlay = document.querySelector('.modal-overlay[style*="flex"]');
    if (overlay) return true;
    return false;
}

document.addEventListener('keydown', e => {
    if (_shouldIgnore(e)) return;
    for (const s of _shortcuts) {
        if (e.key === s.key &&
            !!e.ctrlKey  === s.ctrl &&
            !!e.altKey   === s.alt  &&
            !!e.shiftKey === s.shift) {
            e.preventDefault();
            s.handler(e);
            return;
        }
    }
});

function showShortcutsHelp() {
    const existing = document.getElementById('shortcuts-modal');
    if (existing) { existing.remove(); return; }

    const overlay = document.createElement('div');
    overlay.id        = 'shortcuts-modal';
    overlay.className = 'modal-overlay';
    overlay.style.cssText = 'display:flex;position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,0.6);align-items:center;justify-content:center;';

    const box = document.createElement('div');
    box.style.cssText = 'background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:24px 32px;min-width:340px;max-height:80vh;overflow-y:auto;';

    const title = document.createElement('h3');
    title.textContent = 'Keyboard Shortcuts';
    title.style.cssText = 'margin:0 0 16px;color:var(--text-primary);font-size:14px;';
    box.appendChild(title);

    const table = document.createElement('table');
    table.style.cssText = 'width:100%;border-collapse:collapse;font-size:12px;';

    _shortcuts.forEach(s => {
        const tr = document.createElement('tr');
        const keyStr = [s.ctrl && 'Ctrl', s.alt && 'Alt', s.shift && 'Shift', s.key]
            .filter(Boolean).join('+');
        tr.innerHTML = `
            <td style="padding:4px 12px 4px 0;color:var(--accent);font-family:monospace;white-space:nowrap;">${keyStr}</td>
            <td style="padding:4px 0;color:var(--text-secondary);">${s.description}</td>`;
        table.appendChild(tr);
    });
    box.appendChild(table);

    const close = document.createElement('button');
    close.textContent = 'Close';
    close.style.cssText = 'margin-top:16px;padding:6px 16px;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px;';
    close.addEventListener('click', () => overlay.remove());
    box.appendChild(close);

    overlay.appendChild(box);
    overlay.addEventListener('click', e => { if (e.target === overlay) overlay.remove(); });
    document.body.appendChild(overlay);
}
