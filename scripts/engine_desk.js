/* Equity ENGINE desk — Setup / Pattern / RSI-C / Stretch / Sigma. Yahoo/SQLite only. */
/* global API, apiFetch, selectSymbol, switchTab, writeDeskPrefs, readDeskPrefs */

function _engEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
}

function _engNum(v, digits) {
    if (v == null || Number.isNaN(Number(v))) return '—';
    return Number(v).toFixed(digits == null ? 1 : digits);
}

function _engTone(v) {
    if (v == null || Number.isNaN(Number(v))) return '';
    if (Number(v) > 0) return 'is-up';
    if (Number(v) < 0) return 'is-down';
    return '';
}

function _engHeat(v, lo, hi) {
    if (window.BoardRegistry) {
        return window.BoardRegistry.heatStyle(v, { heat: 'range', heat_scale: { lo, hi } });
    }
    if (v == null || Number.isNaN(Number(v))) return '';
    const n = Number(v);
    const t = Math.max(0, Math.min(1, (n - lo) / (hi - lo || 1)));
    if (t >= 0.5) {
        const g = (t - 0.5) * 2;
        return `background: rgba(34,197,94,${(0.06 + 0.32 * g).toFixed(2)})`;
    }
    const r = (0.5 - t) * 2;
    return `background: rgba(239,68,68,${(0.06 + 0.32 * r).toFixed(2)})`;
}

async function _engCols(boardId, fallback) {
    if (window.BoardRegistry) {
        try {
            const reg = await window.BoardRegistry.load();
            const cols = window.BoardRegistry.visibleColumns(boardId, reg);
            if (cols && cols.length) return cols;
        } catch (_) { /* payload / hardcoded fallback */ }
    }
    return fallback || [];
}

function hideEngineArea() {
    const el = document.getElementById('engine-area');
    if (el) el.style.display = 'none';
}

function showEngineArea() {
    hideEngineArea();
    const el = document.getElementById('engine-area');
    if (el) el.style.display = 'flex';
}

function applyDeskIa(id) {
    const next = id || 'command';
    if (typeof writeDeskPrefs === 'function') writeDeskPrefs({ deskIa: next });
    document.querySelectorAll('#desk-ia-bar .desk-ia-btn').forEach(btn => {
        btn.classList.toggle('on', btn.dataset.ia === next);
    });
    if (next === 'moves') {
        if (typeof switchTab === 'function') switchTab('moves');
        return;
    }
    if (next === 'macro') {
        if (typeof switchTab === 'function') switchTab('macro');
        return;
    }
    if (next === 'book') {
        if (typeof switchTab === 'function') switchTab('pnl');
        return;
    }
    if (next === 'chart') {
        if (typeof switchTab === 'function') switchTab('charts');
        return;
    }
    if (next === 'news') {
        if (typeof switchTab === 'function') switchTab('news');
        return;
    }
    if (typeof switchTab === 'function') switchTab('engine', { ia: next });
    else applyEnginePanel(next);
}

function applyEnginePanel(id) {
    const next = id || 'command';
    document.querySelectorAll('#engine-ia-bar .desk-ia-btn').forEach(btn => {
        btn.classList.toggle('on', btn.dataset.ia === next);
    });
    document.querySelectorAll('#desk-ia-bar .desk-ia-btn').forEach(btn => {
        if (['command', 'setup', 'pattern', 'rsic', 'sigma', 'stretch', 'maps'].includes(btn.dataset.ia)) {
            btn.classList.toggle('on', btn.dataset.ia === next);
        }
    });
    document.querySelectorAll('#engine-area .engine-panel').forEach(panel => {
        panel.style.display = panel.dataset.panel === next ? '' : 'none';
    });
    if (next === 'command') {
        loadEngineCommand();
        loadEngineBoard();
    }
    if (next === 'setup') loadEngineSetupGlance();
    if (next === 'pattern') loadEnginePatterns();
    if (next === 'rsic') loadEngineRsiC();
    if (next === 'stretch') loadEngineStretch();
    if (next === 'sigma') loadEngineSigma();
    if (next === 'maps') loadEngineMaps();
}

function _engEmpty(el, msg) {
    if (!el) return;
    el.innerHTML = `<p class="scanner-empty">${_engEsc(msg || 'Empty — no stored daily bars.')}</p>`;
}

async function loadEngineCommand() {
    const el = document.getElementById('engine-command-body');
    const meta = document.getElementById('engine-command-meta');
    if (!el) return;
    if (meta) meta.textContent = 'GET /api/engine/command…';
    try {
        const data = await apiFetch(`${API}/engine/command?desk=1`);
        if (meta) meta.textContent = data.ready ? `${data.n || 0} names` : (data.message || 'empty');
        if (!data.ready) {
            _engEmpty(el, data.message);
            return;
        }
        const counts = data.engine_counts || {};
        const pats = data.pattern_counts || {};
        const daily = pats.daily || {};
        const weekly = pats.weekly || {};
        const list = (arr) => (arr || []).length
            ? (arr || []).map(s => `<button type="button" class="macro-chip" data-sym="${_engEsc(s)}">${_engEsc(s)}</button>`).join('')
            : '<span class="engine-dim">none</span>';
        el.innerHTML = `
            <div class="engine-count-row">
                <div class="engine-count"><span>OPPORTUNITY</span><strong>${counts.OPPORTUNITY || 0}</strong></div>
                <div class="engine-count"><span>WATCH</span><strong>${counts.WATCH || 0}</strong></div>
                <div class="engine-count"><span>NO TRADE</span><strong>${counts['NO TRADE'] || 0}</strong></div>
            </div>
            <p class="macro-blurb">${_engEsc(data.note || '')}</p>
            <h3>Opportunity</h3>
            <div class="engine-chip-row">${list(data.opportunity)}</div>
            <h3>Pullback-in-uptrend (Daily OS + Weekly TREND↑)</h3>
            <div class="engine-chip-row">${list(data.pullbacks)}</div>
            <h3>Pattern counts</h3>
            <p class="engine-dim">Daily 3M/1M — Breakout ${daily.Breakout || 0} · Breakdown ${daily.Breakdown || 0} · From Bottom ${daily['From Bottom'] || 0} · From Top ${daily['From Top'] || 0}</p>
            <p class="engine-dim">Weekly 1Y/6M — Breakout ${weekly.Breakout || 0} · Breakdown ${weekly.Breakdown || 0} · From Bottom ${weekly['From Bottom'] || 0} · From Top ${weekly['From Top'] || 0}</p>
            <details class="engine-howto"><summary>HOW TO READ — ENGINE state machine</summary>
                <p>${_engEsc((data.formulas && data.formulas.engine) || '')}</p>
                <p>${_engEsc((data.formulas && data.formulas.vcp) || '')}</p>
                <p>${_engEsc((data.formulas && data.formulas.rsi_c) || '')}</p>
            </details>`;
        el.querySelectorAll('[data-sym]').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.dataset.sym && typeof selectSymbol === 'function') selectSymbol(btn.dataset.sym);
            });
        });
        _engPaintTakeaway((data.opportunity || [])[0], data);
        _engPaintCommandScatter();
        const hero = document.getElementById('engine-hero-metric');
        if (hero) {
            const rows = window._engineBoardRows || [];
            const coiled = rows.filter(r => String(r.vcp || '').toUpperCase().includes('COIL')).length;
            const dw = rows.filter(r => r.dw).length;
            hero.textContent = rows.length
                ? `${coiled} names coiled · ${dw} with D+W agree`
                : `${(data.opportunity || []).length} OPPORTUNITY · ${(data.pullbacks || []).length} pullback notes`;
        }
    } catch (err) {
        _engEmpty(el, err.message || 'ENGINE command unavailable');
        if (meta) meta.textContent = 'error';
    }
}

function _engChip(text, kind) {
    if (!text) return '<span class="v2-chip is-gray">—</span>';
    return `<span class="v2-chip ${kind || 'is-gray'}">${_engEsc(text)}</span>`;
}

function _engPaintTakeaway(symbol, data) {
    const card = document.getElementById('engine-takeaway-card');
    if (!card) return;
    const rows = (window._engineBoardRows || []);
    const sym = symbol || (rows[0] && rows[0].symbol);
    const row = rows.find(r => r.symbol === sym);
    if (!row) {
        card.innerHTML = `<p class="v2-card-kicker">TAKEAWAY</p>
            <p class="engine-dim">No live ENGINE row yet. Fetch Yahoo. Comp AAA cards are not data.</p>`;
        return;
    }
    const prim = row.engine_primary || '';
    const cls = prim === 'OPPORTUNITY' ? 'is-opp' : prim === 'WATCH' ? 'is-watch' : 'is-no';
    card.innerHTML = `
        <p class="v2-card-kicker">TAKEAWAY</p>
        <h3 class="engine-story" style="font-size:20px;margin:0 0 8px">${_engEsc(row.symbol)} — research, not a trade</h3>
        <div class="engine-chip-row">
            ${_engChip(prim || 'NO TRADE', cls)}
            ${row.dw ? _engChip(row.dw, 'is-dw') : ''}
            ${_engChip(row.gray_tag || 'RSI-C · VCP', 'is-gray')}
        </div>
        <p>${_engEsc(row.takeaway || '—')}</p>
        <p class="v2-howto">iPhone: this card becomes a sheet on tap. Bias ${row.bias == null ? '—' : _engNum(row.bias)} is a point sum, not a win rate.</p>`;
}

async function _engPaintCommandScatter() {
    const el = document.getElementById('engine-command-scatter');
    if (!el) return;
    try {
        if (window.BoardRegistry && window.BoardRegistry.load) await window.BoardRegistry.load();
        const data = window._engineMaps || await apiFetch(`${API}/engine/maps?desk=1`);
        window._engineMaps = data;
        const pts = ((data.scanner || {}).scatter || []);
        el.innerHTML = `
            <p class="v2-card-kicker">RSI vs. volatility</p>
            <h3>RSI vs. volatility — where names sit</h3>
            <p class="engine-story-sub">Horizontal: RSI posture · Vertical: σ. Soft blue / coral diverging tint.</p>
            ${_engScatter(pts, { xLabel: 'RSI posture', yLabel: 'σ', empty: 'Empty plot — no stored scored points. Never invent dots.' })}
            <p class="v2-howto">How to read: upper-left leans constructive; lower-right is stretched. Points only from stored bars.</p>`;
        el.querySelectorAll('.engine-dot').forEach(node => {
            node.addEventListener('click', () => {
                if (node.dataset.sym && typeof selectSymbol === 'function') selectSymbol(node.dataset.sym);
            });
        });
    } catch (err) {
        el.innerHTML = `<p class="v2-card-kicker">RSI vs. volatility</p><p class="scanner-empty">${_engEsc(err.message || 'Maps unavailable')}</p>`;
    }
}

async function loadEngineSetupGlance() {
    const strEl = document.getElementById('engine-setup-str');
    const stEl = document.getElementById('engine-setup-stretch');
    const patEl = document.getElementById('engine-setup-pattern');
    const meta = document.getElementById('engine-board-meta');
    if (!strEl || !stEl || !patEl) {
        loadEngineBoard();
        return;
    }
    if (meta) meta.textContent = 'GET /api/engine/stretch + /patterns…';
    try {
        const [stretch, patterns] = await Promise.all([
            apiFetch(`${API}/engine/stretch?desk=1`),
            apiFetch(`${API}/engine/patterns?desk=1`),
        ]);
        const strRows = [...(stretch.strongest || []), ...(stretch.breakdowns || [])].slice(0, 8);
        strEl.innerHTML = strRows.length ? strRows.map(it => {
            const n = Number(it.str);
            const w = Math.min(50, Math.abs(n) * 10);
            const side = n >= 0 ? 'is-up' : 'is-dn';
            return `<div class="v2-str-row">
                <button type="button" class="engine-name" data-sym="${_engEsc(it.symbol)}">${_engEsc(it.symbol)}</button>
                <span class="v2-big" style="font-size:20px">${it.str == null ? '—' : (n > 0 ? '+' : '') + it.str}</span>
                <span class="v2-bar"><i class="${side}" style="width:${w}%"></i></span>
            </div>`;
        }).join('') : '<p class="engine-dim">Empty — need ≥56 daily bars for Str.</p>';
        const stretchRows = [...(stretch.compressed || []), ...(stretch.stretched || [])].slice(0, 8);
        stEl.innerHTML = stretchRows.length ? stretchRows.map((it, i) => {
            const pct = it.stretch_pctile != null ? it.stretch_pctile : it.stretch_pct;
            const label = pct == null ? 'MID' : (Number(pct) <= 25 ? 'COMPRESS' : Number(pct) >= 75 ? 'STRETCH' : 'MID');
            const kind = label === 'COMPRESS' ? 'is-coil' : label === 'STRETCH' ? 'is-break' : 'is-gray';
            return `<div class="v2-stretch-row${i === 0 ? ' is-mint' : ''}">
                <button type="button" class="engine-name" data-sym="${_engEsc(it.symbol)}">${_engEsc(it.symbol)}</button>
                <span class="v2-big" style="font-size:20px">${pct == null ? '—' : _engNum(pct, 0) + '%'}</span>
                ${_engChip(label, kind)}
            </div>`;
        }).join('') : '<p class="engine-dim">Empty stretch — ADMA percentile needs n≥3.</p>';
        const dc = (patterns.daily || {}).counts || {};
        const wc = (patterns.weekly || {}).counts || {};
        const cell = (v, lab) => `<div class="v2-pat-cell"><strong>${v == null ? '—' : v}</strong><span>${lab}</span></div>`;
        patEl.innerHTML = `
            <p class="engine-dim">Breakouts</p>
            <div class="v2-pat-grid">${cell(dc.Breakout || 0, '3M')}${cell(null, '1M')}${cell(wc.Breakout || 0, '1Y')}${cell(null, '6M')}</div>
            <p class="engine-dim">Breakdowns</p>
            <div class="v2-pat-grid">${cell(dc.Breakdown || 0, '3M')}${cell(null, '1M')}${cell(wc.Breakdown || 0, '1Y')}${cell(null, '6M')}</div>
            <p class="engine-dim">From Bottom</p>
            <div class="v2-pat-grid">${cell(null, '3M')}${cell(dc['From Bottom'] || 0, '1M')}${cell(null, '1Y')}${cell(wc['From Bottom'] || 0, '6M')}</div>
            <p class="engine-dim">From Top</p>
            <div class="v2-pat-grid">${cell(null, '3M')}${cell(dc['From Top'] || 0, '1M')}${cell(null, '1Y')}${cell(wc['From Top'] || 0, '6M')}</div>`;
        if (meta) meta.textContent = stretch.ready || patterns.ready ? 'setup glance' : (stretch.message || patterns.message || 'empty');
        document.querySelectorAll('#engine-setup-str [data-sym], #engine-setup-stretch [data-sym]').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.dataset.sym && typeof selectSymbol === 'function') selectSymbol(btn.dataset.sym);
            });
        });
    } catch (err) {
        strEl.innerHTML = `<p class="scanner-empty">${_engEsc(err.message || 'Setup glance unavailable')}</p>`;
        if (meta) meta.textContent = 'error';
    }
}

function _engRowClick(tbody) {
    if (!tbody) return;
    tbody.querySelectorAll('tr[data-symbol]').forEach(tr => {
        tr.addEventListener('click', () => {
            if (tr.dataset.symbol && typeof selectSymbol === 'function') selectSymbol(tr.dataset.symbol);
        });
    });
}

async function loadEngineBoard() {
    const tbody = document.getElementById('engine-board-tbody');
    const empty = document.getElementById('engine-board-empty');
    const meta = document.getElementById('engine-board-meta');
    if (!tbody) return;
    if (meta) meta.textContent = 'GET /api/engine/board…';
    try {
        const data = await apiFetch(`${API}/engine/board?desk=1`);
        const rows = Array.isArray(data.rows) ? data.rows : [];
        window._engineBoardRows = rows;
        const cols = await _engCols('engine_setup', data.columns);
        const thead = document.querySelector('#engine-board-table thead');
        if (thead && window.BoardRegistry && cols.length) {
            thead.innerHTML = window.BoardRegistry.headerHtml(cols);
        }
        tbody.innerHTML = '';
        rows.forEach(row => {
            const tr = document.createElement('tr');
            tr.dataset.symbol = row.symbol || '';
            if (window.BoardRegistry && cols.length) {
                tr.innerHTML = cols.map(c => window.BoardRegistry.cellHtml(row, c)).join('');
            } else {
                const sent = row.sentiment || '';
                const takeCls = sent.includes('LONG') ? 'is-long' : sent.includes('SHORT') ? 'is-short' : 'is-neutral';
                tr.innerHTML = `
                <td class="macro-sym">${_engEsc(row.symbol)}</td>
                <td>${_engEsc(row.vcp || '—')}</td>
                <td>${_engEsc(row.tms_zone || '—')}</td>
                <td>${_engEsc(row.impulse || '—')}</td>
                <td class="${row.pattern_w === 'Breakout' ? 'is-up' : row.pattern_w === 'Breakdown' ? 'is-down' : ''}">${_engEsc(row.pattern_w || '—')}</td>
                <td class="${_engTone(row.bias)}">${row.bias == null ? '—' : _engNum(row.bias)}</td>
                <td class="engine-takeaway ${takeCls}">${_engEsc(row.takeaway || '—')}</td>
                <td class="${(row.dw || '').includes('↑') ? 'is-up' : (row.dw || '').includes('↓') ? 'is-down' : ''}">${_engEsc(row.dw || '—')}</td>
                <td class="engine-state">${_engEsc(row.engine || '—')}</td>
                <td>${_engEsc((row.rsi_c && row.rsi_c.state) || '—')}</td>
                <td class="${_engTone(row.vs20)}">${row.vs20 == null ? '—' : _engNum(row.vs20)}</td>
                <td style="${_engHeat(row.dist_52w_pct, -40, 0)}">${row.dist_52w_pct == null ? '—' : _engNum(row.dist_52w_pct)}</td>
                <td class="${_engTone(row.str)}">${row.str == null ? '—' : row.str}</td>
                <td class="engine-tmac" style="${_engHeat(row.tmac_star != null ? row.tmac_star : row.heat_proxy, 0, 99)}" title="${_engEsc(row.tmac_note || 'TMAC* heat proxy — never branded TMAC')}">${(row.tmac_star != null ? row.tmac_star : row.heat_proxy) == null ? '—' : (row.tmac_star != null ? row.tmac_star : row.heat_proxy)}</td>`;
            }
            tbody.appendChild(tr);
        });
        if (empty) empty.style.display = rows.length ? 'none' : 'block';
        if (meta) meta.textContent = data.ready ? `${rows.length} rows` : (data.message || 'empty');
        _engRowClick(tbody);
        tbody.querySelectorAll('tr[data-symbol]').forEach(tr => {
            tr.addEventListener('click', () => _engPaintTakeaway(tr.dataset.symbol));
        });
        if (rows[0]) _engPaintTakeaway(rows[0].symbol);
    } catch (err) {
        tbody.innerHTML = '';
        if (empty) {
            empty.style.display = 'block';
            const p = empty.querySelector('p');
            if (p) p.textContent = err.message || 'ENGINE board unavailable';
        }
        if (meta) meta.textContent = 'error';
    }
}

function _engListCol(title, items, tone) {
    const rows = (items || []).map(it => {
        const tag = it.gray_tag || it.state || '';
        return `<li><button type="button" class="engine-name" data-sym="${_engEsc(it.symbol)}">${_engEsc(it.symbol)}</button>
            <span class="engine-gray">${_engEsc(tag)}</span></li>`;
    }).join('');
    return `<div class="engine-col ${tone || ''}">
        <h3>${_engEsc(title)} <em>${(items || []).length}</em></h3>
        <ul>${rows || '<li class="engine-dim">none</li>'}</ul>
    </div>`;
}

async function loadEnginePatterns() {
    const el = document.getElementById('engine-pattern-body');
    const meta = document.getElementById('engine-pattern-meta');
    if (!el) return;
    if (meta) meta.textContent = 'GET /api/engine/patterns…';
    try {
        const data = await apiFetch(`${API}/engine/patterns?desk=1`);
        const d = data.daily || { counts: {}, rows: {} };
        const w = data.weekly || { counts: {}, rows: {} };
        const dc = d.counts || {};
        const wc = w.counts || {};
        el.innerHTML = `
            <h3>Daily Pattern Scanner (3M / 1M)</h3>
            <div class="engine-quad">
                ${_engListCol(`Breakouts (${dc.Breakout || 0})`, (d.rows || {}).Breakout, 'is-bull')}
                ${_engListCol(`From Bottom (${dc['From Bottom'] || 0})`, (d.rows || {})['From Bottom'], 'is-bull-soft')}
                ${_engListCol(`Breakdowns (${dc.Breakdown || 0})`, (d.rows || {}).Breakdown, 'is-bear')}
                ${_engListCol(`From Top (${dc['From Top'] || 0})`, (d.rows || {})['From Top'], 'is-bear-soft')}
            </div>
            <h3>Weekly Pattern Scanner (1Y / 6M)</h3>
            <div class="engine-quad">
                ${_engListCol(`Breakouts W (${wc.Breakout || 0})`, (w.rows || {}).Breakout, 'is-bull')}
                ${_engListCol(`From Bottom W (${wc['From Bottom'] || 0})`, (w.rows || {})['From Bottom'], 'is-bull-soft')}
                ${_engListCol(`Breakdowns W (${wc.Breakdown || 0})`, (w.rows || {}).Breakdown, 'is-bear')}
                ${_engListCol(`From Top W (${wc['From Top'] || 0})`, (w.rows || {})['From Top'], 'is-bear-soft')}
            </div>
            <details class="engine-howto" open><summary>HOW TO READ — PATTERN SCANNER</summary>
                <p>${_engEsc(data.howto || '')}</p>
            </details>`;
        if (meta) meta.textContent = data.ready ? 'pattern lists' : (data.message || 'empty');
        if (!data.ready) {
            el.insertAdjacentHTML('afterbegin', `<p class="scanner-empty">${_engEsc(data.message || 'Empty pattern scanner.')}</p>`);
        }
        el.querySelectorAll('[data-sym]').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.dataset.sym && typeof selectSymbol === 'function') selectSymbol(btn.dataset.sym);
            });
        });
    } catch (err) {
        _engEmpty(el, err.message || 'Pattern scanner unavailable');
        if (meta) meta.textContent = 'error';
    }
}

function _engBucketTable(title, rows, extra) {
    const head = extra || 'Align';
    const body = (rows || []).map(r => `<tr data-symbol="${_engEsc(r.symbol)}">
        <td class="macro-sym">${_engEsc(r.symbol)}</td>
        <td>${_engEsc(r.state || '—')}</td>
        <td>${r.avg_rsi == null ? '—' : _engNum(r.avg_rsi)}</td>
        <td>${r.align == null ? '—' : _engNum(r.align, 2)}</td>
    </tr>`).join('');
    return `<div class="engine-bucket">
        <h3>${_engEsc(title)}</h3>
        <table class="scanner-table"><thead><tr><th>Asset</th><th>State</th><th>Avg RSI</th><th>${_engEsc(head)}</th></tr></thead>
        <tbody>${body || '<tr><td colspan="4">none</td></tr>'}</tbody></table>
    </div>`;
}

async function loadEngineRsiC() {
    const el = document.getElementById('engine-rsic-body');
    const meta = document.getElementById('engine-rsic-meta');
    if (!el) return;
    const lagEl = document.getElementById('engine-rsic-lag');
    const nEl = document.getElementById('engine-rsic-n');
    const n = nEl ? Number(nEl.value) || 14 : 14;
    const lag = lagEl ? Number(lagEl.value) || 5 : 5;
    if (meta) meta.textContent = `GET /api/engine/rsi-counter?n=${n}&lag=${lag}…`;
    try {
        const data = await apiFetch(`${API}/engine/rsi-counter?desk=1&n=${encodeURIComponent(n)}&lag=${encodeURIComponent(lag)}`);
        const d = data.daily || {};
        const w = data.weekly || {};
        const accel = (data.accelerating || []).map(r =>
            `<li><button type="button" class="engine-name" data-sym="${_engEsc(r.symbol)}">${_engEsc(r.symbol)}</button> <span class="is-up">${r.delta == null ? '—' : '+' + _engNum(r.delta)}</span></li>`).join('');
        const fade = (data.fading || []).map(r =>
            `<li><button type="button" class="engine-name" data-sym="${_engEsc(r.symbol)}">${_engEsc(r.symbol)}</button> <span class="is-down">${r.delta == null ? '—' : _engNum(r.delta)}</span></li>`).join('');
        const sectors = (data.sectors || []).map(r =>
            `<tr data-symbol="${_engEsc(r.symbol)}"><td class="macro-sym">${_engEsc(r.symbol)}</td><td>${r.rsi14 == null ? '—' : _engNum(r.rsi14)}</td><td class="${_engTone(r.delta)}">${r.delta == null ? '—' : _engNum(r.delta)}</td><td>${_engEsc(r.state || '—')}</td></tr>`).join('');
        const pbs = (data.pullbacks || []).map(p =>
            `<li><button type="button" class="engine-name" data-sym="${_engEsc(p.symbol)}">${_engEsc(p.symbol)}</button> <span class="engine-dim">${_engEsc(p.note || '')}</span></li>`).join('');
        el.innerHTML = `
            <div class="engine-rsic-split">
                <section>
                    <h3>Daily LEFT — RSI(2)…RSI(21)</h3>
                    <div class="engine-quad">
                        ${_engBucketTable('OVERSOLD', d.oversold)}
                        ${_engBucketTable('OVERBOUGHT', d.overbought)}
                        ${_engBucketTable('TRENDING HIGHER', d.trend_up)}
                        ${_engBucketTable('TRENDING LOWER', d.trend_dn)}
                    </div>
                </section>
                <section>
                    <h3>Weekly RIGHT — RSI(2)…RSI(21)</h3>
                    <div class="engine-quad">
                        ${_engBucketTable('OVERSOLD W', w.oversold)}
                        ${_engBucketTable('OVERBOUGHT W', w.overbought)}
                        ${_engBucketTable('TRENDING HIGHER W', w.trend_up)}
                        ${_engBucketTable('TRENDING LOWER W', w.trend_dn)}
                    </div>
                </section>
            </div>
            <div class="engine-quad">
                <div class="engine-col"><h3>Accelerating (Δ RSI14)</h3><ul>${accel || '<li class="engine-dim">none</li>'}</ul></div>
                <div class="engine-col"><h3>Fading (Δ RSI14)</h3><ul>${fade || '<li class="engine-dim">none</li>'}</ul></div>
                <div class="engine-col"><h3>Sector RSI</h3>
                    <table class="scanner-table"><thead><tr><th>ETF</th><th>RSI</th><th>Δ</th><th>State</th></tr></thead>
                    <tbody>${sectors || '<tr><td colspan="4">none — sector ETFs only if on the desk</td></tr>'}</tbody></table>
                </div>
                <div class="engine-col"><h3>Pullback-in-uptrend</h3><ul>${pbs || '<li class="engine-dim">none</li>'}</ul></div>
            </div>
            <details class="engine-howto" open><summary>HOW TO READ — RSI COUNTER (DAILY & WEEKLY)</summary>
                <p>${_engEsc(data.howto || '')}</p>
            </details>`;
        if (meta) meta.textContent = data.ready ? `n=${data.rsi_n} lag=${data.lag}` : (data.message || 'empty');
        if (!data.ready) {
            el.insertAdjacentHTML('afterbegin', `<p class="scanner-empty">${_engEsc(data.message || 'Empty RSI-C.')}</p>`);
        }
        el.querySelectorAll('[data-sym], tr[data-symbol]').forEach(node => {
            node.addEventListener('click', () => {
                const sym = node.dataset.sym || node.dataset.symbol;
                if (sym && typeof selectSymbol === 'function') selectSymbol(sym);
            });
        });
    } catch (err) {
        _engEmpty(el, err.message || 'RSI-C unavailable');
        if (meta) meta.textContent = 'error';
    }
}

function _engStretchCol(title, items, metric) {
    const rows = (items || []).map(it => {
        const val = metric === 'str' ? it.str : (it.stretch_pctile == null ? it.stretch_pct : it.stretch_pctile);
        const unit = metric === 'str' ? '' : (it.stretch_pctile == null ? '%' : '%ile');
        return `<li><button type="button" class="engine-name" data-sym="${_engEsc(it.symbol)}">${_engEsc(it.symbol)}</button>
            <strong>${val == null ? '—' : (metric === 'str' ? val : _engNum(val))}${unit}</strong>
            <span class="engine-gray">${_engEsc(it.gray_tag || '')}</span></li>`;
    }).join('');
    return `<div class="engine-col"><h3>${_engEsc(title)}</h3><ul>${rows || '<li class="engine-dim">none</li>'}</ul></div>`;
}

async function loadEngineStretch() {
    const el = document.getElementById('engine-stretch-body');
    const meta = document.getElementById('engine-stretch-meta');
    if (!el) return;
    if (meta) meta.textContent = 'GET /api/engine/stretch…';
    try {
        const data = await apiFetch(`${API}/engine/stretch?desk=1`);
        el.innerHTML = `
            <div class="engine-quad">
                ${_engStretchCol('STRONGEST BREAKOUTS', data.strongest, 'str')}
                ${_engStretchCol('BREAKDOWNS', data.breakdowns, 'str')}
                ${_engStretchCol('MOST STRETCHED (ADMA)', data.stretched, 'pct')}
                ${_engStretchCol('MOST COMPRESSED (ADMA)', data.compressed, 'pct')}
            </div>
            <details class="engine-howto" open><summary>HOW TO READ — BREAKOUT-STRENGTH & STRETCH</summary>
                <p>${_engEsc(data.howto || '')}</p>
            </details>`;
        if (meta) meta.textContent = data.ready ? 'stretch lists' : (data.message || 'empty');
        if (!data.ready) {
            el.insertAdjacentHTML('afterbegin', `<p class="scanner-empty">${_engEsc(data.message || 'Empty stretch board.')}</p>`);
        }
        el.querySelectorAll('[data-sym]').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.dataset.sym && typeof selectSymbol === 'function') selectSymbol(btn.dataset.sym);
            });
        });
    } catch (err) {
        _engEmpty(el, err.message || 'Stretch board unavailable');
        if (meta) meta.textContent = 'error';
    }
}

async function loadEngineSigma() {
    const tbody = document.getElementById('engine-sigma-tbody');
    const empty = document.getElementById('engine-sigma-empty');
    const meta = document.getElementById('engine-sigma-meta');
    if (!tbody) return;
    if (meta) meta.textContent = 'GET /api/engine/sigma…';
    try {
        const data = await apiFetch(`${API}/engine/sigma?desk=1`);
        const rows = Array.isArray(data.rows) ? data.rows : [];
        const cols = await _engCols('engine_sigma', data.columns);
        const thead = document.querySelector('#engine-sigma-table thead');
        if (thead && window.BoardRegistry && cols.length) {
            thead.innerHTML = window.BoardRegistry.headerHtml(cols);
        }
        tbody.innerHTML = '';
        rows.forEach(row => {
            const tr = document.createElement('tr');
            tr.dataset.symbol = row.symbol || '';
            if (window.BoardRegistry && cols.length) {
                tr.innerHTML = cols.map(c => window.BoardRegistry.cellHtml(row, c)).join('');
            } else {
                const cell = (v, lo, hi, digits) =>
                    `<td class="${_engTone(v)}" style="${_engHeat(v, lo, hi)}">${v == null ? '—' : _engNum(v, digits)}</td>`;
                tr.innerHTML = `
                <td class="macro-sym">${_engEsc(row.symbol)}</td>
                <td>${row.price == null ? '—' : _engNum(row.price, 2)}</td>
                ${cell(row.ret_1d, -3, 3, 2)}
                ${cell(row.ret_1w, -6, 6, 2)}
                ${cell(row.ret_1m, -12, 12, 2)}
                ${cell(row.ret_3m, -20, 20, 2)}
                ${cell(row.ret_6m, -30, 30, 2)}
                ${cell(row.ret_12m, -40, 40, 2)}
                ${cell(row.sigma_1d, -2, 2, 2)}
                ${cell(row.sigma_1w, -2, 2, 2)}
                ${cell(row.sigma_1m, -2, 2, 2)}
                <td>${row.rsi14 == null ? '—' : _engNum(row.rsi14)}</td>
                <td class="engine-takeaway">${_engEsc(row.takeaway || '—')}</td>`;
            }
            tbody.appendChild(tr);
        });
        if (empty) empty.style.display = rows.length ? 'none' : 'block';
        if (meta) meta.textContent = data.ready ? `${rows.length} rows` : (data.message || 'empty');
        _engRowClick(tbody);
    } catch (err) {
        tbody.innerHTML = '';
        if (empty) {
            empty.style.display = 'block';
            const p = empty.querySelector('p');
            if (p) p.textContent = err.message || 'Sigma grid unavailable';
        }
        if (meta) meta.textContent = 'error';
    }
}

function _engBar(pct) {
    if (pct == null || Number.isNaN(Number(pct))) return '—';
    const n = Math.max(0, Math.min(100, Number(pct)));
    return `<span class="engine-bar"><i style="width:${n}%"></i><em>${_engNum(n, 0)}%</em></span>`;
}

function _engScatter(points, opts) {
    const o = opts || {};
    const w = 640, h = 320, pad = 36;
    const xs = (points || []).map(p => Number(p.x)).filter(v => Number.isFinite(v));
    const ys = (points || []).map(p => Number(p.y)).filter(v => Number.isFinite(v));
    if (!xs.length || !ys.length) {
        return `<p class="scanner-empty">${_engEsc(o.empty || 'Empty plot — no scored points.')}</p>`;
    }
    const x0 = o.xmin != null ? o.xmin : Math.min(...xs);
    const x1 = o.xmax != null ? o.xmax : Math.max(...xs);
    const y0 = o.ymin != null ? o.ymin : Math.min(...ys);
    const y1 = o.ymax != null ? o.ymax : Math.max(...ys);
    const dx = (x1 - x0) || 1, dy = (y1 - y0) || 1;
    const X = v => pad + ((v - x0) / dx) * (w - 2 * pad);
    const Y = v => h - pad - ((v - y0) / dy) * (h - 2 * pad);
    const dots = (points || []).map(p => {
        const cx = X(Number(p.x)), cy = Y(Number(p.y));
        const fill = p.color || '#F97316';
        const r = 4.5;
        const hollow = p.marker === 'hollow';
        const arrow = p.arrow === 'strengthen' ? '↑' : p.arrow === 'weaken' ? '↓' : '';
        return `<g class="engine-dot" data-sym="${_engEsc(p.symbol)}">
            <circle cx="${cx}" cy="${cy}" r="${r}" fill="${hollow ? 'none' : fill}" stroke="${fill}" stroke-width="1.4"></circle>
            <text x="${cx + 6}" y="${cy + 3}" fill="#8B949E" font-size="9">${_engEsc(p.symbol)}${arrow}</text>
        </g>`;
    }).join('');
    const guides = (o.guides || []).map(g => {
        if (g.v != null) return `<line x1="${X(g.v)}" y1="${pad}" x2="${X(g.v)}" y2="${h - pad}" stroke="${g.color || '#30363d'}" stroke-dasharray="3 3" stroke-width="1"/>`;
        if (g.h != null) return `<line x1="${pad}" y1="${Y(g.h)}" x2="${w - pad}" y2="${Y(g.h)}" stroke="${g.color || '#30363d'}" stroke-dasharray="3 3" stroke-width="1"/>`;
        return '';
    }).join('');
    const band = o.band ? `<rect x="${X(o.band[0])}" y="${pad}" width="${Math.max(0, X(o.band[1]) - X(o.band[0]))}" height="${h - 2 * pad}" fill="#06B6D422"></rect>` : '';
    return `<svg class="engine-scatter" viewBox="0 0 ${w} ${h}" role="img">
        <rect x="0" y="0" width="${w}" height="${h}" fill="#ffffff"></rect>
        ${band}${guides}
        <line x1="${pad}" y1="${h - pad}" x2="${w - pad}" y2="${h - pad}" stroke="#30363d"/>
        <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${h - pad}" stroke="#30363d"/>
        <text x="${w / 2}" y="${h - 8}" fill="#8B949E" font-size="10" text-anchor="middle">${_engEsc(o.xLabel || '')}</text>
        <text x="12" y="16" fill="#8B949E" font-size="10">${_engEsc(o.yLabel || '')}</text>
        ${dots}
    </svg>`;
}

function _engLegend(classes) {
    return `<div class="engine-legend">${Object.entries(classes || {}).map(([k, c]) =>
        `<span><i style="background:${c}"></i>${_engEsc(k)}</span>`).join('')}</div>`;
}

function renderEngineMaps(data, view) {
    const el = document.getElementById('engine-maps-body');
    if (!el) return;
    const tab = view || 'scanner';
    document.querySelectorAll('.engine-map-tabs .desk-ia-btn').forEach(btn => {
        btn.classList.toggle('on', btn.dataset.map === tab);
    });
    const classes = data.classes || {};
    if (!data.ready) {
        el.innerHTML = `<p class="scanner-empty">${_engEsc(data.message || 'Empty maps — no stored bars.')}</p>`;
        return;
    }
    if (tab === 'scanner') {
        const rows = ((data.scanner || {}).rows) || [];
        const cols = (window.BoardRegistry && window.BoardRegistry.visibleColumns)
            ? window.BoardRegistry.visibleColumns('engine_maps')
            : (data.columns || []);
        const body = rows.map(r => {
            if (window.BoardRegistry && cols.length) {
                return `<tr data-symbol="${_engEsc(r.symbol)}">${cols.map(c => window.BoardRegistry.cellHtml(r, c)).join('')}</tr>`;
            }
            return `<tr data-symbol="${_engEsc(r.symbol)}">
            <td class="macro-sym">${_engEsc(r.symbol)}</td>
            <td class="${_engTone(r.str)}">${r.str == null ? '—' : r.str}</td>
            <td>${_engBar(r.stretch_pctile != null ? r.stretch_pctile : (r.stretch_pct == null ? null : 50 + r.stretch_pct))}</td>
            <td class="${_engTone(r.delta_d_1m)}">${r.delta_d_1m == null ? '—' : _engNum(r.delta_d_1m, 2)}</td>
            <td>${r.d65 == null ? '—' : _engNum(r.d65, 2)}</td>
            <td class="${_engTone(r.tms_d)}">${r.tms_d == null ? '—' : r.tms_d}</td>
            <td>${_engBar(r.pos_52w)}</td>
            <td>${r.vol30 == null ? '—' : _engNum(r.vol30)}</td>
            <td>${_engEsc(r.tes_state || '—')}</td>
            <td><span class="engine-gray">${_engEsc(r.gray_tag || '')}</span></td>
            <td class="engine-dir" style="${_engHeat(r.dir5, -5, 5)}">${r.dir5 == null ? '—' : r.dir5}</td>
            <td class="engine-tmac" style="${_engHeat(r.tmac_star, 0, 99)}">${r.tmac_star == null ? '—' : r.tmac_star}</td>
        </tr>`;
        }).join('');
        const head = (window.BoardRegistry && cols.length)
            ? window.BoardRegistry.headerHtml(cols)
            : `<tr><th>Asset</th><th>Str</th><th>Stretch</th><th>ΔD 1m</th><th>D65</th><th>TMS-D</th><th>52w pos</th><th>Vol30</th><th>TES</th><th>RSI-C · VCP</th><th>Dir ±5</th><th title="TMAC* heat proxy — never branded TMAC">TMAC*</th></tr>`;
        el.innerHTML = `
            ${_engScatter((data.scanner || {}).scatter || [], { xLabel: 'Dir ±5', yLabel: 'RSI(14)', xmin: -5, xmax: 5, ymin: 0, ymax: 100, guides: [{ v: 0 }, { h: 25 }, { h: 50 }, { h: 75 }] })}
            ${_engLegend(classes)}
            <div class="scanner-table-wrap"><table class="scanner-table engine-heat-table engine-dense">
                <thead>${head}</thead>
                <tbody>${body || `<tr><td colspan="${Math.max(1, cols.length || 12)}">none</td></tr>`}</tbody>
            </table></div>
            <details class="engine-howto" open><summary>HOW TO READ — SCANNER + TES</summary>
                <p>${_engEsc((data.scanner || {}).howto || '')}</p>
                <p>${_engEsc(data.tes_note || '')}</p>
                <p>${_engEsc(data.tmac_note || '')}</p>
            </details>`;
    } else if (tab === 'rotation') {
        const rot = data.rotation || {};
        el.innerHTML = `
            <h3>CROSS-ASSET ROTATION</h3>
            ${_engScatter(rot.points || [], { xLabel: rot.x_label, yLabel: rot.y_label, xmin: 0, xmax: 100, guides: [{ v: 50 }, { h: 0 }] })}
            ${_engLegend(classes)}
            <details class="engine-howto" open><summary>HOW TO READ — ROTATION</summary><p>${_engEsc(rot.howto || '')}</p></details>`;
    } else if (tab === 'coil') {
        const coil = data.coil || {};
        el.innerHTML = `
            <h3>COIL MAP</h3>
            ${_engScatter(coil.points || [], { xLabel: coil.x_label, yLabel: coil.y_label, xmin: 0, xmax: 1.2, ymin: -20, ymax: 120, band: [0, 0.65], guides: [{ v: 0.45, color: '#06B6D4' }, { v: 0.65, color: '#06B6D4' }, { h: 0 }, { h: 100 }] })}
            ${_engLegend(classes)}
            <details class="engine-howto" open><summary>HOW TO READ — COIL</summary><p>${_engEsc(coil.howto || '')}</p></details>`;
    } else if (tab === 'fractal') {
        const ft = data.fractal_td || {};
        el.innerHTML = `
            <h3>FRACTAL × TD</h3>
            ${_engScatter(ft.points || [], { xLabel: ft.x_label, yLabel: ft.y_label, xmin: 1.1, xmax: 2.1, ymin: -15, ymax: 15, guides: [{ v: 1.3 }, { v: 1.5 }, { h: 13, color: '#EF4444' }, { h: -13, color: '#22C55E' }, { h: 0 }], empty: 'No D65 — SPEC 25/27 window failed. No invented markers.' })}
            ${_engLegend(classes)}
            <details class="engine-howto" open><summary>HOW TO READ — FRACTAL × TD</summary>
                <p>${_engEsc(ft.howto || '')}</p>
                <p>${_engEsc(data.td_note || '')}</p>
            </details>`;
    } else {
        const tm = data.tms_regime || {};
        const pts = [...(tm.weekly || []), ...(tm.daily || [])];
        const spy = tm.spy_strip || {};
        const ex = tm.extremes || {};
        const list = (arr) => (arr || []).map(x => `<li><button type="button" class="engine-name" data-sym="${_engEsc(x.symbol)}">${_engEsc(x.symbol)}</button> ${_engNum(x.ret_12m)}%</li>`).join('');
        el.innerHTML = `
            <h3>TMS REGIME MAP</h3>
            <p class="engine-dim">SPY strip: ${_engEsc(spy.label || '—')} — ${_engEsc(spy.note || '')}</p>
            <p class="engine-dim">By zone: ${Object.keys(tm.by_zone || {}).map(z => `${_engEsc(z)} ${(tm.by_zone[z] || []).join(', ')}`).join(' · ') || '—'}</p>
            ${_engScatter(pts, { xLabel: tm.x_label, yLabel: tm.y_label, xmin: -100, xmax: 100, ymin: -25, ymax: 25, guides: [{ v: 0 }, { h: 0 }] })}
            ${_engLegend(classes)}
            <div class="engine-quad">
                <div class="engine-col is-bull"><h3>TOP 12M %</h3><ul>${list(ex.top_12m) || '<li class="engine-dim">none</li>'}</ul></div>
                <div class="engine-col is-bear"><h3>BOTTOM 12M %</h3><ul>${list(ex.bottom_12m) || '<li class="engine-dim">none</li>'}</ul></div>
            </div>
            <details class="engine-howto" open><summary>HOW TO READ — TMS REGIME</summary><p>${_engEsc(tm.howto || '')}</p></details>`;
    }
    el.querySelectorAll('[data-sym], tr[data-symbol], .engine-dot').forEach(node => {
        node.addEventListener('click', () => {
            const sym = node.dataset.sym || node.dataset.symbol;
            if (sym && typeof selectSymbol === 'function') selectSymbol(sym);
        });
    });
}

async function loadEngineMaps() {
    const el = document.getElementById('engine-maps-body');
    const meta = document.getElementById('engine-maps-meta');
    if (!el) return;
    if (meta) meta.textContent = 'GET /api/engine/maps…';
    try {
        if (window.BoardRegistry && window.BoardRegistry.load) {
            await window.BoardRegistry.load();
        }
        const data = await apiFetch(`${API}/engine/maps?desk=1`);
        window._engineMaps = data;
        const on = document.querySelector('.engine-map-tabs .desk-ia-btn.on');
        renderEngineMaps(data, on ? on.dataset.map : 'scanner');
        if (meta) meta.textContent = data.ready ? `${data.count || 0} names` : (data.message || 'empty');
    } catch (err) {
        el.innerHTML = `<p class="scanner-empty">${_engEsc(err.message || 'Maps unavailable')}</p>`;
        if (meta) meta.textContent = 'error';
    }
}

function bindEngineDesk() {
    document.querySelectorAll('#desk-ia-bar .desk-ia-btn').forEach(btn => {
        btn.addEventListener('click', () => applyDeskIa(btn.dataset.ia));
    });
    document.querySelectorAll('#engine-ia-bar .desk-ia-btn').forEach(btn => {
        btn.addEventListener('click', () => applyEnginePanel(btn.dataset.ia));
    });
    document.getElementById('btn-engine-command')?.addEventListener('click', () => loadEngineCommand());
    document.getElementById('btn-engine-board')?.addEventListener('click', () => loadEngineBoard());
    document.getElementById('btn-engine-patterns')?.addEventListener('click', () => loadEnginePatterns());
    document.getElementById('btn-engine-rsic')?.addEventListener('click', () => loadEngineRsiC());
    document.getElementById('btn-engine-stretch')?.addEventListener('click', () => loadEngineStretch());
    document.getElementById('btn-engine-sigma')?.addEventListener('click', () => loadEngineSigma());
    document.getElementById('btn-engine-maps')?.addEventListener('click', () => loadEngineMaps());
    document.querySelectorAll('.engine-map-tabs .desk-ia-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.engine-map-tabs .desk-ia-btn').forEach(b => b.classList.toggle('on', b === btn));
            if (window._engineMaps) renderEngineMaps(window._engineMaps, btn.dataset.map);
        });
    });
    document.getElementById('engine-rsic-lag')?.addEventListener('change', () => loadEngineRsiC());
    document.getElementById('engine-rsic-n')?.addEventListener('change', () => loadEngineRsiC());
}

window.hideEngineArea = hideEngineArea;
window.showEngineArea = showEngineArea;
window.applyDeskIa = applyDeskIa;
window.applyEnginePanel = applyEnginePanel;
window.bindEngineDesk = bindEngineDesk;
window.loadEngineBoard = loadEngineBoard;
window.loadEngineSetupGlance = loadEngineSetupGlance;
window.loadEngineSigma = loadEngineSigma;
window.loadEngineMaps = loadEngineMaps;
window.renderEngineMaps = renderEngineMaps;
