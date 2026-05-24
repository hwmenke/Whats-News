/**
 * sector.js — Sector Heatmap
 * Fetches /api/sector-heatmap and renders sector rows with return heat cells,
 * expandable to per-symbol detail.
 */

function _secEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

function _heatCell(v) {
    if (v === null || v === undefined || !Number.isFinite(v)) return '<td class="heat-cell">—</td>';
    const pct = v * 100;
    // green for positive, red for negative; intensity scales with magnitude
    const mag = Math.min(Math.abs(pct) / 5, 1);   // saturate at ±5%
    const alpha = (0.12 + mag * 0.55).toFixed(2);
    const color = pct >= 0 ? `rgba(34,197,94,${alpha})` : `rgba(239,68,68,${alpha})`;
    const txt = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
    return `<td class="heat-cell" style="background:${color}">${txt}</td>`;
}

function _sectorRow(s, idx) {
    const symRows = (s.symbols || []).map(r => `
        <tr class="sec-sym-row">
            <td class="sec-sym">${_secEsc(r.symbol)}</td>
            <td>${(r.close ?? 0).toFixed(2)}</td>
            ${_heatCell(r.ret_1d)}${_heatCell(r.ret_5d)}${_heatCell(r.ret_20d)}${_heatCell(r.ret_ytd)}
        </tr>`).join('');
    return `
        <tbody class="sec-group">
            <tr class="sec-head" onclick="toggleSectorGroup(${idx})">
                <td class="sec-name"><span class="sec-caret" id="sec-caret-${idx}">▸</span> ${_secEsc(s.sector)} <span class="sec-count">(${s.count})</span></td>
                <td></td>
                ${_heatCell(s.avg_1d)}${_heatCell(s.avg_5d)}${_heatCell(s.avg_20d)}${_heatCell(s.avg_ytd)}
            </tr>
            <tr class="sec-detail" id="sec-detail-${idx}" style="display:none;">
                <td colspan="6">
                    <table class="sec-sym-table"><tbody>${symRows}</tbody></table>
                </td>
            </tr>
        </tbody>`;
}

function toggleSectorGroup(idx) {
    const det = document.getElementById(`sec-detail-${idx}`);
    const car = document.getElementById(`sec-caret-${idx}`);
    if (!det) return;
    const open = det.style.display !== 'none';
    det.style.display = open ? 'none' : 'table-row';
    if (car) car.textContent = open ? '▸' : '▾';
}

async function initSector() {
    const table = document.getElementById('sector-table');
    if (!table) return;
    table.innerHTML = '<tbody><tr><td class="sec-muted"><span class="spinner"></span> Computing sector returns…</td></tr></tbody>';

    try {
        const data = await apiFetch(`${API}/sector-heatmap`);
        if (!Array.isArray(data) || data.length === 0) {
            table.innerHTML = '<tbody><tr><td class="sec-muted">No data. Add symbols (with sectors) and fetch data first.</td></tr></tbody>';
            return;
        }
        const header = `
            <thead><tr>
                <th class="sec-name">Sector</th><th>Close</th>
                <th>1D</th><th>5D</th><th>20D</th><th>YTD</th>
            </tr></thead>`;
        table.innerHTML = header + data.map((s, i) => _sectorRow(s, i)).join('');
    } catch (e) {
        table.innerHTML = `<tbody><tr><td class="sec-muted">Failed to load: ${_secEsc(e.message || e)}</td></tr></tbody>`;
    }
}
