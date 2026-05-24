/**
 * signals.js — Technical Signals Dashboard
 * Fetches /api/signals (all watched symbols) and renders a ranked signal table.
 */

function _sigEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

function _sigChips(signals) {
    if (!signals || !signals.length) return '<span class="sig-muted">—</span>';
    return signals.map(s => {
        const cls = s.bull === true ? 'sig-bull' : s.bull === false ? 'sig-bear' : 'sig-neutral';
        return `<span class="sig-chip ${cls}">${_sigEsc(s.label)}</span>`;
    }).join(' ');
}

function _scoreCell(score) {
    const cls = score > 0 ? 'sig-bull' : score < 0 ? 'sig-bear' : 'sig-neutral';
    const sign = score > 0 ? '+' : '';
    return `<span class="sig-score ${cls}">${sign}${score}</span>`;
}

async function initSignals() {
    const body = document.getElementById('signals-body');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="7" class="sig-muted"><span class="spinner"></span> Scanning watchlist…</td></tr>';

    try {
        const data = await apiFetch(`${API}/signals`);
        if (!Array.isArray(data) || data.length === 0) {
            body.innerHTML = '<tr><td colspan="7" class="sig-muted">No signals. Add symbols and fetch data first.</td></tr>';
            return;
        }
        body.innerHTML = data.map(r => `
            <tr>
                <td><strong>${_sigEsc(r.symbol)}</strong></td>
                <td>${(r.close ?? 0).toFixed(2)}</td>
                <td>${_scoreCell(r.score ?? 0)}</td>
                <td>${(r.rsi14 ?? 0).toFixed(1)}</td>
                <td>${(r.macd ?? 0).toFixed(4)}</td>
                <td>${(r.vol_z ?? 0).toFixed(2)}</td>
                <td class="sig-chips">${_sigChips(r.signals)}</td>
            </tr>
        `).join('');
    } catch (e) {
        body.innerHTML = `<tr><td colspan="7" class="sig-muted">Failed to load signals: ${_sigEsc(e.message || e)}</td></tr>`;
    }
}
