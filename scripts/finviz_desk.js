/* Finviz public HTML — parse-only. Empty when blocked. No invented rows. */
/* global API, apiFetch, selectSymbol, writeDeskPrefs */

async function loadFinvizSettings() {
    const enabled = document.getElementById('finviz-enabled');
    const ttl = document.getElementById('finviz-ttl');
    try {
        const data = await apiFetch(`${API}/finviz/settings`);
        if (enabled) enabled.checked = data.enabled !== false;
        if (ttl) ttl.value = String(data.ttl_sec || 3600);
    } catch {
        /* keep defaults */
    }
}

async function saveFinvizSettings() {
    const enabled = document.getElementById('finviz-enabled');
    const ttl = document.getElementById('finviz-ttl');
    try {
        await apiFetch(`${API}/finviz/settings`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                enabled: enabled ? enabled.checked : true,
                ttl_sec: ttl ? Number(ttl.value) || 3600 : 3600,
            }),
        });
    } catch (err) {
        if (typeof toast === 'function') toast(err.message || 'Finviz settings failed');
    }
}

async function loadFinvizPresets() {
    const sel = document.getElementById('finviz-preset');
    if (!sel || sel.options.length > 1) return;
    try {
        const data = await apiFetch(`${API}/finviz/presets`);
        const presets = data.presets || [];
        const current = sel.value || data.default || 'qulla_momentum';
        sel.innerHTML = '';
        presets.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = p.label || p.id;
            sel.appendChild(opt);
        });
        if ([...sel.options].some(o => o.value === current)) sel.value = current;
    } catch {
        /* named fallback already in HTML */
    }
}

function _finvizQuoteHtml(q) {
    if (!q || !q.ready) {
        return `<p class="macro-blurb">${(q && q.reason) || 'No Finviz quote — empty, not invented.'}</p>`;
    }
    const s = q.snapshot || {};
    const rows = [
        ['Name', q.name || ''],
        ['Sector', q.sector || s.sector || ''],
        ['Industry', q.industry || s.industry || ''],
        ['Mkt cap', s.market_cap || ''],
        ['P/E', s.pe || ''],
        ['EPS', s.eps_ttm || ''],
        ['Target', s.target_price || ''],
        ['RSI', s.rsi_14 || ''],
        ['Perf W/M/YTD', [s.perf_week, s.perf_month, s.perf_ytd].filter(Boolean).join(' · ')],
        ['Short float', s.short_float || ''],
    ].filter(([, v]) => v);
    const news = (q.news || []).slice(0, 6).map(n => {
        const title = n.title || '';
        const url = n.url || '#';
        return `<li><a href="${url}" target="_blank" rel="noopener">${title}</a></li>`;
    }).join('');
    return `
        <dl class="finviz-quote-dl">
            ${rows.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join('')}
        </dl>
        ${news ? `<ul class="finviz-news">${news}</ul>` : ''}
        <p class="macro-blurb">Parsed Finviz HTML. Missing fields stay blank.</p>`;
}

async function loadFinvizQuote(symbol) {
    const box = document.getElementById('finviz-quote-panel');
    if (!box || !symbol) return;
    box.innerHTML = '<p class="macro-blurb">GET /api/finviz/quote…</p>';
    try {
        const q = await apiFetch(`${API}/finviz/quote/${encodeURIComponent(symbol)}`);
        box.innerHTML = _finvizQuoteHtml(q);
    } catch (err) {
        box.innerHTML = `<p class="macro-blurb">${err.message || 'Finviz quote unavailable'}</p>`;
    }
}

async function loadFinvizScreener(opts = {}) {
    const tbody = document.getElementById('finviz-screener-tbody');
    const empty = document.getElementById('finviz-screener-empty');
    const meta = document.getElementById('finviz-screener-meta');
    const note = document.getElementById('finviz-screener-note');
    const sel = document.getElementById('finviz-preset');
    if (!tbody) return;
    const preset = (opts.preset || (sel && sel.value) || 'qulla_momentum');
    if (sel) sel.value = preset;
    if (typeof writeDeskPrefs === 'function') writeDeskPrefs({ finvizPreset: preset });
    if (meta) meta.textContent = opts.force ? 'POST /api/finviz/screener/refresh…' : 'GET /api/finviz/screener…';
    try {
        const data = opts.force
            ? await apiFetch(`${API}/finviz/screener/refresh`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ preset }),
            })
            : await apiFetch(`${API}/finviz/screener?preset=${encodeURIComponent(preset)}`);
        const rows = Array.isArray(data.rows) ? data.rows : [];
        tbody.innerHTML = '';
        rows.forEach(row => {
            const tr = document.createElement('tr');
            tr.dataset.symbol = row.symbol || '';
            tr.innerHTML = `
                <td class="macro-sym">${row.symbol || ''}</td>
                <td>${row.company || ''}</td>
                <td>${row.sector || ''}</td>
                <td>${row.industry || ''}</td>
                <td>${row.market_cap || ''}</td>
                <td>${row.pe || ''}</td>
                <td>${row.price || ''}</td>
                <td>${row.change || ''}</td>`;
            tr.addEventListener('click', () => {
                if (row.symbol && typeof selectSymbol === 'function') selectSymbol(row.symbol);
                loadFinvizQuote(row.symbol);
            });
            tbody.appendChild(tr);
        });
        if (empty) {
            empty.style.display = rows.length ? 'none' : 'block';
            const p = empty.querySelector('p');
            if (p && !rows.length) p.textContent = data.reason || 'No Finviz rows. Empty is a block or empty screen — not invented tickers.';
        }
        if (meta) meta.textContent = `${data.count || 0} rows · ${data.from_cache ? 'cache' : 'live'} · HTTP ${data.http_status ?? '—'}`;
        if (note) {
            const docs = data.filter_docs || {};
            const codes = (data.filters || []).map(c => `${c} (${docs[c] || ''})`).join(', ');
            note.textContent = `${data.blurb || ''} ${data.reason || ''} Filters: ${codes}`.trim();
        }
    } catch (err) {
        if (meta) meta.textContent = 'error';
        if (empty) {
            empty.style.display = 'block';
            const p = empty.querySelector('p');
            if (p) p.textContent = err.message || 'Finviz screener unavailable';
        }
    }
}

function bindFinvizDesk() {
    loadFinvizSettings();
    loadFinvizPresets();
    document.getElementById('finviz-enabled')?.addEventListener('change', saveFinvizSettings);
    document.getElementById('finviz-ttl')?.addEventListener('change', saveFinvizSettings);
    document.getElementById('btn-finviz-screener')?.addEventListener('click', () => loadFinvizScreener());
    document.getElementById('btn-finviz-refresh')?.addEventListener('click', () => loadFinvizScreener({ force: true }));
    document.getElementById('finviz-preset')?.addEventListener('change', () => loadFinvizScreener());
}

window.loadFinvizScreener = loadFinvizScreener;
window.loadFinvizQuote = loadFinvizQuote;
window.bindFinvizDesk = bindFinvizDesk;
window.loadFinvizSettings = loadFinvizSettings;
