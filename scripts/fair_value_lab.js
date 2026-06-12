/* ============================================================
   fair_value_lab.js — Fair Value tab (FiveThirtyEight style)
   Renders /api/fair-value/<symbol>?model=trend|pca:
     header  : forecast cards (1W/1M), today's percentile, gap,
               OOS report card (hit rates, IC, price-does-the-work)
     panel 1 : price vs fair value with ±1σ/±2σ bands
     panel 2 : divergence in σ with ±1/2/3σ guide lines
     panel 3 : distribution of the divergence (histogram +
               normal fit + KDE) with a TODAY marker
   ============================================================ */

const FVD = {
    model: 'trend',
    loadedFor: null,          // `${symbol}|${model}`
    charts: {},
    // FiveThirtyEight palette
    c: {
        blue:   '#30a2da',
        red:    '#fc4f30',
        yellow: '#e5ae38',
        green:  '#6d904f',
        gray:   '#8b8b8b',
        dark:   '#3c3c3c',
        grid:   '#dcdcdc',
        bg:     '#f0f0f0',
    },
};

// ── helpers ──────────────────────────────────────────────────

function fvdPct(x, nd = 1) {
    return (x === null || x === undefined || !isFinite(x))
        ? '—' : (x >= 0 ? '+' : '') + (x * 100).toFixed(nd) + '%';
}

function fvdOrdinal(p) {
    if (p === null || p === undefined) return '—';
    const n = Math.round(p * 100);
    const suff = (n % 10 === 1 && n % 100 !== 11) ? 'st'
               : (n % 10 === 2 && n % 100 !== 12) ? 'nd'
               : (n % 10 === 3 && n % 100 !== 13) ? 'rd' : 'th';
    return `${n}${suff}`;
}

function fvdChart(id, config) {
    if (FVD.charts[id]) FVD.charts[id].destroy();
    const el = document.getElementById(id);
    if (!el) return;
    FVD.charts[id] = new Chart(el, config);
}

function fvdOpts(extra = {}) {
    return Object.assign({
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: '#ffffff', borderColor: '#c7c7c7', borderWidth: 1,
                titleColor: '#111', bodyColor: '#3c3c3c',
                titleFont: { family: 'Helvetica, Arial, sans-serif', size: 11, weight: 'bold' },
                bodyFont:  { family: 'Helvetica, Arial, sans-serif', size: 11 },
            },
        },
        scales: {
            x: { grid:  { color: FVD.c.grid },
                 ticks: { color: '#777', maxTicksLimit: 7, maxRotation: 0,
                          font: { family: 'Helvetica, Arial, sans-serif', size: 10 } } },
            y: { grid:  { color: FVD.c.grid },
                 ticks: { color: '#777', maxTicksLimit: 6,
                          font: { family: 'Helvetica, Arial, sans-serif', size: 10 } } },
        },
    }, extra);
}

// ── entry point ──────────────────────────────────────────────

async function initFairValueLab(force = false) {
    const sym     = state.activeSymbol;
    const empty   = document.getElementById('fvd-empty');
    const results = document.getElementById('fvd-results');
    const errBox  = document.getElementById('fvd-error');
    const loading = document.getElementById('fvd-loading');

    if (!sym) {
        empty.style.display = 'flex';
        results.style.display = 'none';
        errBox.style.display = 'none';
        return;
    }
    const key = `${sym}|${FVD.model}`;
    if (!force && FVD.loadedFor === key && results.style.display !== 'none') return;

    empty.style.display = 'none';
    errBox.style.display = 'none';
    loading.style.display = 'flex';

    try {
        const res  = await fetch(`/api/fair-value/${encodeURIComponent(sym)}?model=${FVD.model}`);
        const data = await res.json();
        if (!res.ok || data.error) throw new Error(data.error || `HTTP ${res.status}`);
        FVD.loadedFor = key;
        results.style.display = 'block';
        fvdRenderHeader(data);
        fvdRenderPrice(data);
        fvdRenderDivergence(data);
        fvdRenderDistribution(data);
    } catch (e) {
        results.style.display = 'none';
        errBox.style.display = 'block';
        errBox.textContent = `MODEL ERROR — ${e.message}`;
    } finally {
        loading.style.display = 'none';
    }
}

function fvdSetModel(m) {
    FVD.model = m;
    document.getElementById('fvd-model-trend').classList.toggle('fvd-model-active', m === 'trend');
    document.getElementById('fvd-model-pca').classList.toggle('fvd-model-active', m === 'pca');
    initFairValueLab(true);
}

// ── header ───────────────────────────────────────────────────

const FVD_VERDICT = {
    STRONG:       { color: '#6d904f', text: 'STRONG — divergences have reverted out of sample' },
    OK:           { color: '#e5ae38', text: 'OK — some out-of-sample edge, size accordingly' },
    WEAK:         { color: '#fc4f30', text: 'WEAK — divergence has NOT predicted reversion here' },
    INSUFFICIENT: { color: '#8b8b8b', text: 'INSUFFICIENT — too few ±2σ events to judge' },
};

function fvdRenderHeader(d) {
    const cur = d.current, v = d.validation;
    const z   = cur.z ?? 0;
    const stateWord = z >= 2 ? 'rich' : z >= 1 ? 'somewhat rich'
                    : z <= -2 ? 'cheap' : z <= -1 ? 'somewhat cheap' : 'near fair value';

    document.getElementById('fvd-title').textContent =
        `Is ${d.symbol} away from fair value?`;
    document.getElementById('fvd-subtitle').textContent =
        `${d.meta.anchor} · today ${d.symbol} trades ${fvdPct(cur.gap_pct)} from the model ` +
        `(z = ${z >= 0 ? '+' : ''}${z.toFixed(1)}σ, ${stateWord}). ` +
        `All forecasts are walk-forward: coefficients only ever see data that was available at the time.`;
    document.getElementById('fvd-universe').textContent =
        d.universe ? `PANEL: ${d.universe.length} ASSETS · ${(d.meta.panel_scope || 'WATCHLIST').toUpperCase()}` : '';

    const pctColor = (cur.pct_emp >= 0.95 || cur.pct_emp <= 0.05) ? FVD.c.red
                   : (cur.pct_emp >= 0.84 || cur.pct_emp <= 0.16) ? FVD.c.yellow : FVD.c.dark;
    const fc = (x) => x === null ? '—' : fvdPct(x, 2);
    const fcColor = (x) => x === null ? FVD.c.gray : x > 0 ? FVD.c.green : FVD.c.red;
    const verdict = FVD_VERDICT[v.verdict] || FVD_VERDICT.INSUFFICIENT;

    document.getElementById('fvd-cards').innerHTML = `
        <div class="fvd-card">
            <div class="fvd-card-label">TODAY'S PERCENTILE</div>
            <div class="fvd-card-big" style="color:${pctColor}">${fvdOrdinal(cur.pct_emp)}</div>
            <div class="fvd-card-foot">of the last ${d.dist.z_hist.length} bars (normal fit: ${fvdOrdinal(cur.pct_norm)})</div>
        </div>
        <div class="fvd-card">
            <div class="fvd-card-label">GAP TO FAIR VALUE</div>
            <div class="fvd-card-big" style="color:${cur.gap_pct > 0 ? FVD.c.red : FVD.c.green}">${fvdPct(cur.gap_pct)}</div>
            <div class="fvd-card-foot">z = ${z >= 0 ? '+' : ''}${z.toFixed(2)}σ</div>
        </div>
        <div class="fvd-card">
            <div class="fvd-card-label">1-WEEK FORECAST</div>
            <div class="fvd-card-big" style="color:${fcColor(cur.fcast_1w)}">${fc(cur.fcast_1w)}</div>
            <div class="fvd-card-foot">walk-forward regression on z</div>
        </div>
        <div class="fvd-card">
            <div class="fvd-card-label">1-MONTH FORECAST</div>
            <div class="fvd-card-big" style="color:${fcColor(cur.fcast_1m)}">${fc(cur.fcast_1m)}</div>
            <div class="fvd-card-foot">walk-forward regression on z</div>
        </div>
        <div class="fvd-card fvd-card-verdict" style="border-top-color:${verdict.color}">
            <div class="fvd-card-label">MODEL VERDICT</div>
            <div class="fvd-card-big" style="color:${verdict.color}">${v.verdict}</div>
            <div class="fvd-card-foot">${verdict.text}</div>
        </div>`;

    const pw = v.price_work;
    const item = (label, value, title = '') => `
        <div class="fvd-rep-item" title="${title}">
            <span class="fvd-rep-label">${label}</span>
            <span class="fvd-rep-val">${value}</span>
        </div>`;
    document.getElementById('fvd-report').innerHTML =
        `<div class="fvd-rep-head">OUT-OF-SAMPLE REPORT CARD · ±2σ EVENTS</div>` +
        item('HIT 1W', v.h5.hit === null ? '—' : (v.h5.hit * 100).toFixed(0) + '%',
             'After |z| ≥ 2, how often price moved toward the anchor within a week') +
        item('HIT 1M', v.h21.hit === null ? '—' : (v.h21.hit * 100).toFixed(0) + '%') +
        item('IC 1M', v.h21.ic === null ? '—' : v.h21.ic.toFixed(2),
             'Correlation between walk-forward forecasts and realised 1-month returns') +
        item('EVENTS', `${v.h21.n_events}`) +
        item('CHEAP → 1M', fvdPct(v.h21.mean_cheap, 1),
             'Mean realised 1-month return after z ≤ −2 (cheap) events') +
        item('RICH → 1M', fvdPct(v.h21.mean_rich, 1)) +
        item('CONVERGED', pw.conv_rate === null ? '—' : (pw.conv_rate * 100).toFixed(0) + '%',
             'Share of ±2σ events where the gap was smaller a month later') +
        item('PRICE DOES THE WORK', pw.price_share === null ? '—' : (pw.price_share * 100).toFixed(0) + '%',
             'Of the gap that closed, the fraction closed by PRICE moving to the model — not the model chasing price');

    document.getElementById('fvd-footer').textContent =
        `SOURCE: LOCAL OHLCV (${d.n_bars} BARS) · MODEL: ${d.meta.anchor.toUpperCase()} · AS OF ${d.as_of} · ` +
        `FORECASTS REFIT EVERY 21 BARS ON AN EXPANDING WINDOW`;
}

// ── panel 1: price vs fair value ─────────────────────────────

function fvdRenderPrice(d) {
    const s = d.series;
    fvdChart('fvd-price-chart', {
        type: 'line',
        data: {
            labels: s.dates,
            datasets: [
                { data: s.up2, borderColor: 'transparent', pointRadius: 0, fill: false },
                { data: s.dn2, borderColor: 'transparent', pointRadius: 0,
                  fill: '-1', backgroundColor: 'rgba(252,79,48,0.06)' },
                { data: s.up1, borderColor: 'rgba(252,79,48,0.25)', borderWidth: 1,
                  pointRadius: 0, fill: false },
                { data: s.dn1, borderColor: 'rgba(252,79,48,0.25)', borderWidth: 1,
                  pointRadius: 0, fill: '-1', backgroundColor: 'rgba(252,79,48,0.10)' },
                { label: 'FAIR VALUE', data: s.fv, borderColor: FVD.c.red,
                  borderWidth: 2.5, pointRadius: 0, fill: false },
                { label: d.symbol, data: s.close, borderColor: FVD.c.blue,
                  borderWidth: 2.5, pointRadius: 0, fill: false },
            ],
        },
        options: fvdOpts({
            plugins: {
                legend: { display: true, position: 'top', align: 'end',
                          labels: { color: '#3c3c3c', boxWidth: 18, boxHeight: 3,
                                    filter: (it) => !!it.text,
                                    font: { family: 'Helvetica, Arial, sans-serif', size: 11, weight: 'bold' } } },
                tooltip: { backgroundColor: '#fff', borderColor: '#c7c7c7', borderWidth: 1,
                           titleColor: '#111', bodyColor: '#3c3c3c' },
            },
        }),
    });
}

// ── panel 2: divergence with σ guide lines ───────────────────

function fvdRenderDivergence(d) {
    const s = d.series;
    const n = s.z.length;
    const guide = (lvl, color, width = 1) => ({
        data: Array(n).fill(lvl), borderColor: color, borderWidth: width,
        borderDash: [6, 4], pointRadius: 0, fill: false,
    });
    const zMax = Math.ceil(Math.max(3.4, ...s.z.filter(v => v !== null).map(Math.abs)) + 0.3);

    fvdChart('fvd-div-chart', {
        type: 'line',
        data: {
            labels: s.dates,
            datasets: [
                { data: s.z, borderColor: FVD.c.blue, borderWidth: 2.2, pointRadius: 0,
                  fill: { target: 'origin' }, backgroundColor: 'rgba(48,162,218,0.12)' },
                guide(0, '#9b9b9b'),
                guide(1, '#b5b5b5'), guide(-1, '#b5b5b5'),
                guide(2, '#8b8b8b', 1.4), guide(-2, '#8b8b8b', 1.4),
                guide(3, FVD.c.red, 1.4), guide(-3, FVD.c.red, 1.4),
            ],
        },
        options: fvdOpts({
            scales: {
                x: { grid: { color: FVD.c.grid },
                     ticks: { color: '#777', maxTicksLimit: 7, maxRotation: 0,
                              font: { family: 'Helvetica, Arial, sans-serif', size: 10 } } },
                y: { min: -zMax, max: zMax,
                     grid: { color: FVD.c.grid },
                     ticks: { color: '#777', stepSize: 1,
                              font: { family: 'Helvetica, Arial, sans-serif', size: 10 },
                              callback: (v) => `${v > 0 ? '+' : ''}${v}σ` } },
            },
        }),
    });
}

// ── panel 3: distribution of the divergence ──────────────────

function fvdRenderDistribution(d) {
    const zs  = d.dist.z_hist.filter(v => v !== null);
    const cur = d.current.z;
    const mu  = d.dist.mu, sd = Math.max(d.dist.sd, 1e-6);

    const lo = Math.min(-3.5, Math.min(...zs), cur) - 0.25;
    const hi = Math.max(3.5, Math.max(...zs), cur) + 0.25;
    const nb = 27, bw = (hi - lo) / nb;
    const centers = Array.from({ length: nb }, (_, i) => lo + (i + 0.5) * bw);
    const counts  = Array(nb).fill(0);
    zs.forEach(v => {
        const k = Math.min(nb - 1, Math.max(0, Math.floor((v - lo) / bw)));
        counts[k]++;
    });

    // parametric: normal fit, scaled to counts
    const pdf = (x) => Math.exp(-0.5 * ((x - mu) / sd) ** 2) / (sd * Math.sqrt(2 * Math.PI));
    const normY = centers.map(x => pdf(x) * zs.length * bw);

    // non-parametric: gaussian KDE, Silverman bandwidth
    const kbw = 1.06 * sd * Math.pow(zs.length, -0.2);
    const kdeY = centers.map(x => {
        let s2 = 0;
        for (const v of zs) s2 += Math.exp(-0.5 * ((x - v) / kbw) ** 2);
        return s2 / (zs.length * kbw * Math.sqrt(2 * Math.PI)) * zs.length * bw;
    });

    // TODAY marker: a thin bar at the current z's bin
    const peak = Math.max(...counts, ...normY, ...kdeY);
    const curIdx = Math.min(nb - 1, Math.max(0, Math.floor((cur - lo) / bw)));
    const marker = Array(nb).fill(null);
    marker[curIdx] = peak * 1.06;

    document.getElementById('fvd-dist-sub').textContent =
        `Last ${zs.length} bars · gray bars = observed, green = kernel density, blue = normal fit · ` +
        `TODAY: z = ${cur >= 0 ? '+' : ''}${cur.toFixed(2)}σ → ${fvdOrdinal(d.current.pct_emp)} percentile`;

    fvdChart('fvd-dist-chart', {
        type: 'bar',
        data: {
            labels: centers.map(c2 => c2.toFixed(1)),
            datasets: [
                { type: 'bar', label: 'TODAY', data: marker,
                  backgroundColor: FVD.c.red, barPercentage: 0.25, categoryPercentage: 1.0 },
                { type: 'bar', label: 'OBSERVED', data: counts,
                  backgroundColor: '#c9c9c9', barPercentage: 1.0, categoryPercentage: 0.92 },
                { type: 'line', label: 'KDE', data: kdeY, borderColor: FVD.c.green,
                  borderWidth: 2.2, pointRadius: 0, fill: false, tension: 0.35 },
                { type: 'line', label: 'NORMAL FIT', data: normY, borderColor: FVD.c.blue,
                  borderWidth: 2, borderDash: [5, 4], pointRadius: 0, fill: false, tension: 0.35 },
            ],
        },
        options: fvdOpts({
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: true, position: 'top', align: 'end',
                          labels: { color: '#3c3c3c', boxWidth: 14, boxHeight: 3,
                                    font: { family: 'Helvetica, Arial, sans-serif', size: 10, weight: 'bold' } } },
                tooltip: { backgroundColor: '#fff', borderColor: '#c7c7c7', borderWidth: 1,
                           titleColor: '#111', bodyColor: '#3c3c3c',
                           callbacks: { title: (it) => `z ≈ ${it[0].label}σ` } },
            },
            scales: {
                x: { grid: { display: false },
                     ticks: { color: '#777', maxTicksLimit: 9, maxRotation: 0,
                              font: { family: 'Helvetica, Arial, sans-serif', size: 10 },
                              callback: function (v, i) {
                                  const x = parseFloat(this.getLabelForValue(i));
                                  return Math.abs(x % 1) < bw ? `${x > 0 ? '+' : ''}${Math.round(x)}σ` : '';
                              } } },
                y: { grid: { color: FVD.c.grid },
                     ticks: { color: '#777', maxTicksLimit: 5,
                              font: { family: 'Helvetica, Arial, sans-serif', size: 10 } } },
            },
        }),
    });
}
