/**
 * journal.js — Trade Journal
 * Lists entries from /api/journal and supports add/delete. Edit is left to the
 * inline forms; closed trades show realised P&L.
 */

function _jnlEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

function _jnlPnl(e) {
    if (e.exit_price === null || e.exit_price === undefined) return '<span class="jnl-open">open</span>';
    const dir = (e.direction === 'short') ? -1 : 1;
    const pnl = (e.exit_price - e.entry_price) * (e.qty || 1) * dir;
    const cls = pnl >= 0 ? 'jnl-pos' : 'jnl-neg';
    return `<span class="${cls}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}</span>`;
}

async function loadJournal() {
    const tbody = document.getElementById('journal-body');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="8" class="jnl-muted"><span class="spinner"></span> Loading…</td></tr>';
    try {
        const entries = await apiFetch(`${API}/journal`);
        if (!Array.isArray(entries) || entries.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="jnl-muted">No journal entries yet.</td></tr>';
            return;
        }
        tbody.innerHTML = entries.map(e => `
            <tr>
                <td><strong>${_jnlEsc(e.symbol)}</strong></td>
                <td class="${e.direction === 'short' ? 'jnl-neg' : 'jnl-pos'}">${_jnlEsc(e.direction)}</td>
                <td>${_jnlEsc(e.entry_date)}</td>
                <td>${Number(e.entry_price).toFixed(2)}</td>
                <td>${e.exit_price !== null && e.exit_price !== undefined ? Number(e.exit_price).toFixed(2) : '—'}</td>
                <td>${_jnlPnl(e)}</td>
                <td>${_jnlEsc(e.tags)}</td>
                <td><button class="btn btn-ghost btn-icon" title="Delete" onclick="deleteJournalEntry(${e.id})">✕</button></td>
            </tr>`).join('');
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="8" class="jnl-muted">Failed to load: ${_jnlEsc(err.message || err)}</td></tr>`;
    }
}

async function submitJournalEntry() {
    const g = id => document.getElementById(id);
    const body = {
        symbol:      (g('jnl-symbol')?.value || '').trim().toUpperCase(),
        direction:   g('jnl-direction')?.value || 'long',
        entry_date:  g('jnl-entry-date')?.value || undefined,
        entry_price: parseFloat(g('jnl-entry-price')?.value),
        exit_price:  g('jnl-exit-price')?.value ? parseFloat(g('jnl-exit-price').value) : undefined,
        qty:         g('jnl-qty')?.value ? parseFloat(g('jnl-qty').value) : 1,
        setup:       g('jnl-setup')?.value || '',
        tags:        g('jnl-tags')?.value || '',
        thesis:      g('jnl-thesis')?.value || '',
    };
    if (!body.symbol || !Number.isFinite(body.entry_price)) {
        toast('Symbol and entry price are required', 'warning');
        return;
    }
    try {
        await apiFetch(`${API}/journal`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        toast('Journal entry added', 'success');
        ['jnl-symbol', 'jnl-entry-price', 'jnl-exit-price', 'jnl-qty', 'jnl-setup', 'jnl-tags', 'jnl-thesis']
            .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
        loadJournal();
    } catch (e) {
        toastFromError(e, 'Journal');
    }
}

async function deleteJournalEntry(id) {
    try {
        await apiFetch(`${API}/journal/${id}`, { method: 'DELETE' });
        loadJournal();
    } catch (e) {
        toastFromError(e, 'Journal');
    }
}

function initJournal() {
    const sym = document.getElementById('jnl-symbol');
    if (sym && !sym.value && state.activeSymbol) sym.value = state.activeSymbol;
    loadJournal();
}
