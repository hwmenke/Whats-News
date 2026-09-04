/* Warnings — alert surface from ENGINE Pattern / VCP / RSI-C. No second estimator. */
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
        <td>${_wnEsc(r.pattern_w || '—')}</td>
        <td>${_wnEsc(r.vcp || '—')}</td>
        <td>${_wnEsc(r.rsi_c || '—')}</td>
        <td class="mm-z">${_wnEsc(str)}</td>
        <td class="wn-note">${_wnEsc(note || '—')}</td>
    </tr>`;
}

function _wnTable(title, rows) {
    const list = Array.isArray(rows) ? rows : [];
    if (!list.length) {
        return `<section class="wn-card"><h3>${_wnEsc(title)}</h3><p class="wn-empty">none</p></section>`;
    }
    return `<section class="wn-card">
        <h3>${_wnEsc(title)} <span class="wn-n">${list.length}</span></h3>
        <table class="wn-table mm-table">
            <thead><tr><th>Sym</th><th>D</th><th>W</th><th>VCP</th><th>RSI-C</th><th>Str</th><th>Note</th></tr></thead>
            <tbody>${list.map(_wnRow).join('')}</tbody>
        </table>
    </section>`;
}

function renderWarnings(data) {
    const grid = document.getElementById('warnings-grid');
    const note = document.getElementById('warnings-note');
    if (!grid) return;
    if (note) note.textContent = data.note || data.howto || '';
    if (!data.ready) {
        grid.innerHTML = `<p class="scanner-empty">${_wnEsc(data.message || 'Empty warnings — no Pattern / VCP / RSI-C hits on stored bars.')}</p>`;
        return;
    }
    const bo = data.breakouts || {};
    const d = bo.daily || {};
    const w = bo.weekly || {};
    const vcp = data.vcp || {};
    const rsi = data.rsi_c || {};
    const rd = rsi.daily || {};
    const rw = rsi.weekly || {};
    const stretch = data.stretch || {};
    grid.innerHTML = [
        _wnTable('Takeaways', data.takeaways),
        _wnTable('Breakouts D 3M', d.Breakout),
        _wnTable('Breakdowns D 3M', d.Breakdown),
        _wnTable('From Bottom D 1M', d['From Bottom']),
        _wnTable('From Top D 1M', d['From Top']),
        _wnTable('Breakouts W 1Y', w.Breakout),
        _wnTable('Breakdowns W 1Y', w.Breakdown),
        _wnTable('From Bottom W 6M', w['From Bottom']),
        _wnTable('From Top W 6M', w['From Top']),
        _wnTable('VCP Tightening', vcp.tightening),
        _wnTable('VCP Coiled', vcp.coiled),
        _wnTable('RSI-C D OS', rd.oversold),
        _wnTable('RSI-C D OB', rd.overbought),
        _wnTable('RSI-C D Trend↑', rd.trend_up),
        _wnTable('RSI-C D Trend↓', rd.trend_dn),
        _wnTable('RSI-C W OS', rw.oversold),
        _wnTable('RSI-C W OB', rw.overbought),
        _wnTable('RSI-C W Trend↑', rw.trend_up),
        _wnTable('RSI-C W Trend↓', rw.trend_dn),
        _wnTable('D+W ↑', rsi.dw_up),
        _wnTable('D+W ↓', rsi.dw_dn),
        _wnTable('Strongest breakouts', stretch.strongest),
        _wnTable('Most stretched', stretch.stretched),
        _wnTable('Most compressed', stretch.compressed),
    ].join('');
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
