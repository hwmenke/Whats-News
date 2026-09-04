/* Warnings — dense Excel takeaways from ENGINE Pattern / VCP / RSI-C. */
/* global API, apiFetch, selectSymbol, hideEngineArea */

function _wnEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function hideWarningsArea() {
    const el = document.getElementById('warnings-area');
    if (el) el.style.display = 'none';
}

function showWarningsArea() {
    if (typeof hideEngineArea === 'function') hideEngineArea();
    const el = document.getElementById('warnings-area');
    if (el) el.style.display = 'flex';
}

function _wnRow(r) {
    const str = r.str == null || Number.isNaN(Number(r.str)) ? '—' : String(r.str);
    const note = r.label || r.takeaway || '';
    return `<tr>
        <td class="mm-name wn-sym">${_wnEsc(r.symbol || '')}</td>
        <td>${_wnEsc(r.pattern_d || '—')}</td>
        <td>${_wnEsc(r.vcp || '—')}</td>
        <td>${_wnEsc(r.rsi_c || '—')}</td>
        <td class="mm-z">${_wnEsc(str)}</td>
        <td class="wn-note">${_wnEsc(note || '—')}</td>
    </tr>`;
}

function _wnTable(title, rows, hero) {
    const list = Array.isArray(rows) ? rows : [];
    if (!list.length) return '';
    return `<section class="wn-card${hero ? ' wn-hero' : ''}">
        <h3>${_wnEsc(title)} <span class="wn-n">${list.length}</span></h3>
        <table class="wn-table mm-table">
            <thead><tr><th>Sym</th><th>D</th><th>VCP</th><th>RSI-C</th><th>Str</th><th>Note</th></tr></thead>
            <tbody>${list.map(_wnRow).join('')}</tbody>
        </table>
    </section>`;
}

function renderWarnings(data) {
    const grid = document.getElementById('warnings-grid');
    const note = document.getElementById('warnings-note');
    if (!grid) return;
    if (note) note.textContent = '';
    if (!data.ready) {
        window.__wnHasHits = false;
        const msg = data.message || 'Empty warnings — no Pattern / VCP / RSI-C hits on stored bars.';
        const honest = /no stored bars/i.test(msg) && data.source
            ? 'Empty warnings — no Pattern / VCP / RSI-C hits on stored bars.'
            : msg;
        grid.innerHTML = `<p class="scanner-empty">${_wnEsc(honest)}</p>`;
        return;
    }
    window.__wnHasHits = Array.isArray(data.takeaways) && data.takeaways.length > 0;
    const bo = data.breakouts || {};
    const d = bo.daily || {};
    const w = bo.weekly || {};
    const vcp = data.vcp || {};
    const rsi = data.rsi_c || {};
    const rd = rsi.daily || {};
    const rw = rsi.weekly || {};
    const stretch = data.stretch || {};
    // Hero first: takeaways + coiled + stretch. Skip empty buckets (no "none" chrome).
    grid.innerHTML = [
        _wnTable('Takeaways', data.takeaways, true),
        _wnTable('Breaking up D', d.Breakout),
        _wnTable('Breaking down D', d.Breakdown),
        _wnTable('VCP Coiled', vcp.coiled),
        _wnTable('VCP Tightening', vcp.tightening),
        _wnTable('Strongest', stretch.strongest),
        _wnTable('Stretched', stretch.stretched),
        _wnTable('Compressed', stretch.compressed),
        _wnTable('From Bottom D', d['From Bottom']),
        _wnTable('From Top D', d['From Top']),
        _wnTable('Breakouts W', w.Breakout),
        _wnTable('Breakdowns W', w.Breakdown),
        _wnTable('RSI-C D OS', rd.oversold),
        _wnTable('RSI-C D OB', rd.overbought),
        _wnTable('RSI-C D Trend↑', rd.trend_up),
        _wnTable('RSI-C D Trend↓', rd.trend_dn),
        _wnTable('RSI-C W OS', rw.oversold),
        _wnTable('RSI-C W OB', rw.overbought),
        _wnTable('D+W ↑', rsi.dw_up),
        _wnTable('D+W ↓', rsi.dw_dn),
    ].filter(Boolean).join('');
    grid.querySelectorAll('.wn-sym').forEach(td => {
        td.addEventListener('click', () => {
            const sym = td.textContent.trim();
            if (sym && typeof selectSymbol === 'function') selectSymbol(sym);
        });
    });
}

async function loadWarnings() {
    const grid = document.getElementById('warnings-grid');
    const note = document.getElementById('warnings-note');
    if (!grid) return;
    grid.innerHTML = '<p class="scanner-ts">GET /api/engine/warnings…</p>';
    try {
        const data = await apiFetch(`${API}/engine/warnings?desk=1`);
        renderWarnings(data || {});
    } catch (err) {
        if (note) note.textContent = err.message || 'Warnings unavailable';
        grid.innerHTML = `<p class="scanner-empty">${_wnEsc(err.message || 'Warnings unavailable')}</p>`;
    }
}

window.hideWarningsArea = hideWarningsArea;
window.showWarningsArea = showWarningsArea;
window.loadWarnings = loadWarnings;
window.renderWarnings = renderWarnings;
