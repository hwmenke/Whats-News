/**
 * knn_forecast.js — KNN Pattern-Recognition Forecast UI
 *
 * Controls: symbol (from state), freq, K neighbours, 5 group-weight sliders
 * Output:   4 horizon cards + neighbour table + feature snapshot panel
 */

// ── State ─────────────────────────────────────────────────────
const knnState = {
    freq:   'daily',
    k:      20,
    result: null,
    weights: {
        trend:        0.25,
        momentum:     0.25,
        volatility:   0.20,
        price_action: 0.20,
        volume:       0.10,
    },
};

// ── Horizon metadata ──────────────────────────────────────────
const KNN_HORIZONS = [
    { h: 5,   label: 'Short',    sublabel: '1 Week',     icon: '⚡' },
    { h: 20,  label: 'Medium',   sublabel: '1 Month',    icon: '📈' },
    { h: 63,  label: 'Long',     sublabel: '1 Quarter',  icon: '🎯' },
    { h: 126, label: 'Extended', sublabel: '6 Months',   icon: '🔭' },
];

const KNN_GROUPS = {
    trend:        { label: 'Trend / KAMA',   color: '#3b82f6', icon: '📊' },
    momentum:     { label: 'Momentum',        color: '#22c55e', icon: '⚡' },
    volatility:   { label: 'Volatility',      color: '#f59e0b', icon: '🌊' },
    price_action: { label: 'Price Action',    color: '#a855f7', icon: '🕯' },
    volume:       { label: 'Volume / OBV',    color: '#06b6d4', icon: '📦' },
};

// ── Frequency toggle ──────────────────────────────────────────
function knnSetFreq(f) {
    knnState.freq = f;
    document.querySelectorAll('#knn-area .knn-freq-btn').forEach(b =>
        b.classList.toggle('knn-active', b.dataset.val === f)
    );
}

// ── Weight sliders ────────────────────────────────────────────
function knnUpdateWeight(group, val) {
    knnState.weights[group] = parseFloat(val);
    const display = document.getElementById(`knn-w-val-${group}`);
    if (display) display.textContent = parseFloat(val).toFixed(2);
    _knnSyncWeightTotal();
}

function _knnSyncWeightTotal() {
    const total = Object.values(knnState.weights).reduce((a, b) => a + b, 0);
    const el    = document.getElementById('knn-weight-total');
    if (el) {
        el.textContent = total.toFixed(2);
        el.className   = 'knn-weight-total ' +
            (Math.abs(total - 1.0) < 0.01 ? 'knn-wt-ok' : 'knn-wt-warn');
    }
}

function knnResetWeights() {
    const defaults = { trend:0.25, momentum:0.25, volatility:0.20, price_action:0.20, volume:0.10 };
    Object.entries(defaults).forEach(([g, v]) => {
        knnState.weights[g] = v;
        const slider  = document.getElementById(`knn-slider-${g}`);
        const display = document.getElementById(`knn-w-val-${g}`);
        if (slider)  slider.value = v;
        if (display) display.textContent = v.toFixed(2);
    });
    _knnSyncWeightTotal();
}

// ── Run ───────────────────────────────────────────────────────
async function knnRunForecast() {
    const symbol = (typeof state !== 'undefined') ? state.activeSymbol : null;
    if (!symbol) { toast('Select a symbol first', 'warning'); return; }

    _knnSetLoading(true);
    try {
        const result = await apiFetch(`${API}/knn-forecast/${symbol}`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({
                freq:    knnState.freq,
                k:       parseInt(document.getElementById('knn-k-input')?.value || '20'),
                weights: knnState.weights,
            }),
        });
        knnState.result = result;
        _knnRenderResults(result);
    } catch (e) {
        toastFromError(e, 'KNN');
        _knnShowEmpty('Error: ' + e.message);
    } finally {
        _knnSetLoading(false);
    }
}

// ── Render results ────────────────────────────────────────────
function _knnRenderResults(data) {
    document.getElementById('knn-empty').style.display   = 'none';
    document.getElementById('knn-results').style.display = '';

    _knnRenderMeta(data);
    _knnRenderHorizons(data.horizons);
    _knnRenderNeighborTable(data.neighbors);
    _knnRenderFeaturePanel(data.features);
}

function _knnRenderMeta(data) {
    const el = document.getElementById('knn-meta');
    if (!el) return;
    el.style.display = 'flex';
    el.innerHTML =
        `<span class="knn-meta-item">📅 Query: <b>${data.query_date}</b></span>` +
        `<span class="knn-meta-sep">·</span>` +
        `<span class="knn-meta-item">🔍 K = <b>${data.k}</b> neighbours</span>` +
        `<span class="knn-meta-sep">·</span>` +
        `<span class="knn-meta-item">📚 Training: <b>${data.n_train}</b> bars</span>` +
        `<span class="knn-meta-sep">·</span>` +
        `<span class="knn-meta-item">📆 Freq: <b>${data.freq}</b></span>`;
}

function _knnRenderHorizons(horizons) {
    const container = document.getElementById('knn-horizon-cards');
    if (!container) return;

    container.innerHTML = (horizons || []).map(h => {
        const meta     = KNN_HORIZONS.find(m => m.h === h.horizon) || {};
        const bull     = h.bull_pct;
        const bear     = bull != null ? (1 - bull) : null;
        const bullPct  = bull != null ? Math.round(bull * 100) : null;
        const bearPct  = bear != null ? Math.round(bear * 100) : null;
        const meanRet  = h.mean_ret;
        const signal   = bull == null ? 'neutral'
                       : bull > 0.65  ? 'bull-strong'
                       : bull > 0.55  ? 'bull'
                       : bull < 0.35  ? 'bear-strong'
                       : bull < 0.45  ? 'bear'
                       :                'neutral';

        const signalLabel = {
            'bull-strong': 'BULLISH',
            'bull':        'LEAN BULL',
            'neutral':     'NEUTRAL',
            'bear':        'LEAN BEAR',
            'bear-strong': 'BEARISH',
        }[signal] || '—';

        const retColor = meanRet == null ? 'var(--text-muted)'
                       : meanRet > 0     ? 'var(--green)'
                       :                   'var(--red)';

        const fmtPct = v => v == null ? '—' : (v >= 0 ? '+' : '') + (v * 100).toFixed(1) + '%';

        const confBar = h.confidence != null
            ? `<div class="knn-conf-bar"><div class="knn-conf-fill" style="width:${Math.round(h.confidence*100)}%"></div></div>
               <span class="knn-conf-label">${Math.round(h.confidence*100)}% conf.</span>`
            : '';

        return `
        <div class="knn-horizon-card knn-h-${signal}">
          <div class="knn-h-header">
            <span class="knn-h-icon">${meta.icon || '📊'}</span>
            <div>
              <div class="knn-h-label">${meta.label || h.horizon + 'd'}</div>
              <div class="knn-h-sublabel">${meta.sublabel || ''} · ${h.horizon} bars</div>
            </div>
            <div class="knn-h-signal knn-sig-${signal}">${signalLabel}</div>
          </div>

          <div class="knn-h-gauge">
            <div class="knn-gauge-bar">
              <div class="knn-gauge-bull" style="width:${bullPct ?? 50}%"></div>
            </div>
            <div class="knn-gauge-labels">
              <span class="knn-gauge-bull-label">${bullPct ?? '—'}% Bull</span>
              <span class="knn-gauge-bear-label">${bearPct ?? '—'}% Bear</span>
            </div>
          </div>

          <div class="knn-h-stats">
            <div class="knn-h-stat">
              <div class="knn-h-stat-label">Exp. Return</div>
              <div class="knn-h-stat-val" style="color:${retColor}">${fmtPct(meanRet)}</div>
            </div>
            <div class="knn-h-stat">
              <div class="knn-h-stat-label">Median</div>
              <div class="knn-h-stat-val">${fmtPct(h.median)}</div>
            </div>
            <div class="knn-h-stat">
              <div class="knn-h-stat-label">Q25 / Q75</div>
              <div class="knn-h-stat-val">${fmtPct(h.q25)} / ${fmtPct(h.q75)}</div>
            </div>
          </div>

          <div class="knn-h-conf">
            ${confBar}
          </div>
        </div>`;
    }).join('');
}

function _knnRenderNeighborTable(neighbors) {
    const el = document.getElementById('knn-neighbor-table');
    if (!el || !neighbors?.length) return;

    const hCols = KNN_HORIZONS.map(m =>
        `<th class="knn-nt-th">${m.icon} ${m.label}</th>`
    ).join('');

    const fmtR = v => {
        if (v == null) return '<span style="color:var(--text-dim)">—</span>';
        const pct = (v * 100).toFixed(1);
        const cls = v > 0 ? 'knn-ret-pos' : v < 0 ? 'knn-ret-neg' : '';
        return `<span class="${cls}">${v >= 0 ? '+' : ''}${pct}%</span>`;
    };

    const rows = neighbors.map(n => {
        const simPct  = Math.round(n.similarity * 100);
        const simColor= simPct > 75 ? '#22c55e' : simPct > 50 ? '#f59e0b' : '#94a3b8';
        const retCols = KNN_HORIZONS.map(m =>
            `<td class="knn-nt-td">${fmtR(n[`ret_h${m.h}`])}</td>`
        ).join('');

        return `<tr class="knn-nt-row">
          <td class="knn-nt-td knn-nt-rank">#${n.rank}</td>
          <td class="knn-nt-td knn-nt-date">${n.date}</td>
          <td class="knn-nt-td">
            <div class="knn-sim-badge" style="--sim-color:${simColor}">
              <div class="knn-sim-bar" style="width:${simPct}%"></div>
              <span class="knn-sim-val">${simPct}%</span>
            </div>
          </td>
          ${retCols}
        </tr>`;
    }).join('');

    el.innerHTML = `
      <div class="knn-nt-title">Top-${neighbors.length} Most Similar Historical Periods</div>
      <div class="knn-nt-wrap">
        <table class="knn-nt">
          <thead><tr>
            <th class="knn-nt-th">#</th>
            <th class="knn-nt-th">Date</th>
            <th class="knn-nt-th">Similarity</th>
            ${hCols}
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
}

function _knnRenderFeaturePanel(features) {
    const el = document.getElementById('knn-feature-panel');
    if (!el || !features) return;

    const grouped = {};
    Object.entries(features).forEach(([key, f]) => {
        if (!grouped[f.group]) grouped[f.group] = [];
        grouped[f.group].push({ key, ...f });
    });

    const groupOrder = ['trend', 'momentum', 'volatility', 'price_action', 'volume'];
    let html = '';

    groupOrder.forEach(grp => {
        const gMeta = KNN_GROUPS[grp] || {};
        const feats = grouped[grp] || [];
        if (!feats.length) return;

        const rows = feats.map(f => {
            const norm    = f.norm;
            const barPct  = Math.min(100, Math.round(Math.abs(norm) / 3 * 100));
            const barDir  = norm >= 0 ? 'right' : 'left';
            const barCls  = norm > 0.5 ? 'knn-fb-bull' : norm < -0.5 ? 'knn-fb-bear' : 'knn-fb-neut';
            const valFmt  = f.value != null ? f.value.toFixed(3) : '—';

            return `
            <div class="knn-feat-row" title="${f.desc}">
              <span class="knn-feat-label">${f.label}</span>
              <div class="knn-feat-bar-wrap">
                <div class="knn-feat-bar ${barCls} knn-fb-${barDir}" style="width:${barPct}%"></div>
              </div>
              <span class="knn-feat-val">${valFmt}</span>
              <span class="knn-feat-norm ${norm > 0 ? 'knn-fn-pos' : norm < 0 ? 'knn-fn-neg' : ''}"
                    title="z-score">${norm >= 0 ? '+' : ''}${norm.toFixed(2)}σ</span>
            </div>`;
        }).join('');

        html += `
        <div class="knn-feat-group">
          <div class="knn-feat-group-header" style="--grp-color:${gMeta.color}">
            <span>${gMeta.icon || ''}</span>
            <span>${gMeta.label || grp}</span>
            <span class="knn-feat-weight-badge">w=${knnState.weights[grp]?.toFixed(2) || '?'}</span>
          </div>
          ${rows}
        </div>`;
    });

    el.innerHTML = html || '<div class="knn-no-feat">No feature data</div>';
}

// ── Loading / error helpers ───────────────────────────────────
function _knnSetLoading(on) {
    const btn    = document.getElementById('btn-knn-run');
    const loadEl = document.getElementById('knn-loading');
    if (on) {
        if (btn)    { btn.disabled = true; btn.textContent = '⏳ Searching…'; }
        if (loadEl) loadEl.style.display = 'flex';
    } else {
        if (btn)    { btn.disabled = false; btn.textContent = '🔮 Find Patterns'; }
        if (loadEl) loadEl.style.display = 'none';
    }
}

function _knnShowEmpty(msg) {
    const el = document.getElementById('knn-empty');
    if (el) {
        el.style.display = '';
        el.innerHTML = `<div class="empty-icon">⚠</div><p>${msg}</p>`;
    }
    const res = document.getElementById('knn-results');
    if (res) res.style.display = 'none';
}

// ── Init ──────────────────────────────────────────────────────
function initKnnForecast() {
    knnResetWeights();
}
