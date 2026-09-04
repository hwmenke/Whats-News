/**
 * Macro / Edges desk — shared with the iPhone client.
 * Uses /api/macro/board, /api/edges/board, /api/sleeves, /api/universe/core50.
 * Cards light up only when stored Yahoo bars exist. No invented PX / z / win rates.
 */
/* global API, apiFetch, loadSymbols, selectSymbol, toast */

let _macroBoard = null;
let _edgesBoard = null;
let _macroBusy = false;

function _esc(s) {
    return String(s ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/"/g, '&quot;');
}

function _pct(v, digits = 1) {
    if (v == null || !Number.isFinite(Number(v))) return '—';
    const n = Number(v);
    return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

function _num(v, digits = 2) {
    if (v == null || !Number.isFinite(Number(v))) return '—';
    return Number(v).toFixed(digits);
}

function _chgClass(v) {
    if (v == null || !Number.isFinite(Number(v))) return '';
    return Number(v) >= 0 ? 'positive' : 'negative';
}

async function initMacroDesk() {
    await Promise.all([loadMacroBoard(), loadEdgesBoard(), loadFractalNote()]);
    renderMacroSeedBar();
}

async function loadMacroBoard() {
    const grid = document.getElementById('macro-sleeve-grid');
    const loading = document.getElementById('macro-loading');
    if (loading) loading.style.display = 'flex';
    try {
        _macroBoard = await apiFetch(`${API}/macro/board`);
        renderDeskRegime(_macroBoard.regime);
        renderSleeveGrid(_macroBoard.sleeves || []);
        const note = document.getElementById('macro-board-note');
        if (note) note.textContent = _macroBoard.note || '';
    } catch (err) {
        if (grid) {
            grid.innerHTML = `<div class="macro-empty">Macro board unavailable: ${_esc(err.message)}</div>`;
        }
    } finally {
        if (loading) loading.style.display = 'none';
    }
}

async function loadEdgesBoard() {
    const wrap = document.getElementById('edges-board');
    if (!wrap) return;
    try {
        _edgesBoard = await apiFetch(`${API}/edges/board`);
        renderEdgesBoard(_edgesBoard);
    } catch (err) {
        wrap.innerHTML = `<div class="macro-empty">Edges unavailable: ${_esc(err.message)}</div>`;
    }
}

async function loadFractalNote() {
    const el = document.getElementById('fractal-stub');
    if (!el) return;
    try {
        const data = await apiFetch(`${API}/fractal/status`);
        el.textContent = data.available
            ? 'Fractal D is available.'
            : (data.reason || 'Fractal: needs local odds-edge');
    } catch {
        el.textContent = 'Fractal: needs local odds-edge';
    }
}

function renderDeskRegime(regime) {
    const el = document.getElementById('desk-regime');
    const banner = document.getElementById('macro-regime');
    if (!regime || !regime.ready) {
        if (el) {
            el.style.display = 'none';
            el.textContent = '';
        }
        if (banner) {
            banner.className = 'macro-regime is-missing';
            banner.innerHTML = `
                <strong>Regime</strong>
                <span>${_esc(regime && regime.note ? regime.note : 'No stored ^VIX/VIX — line omitted.')}</span>
                <button type="button" class="btn btn-ghost btn-sm" id="btn-fetch-vix">Fetch ^VIX</button>`;
            banner.querySelector('#btn-fetch-vix')?.addEventListener('click', fetchVixForRegime);
        }
        return;
    }
    const label = `${regime.label} · VIX ${regime.vix}` +
        (regime.percentile_1y != null ? ` (${regime.percentile_1y}th %ile 1y)` : '');
    if (el) {
        el.style.display = '';
        el.textContent = label;
        el.className = `desk-regime regime-${String(regime.label || '').toLowerCase()}`;
        el.title = regime.note || 'From stored Yahoo VIX bars';
    }
    if (banner) {
        banner.className = `macro-regime regime-${String(regime.label || '').toLowerCase()}`;
        banner.innerHTML = `<strong>${_esc(regime.label)}</strong><span>VIX ${_esc(regime.vix)} · stored Yahoo bars only</span>`;
    }
}

async function fetchVixForRegime() {
    try {
        await apiFetch(`${API}/symbols`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: '^VIX' }),
        });
        await apiFetch(`${API}/fetch/${encodeURIComponent('^VIX')}`, { method: 'POST' });
        if (typeof loadSymbols === 'function') await loadSymbols();
        await loadMacroBoard();
    } catch (err) {
        if (typeof toast === 'function') toast(err.message || 'VIX fetch failed', 'error');
    }
}

function renderMacroSeedBar() {
    const bar = document.getElementById('macro-seed-bar');
    if (!bar) return;
    const sleeves = (_macroBoard && _macroBoard.sleeves) || [];
    bar.innerHTML = '';
    const coreBtn = document.createElement('button');
    coreBtn.type = 'button';
    coreBtn.className = 'btn btn-primary btn-sm';
    coreBtn.textContent = 'Seed Core 50';
    coreBtn.title = 'Add ~50 liquid names to the desk. Does not download Yahoo.';
    coreBtn.addEventListener('click', seedCore50);
    bar.appendChild(coreBtn);

    sleeves.forEach(sleeve => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-ghost btn-sm';
        btn.textContent = `${sleeve.label} · ${sleeve.ready_count || 0}/${(sleeve.tickers || []).length}`;
        btn.title = sleeve.blurb || sleeve.label;
        btn.addEventListener('click', () => seedAndFetchSleeve(sleeve.id));
        bar.appendChild(btn);
    });
}

function renderSleeveGrid(sleeves) {
    const grid = document.getElementById('macro-sleeve-grid');
    if (!grid) return;
    if (!sleeves.length) {
        grid.innerHTML = '<div class="macro-empty">No sleeves. Restart the Python app so /api/sleeves is live.</div>';
        return;
    }
    grid.innerHTML = '';
    sleeves.forEach(sleeve => {
        const card = document.createElement('section');
        card.className = 'macro-sleeve-card';
        const rows = (sleeve.rows || []).map(row => {
            if (!row.ready) {
                return `<tr class="is-dark"><td>${_esc(row.symbol)}</td><td colspan="4" class="dim">no bars</td></tr>`;
            }
            const zCls = row.extreme ? 'z-extreme' : '';
            return `<tr class="${row.extreme ? 'is-extreme' : ''}" data-symbol="${_esc(row.symbol)}">
                <td class="macro-sym">${_esc(row.symbol)}</td>
                <td>${_num(row.px)}</td>
                <td class="${_chgClass(row.day_pct)}">${_pct(row.day_pct)}</td>
                <td class="${zCls}">${_num(row.z30)}</td>
                <td class="${zCls}">${_num(row.z14)}</td>
            </tr>`;
        }).join('');
        const skip = sleeve.skipped
            ? `<p class="macro-skipped">${_esc(sleeve.skipped)}</p>`
            : '';
        card.innerHTML = `
            <header>
                <strong>${_esc(sleeve.label)}</strong>
                <span class="macro-lit">${sleeve.ready_count || 0}/${(sleeve.tickers || []).length} lit</span>
                <button type="button" class="btn btn-ghost btn-sm" data-seed="${_esc(sleeve.id)}">Seed + fetch</button>
            </header>
            <p class="macro-blurb">${_esc(sleeve.blurb || '')}</p>
            ${skip}
            <table class="macro-mini">
                <thead><tr><th></th><th>PX</th><th>Day</th><th>Z30</th><th>Z14</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
        card.querySelector('[data-seed]')?.addEventListener('click', () => seedAndFetchSleeve(sleeve.id));
        card.querySelectorAll('tr[data-symbol]').forEach(tr => {
            tr.addEventListener('click', () => {
                if (typeof selectSymbol === 'function') selectSymbol(tr.dataset.symbol);
            });
        });
        grid.appendChild(card);
    });
}

function renderEdgesBoard(board) {
    const wrap = document.getElementById('edges-board');
    if (!wrap) return;
    const online = (board.online || []).map(t => `<span class="setup-tag">${_esc(t)}</span>`).join('')
        || '<span class="dim">No live tags — fetch sleeve bars first.</span>';
    const sections = (board.sections || []).map(sec => {
        const body = (sec.rows || []).map(row => {
            if (!row.ready) {
                return `<tr class="is-dark"><td>${_esc(row.symbol)}</td><td colspan="7" class="dim">no bars</td></tr>`;
            }
            const tags = (row.tags || []).map(t => `<span class="setup-tag">${_esc(t)}</span>`).join('') || '—';
            return `<tr data-symbol="${_esc(row.symbol)}">
                <td class="macro-sym">${_esc(row.symbol)}</td>
                <td>${_num(row.d_rsi14, 1)}</td>
                <td>${_num(row.w_rsi14, 1)}</td>
                <td class="${_chgClass(row.vs50d)}">${_pct(row.vs50d)}</td>
                <td class="${_chgClass(row.vs200d)}">${_pct(row.vs200d)}</td>
                <td>${_esc(row.slope200 || '—')}</td>
                <td>${_esc(row.regime || '—')}</td>
                <td class="setup-tags">${tags}</td>
            </tr>`;
        }).join('');
        return `<section class="edges-section">
            <h3>${_esc(sec.label)}</h3>
            <table class="scanner-table edges-table">
                <thead><tr>
                    <th>Name</th><th>dRSI14</th><th>wRSI14</th>
                    <th>vs 50d</th><th>vs 200d</th><th>200d</th><th>Regime</th><th>Live tags</th>
                </tr></thead>
                <tbody>${body}</tbody>
            </table>
        </section>`;
    }).join('');

    const buckets = board.setup_buckets || {};
    const bucketHtml = Object.entries(buckets).map(([id, names]) => {
        const chips = (names || []).map(s =>
            `<button type="button" class="macro-chip" data-open="${_esc(s)}">${_esc(s)}</button>`
        ).join('') || '<span class="dim">none</span>';
        return `<div class="edges-bucket"><strong>${_esc(id)}</strong><div>${chips}</div></div>`;
    }).join('');

    wrap.innerHTML = `
        <div class="edges-online">
            <strong>Edges online</strong>
            <div>${online}</div>
            <p class="macro-blurb">${_esc(board.note || '')}</p>
        </div>
        ${sections}
        <div class="edges-buckets">
            <h3>Stock-level setups (desk)</h3>
            ${bucketHtml}
        </div>`;
    wrap.querySelectorAll('[data-symbol], [data-open]').forEach(el => {
        el.addEventListener('click', () => {
            const sym = el.dataset.symbol || el.dataset.open;
            if (sym && typeof selectSymbol === 'function') selectSymbol(sym);
        });
    });
}

async function seedAndFetchSleeve(id) {
    if (_macroBusy) return;
    _macroBusy = true;
    try {
        await apiFetch(`${API}/sleeves/${encodeURIComponent(id)}/seed`, { method: 'POST' });
        if (typeof loadSymbols === 'function') await loadSymbols();
        const spec = ((_macroBoard && _macroBoard.sleeves) || []).find(s => s.id === id);
        const tickers = (spec && spec.tickers) || [];
        for (const t of tickers) {
            try {
                await apiFetch(`${API}/fetch/${encodeURIComponent(t)}`, { method: 'POST' });
            } catch (err) {
                if (err.status === 429 || err.code === 'yahoo_throttle') {
                    if (typeof toast === 'function') {
                        toast(err.message || 'Yahoo is rate-limiting. Try again in a minute.', 'warning');
                    }
                    break;
                }
            }
            await loadMacroBoard();
            renderMacroSeedBar();
        }
        await loadEdgesBoard();
        if (typeof loadSymbols === 'function') await loadSymbols();
    } catch (err) {
        if (typeof toast === 'function') toast(err.message || 'Sleeve seed failed', 'error');
    } finally {
        _macroBusy = false;
    }
}

async function seedCore50() {
    if (_macroBusy) return;
    _macroBusy = true;
    try {
        const data = await apiFetch(`${API}/universe/core50`, { method: 'POST' });
        if (typeof toast === 'function') {
            toast(`Core 50 on desk (${data.count || 0} names). Fetch Yahoo per name.`, 'info');
        }
        if (typeof loadSymbols === 'function') await loadSymbols();
        await loadMacroBoard();
        renderMacroSeedBar();
    } catch (err) {
        if (typeof toast === 'function') toast(err.message || 'Core 50 failed', 'error');
    } finally {
        _macroBusy = false;
    }
}

window.initMacroDesk = initMacroDesk;
window.loadMacroBoard = loadMacroBoard;
window.seedCore50 = seedCore50;
window.seedAndFetchSleeve = seedAndFetchSleeve;
window.renderDeskRegime = renderDeskRegime;
