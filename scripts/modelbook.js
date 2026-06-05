// ════════════════════════════════════════════════════════════
// modelbook.js — screenshot gallery of past trades (study winners/failures)
// ════════════════════════════════════════════════════════════

let _mbTrades = [];

function mbEsc(s) {
    return String(s ?? '').replace(/[&<>"]/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

async function loadModelBook() {
    try { _mbTrades = await apiFetch(`${API}/journal/trades`); }
    catch (e) { toast(e.message, 'error'); return; }
    renderModelBook();
}

function renderModelBook() {
    const res = (document.getElementById('mb-result').value || '').toLowerCase();
    const setupF = (document.getElementById('mb-setup').value || '').toLowerCase();
    const grid = document.getElementById('modelbook-grid');

    const cards = _mbTrades.filter(t => {
        if (res && (t.result || '').toLowerCase() !== res) return false;
        if (setupF && !(t.setup_type || '').toLowerCase().includes(setupF)) return false;
        return t.chart_entry_url || t.chart_exit_url;
    });

    if (!cards.length) {
        grid.innerHTML = `<p style="color:#888;padding:16px;">No trades with chart screenshots match. Capture charts when logging trades to build your model book.</p>`;
        return;
    }
    const rcls = v => v == null ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));
    grid.innerHTML = cards.map(t => {
        const img = t.chart_exit_url || t.chart_entry_url;
        const r = t.r_multiple;
        return `<div class="mb-card">
            <a href="${mbEsc(img)}" target="_blank"><img src="${mbEsc(img)}" loading="lazy"></a>
            <div class="mb-meta">
              <span class="mb-sym">${mbEsc(t.symbol)}</span>
              <span class="mb-setup">${mbEsc(t.setup_type || '')}</span>
              <span class="${rcls(r)}">${r == null ? (t.result || '') : (Number(r).toFixed(2) + 'R')}</span>
            </div>
            ${t.notes ? `<div class="mb-notes">${mbEsc(t.notes)}</div>` : ''}
        </div>`;
    }).join('');
}
