/**
 * vol_momentum.js — Vol-Adjusted Momentum panel (turnover-brake portfolio)
 *
 * Table: every watchlist symbol with S = M/(σ+ε), cross-sectional rank,
 * dollar-neutral target weight, Δw, gain-vs-cost brake and the resulting
 * decision (TRADE / BRAKE / NO_TRADE_BAND) + basket (LONG / SHORT / NEUTRAL).
 * "Apply" persists partial-adjusted weights so the next run's Δw is real.
 */

const vmState = { result: null, sortCol: 'rank', sortAsc: true };

const VM_DECISION_META = {
    TRADE:         { cls: 'vm-trade', label: '⚡ Trade' },
    BRAKE:         { cls: 'vm-brake', label: '⛔ Brake' },
    NO_TRADE_BAND: { cls: 'vm-band',  label: '· Band'  },
};

const VM_BASKET_META = {
    LONG:    { cls: 'vm-long',    label: '▲ Long'  },
    SHORT:   { cls: 'vm-short',   label: '▼ Short' },
    NEUTRAL: { cls: 'vm-neutral', label: '— Neutral' },
    HOLD:    { cls: 'vm-hold',    label: 'Hold' },
};

// ── Params ────────────────────────────────────────────────────
function _vmParams() {
    const val = id => {
        const el = document.getElementById(id);
        return el && el.value !== '' ? el.value : null;
    };
    const p = {};
    [['vm-mom-lb','mom_lb'], ['vm-vol-lb','vol_lb'], ['vm-skip','skip'],
     ['vm-lmax','l_max'], ['vm-kappa','kappa'], ['vm-tau','tau'],
     ['vm-lam','lam'], ['vm-dw','delta_w'], ['vm-ds','delta_s'],
     ['vm-cost','spread_bps']].forEach(([id, key]) => {
        const v = val(id);
        if (v !== null) p[key] = v;
    });
    return p;
}

function _vmQuery() {
    const p = _vmParams();
    const qs = Object.entries(p).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
    return qs ? `?${qs}` : '';
}

// ── Load / Apply / Reset ──────────────────────────────────────
async function loadVolMomentum() {
    _vmSetLoading(true);
    try {
        const data = await apiFetch(`${API}/vol-momentum${_vmQuery()}`);
        vmState.result = data;
        _vmRender(data);
    } catch (e) {
        toastFromError(e, 'Vol Momentum');
        _vmShowError(e.message);
    } finally {
        _vmSetLoading(false);
    }
}

async function applyVolMomentum() {
    if (!confirm('Persist the partial-adjusted weights as the new previous state?')) return;
    _vmSetLoading(true);
    try {
        const data = await apiFetch(`${API}/vol-momentum/apply`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(_vmParams()),
        });
        vmState.result = data;
        _vmRender(data);
        toast(`Applied — ${data.applied} weights saved`, 'success');
    } catch (e) {
        toastFromError(e, 'Apply');
    } finally {
        _vmSetLoading(false);
    }
}

async function resetVolMomentumState() {
    if (!confirm('Clear all persisted weights? Next run starts from w=0, S_prev=0.')) return;
    try {
        const data = await apiFetch(`${API}/vol-momentum/state`, { method: 'DELETE' });
        toast(`State cleared (${data.cleared} rows)`, 'info');
        loadVolMomentum();
    } catch (e) {
        toastFromError(e, 'Reset');
    }
}

// ── Render ────────────────────────────────────────────────────
function _vmRender(data) {
    document.getElementById('vm-empty').style.display   = 'none';
    document.getElementById('vm-error').style.display   = 'none';
    document.getElementById('vm-results').style.display = '';

    const s = data.summary;
    const fmtW = v => (v === null || v === undefined) ? '--'
        : (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
    const set = (id, val) => {
        const el = document.getElementById(id);
        if (el) el.textContent = val;
    };
    set('vm-sum-n',        `${s.n_traded}/${s.n}`);
    set('vm-sum-long',     String(s.n_long));
    set('vm-sum-short',    String(s.n_short));
    set('vm-sum-gross',    fmtW(s.gross));
    set('vm-sum-net',      fmtW(s.net));
    set('vm-sum-turnover', fmtW(s.turnover));

    const note = document.getElementById('vm-skipped-note');
    if (note) {
        note.textContent = (data.skipped || []).length
            ? `Skipped (not enough history): ${data.skipped.join(', ')}`
            : '';
    }
    _vmRenderTable(data.rows);
}

function _vmRenderTable(rows) {
    const col = vmState.sortCol;
    const dir = vmState.sortAsc ? 1 : -1;
    const sorted = [...rows].sort((a, b) => {
        const av = a[col], bv = b[col];
        if (av === null || av === undefined) return 1;
        if (bv === null || bv === undefined) return -1;
        return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
    });

    const fmtPct = v => (v === null || v === undefined) ? '--'
        : (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
    const fmtS = v => (v === null || v === undefined) ? '--' : v.toFixed(3);
    const cls  = v => (v === null || v === undefined) ? '' : (v >= 0 ? 'vm-pos' : 'vm-neg');

    const cols = [
        ['rank', '#'], ['symbol', 'Symbol'], ['price', 'Price'],
        ['mom', 'Mom'], ['vol', 'σ (ann)'], ['s', 'S'], ['ds', 'ΔS'],
        ['w_prev', 'w prev'], ['w_target', 'w★'], ['dw', 'Δw'],
        ['gain', 'Gain'], ['cost', 'Cost'],
        ['decision', 'Decision'], ['basket', 'Basket'], ['w_new', 'w new'],
    ];
    const head = cols.map(([key, label]) =>
        `<th onclick="_vmSort('${key}')" style="cursor:pointer;"
             title="Sort by ${label}">${label}${col === key ? (vmState.sortAsc ? ' ▲' : ' ▼') : ''}</th>`
    ).join('');

    const body = sorted.map(r => {
        const d = VM_DECISION_META[r.decision] || { cls: '', label: r.decision };
        const b = VM_BASKET_META[r.basket]     || { cls: '', label: r.basket };
        return `<tr>
            <td>${r.rank}</td>
            <td class="gs-sym-cell"><a href="#" onclick="selectSymbol('${r.symbol}');return false;">${r.symbol}</a></td>
            <td>$${r.price ?? '--'}</td>
            <td class="${cls(r.mom)}">${fmtPct(r.mom)}</td>
            <td>${fmtPct(r.vol)}</td>
            <td class="${cls(r.s)}"><b>${fmtS(r.s)}</b></td>
            <td class="${cls(r.ds)}">${fmtS(r.ds)}</td>
            <td>${fmtPct(r.w_prev)}</td>
            <td class="${cls(r.w_target)}">${fmtPct(r.w_target)}</td>
            <td class="${cls(r.dw)}">${fmtPct(r.dw)}</td>
            <td>${r.gain !== null && r.gain !== undefined ? r.gain.toExponential(2) : '--'}</td>
            <td>${r.cost !== null && r.cost !== undefined ? r.cost.toExponential(2) : '--'}</td>
            <td><span class="vm-badge ${d.cls}">${d.label}</span></td>
            <td><span class="vm-badge ${b.cls}">${b.label}</span></td>
            <td class="${cls(r.w_new)}"><b>${fmtPct(r.w_new)}</b></td>
        </tr>`;
    }).join('');

    document.getElementById('vm-table-wrap').innerHTML =
        `<table id="vm-tbl" class="scanner-table" style="width:100%;">
           <thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function _vmSort(col) {
    if (vmState.sortCol === col) vmState.sortAsc = !vmState.sortAsc;
    else { vmState.sortCol = col; vmState.sortAsc = (col === 'rank' || col === 'symbol'); }
    if (vmState.result) _vmRenderTable(vmState.result.rows);
}

// ── Plumbing ──────────────────────────────────────────────────
function _vmSetLoading(on) {
    const el = document.getElementById('vm-loading');
    if (el) el.style.display = on ? 'flex' : 'none';
}

function _vmShowError(msg) {
    const el = document.getElementById('vm-error');
    if (el) {
        el.style.display = '';
        el.textContent = msg;
    }
    document.getElementById('vm-results').style.display = 'none';
    document.getElementById('vm-empty').style.display   = 'none';
}

function initVolMomentum() {
    if (!vmState.result) loadVolMomentum();
}
