/* Paper P&L + Book — marks from /api/book/pnl. No invented AXE-scale numbers. */

function _pnlEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function _pnlMoney(v, digits = 2) {
    if (v == null || Number.isNaN(Number(v))) return '—';
    const n = Number(v);
    const abs = Math.abs(n).toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    });
    return `${n < 0 ? '−' : ''}$${abs}`;
}

function _pnlPct(v) {
    if (v == null || Number.isNaN(Number(v))) return '—';
    const n = Number(v);
    return `${n >= 0 ? '+' : ''}${n.toFixed(2)}%`;
}

function _pnlTone(v) {
    if (v == null) return '';
    if (Number(v) > 0) return 'is-up';
    if (Number(v) < 0) return 'is-down';
    return '';
}

function hideBookAreas() {
    const pnl = document.getElementById('pnl-area');
    const book = document.getElementById('book-area');
    if (pnl) pnl.style.display = 'none';
    if (book) book.style.display = 'none';
    if (typeof hideEngineArea === 'function') hideEngineArea();
}

function showPnlArea() {
    hideBookAreas();
    const el = document.getElementById('pnl-area');
    if (el) el.style.display = 'flex';
    loadPaperPnl();
}

function showBookArea() {
    hideBookAreas();
    const el = document.getElementById('book-area');
    if (el) el.style.display = 'flex';
    loadPaperBook();
}

function _drawPnlCurve(points) {
    const canvas = document.getElementById('pnl-curve');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.parentElement ? canvas.parentElement.clientWidth : 360;
    canvas.width = Math.max(280, w);
    canvas.height = 168;
    const W = canvas.width;
    const H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = '#0d1117';
    ctx.fillRect(0, 0, W, H);
    ctx.strokeStyle = '#2a3140';
    ctx.lineWidth = 1;
    for (let i = 1; i < 5; i++) {
        const y = (H / 5) * i;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(W, y);
        ctx.stroke();
    }
    for (let i = 1; i < 5; i++) {
        const x = (W / 5) * i;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, H);
        ctx.stroke();
    }
    if (!points || points.length < 2) {
        ctx.fillStyle = '#4a5568';
        ctx.font = '12px sans-serif';
        ctx.fillText('No daily mark series — add lines and store Yahoo closes.', 10, H / 2);
        return;
    }
    const vals = points.map(p => Number(p.nav));
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = max - min || 1;
    const pad = 6;
    const xy = i => ({
        x: pad + (i / (vals.length - 1)) * (W - pad * 2),
        y: pad + (1 - (vals[i] - min) / span) * (H - pad * 2),
    });
    const open = vals[0];
    for (let i = 1; i < vals.length; i++) {
        const a = xy(i - 1);
        const b = xy(i);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = vals[i] >= open ? '#22c55e' : '#ef4444';
        ctx.lineWidth = 2.2;
        ctx.stroke();
    }
}

async function loadPaperPnl() {
    const note = document.getElementById('pnl-note');
    try {
        const data = await apiFetch(`${API}/book/pnl`);
        const nameEl = document.getElementById('pnl-desk-name');
        if (nameEl && data.desk_name && document.activeElement !== nameEl) {
            nameEl.value = String(data.desk_name).toUpperCase();
        }
        const pct = document.getElementById('pnl-today-pct');
        const usd = document.getElementById('pnl-today-usd');
        const nav = document.getElementById('pnl-nav');
        if (pct) {
            pct.textContent = _pnlPct(data.today_pnl_pct);
            pct.className = `pnl-today-pct ${_pnlTone(data.today_pnl_pct)}`;
        }
        if (usd) {
            usd.textContent = _pnlMoney(data.today_pnl);
            usd.className = `pnl-today-usd ${_pnlTone(data.today_pnl)}`;
        }
        const chips = document.getElementById('pnl-alert-chips');
        if (chips) {
            const conc = data.concentration || {};
            const dd = data.drawdown || {};
            const alerts = Array.isArray(data.alerts) ? data.alerts : [];
            const bits = [];
            if (conc.ready) {
                bits.push(`<span class="pnl-chip">${_pnlEsc(`Top ${conc.top_symbol || ''} ${conc.top_weight_pct ?? '—'}% · HHI ${conc.hhi ?? '—'}`)}</span>`);
            }
            if (dd.ready && dd.max_dd_pct != null) {
                bits.push(`<span class="pnl-chip">${_pnlEsc(`Max DD ${Number(dd.max_dd_pct).toFixed(1)}%`)}</span>`);
            }
            alerts.forEach(a => {
                bits.push(`<span class="pnl-chip is-alert">${_pnlEsc(a.label || a.id)}</span>`);
            });
            chips.innerHTML = bits.join('');
        }
        const exp = data.exposure || {};
        const metrics = document.getElementById('pnl-metrics');
        if (metrics) {
            const netPct = exp.net_pct == null ? '—' : `${Number(exp.net_pct).toFixed(0)}%`;
            const conc = data.concentration || {};
            const dd = data.drawdown || {};
            const rows = [
                ['Equities', data.ready ? _pnlMoney(exp.gross) : '—'],
                ['Longs', data.ready ? _pnlMoney(exp.long) : '—'],
                ['Shorts', data.ready ? _pnlMoney(exp.short) : '—'],
                ['Net Exposure', data.ready ? netPct : '—'],
                ['Beta', data.beta_spy == null ? '—' : Number(data.beta_spy).toFixed(2)],
                ['Top weight', conc.top_weight_pct == null ? '—' : `${Number(conc.top_weight_pct).toFixed(1)}%`],
                ['HHI', conc.hhi == null ? '—' : String(conc.hhi)],
                ['Max DD', dd.max_dd_pct == null ? '—' : `${Number(dd.max_dd_pct).toFixed(1)}%`],
            ];
            metrics.innerHTML = rows.map(([k, v]) => `
                <div class="pnl-exp-row">
                    <span>${_pnlEsc(k)}</span>
                    <span>${_pnlEsc(v)}</span>
                </div>`).join('');
        }
        const varEl = document.getElementById('pnl-var');
        if (varEl) {
            const v = data.var || {};
            if (!v.hist_95) {
                varEl.innerHTML = '<p class="macro-blurb">VaR omitted — need ≥20 daily book returns from stored closes.</p>';
            } else {
                const row = (label, pack) => `
                    <div class="pnl-metric">
                        <span class="pnl-metric-k">${_pnlEsc(label)}</span>
                        <span class="pnl-metric-v">${pack?.pct == null ? '—' : _pnlEsc(Number(pack.pct).toFixed(2) + '%')}</span>
                        <span class="pnl-metric-p">${_pnlEsc(_pnlMoney(pack?.usd))}</span>
                    </div>`;
                varEl.innerHTML = `
                    <div class="pnl-var-title">1-day VaR / ES (book NAV returns)</div>
                    <div class="pnl-metrics">
                        ${row('Hist 95%', v.hist_95)}
                        ${row('Hist 99%', v.hist_99)}
                        ${row('Param 95%', v.param_95)}
                        ${row('Param 99%', v.param_99)}
                        ${row('ES 95%', v.es_95)}
                    </div>
                    <p class="macro-blurb">${_pnlEsc(v.note || '')}</p>`;
            }
        }
        const distEl = document.getElementById('pnl-dist');
        if (distEl) {
            const d = data.distribution || {};
            const maxN = Math.max(1, ...(d.bins || []).map(b => b.n));
            distEl.innerHTML = `
                <div class="pnl-var-title">Daily return distribution</div>
                <p class="macro-blurb">n=${d.n || 0} · mean ${d.mean == null ? '—' : d.mean.toFixed(3) + '%'} · σ ${d.stdev == null ? '—' : d.stdev.toFixed(3) + '%'} · skew ${d.skew == null ? '—' : d.skew.toFixed(2)}</p>
                <div class="pnl-hist">${(d.bins || []).map(b => `
                    <div class="pnl-hist-bar" style="height:${Math.max(4, (b.n / maxN) * 64)}px" title="${b.lo}–${b.hi}% · ${b.n}"></div>
                `).join('')}</div>`;
        }
        const tape = document.getElementById('pnl-tape');
        if (tape) {
            const rows = data.tape || [];
            if (!rows.length) {
                tape.innerHTML = '<div class="pnl-tape-row"><span class="macro-blurb">No tape — empty book.</span></div>';
            } else {
                const mid = Math.ceil(rows.length / 2) || 1;
                const chunk = (part) => part.map(t => `
                    <button type="button" class="pnl-tape-item ${_pnlTone(t.day_pct)}" data-symbol="${_pnlEsc(t.symbol)}">
                        <span class="pnl-tape-sym">${_pnlEsc(t.symbol)}</span>
                        <span>${t.ready ? _pnlEsc(_pnlPct(t.day_pct)) : '—'}</span>
                    </button>`).join('');
                tape.innerHTML = `<div class="pnl-tape-row">${chunk(rows.slice(0, mid))}</div>
                    <div class="pnl-tape-row">${chunk(rows.slice(mid))}</div>`;
            }
            tape.querySelectorAll('[data-symbol]').forEach(btn => {
                btn.addEventListener('click', () => {
                    if (typeof selectSymbol === 'function') selectSymbol(btn.dataset.symbol);
                });
            });
        }
        const label = document.getElementById('pnl-curve-label');
        if (label) label.textContent = data.curve_label || '';
        _drawPnlCurve(data.equity_curve || []);
        if (note) note.textContent = data.message || data.note || '';
    } catch (err) {
        if (note) note.textContent = err.message || 'P&L unavailable';
    }
}

async function loadPaperBook() {
    const tbody = document.getElementById('book-tbody');
    const empty = document.getElementById('book-empty');
    if (!tbody) return;
    try {
        const data = await apiFetch(`${API}/book/pnl`);
        const rows = data.positions || [];
        tbody.innerHTML = '';
        rows.forEach(row => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td class="macro-sym">${_pnlEsc(row.symbol)}</td>
                <td>${_pnlEsc(row.side)}</td>
                <td>${row.qty == null ? '—' : row.qty}</td>
                <td>${_pnlEsc(row.source || '')}</td>
                <td>${row.avg_cost == null ? '—' : row.avg_cost}</td>
                <td>${row.price == null ? '—' : row.price}</td>
                <td>${_pnlEsc(_pnlMoney(row.market_value))}</td>
                <td class="${_pnlTone(row.day_pct)}">${row.day_pct == null ? '—' : _pnlEsc(_pnlPct(row.day_pct))}</td>
                <td>${row.vs_sma50 == null ? '—' : _pnlEsc(_pnlPct(row.vs_sma50))}</td>
                <td>${row.rsi14 == null ? '—' : Number(row.rsi14).toFixed(1)}</td>
                <td>${_pnlEsc(row.fractal_read || '—')}</td>
                <td>${_pnlEsc(row.hmm_label || '—')}</td>
                <td class="${_pnlTone(row.day_pnl)}">${_pnlEsc(_pnlMoney(row.day_pnl))}</td>
                <td class="${_pnlTone(row.unrealized)}">${_pnlEsc(_pnlMoney(row.unrealized))}</td>
                <td><button type="button" class="btn btn-ghost btn-sm book-del" data-id="${row.id}">✕</button></td>`;
            tr.querySelector('.macro-sym')?.addEventListener('click', () => {
                if (row.symbol && typeof selectSymbol === 'function') selectSymbol(row.symbol);
            });
            tr.querySelector('.book-del')?.addEventListener('click', async () => {
                await apiFetch(`${API}/book/positions/${row.id}`, { method: 'DELETE' });
                await loadPaperBook();
                await loadPaperPnl();
            });
            tbody.appendChild(tr);
        });
        if (empty) empty.style.display = rows.length ? 'none' : 'block';
    } catch (err) {
        if (empty) {
            empty.style.display = 'block';
            empty.textContent = err.message || 'Book unavailable';
        }
    }
}

function bindPaperBook() {
    document.getElementById('btn-pnl-refresh')?.addEventListener('click', () => loadPaperPnl());
    document.getElementById('btn-book-reload')?.addEventListener('click', () => loadPaperBook());
    document.getElementById('btn-alpaca-sync')?.addEventListener('click', async () => {
        const msg = document.getElementById('alpaca-sync-msg');
        if (msg) msg.textContent = 'POST /api/alpaca/sync…';
        try {
            const data = await apiFetch(`${API}/alpaca/sync`, { method: 'POST' });
            if (msg) {
                msg.textContent = data.ok
                    ? `Alpaca paper — not live P&L. Imported ${data.imported || 0} ${data.source || 'alpaca_paper'} lines.`
                    : (data.reason || data.note || 'Alpaca paper unavailable');
            }
            await loadPaperBook();
            await loadPaperPnl();
        } catch (err) {
            if (msg) msg.textContent = err.message || 'Alpaca paper sync failed';
        }
    });
    document.getElementById('btn-book-import')?.addEventListener('click', async () => {
        const csv = document.getElementById('book-csv')?.value || '';
        const replace = !!document.getElementById('book-replace')?.checked;
        const msg = document.getElementById('book-import-msg');
        try {
            const data = await apiFetch(`${API}/book/import`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ csv, replace }),
            });
            if (msg) msg.textContent = data.error || `Imported ${data.imported || 0} lines.`;
            await loadPaperBook();
            await loadPaperPnl();
        } catch (err) {
            if (msg) msg.textContent = err.message || 'Import failed';
        }
    });
    document.getElementById('book-add-form')?.addEventListener('submit', async ev => {
        ev.preventDefault();
        const symbol = document.getElementById('book-add-symbol')?.value || '';
        const qty = document.getElementById('book-add-qty')?.value;
        const side = document.getElementById('book-add-side')?.value || 'long';
        const avg = document.getElementById('book-add-cost')?.value;
        await apiFetch(`${API}/book/positions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                symbol,
                qty: qty === '' ? null : Number(qty),
                side,
                avg_cost: avg === '' ? null : Number(avg),
            }),
        });
        document.getElementById('book-add-symbol').value = '';
        await loadPaperBook();
        await loadPaperPnl();
    });
    const nameEl = document.getElementById('pnl-desk-name');
    nameEl?.addEventListener('change', async () => {
        await apiFetch(`${API}/book/meta`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ desk_name: nameEl.value }),
        });
    });
}

document.addEventListener('DOMContentLoaded', bindPaperBook);
