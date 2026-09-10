/**
 * Market Moves dense grid — QUANT-locked z from /api/market-moves.
 * Utilitarian Inter + mono. No invented PX/z. No fake gamma.
 */
(function () {
    const API = (typeof window !== 'undefined' && window.API_BASE) ? window.API_BASE : '';

    function hideMovesArea() {
        const el = document.getElementById('moves-area');
        if (el) el.style.display = 'none';
    }

    function showMovesArea() {
        const el = document.getElementById('moves-area');
        if (el) el.style.display = 'flex';
        loadMarketMoves();
    }

    function _esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function _num(v, digits) {
        if (v == null || Number.isNaN(Number(v))) return '—';
        return Number(v).toFixed(digits);
    }

    function _heat(z) {
        if (window.BoardRegistry) {
            return window.BoardRegistry.heatStyle(z, { heat: 'z', heat_scale: { lo: -3, hi: 3 } });
        }
        if (z == null || Number.isNaN(Number(z))) return '';
        const a = Math.min(1, Math.abs(Number(z)) / 3);
        if (Number(z) >= 0) return `background: rgba(34,197,94,${(0.06 + 0.32 * a).toFixed(2)})`;
        return `background: rgba(239,68,68,${(0.06 + 0.32 * a).toFixed(2)})`;
    }

    function _zCell(z, extreme) {
        if (z == null || Number.isNaN(Number(z))) return '<td class="mm-z">—</td>';
        const n = Number(z);
        const sign = n > 0 ? '+' : '';
        const bullet = extreme || Math.abs(n) >= 2 ? '• ' : '';
        const cls = n >= 0 ? 'mm-up' : 'mm-dn';
        return `<td class="mm-z ${cls}" style="${_heat(n)}">${bullet}${sign}${n.toFixed(1)}</td>`;
    }

    function _mmCols(data) {
        if (window.BoardRegistry && window.BoardRegistry.visibleColumns) {
            const cols = window.BoardRegistry.visibleColumns('market_moves');
            if (cols && cols.length) return cols;
        }
        return data && data.columns ? data.columns : [];
    }

    function renderGroup(group, cols) {
        const useReg = window.BoardRegistry && cols && cols.length;
        const rows = (group.rows || []).map(r => {
            if (useReg) {
                return `<tr>${cols.map(c => window.BoardRegistry.cellHtml(r, c)).join('')}</tr>`;
            }
            const ready = r.ready && r.px != null;
            const chg = r.day_pct;
            const chgCls = chg == null ? '' : (chg >= 0 ? 'mm-up' : 'mm-dn');
            const chgTxt = chg == null ? '—' : `${chg >= 0 ? '+' : ''}${Number(chg).toFixed(1)}${group.kind === 'yield' ? '' : ''}`;
            return `<tr>
                <td class="mm-name">${_esc(r.name)}</td>
                <td class="mm-px">${ready ? _num(r.px, Math.abs(Number(r.px)) < 10 ? 3 : 2) : '—'}</td>
                <td class="mm-day ${chgCls}">${chgTxt}</td>
                ${_zCell(r.z, r.extreme)}
                ${_zCell(r.z14, false)}
            </tr>`;
        }).join('');
        const head = useReg
            ? window.BoardRegistry.headerHtml(cols)
            : '<tr><th>Name</th><th>PX</th><th>DAY%</th><th>Z</th><th>14D Z</th></tr>';
        return `<section class="mm-card" data-group="${_esc(group.id)}">
            <h3>${_esc(group.label)}</h3>
            <table class="mm-table">
                <thead>${head}</thead>
                <tbody>${rows}</tbody>
            </table>
        </section>`;
    }

    function renderBoard(data) {
        const root = document.getElementById('moves-grid');
        const meta = document.getElementById('moves-meta');
        const legend = document.getElementById('moves-legend');
        const source = document.getElementById('moves-source');
        if (!root) return;
        const groups = data.groups || [];
        const mmCols = _mmCols(data);
        const cols = [[], [], []];
        groups.forEach(g => {
            const c = Number(g.col);
            cols[c === 1 || c === 2 ? c : 0].push(g);
        });
        root.innerHTML = cols.map(col =>
            `<div class="mm-col">${col.map(g => renderGroup(g, mmCols)).join('')}</div>`
        ).join('');
        if (meta) {
            const asof = data.asof ? `session ${data.asof}` : 'no stored session';
            meta.textContent = `${data.asof_et || ''} · ${asof}`;
        }
        if (legend) legend.textContent = data.legend || '';
        if (source) source.textContent = data.source || '';
    }

    async function loadMarketMoves() {
        const loading = document.getElementById('moves-loading');
        if (loading) loading.style.display = 'block';
        try {
            if (window.BoardRegistry && window.BoardRegistry.load) {
                await window.BoardRegistry.load();
            }
            const res = await fetch(`${API}/api/market-moves`);
            const data = await res.json();
            renderBoard(data || {});
        } catch (err) {
            const root = document.getElementById('moves-grid');
            if (root) root.innerHTML = `<p class="mm-empty">Could not load Market Moves. ${String(err.message || err)}</p>`;
        } finally {
            if (loading) loading.style.display = 'none';
        }
    }

    async function seedAndFetchCore() {
        const btn = document.getElementById('btn-moves-fetch');
        const meta = document.getElementById('moves-fetch-meta');
        if (btn) btn.disabled = true;
        if (meta) meta.textContent = 'Seeding Indexes + Big Tech + Sectors…';
        try {
            await fetch(`${API}/api/market-moves/seed`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ groups: ['indexes', 'big_tech', 'sectors'] }),
            });
            if (meta) meta.textContent = 'Fetching Yahoo into finance.db…';
            const res = await fetch(`${API}/api/market-moves/fetch-core`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ delay: 1.2, period: '1y' }),
            });
            const data = await res.json();
            const ok = (data.fetched || []).length;
            const fail = (data.failed || []).length;
            if (meta) meta.textContent = `Fetched ${ok} · blank ${fail} (Yahoo miss = —)`;
            await loadMarketMoves();
        } catch (err) {
            if (meta) meta.textContent = err.message || 'Fetch failed';
        } finally {
            if (btn) btn.disabled = false;
        }
    }

    function bindMoves() {
        document.getElementById('btn-moves-reload')?.addEventListener('click', () => loadMarketMoves());
        document.getElementById('btn-moves-fetch')?.addEventListener('click', () => seedAndFetchCore());
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindMoves);
    } else {
        bindMoves();
    }

    window.hideMovesArea = hideMovesArea;
    window.showMovesArea = showMovesArea;
    window.loadMarketMoves = loadMarketMoves;
    window.seedAndFetchCoreMoves = seedAndFetchCore;
})();
