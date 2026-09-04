/* Scanner pack — MA / RSI / Breakout + style tags + breadth. Stored bars only. */
/* global API, apiFetch, selectSymbol */

function _packNum(v, digits) {
    if (v == null || Number.isNaN(Number(v))) return '—';
    return Number(v).toFixed(digits == null ? 1 : digits);
}

function _packEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function renderScanBreadth(strip) {
    const el = document.getElementById('scan-breadth');
    if (!el) return;
    const data = strip || {};
    const empty = !data.ready;
    el.classList.toggle('is-empty', empty);
    const cell = (k, v, hint) => `
        <div class="scan-breadth-cell" title="${_packEsc(hint || '')}">
            <span class="scan-breadth-k">${_packEsc(k)}</span>
            <span class="scan-breadth-v">${_packEsc(v)}</span>
        </div>`;
    const stored = Number(data.stored_n || 0);
    const wnHits = !!(document.getElementById('warnings-grid')?.querySelector('table, .wn-sym'));
    const hasBars = stored > 0 || wnHits || window.__wnHasHits === true;
    const emptyMsg = hasBars
        ? (data.message && !/empty universe/i.test(data.message)
            ? data.message
            : (stored > 0
                ? `Desk list empty — ${stored} names have stored bars.`
                : 'ENGINE has hits from stored bars. Breadth dashes until the desk list is scored.'))
        : (stored > 0
            ? `Desk list empty — ${stored} names have stored bars.`
            : (data.message || 'Empty universe — no stored bars to score.'));
    const help = empty
        ? (hasBars
            ? emptyMsg
            : 'Stockbee-style breadth from stored Yahoo closes. Dashes until the desk list has bars.')
        : (data.note || 'Stockbee-style breadth idea from our Yahoo/SQLite universe.');
    const ad = (adv, dec) => (adv == null && dec == null) ? '—' : `${adv ?? 0} / ${dec ?? 0}`;
    el.innerHTML = `
        <div class="scan-breadth-cells">
            ${cell('% >SMA50', empty || data.pct_above_sma50 == null ? '—' : `${_packNum(data.pct_above_sma50)}%`, 'Our universe, not a scraped Market Monitor')}
            ${cell('% >SMA200', empty || data.pct_above_sma200 == null ? '—' : `${_packNum(data.pct_above_sma200)}%`, 'SMA200 from stored closes')}
            ${cell('A/D 1d', empty ? '—' : ad(data.adv_1d, data.dec_1d), 'Advances / declines vs prior close')}
            ${cell('A/D 5d', empty ? '—' : ad(data.adv_5d, data.dec_5d), 'Advances / declines vs close 5 sessions ago')}
        </div>
        <details class="scan-help">
            <summary>How scans work</summary>
            <p class="scan-breadth-note">${_packEsc(help)}</p>
        </details>`;
}

async function loadScanBreadth() {
    const el = document.getElementById('scan-breadth');
    if (!el) return;
    try {
        const data = await apiFetch(`${API}/scans/breadth?desk=1`);
        renderScanBreadth(data);
    } catch (err) {
        renderScanBreadth({ ready: false, message: err.message || 'Breadth unavailable' });
    }
}

async function loadScanPack(lens) {
    const tbody = document.getElementById('scan-pack-tbody');
    const empty = document.getElementById('scan-pack-empty');
    const meta = document.getElementById('scan-pack-meta');
    const note = document.getElementById('scan-pack-note');
    if (!tbody) return;
    const kind = lens || (typeof readDeskPrefs === 'function' ? readDeskPrefs().scanLens : 'ma') || 'ma';
    if (meta) meta.textContent = `GET /api/scans/pack?lens=${kind}…`;
    try {
        const data = await apiFetch(`${API}/scans/pack?desk=1&lens=${encodeURIComponent(kind)}`);
        if (data.breadth) renderScanBreadth(data.breadth);
        if (note) {
            const extra = kind === 'oneil' ? (data.oneil_note || 'price/RS only — no fundamentals feed')
                : kind === 'vcp' ? (data.vcp_note || 'honest proxy, not certified VCP')
                : (data.note || '');
            note.textContent = extra;
        }
        const rows = Array.isArray(data.rows) ? data.rows : [];
        tbody.innerHTML = '';
        rows.forEach(row => {
            const tr = document.createElement('tr');
            tr.dataset.symbol = row.symbol || '';
            const tags = (row.tags || []).map(t => `<span class="setup-tag">${_packEsc(t)}</span>`).join('');
            tr.innerHTML = `
                <td class="macro-sym">${_packEsc(row.symbol)}</td>
                <td>${row.day_pct == null ? '—' : _packNum(row.day_pct)}</td>
                <td>${row.vs20 == null ? '—' : _packNum(row.vs20)}</td>
                <td>${row.vs50 == null ? '—' : _packNum(row.vs50)}</td>
                <td>${row.vs200 == null ? '—' : _packNum(row.vs200)}</td>
                <td>${row.rsi14 == null ? '—' : _packNum(row.rsi14)}</td>
                <td>${row.dist_52w_pct == null ? '—' : _packNum(row.dist_52w_pct)}</td>
                <td>${row.vol_ratio == null ? '—' : _packNum(row.vol_ratio) + '×'}</td>
                <td>${tags || '—'}</td>`;
            tr.addEventListener('click', () => {
                if (row.symbol && typeof selectSymbol === 'function') selectSymbol(row.symbol);
            });
            tbody.appendChild(tr);
        });
        if (empty) {
            empty.style.display = rows.length ? 'none' : 'block';
            const p = empty.querySelector('p');
            if (p && !rows.length) p.textContent = data.message || 'No pack hits from stored bars. Empty is honest.';
        }
        if (meta) meta.textContent = `${data.count || 0} / ${data.scanned || 0}`;
        document.querySelectorAll('#scan-pack-styles .scan-style-chip').forEach(btn => {
            btn.classList.toggle('on', btn.dataset.lens === kind);
        });
    } catch (err) {
        if (meta) meta.textContent = 'error';
        if (empty) {
            empty.style.display = 'block';
            const p = empty.querySelector('p');
            if (p) p.textContent = err.message || 'Pack unavailable';
        }
    }
}

function bindScanPack() {
    document.getElementById('btn-scan-pack')?.addEventListener('click', () => {
        const lens = typeof readDeskPrefs === 'function' ? readDeskPrefs().scanLens : 'ma';
        loadScanPack(lens);
    });
    document.querySelectorAll('#scan-pack-styles .scan-style-chip').forEach(btn => {
        btn.addEventListener('click', () => {
            if (typeof applyScanLens === 'function') applyScanLens(btn.dataset.lens);
        });
    });
}

window.loadScanPack = loadScanPack;
window.loadScanBreadth = loadScanBreadth;
window.renderScanBreadth = renderScanBreadth;
window.bindScanPack = bindScanPack;
