/* ============================================================
   signal_scanner.js — Signals tab
   - Routine pills: toggle which scanners run (persisted)
   - SCAN ▸ WATCHLIST runs /api/signals across all symbols
   - Star a signal to keep it on the ★ FLAGGED list across
     scans and sessions (localStorage snapshot of the signal)
   - Click a symbol to jump into its Quant Lab screen
   ============================================================ */

const SG = {
    data: null,                 // last scan response
    filter: 'all',              // all | bull | bear | watch | flagged
    catalog: null,              // routine catalog (id, label, desc)
    flags: {},                  // sigKey → signal snapshot
    disabled: new Set(),        // routine ids switched off
};

(function sgRestore() {
    try { SG.flags = JSON.parse(localStorage.getItem('sg_flags') || '{}'); } catch (e) { SG.flags = {}; }
    try { SG.disabled = new Set(JSON.parse(localStorage.getItem('sg_routines_off') || '[]')); } catch (e) { SG.disabled = new Set(); }
})();

function sgPersist() {
    localStorage.setItem('sg_flags', JSON.stringify(SG.flags));
    localStorage.setItem('sg_routines_off', JSON.stringify([...SG.disabled]));
}

function sgKey(s) { return `${s.symbol}|${s.routine}|${s.date}`; }

// ── init (called by switchTab) ───────────────────────────────

async function initSignalScanner() {
    if (!SG.catalog) {
        try {
            const res = await fetch('/api/signals/routines');
            SG.catalog = await res.json();
        } catch (e) {
            SG.catalog = [];
        }
    }
    sgRenderPills();
    sgUpdateFlagCount();
    if (SG.data) sgRender();
}

// ── routine pills ────────────────────────────────────────────

function sgRenderPills() {
    const wrap = document.getElementById('sg-routine-pills');
    if (!wrap || !SG.catalog) return;
    wrap.innerHTML = SG.catalog.map(r => {
        const off = SG.disabled.has(r.id);
        const count = SG.data
            ? (SG.data.routines.find(x => x.id === r.id)?.count ?? 0) : null;
        return `<button class="sg-pill ${off ? 'sg-pill-off' : ''}"
                        title="${r.desc}"
                        onclick="sgToggleRoutine('${r.id}')">
                    ${r.label}${count !== null && !off ? ` <b>${count}</b>` : ''}
                </button>`;
    }).join('');
}

function sgToggleRoutine(id) {
    if (SG.disabled.has(id)) SG.disabled.delete(id);
    else SG.disabled.add(id);
    sgPersist();
    sgRenderPills();
    if (SG.data) sgRender();   // re-filter the already-loaded scan
}

// ── scanning ─────────────────────────────────────────────────

async function sgRunScan() {
    const btn     = document.getElementById('btn-sg-scan');
    const loading = document.getElementById('sg-loading');
    btn.disabled = true;
    loading.style.display = 'flex';
    try {
        const res  = await fetch('/api/signals');
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
        SG.data = data;
        SG.track = null;   // journal grew — stale track record
        const fired = data.signals.length;
        document.getElementById('sg-meta').textContent =
            `${data.n_symbols} SYMBOLS · ${fired} SIGNAL${fired === 1 ? '' : 'S'}`
            + (data.journaled_new ? ` · ${data.journaled_new} JOURNALED` : '')
            + (data.skipped.length ? ` · ${data.skipped.length} SKIPPED (NOT ENOUGH DATA)` : '');
        sgRenderPills();
        sgRender();
    } catch (e) {
        toast(`Signal scan failed: ${e.message}`, 'error');
    } finally {
        btn.disabled = false;
        loading.style.display = 'none';
    }
}

// ── filtering & rendering ────────────────────────────────────

function sgSetFilter(f) {
    SG.filter = f;
    document.querySelectorAll('.sg-filter-btn').forEach(b =>
        b.classList.toggle('sg-f-active', b.dataset.f === f));
    sgRender();
}

function sgVisibleSignals() {
    if (SG.filter === 'flagged') {
        // flagged snapshots survive across scans and sessions
        return Object.values(SG.flags)
            .sort((a, b) => (b.date + b.strength).localeCompare(a.date + a.strength));
    }
    if (!SG.data) return [];
    let sigs = SG.data.signals.filter(s => !SG.disabled.has(s.routine) && !s.error);
    if (SG.filter !== 'all') sigs = sigs.filter(s => s.side === SG.filter);
    return sigs;
}

function sgUpdateFlagCount() {
    const el = document.getElementById('sg-flag-count');
    const n = Object.keys(SG.flags).length;
    if (el) el.textContent = n ? `(${n})` : '';
}

const SG_SIDE = {
    bull:  { icon: '▲', cls: 'sg-side-bull',  label: 'BULL'  },
    bear:  { icon: '▼', cls: 'sg-side-bear',  label: 'BEAR'  },
    watch: { icon: '◆', cls: 'sg-side-watch', label: 'WATCH' },
};

function sgRender() {
    const empty   = document.getElementById('sg-empty');
    const results = document.getElementById('sg-results');
    const tbody   = document.getElementById('sg-tbody');
    const sigs    = sgVisibleSignals();

    if (!SG.data && SG.filter !== 'flagged') {
        empty.style.display = 'flex';
        results.style.display = 'none';
        return;
    }
    empty.style.display = 'none';
    results.style.display = 'block';

    if (!sigs.length) {
        tbody.innerHTML = `<tr><td colspan="8" class="sg-none">
            ${SG.filter === 'flagged' ? 'NO FLAGGED SIGNALS — STAR ONE FROM A SCAN'
                                      : 'NO SIGNALS FIRED FOR THIS FILTER'}</td></tr>`;
        return;
    }

    tbody.innerHTML = sigs.map(s => {
        const key     = sgKey(s);
        const flagged = !!SG.flags[key];
        const side    = SG_SIDE[s.side] || SG_SIDE.watch;
        return `<tr>
            <td><button class="sg-star ${flagged ? 'sg-star-on' : ''}"
                        onclick="sgToggleFlag('${key.replace(/'/g, '')}')"
                        title="${flagged ? 'Unflag' : 'Flag this signal'}">★</button></td>
            <td><span class="sg-symbol" onclick="sgOpenSymbol('${s.symbol}')">${s.symbol}</span></td>
            <td class="sg-label">${s.label}</td>
            <td><span class="sg-side ${side.cls}">${side.icon} ${side.label}</span></td>
            <td>
                <div class="sg-str-wrap">
                    <div class="sg-str-bar"><div class="${side.cls}" style="width:${Math.min(s.strength, 100)}%"></div></div>
                    <span class="sg-str-val">${Math.round(s.strength)}</span>
                </div>
            </td>
            <td class="sg-detail">${s.detail}</td>
            <td class="sg-date">${s.date}</td>
            <td class="sg-price">${s.price ?? '—'}</td>
        </tr>`;
    }).join('');
}

// ── flagging ─────────────────────────────────────────────────

function sgToggleFlag(key) {
    if (SG.flags[key]) {
        delete SG.flags[key];
    } else {
        const sig = (SG.data?.signals || []).find(s => sgKey(s) === key)
                 || Object.values(SG.flags).find(s => sgKey(s) === key);
        if (sig) SG.flags[key] = sig;
    }
    sgPersist();
    sgUpdateFlagCount();
    sgRender();
}

// ── navigation ───────────────────────────────────────────────

function sgOpenSymbol(symbol) {
    selectSymbol(symbol);
    switchTab('quant');
}

// ── routine track record ─────────────────────────────────────

SG.track = null;

async function sgToggleTrack() {
    const box = document.getElementById('sg-track');
    if (box.style.display !== 'none') { box.style.display = 'none'; return; }
    box.style.display = 'block';
    if (SG.track) { sgRenderTrack(); return; }

    const loading = document.getElementById('sg-loading');
    loading.style.display = 'flex';
    try {
        const res  = await fetch('/api/signals/track-record');
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
        SG.track = data;
        sgRenderTrack();
    } catch (e) {
        box.style.display = 'none';
        toast(`Track record failed: ${e.message}`, 'error');
    } finally {
        loading.style.display = 'none';
    }
}

function sgRenderTrack() {
    const d = SG.track;
    if (!d) return;
    document.getElementById('sg-track-meta').textContent =
        `HIST = RULE REPLAYED OVER ${d.n_symbols} SYMBOLS' FULL HISTORY · ` +
        `LIVE = ${d.n_journal} JOURNALED SIGNAL${d.n_journal === 1 ? '' : 'S'} FROM YOUR SCANS`;

    const pct = (x) => x === null || x === undefined ? '—' : (x * 100).toFixed(0) + '%';
    const ret = (x) => x === null || x === undefined ? '—' : (x >= 0 ? '+' : '') + (x * 100).toFixed(2) + '%';
    const hitColor = (x) => x === null ? '#5a6472' : x >= 0.55 ? '#00d26a' : x <= 0.45 ? '#ff4d3d' : '#b8c0c8';
    const retColor = (x) => x === null ? '#5a6472' : x > 0 ? '#00d26a' : '#ff4d3d';

    document.getElementById('sg-track-tbody').innerHTML = d.rows.map(r => {
        const h5 = r.hist.h5, h21 = r.hist.h21, lv = r.live;
        if (!r.hist.available) {
            return `<tr>
                <td class="sg-label">${r.label}</td>
                <td class="sg-detail" colspan="5">live-only (model-based routine, no vectorised replay)</td>
                <td>${lv.n}</td>
                <td style="color:${hitColor(lv.h21.hit)}">${pct(lv.h21.hit)}</td>
                <td style="color:${retColor(lv.h21.avg)}">${ret(lv.h21.avg)}</td>
            </tr>`;
        }
        return `<tr>
            <td class="sg-label">${r.label}</td>
            <td>${h21.n}</td>
            <td style="color:${hitColor(h5.hit)}">${pct(h5.hit)}</td>
            <td style="color:${retColor(h5.avg)}">${ret(h5.avg)}</td>
            <td style="color:${hitColor(h21.hit)}">${pct(h21.hit)}</td>
            <td style="color:${retColor(h21.avg)}">${ret(h21.avg)}</td>
            <td>${lv.n}</td>
            <td style="color:${hitColor(lv.h21.hit)}">${pct(lv.h21.hit)}</td>
            <td style="color:${retColor(lv.h21.avg)}">${ret(lv.h21.avg)}</td>
        </tr>`;
    }).join('');
}
