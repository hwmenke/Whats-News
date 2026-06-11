/* ============================================================
   quant_lab.js — Bloomberg-terminal-style Quant Lab tab
   Renders /api/quant-lab/<symbol>:
     header dials  : VALUATION (cheap↔rich) · DIRECTION (lower↔higher)
     FV  panel     : fair-value trend channel + valuation→fwd-1w edge curve
     KNN panel     : analog fan forecast (percentile cone + spaghetti)
     CTA panel     : 3-speed EWMAC equity vs buy&hold + forecast strip
     EXH panel     : exhaustion event study + oscillator
     AUTOML strip  : on-demand PyCaret leaderboard (/api/pycaret)
   ============================================================ */

const QL = {
    charts: {},          // id → Chart instance
    loadedFor: null,     // symbol of currently rendered data
    colors: {
        amber:  '#fb8b1e',
        green:  '#00d26a',
        red:    '#ff4d3d',
        cyan:   '#4dd0e1',
        white:  '#e8e8e8',
        gray:   '#5a6472',
        grid:   'rgba(120,130,140,0.10)',
    },
};

// ── helpers ──────────────────────────────────────────────────

function qlPct(x, nd = 2) {
    return (x === null || x === undefined || !isFinite(x))
        ? '—' : (x * 100).toFixed(nd) + '%';
}

function qlNum(x, nd = 2) {
    return (x === null || x === undefined || !isFinite(x)) ? '—' : Number(x).toFixed(nd);
}

function qlSignColor(v) {
    if (v === null || v === undefined || !isFinite(v)) return QL.colors.gray;
    return v > 0 ? QL.colors.green : v < 0 ? QL.colors.red : QL.colors.gray;
}

function qlChart(canvasId, config) {
    if (QL.charts[canvasId]) QL.charts[canvasId].destroy();
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    QL.charts[canvasId] = new Chart(ctx, config);
    return QL.charts[canvasId];
}

function qlBaseOpts(extra = {}) {
    return Object.assign({
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: '#0a0a0a',
                borderColor: '#3a3a3a',
                borderWidth: 1,
                titleColor: QL.colors.amber,
                bodyColor: QL.colors.white,
                titleFont: { family: "'JetBrains Mono', monospace", size: 10 },
                bodyFont:  { family: "'JetBrains Mono', monospace", size: 10 },
            },
        },
        scales: {
            x: {
                grid:  { color: QL.colors.grid },
                ticks: { color: '#6a7480', maxTicksLimit: 8, maxRotation: 0,
                         font: { family: "'JetBrains Mono', monospace", size: 9 } },
            },
            y: {
                grid:  { color: QL.colors.grid },
                ticks: { color: '#6a7480', maxTicksLimit: 6,
                         font: { family: "'JetBrains Mono', monospace", size: 9 } },
            },
        },
    }, extra);
}

function qlStatChips(elId, chips) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.innerHTML = chips.map(c => `
        <div class="ql-stat" ${c.title ? `title="${c.title}"` : ''}>
            <span class="ql-stat-lbl">${c.label}</span>
            <span class="ql-stat-val" style="color:${c.color || QL.colors.white}">${c.value}</span>
        </div>`).join('');
}

function qlSetBadge(id, score, posLabel, negLabel) {
    const el = document.getElementById(id);
    if (!el) return;
    if (score === null || score === undefined) { el.textContent = 'N/A'; return; }
    const label = score > 15 ? posLabel : score < -15 ? negLabel : 'NEUTRAL';
    el.textContent = `${label} ${score > 0 ? '+' : ''}${score.toFixed(0)}`;
    el.style.color = score > 15 ? QL.colors.green
                   : score < -15 ? QL.colors.red : QL.colors.gray;
}

// ── entry point (called by switchTab) ────────────────────────

async function initQuantLab(force = false) {
    const sym = state.activeSymbol;
    const empty   = document.getElementById('ql-empty');
    const results = document.getElementById('ql-results');
    const errBox  = document.getElementById('ql-error');
    const loading = document.getElementById('ql-loading');

    if (!sym) {
        empty.style.display = 'flex';
        results.style.display = 'none';
        errBox.style.display = 'none';
        return;
    }
    if (!force && QL.loadedFor === sym && results.style.display !== 'none') return;

    empty.style.display = 'none';
    errBox.style.display = 'none';
    loading.style.display = 'flex';

    try {
        const res  = await fetch(`/api/quant-lab/${encodeURIComponent(sym)}`);
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);

        QL.loadedFor = sym;
        results.style.display = 'flex';
        document.getElementById('ql-automl').style.display = 'none';
        qlRenderHeader(data);
        qlRenderFairValue(data.fair_value);
        qlRenderKnn(data.knn);
        qlRenderCta(data.cta);
        qlRenderExhaustion(data.exhaustion);
        qlRenderSqueeze(data.squeeze);
        qlRenderMeanRev(data.mean_reversion);
    } catch (e) {
        results.style.display = 'none';
        errBox.style.display = 'flex';
        errBox.innerHTML = `<span class="ql-err-code">ERR</span> ${e.message}`;
    } finally {
        loading.style.display = 'none';
    }
}

// ── header strip ─────────────────────────────────────────────

function qlSetDial(markerId, readId, score, posWord, negWord) {
    const marker = document.getElementById(markerId);
    const read   = document.getElementById(readId);
    const v = (score === null || score === undefined) ? 0 : score;
    marker.style.left = `${(v + 100) / 2}%`;
    const word = v > 15 ? posWord : v < -15 ? negWord : 'NEUTRAL';
    read.textContent = `${word} ${v > 0 ? '+' : ''}${v.toFixed(0)}`;
    read.style.color = v > 15 ? QL.colors.green : v < -15 ? QL.colors.red : QL.colors.gray;
}

function qlRenderHeader(d) {
    document.getElementById('ql-sym').textContent  = d.symbol;
    document.getElementById('ql-last').textContent = qlNum(d.last_close, 2);
    document.getElementById('ql-asof').textContent =
        `${d.as_of} · ${d.n_bars} BARS · DAILY`;

    const c = d.composite || {};
    // valuation dial: positive = RICH (red side), negative = CHEAP (green side)
    const valMarker = document.getElementById('ql-val-marker');
    const valRead   = document.getElementById('ql-val-read');
    const v = c.valuation ?? 0;
    valMarker.style.left = `${(v + 100) / 2}%`;
    valRead.textContent  = (v > 15 ? 'RICH ' : v < -15 ? 'CHEAP ' : 'FAIR ')
                           + (v > 0 ? '+' : '') + v.toFixed(0);
    valRead.style.color  = v > 15 ? QL.colors.red : v < -15 ? QL.colors.green : QL.colors.gray;

    qlSetDial('ql-dir-marker', 'ql-dir-read', c.direction, 'HIGHER', 'LOWER');

    const conv = document.getElementById('ql-conv');
    conv.textContent = c.conviction || '—';
    conv.style.color = c.conviction === 'HIGH' ? QL.colors.green
                     : c.conviction === 'MED'  ? QL.colors.amber : QL.colors.gray;

    const comp = c.components || {};
    document.getElementById('ql-comp-chips').innerHTML = [
        ['CTA',  comp.cta,      v2 => (v2 > 0 ? '+' : '') + qlNum(v2, 0)],
        ['KNN',  comp.knn,      v2 => (v2 > 0 ? '+' : '') + qlNum(v2, 0)],
        ['EXH',  comp.exh_kick, v2 => (v2 > 0 ? '+' : '') + qlNum(v2, 0)],
        ['MR',   comp.mr,       v2 => (v2 > 0 ? '+' : '') + qlNum(v2, 0)],
        ['FV·1W', comp.fv_edge_1w, v2 => qlPct(v2, 2)],
    ].map(([lbl, val, fmt]) => `
        <span class="ql-chip">
            ${lbl} <b style="color:${qlSignColor(val)}">${val === null || val === undefined ? '—' : fmt(val)}</b>
        </span>`).join('');
}

// ── FV panel ─────────────────────────────────────────────────

function qlRenderFairValue(fv) {
    if (!fv) return;
    // valuation semantics: cheap = green (opportunity), rich = red
    const badge = document.getElementById('ql-fv-badge');
    if (fv.score === null || fv.score === undefined) {
        badge.textContent = 'N/A';
    } else {
        const v = fv.score;
        badge.textContent = `${v > 15 ? 'RICH' : v < -15 ? 'CHEAP' : 'FAIR'} ${v > 0 ? '+' : ''}${v.toFixed(0)}`;
        badge.style.color = v > 15 ? QL.colors.red : v < -15 ? QL.colors.green : QL.colors.gray;
    }

    const s = fv.series;
    qlChart('ql-fv-chart', {
        type: 'line',
        data: {
            labels: s.dates,
            datasets: [
                { data: s.up2, borderColor: 'transparent', pointRadius: 0, fill: false },
                { data: s.dn2, borderColor: 'transparent', pointRadius: 0,
                  fill: '-1', backgroundColor: 'rgba(251,139,30,0.05)' },
                { data: s.up1, borderColor: 'rgba(251,139,30,0.35)', borderWidth: 1,
                  borderDash: [3, 3], pointRadius: 0, fill: false },
                { data: s.dn1, borderColor: 'rgba(251,139,30,0.35)', borderWidth: 1,
                  borderDash: [3, 3], pointRadius: 0,
                  fill: '-1', backgroundColor: 'rgba(251,139,30,0.08)' },
                { label: 'FAIR VALUE', data: s.fv, borderColor: QL.colors.amber,
                  borderWidth: 1.5, pointRadius: 0, fill: false },
                { label: 'CLOSE', data: s.close, borderColor: QL.colors.white,
                  borderWidth: 1.5, pointRadius: 0, fill: false },
            ],
        },
        options: qlBaseOpts(),
    });

    // edge curve: avg forward 1-week return per valuation bucket
    const bins = fv.bins.filter(b => b.n > 0);
    qlChart('ql-edge-chart', {
        type: 'bar',
        data: {
            labels: bins.map(b => b.label),
            datasets: [{
                data: bins.map(b => b.mean === null ? null : b.mean * 100),
                backgroundColor: bins.map(b =>
                    b.current ? QL.colors.amber
                              : (b.mean > 0 ? 'rgba(0,210,106,0.55)' : 'rgba(255,77,61,0.55)')),
                borderColor: bins.map(b => b.current ? '#fff' : 'transparent'),
                borderWidth: bins.map(b => b.current ? 1 : 0),
            }],
        },
        options: qlBaseOpts({
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#0a0a0a', borderColor: '#3a3a3a', borderWidth: 1,
                    titleColor: QL.colors.amber, bodyColor: QL.colors.white,
                    callbacks: {
                        label: (c2) => {
                            const b = bins[c2.dataIndex];
                            return ` MEAN ${qlPct(b.mean)} · MED ${qlPct(b.median)} · HIT ${qlPct(b.hit, 0)} · N=${b.n}`;
                        },
                    },
                },
            },
        }),
    });

    const comp = fv.components || {};
    qlStatChips('ql-fv-stats', [
        { label: 'E[1W] HERE', value: qlPct(fv.edge_1w), color: qlSignColor(fv.edge_1w),
          title: 'Historical mean forward 1-week return in the current valuation bucket' },
        { label: 'TREND σ', value: qlNum(comp.trend_resid),
          title: 'Log-price residual vs 126-bar trend, in residual-σ' },
        { label: 'KAMA50 Z', value: qlNum(comp.kama_gap) },
        { label: '52W RANGE', value: qlNum(comp.range_pos) },
        { label: 'RSI %ILE', value: qlNum(comp.rsi_pct) },
    ]);
}

// ── KNN panel ────────────────────────────────────────────────

function qlRenderKnn(knn) {
    const panel = document.getElementById('ql-knn-panel');
    if (!knn) {
        qlSetBadge('ql-knn-badge', null, '', '');
        qlStatChips('ql-knn-stats', [{ label: 'STATUS', value: 'INSUFFICIENT HISTORY' }]);
        if (QL.charts['ql-knn-chart']) { QL.charts['ql-knn-chart'].destroy(); delete QL.charts['ql-knn-chart']; }
        return;
    }
    qlSetBadge('ql-knn-badge', knn.score, 'HIGHER', 'LOWER');

    const hist  = knn.history;
    const nH    = hist.close.length;
    const last  = hist.close[nH - 1];
    const labels = hist.dates.map(d2 => d2.slice(5))
        .concat(Array.from({ length: 21 }, (_, i) => `+${i + 1}`));

    const fanDs = (p, color, fillTo) => ({
        data: Array(nH - 1).fill(null)
            .concat([last])
            .concat(knn.fan[p].map(r => last * (1 + r))),
        borderColor: color, borderWidth: p === '50' ? 1.8 : 1,
        borderDash: p === '50' ? [] : [3, 3],
        pointRadius: 0, fill: fillTo, spanGaps: false,
        backgroundColor: fillTo ? 'rgba(77,208,225,0.10)' : undefined,
        label: `P${p}`,
    });

    const spaghetti = knn.analogs.map(a => ({
        data: Array(nH - 1).fill(null).concat([last]).concat(a.path.map(r => last * (1 + r))),
        borderColor: 'rgba(150,160,170,0.18)', borderWidth: 1,
        pointRadius: 0, fill: false, label: `≈ ${a.date}`,
    }));

    qlChart('ql-knn-chart', {
        type: 'line',
        data: {
            labels,
            datasets: [
                ...spaghetti,
                fanDs('90', 'rgba(77,208,225,0.45)', false),
                fanDs('10', 'rgba(77,208,225,0.45)', '-1'),
                fanDs('75', 'rgba(77,208,225,0.7)', false),
                fanDs('25', 'rgba(77,208,225,0.7)', '-1'),
                fanDs('50', QL.colors.cyan, false),
                { label: 'CLOSE',
                  data: hist.close.concat(Array(21).fill(null)),
                  borderColor: QL.colors.white, borderWidth: 1.6, pointRadius: 0, fill: false },
            ],
        },
        options: qlBaseOpts({ interaction: { mode: 'nearest', intersect: false } }),
    });

    const h5  = knn.horizons.find(h => h.h === 5)  || {};
    const h21 = knn.horizons.find(h => h.h === 21) || {};
    qlStatChips('ql-knn-stats', [
        { label: 'ANALOGS', value: `${knn.k} / ${knn.n_train}`,
          title: 'De-overlapped nearest neighbours / candidate bars' },
        { label: 'P(UP) 1W', value: qlPct(h5.p_up, 0), color: qlSignColor((h5.p_up ?? 0.5) - 0.5) },
        { label: 'MED 1W', value: qlPct(h5.median), color: qlSignColor(h5.median) },
        { label: 'P(UP) 1M', value: qlPct(h21.p_up, 0), color: qlSignColor((h21.p_up ?? 0.5) - 0.5) },
        { label: 'MED 1M', value: qlPct(h21.median), color: qlSignColor(h21.median) },
    ]);
}

// ── CTA panel ────────────────────────────────────────────────

function qlRenderCta(cta) {
    if (!cta) return;
    qlSetBadge('ql-cta-badge', cta.score, 'LONG', 'SHORT');

    const s = cta.series;
    qlChart('ql-cta-chart', {
        type: 'line',
        data: {
            labels: s.dates.map(d2 => d2.slice(2)),
            datasets: [
                { label: 'CTA', data: s.equity, borderColor: QL.colors.amber,
                  borderWidth: 1.6, pointRadius: 0, fill: false },
                { label: 'BUY&HOLD', data: s.bh, borderColor: QL.colors.gray,
                  borderWidth: 1.2, pointRadius: 0, fill: false },
            ],
        },
        options: qlBaseOpts({
            plugins: {
                legend: { display: true, position: 'top', align: 'end',
                          labels: { color: '#8a94a0', boxWidth: 14, boxHeight: 2,
                                    font: { family: "'JetBrains Mono', monospace", size: 9 } } },
                tooltip: { backgroundColor: '#0a0a0a', borderColor: '#3a3a3a', borderWidth: 1,
                           titleColor: QL.colors.amber, bodyColor: QL.colors.white },
            },
        }),
    });

    qlChart('ql-cta-fc-chart', {
        type: 'bar',
        data: {
            labels: s.dates.map(d2 => d2.slice(2)),
            datasets: [{
                data: s.forecast,
                backgroundColor: s.forecast.map(v =>
                    v > 0 ? 'rgba(0,210,106,0.6)' : 'rgba(255,77,61,0.6)'),
                barPercentage: 1.0, categoryPercentage: 1.0,
            }],
        },
        options: qlBaseOpts({
            scales: {
                x: { display: false },
                y: { min: -100, max: 100,
                     grid: { color: QL.colors.grid },
                     ticks: { color: '#6a7480', stepSize: 100,
                              font: { family: "'JetBrains Mono', monospace", size: 9 } } },
            },
        }),
    });

    const st = cta.stats, sp = (cta.speeds || []);
    qlStatChips('ql-cta-stats', [
        { label: 'POSITION', value: `${qlNum(cta.position, 2)}x`,
          color: qlSignColor(cta.position),
          title: 'Vol-targeted position (15% ann. target, ±2x cap)' },
        { label: 'SHARPE', value: `${qlNum(st.strategy.sharpe)} / ${qlNum(st.buy_hold.sharpe)}`,
          title: 'Strategy / Buy & Hold' },
        { label: 'CAGR', value: `${qlPct(st.strategy.cagr, 1)} / ${qlPct(st.buy_hold.cagr, 1)}` },
        { label: 'MAXDD', value: `${qlPct(st.strategy.maxdd, 0)} / ${qlPct(st.buy_hold.maxdd, 0)}` },
        ...sp.map(x => ({ label: x.label.replace('EWMAC ', 'E'),
                          value: (x.score > 0 ? '+' : '') + qlNum(x.score, 0),
                          color: qlSignColor(x.score) })),
    ]);
}

// ── Exhaustion panel ─────────────────────────────────────────

function qlRenderExhaustion(exh) {
    if (!exh) return;
    qlSetBadge('ql-exh-badge', exh.score, 'BLOW-OFF', 'WASHOUT');

    const s = exh.series;
    const n = s.close.length;
    const evUp = Array(n).fill(null), evDn = Array(n).fill(null);
    (exh.events || []).forEach(ev => {
        if (ev.i >= 0 && ev.i < n) (ev.side > 0 ? evUp : evDn)[ev.i] = ev.price;
    });

    qlChart('ql-exh-chart', {
        type: 'line',
        data: {
            labels: s.dates.map(d2 => d2.slice(2)),
            datasets: [
                { label: 'CLOSE', data: s.close, borderColor: QL.colors.white,
                  borderWidth: 1.4, pointRadius: 0, fill: false },
                { label: 'BLOW-OFF', data: evUp, borderColor: 'transparent',
                  pointStyle: 'triangle', pointRotation: 180, pointRadius: 6,
                  pointBackgroundColor: QL.colors.red, showLine: false },
                { label: 'CAPITULATION', data: evDn, borderColor: 'transparent',
                  pointStyle: 'triangle', pointRadius: 6,
                  pointBackgroundColor: QL.colors.green, showLine: false },
            ],
        },
        options: qlBaseOpts({ interaction: { mode: 'nearest', intersect: false } }),
    });

    qlChart('ql-exh-osc-chart', {
        type: 'line',
        data: {
            labels: s.dates.map(d2 => d2.slice(2)),
            datasets: [
                { data: s.e, borderColor: QL.colors.cyan, borderWidth: 1.2,
                  pointRadius: 0, fill: { target: 'origin' },
                  backgroundColor: 'rgba(77,208,225,0.07)' },
                { data: Array(n).fill(70),  borderColor: 'rgba(255,77,61,0.4)',
                  borderWidth: 1, borderDash: [4, 4], pointRadius: 0 },
                { data: Array(n).fill(-70), borderColor: 'rgba(0,210,106,0.4)',
                  borderWidth: 1, borderDash: [4, 4], pointRadius: 0 },
            ],
        },
        options: qlBaseOpts({
            scales: {
                x: { display: false },
                y: { min: -100, max: 100,
                     grid: { color: QL.colors.grid },
                     ticks: { color: '#6a7480', stepSize: 100,
                              font: { family: "'JetBrains Mono', monospace", size: 9 } } },
            },
        }),
    });

    const b = exh.stats.blowoff, c = exh.stats.capitulation, base = exh.stats.base;
    qlStatChips('ql-exh-stats', [
        { label: 'BLOW-OFF→1M', value: `${qlPct(b.fwd21)} (n=${b.n})`,
          color: qlSignColor(b.fwd21),
          title: 'Mean fwd 1-month return after past blow-off readings (score ≥ +70)' },
        { label: 'WASHOUT→1M', value: `${qlPct(c.fwd21)} (n=${c.n})`,
          color: qlSignColor(c.fwd21),
          title: 'Mean fwd 1-month return after past capitulation readings (score ≤ −70)' },
        { label: 'BASE 1M', value: qlPct(base.fwd21),
          title: 'Unconditional mean fwd 1-month return' },
        { label: 'TD COUNT', value: qlNum(exh.components.td_count, 0) },
        { label: 'VOL CLIMAX', value: qlNum(exh.components.vol_climax) },
    ]);
}

// ── Squeeze panel ────────────────────────────────────────────

function qlRenderSqueeze(sqz) {
    if (!sqz) return;
    const badge = document.getElementById('ql-sqz-badge');
    const sc = sqz.score;
    if (sc === null || sc === undefined) {
        badge.textContent = 'N/A';
    } else {
        badge.textContent = sc >= 85 ? `COILED ${sc.toFixed(0)} · ${sqz.trend_side}`
                          : sc >= 60 ? `TIGHTENING ${sc.toFixed(0)}`
                          : `LOOSE ${sc.toFixed(0)}`;
        badge.style.color = sc >= 85 ? QL.colors.amber
                          : sc >= 60 ? QL.colors.cyan : QL.colors.gray;
    }

    const s = sqz.series;
    const n = s.close.length;
    const ev = Array(n).fill(null);
    (sqz.events || []).forEach(e => { if (e.i >= 0 && e.i < n) ev[e.i] = e.price; });

    qlChart('ql-sqz-chart', {
        type: 'line',
        data: {
            labels: s.dates.map(d2 => d2.slice(2)),
            datasets: [
                { label: 'CLOSE', data: s.close, borderColor: QL.colors.white,
                  borderWidth: 1.4, pointRadius: 0, fill: false },
                { label: 'SQUEEZE START', data: ev, borderColor: 'transparent',
                  pointStyle: 'rectRot', pointRadius: 6,
                  pointBackgroundColor: QL.colors.amber, showLine: false },
            ],
        },
        options: qlBaseOpts({ interaction: { mode: 'nearest', intersect: false } }),
    });

    qlChart('ql-sqz-osc-chart', {
        type: 'line',
        data: {
            labels: s.dates.map(d2 => d2.slice(2)),
            datasets: [
                { data: s.sq, borderColor: QL.colors.amber, borderWidth: 1.2,
                  pointRadius: 0, fill: { target: 'origin' },
                  backgroundColor: 'rgba(251,139,30,0.08)' },
                { data: Array(n).fill(85), borderColor: 'rgba(251,139,30,0.45)',
                  borderWidth: 1, borderDash: [4, 4], pointRadius: 0 },
            ],
        },
        options: qlBaseOpts({
            scales: {
                x: { display: false },
                y: { min: 0, max: 100,
                     grid: { color: QL.colors.grid },
                     ticks: { color: '#6a7480', stepSize: 50,
                              font: { family: "'JetBrains Mono', monospace", size: 9 } } },
            },
        }),
    });

    const st = sqz.stats;
    qlStatChips('ql-sqz-stats', [
        { label: 'COMPRESSION', value: `${qlNum(sqz.score, 0)}/100`,
          color: sqz.score >= 85 ? QL.colors.amber : QL.colors.white },
        { label: 'TREND SIDE', value: sqz.trend_side,
          color: sqz.trend_side === 'LONG' ? QL.colors.green
               : sqz.trend_side === 'SHORT' ? QL.colors.red : QL.colors.gray,
          title: 'EWMAC 16/64 sign — the likely breakout direction' },
        { label: '|1M| AFTER SQZ', value: `${qlPct(st.ev_abs_1m)} (n=${st.n_events})`,
          title: 'Mean absolute 1-month move after past compression episodes' },
        { label: '|1M| BASE', value: qlPct(st.base_abs_1m) },
        { label: 'TREND CALLED IT', value: qlPct(st.dir_agree, 0),
          title: 'How often the trend filter sign matched the post-squeeze move' },
    ]);
}

// ── Mean Reversion panel ─────────────────────────────────────

function qlRenderMeanRev(mr) {
    const badge = document.getElementById('ql-mr-badge');
    if (!mr) {
        badge.textContent = 'N/A';
        qlStatChips('ql-mr-stats', [{ label: 'STATUS', value: 'INSUFFICIENT HISTORY' }]);
        if (QL.charts['ql-mr-chart']) { QL.charts['ql-mr-chart'].destroy(); delete QL.charts['ql-mr-chart']; }
        return;
    }
    badge.textContent = mr.character;
    badge.style.color = mr.character === 'MEAN-REVERTING' ? QL.colors.cyan
                      : mr.character === 'TRENDING' ? QL.colors.amber : QL.colors.gray;

    const s = mr.series;
    const n = s.close.length;
    const hasProj = (s.proj || []).length === 21;
    const labels = s.dates.map(d2 => d2.slice(5))
        .concat(Array.from({ length: 21 }, (_, i) => `+${i + 1}`));
    const lastClose = s.close[n - 1];

    qlChart('ql-mr-chart', {
        type: 'line',
        data: {
            labels,
            datasets: [
                { label: 'FAIR VALUE', data: s.fv.concat(hasProj ? s.fv_path : Array(21).fill(null)),
                  borderColor: QL.colors.amber, borderWidth: 1.3, pointRadius: 0, fill: false },
                ...(hasProj ? [{
                  label: 'E[REVERSION PATH]',
                  data: Array(n - 1).fill(null).concat([lastClose]).concat(s.proj),
                  borderColor: QL.colors.cyan, borderWidth: 1.6, borderDash: [5, 4],
                  pointRadius: 0, fill: false }] : []),
                { label: 'CLOSE', data: s.close.concat(Array(21).fill(null)),
                  borderColor: QL.colors.white, borderWidth: 1.5, pointRadius: 0, fill: false },
            ],
        },
        options: qlBaseOpts({ interaction: { mode: 'nearest', intersect: false } }),
    });

    qlStatChips('ql-mr-stats', [
        { label: 'STRETCH', value: `${qlNum(mr.resid_z, 1)}σ`,
          color: qlSignColor(-(mr.resid_z ?? 0)),
          title: 'Log-price residual vs the 126-bar trend channel' },
        { label: 'HALF-LIFE', value: mr.half_life === null ? 'NONE' : `${qlNum(mr.half_life, 0)} BARS`,
          title: 'Ornstein-Uhlenbeck half-life of the residual (AR(1) fit)' },
        { label: 'AR(1) φ', value: qlNum(mr.phi, 3) },
        { label: 'HURST', value: qlNum(mr.hurst, 2),
          title: '< 0.5 mean-reverting · ≈ 0.5 random walk · > 0.5 trending' },
        { label: 'VR(10)', value: qlNum(mr.vr10, 2),
          title: 'Variance ratio: < 1 mean-reverting, > 1 trending' },
        { label: 'REVERT HIT', value: mr.revert_hit === null ? '—'
              : `${qlPct(mr.revert_hit, 0)} (n=${mr.n_stretch_events})`,
          title: 'After |stretch| ≥ 2σ, how often it was smaller 21 bars later' },
    ]);
}

// ── AutoML (PyCaret, on demand) ──────────────────────────────

async function qlRunAutoML() {
    const sym = state.activeSymbol;
    if (!sym) { toast('Select a symbol first', 'warning'); return; }

    const btn  = document.getElementById('ql-automl-btn');
    const box  = document.getElementById('ql-automl');
    btn.disabled = true;
    btn.textContent = 'TRAINING…';
    box.style.display = 'block';
    box.innerHTML = `<div class="ql-automl-status">
        <span class="spinner"></span> PYCARET ▸ COMPARING 5 CLASSIFIERS ON 17 FEATURES
        — 5D HORIZON · TIMESERIES CV · this can take 1–3 min</div>`;

    try {
        const res  = await fetch(`/api/pycaret/${encodeURIComponent(sym)}?horizon=5&n_models=5`);
        const d    = await res.json();
        if (!res.ok || d.error) throw new Error(d.error || `HTTP ${res.status}`);

        const up   = d.prediction === 'UP';
        const fi   = Object.entries(d.feature_importance || {})
                       .sort((a, b2) => b2[1] - a[1]).slice(0, 6);
        const fiMax = fi.length ? fi[0][1] : 1;

        box.innerHTML = `
            <div class="ql-automl-head">
                <span class="ql-fn">ML</span> PYCARET AUTOML · ${d.symbol} · ${d.horizon_days}D HORIZON
                <span class="ql-automl-pred" style="color:${up ? QL.colors.green : QL.colors.red}">
                    ${d.prediction} ${qlPct(d.confidence, 0)} CONF</span>
                <span class="ql-automl-meta">${d.training_samples} SAMPLES · AS OF ${d.as_of}</span>
            </div>
            <div class="ql-automl-body">
                <table class="ql-table">
                    <thead><tr><th>MODEL</th><th>ACC</th><th>AUC</th><th>F1</th></tr></thead>
                    <tbody>
                        ${(d.leaderboard || []).map((r, i) => `
                            <tr class="${i === 0 ? 'ql-tr-best' : ''}">
                                <td>${r.Model || '—'}</td>
                                <td>${qlNum(r.Accuracy, 3)}</td>
                                <td>${qlNum(r.AUC, 3)}</td>
                                <td>${qlNum(r.F1, 3)}</td>
                            </tr>`).join('')}
                    </tbody>
                </table>
                <div class="ql-fi">
                    <div class="ql-fi-title">FEATURE IMPORTANCE (BEST MODEL)</div>
                    ${fi.map(([k, v]) => `
                        <div class="ql-fi-row">
                            <span class="ql-fi-name">${k}</span>
                            <div class="ql-fi-bar"><div style="width:${(v / fiMax * 100).toFixed(0)}%"></div></div>
                            <span class="ql-fi-val">${qlNum(v, 3)}</span>
                        </div>`).join('') || '<div class="ql-fi-row">n/a for this model</div>'}
                </div>
            </div>`;
    } catch (e) {
        box.innerHTML = `<div class="ql-automl-status" style="color:${QL.colors.red}">
            AUTOML FAILED — ${e.message}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = 'AUTOML ▸ RUN';
    }
}
