/**
 * swirligram.js — RSI & KAMA-Pct Phase-Space (Swirligram) tab
 *
 * Charts:
 *   RSI:       X = RSI,        Y = Δ RSI per bar   — gradient trail + current dot
 *   KAMA Pct:  X = Pct Rank,   Y = Δ Pct per bar   — same pattern, different colour
 *   Timelines: classic line with zone bands (RSI 0-100 or Pct Rank 0-100)
 */

// ── State ──────────────────────────────────────────────────────────────────────
const swState = {
    charts: {
        dailyPhase:    null,
        weeklyPhase:   null,
        dailyTimeline: null,
        weeklyTimeline:null,
        kamaFastPhase: null,
        kamaTrendPhase:null,
        kamaFastTL:    null,
        kamaTrendTL:   null,
    },
};

// ── Colour maps ────────────────────────────────────────────────────────────────
const SW_SIG_COLORS = {
    green:  '#22c55e',
    yellow: '#eab308',
    orange: '#f97316',
    gray:   '#64748b',
};

const SW_BADGE_CLASS = {
    green:  'sw-badge-green',
    yellow: 'sw-badge-yellow',
    orange: 'sw-badge-orange',
    gray:   'sw-badge-gray',
};

// ── Init ───────────────────────────────────────────────────────────────────────
function initSwirligram() {
    if (typeof state !== 'undefined' && state.activeSymbol) {
        swLoad();
    }
}

// ── Load data ──────────────────────────────────────────────────────────────────
async function swLoad() {
    const symbol = (typeof state !== 'undefined') ? state.activeSymbol : null;
    if (!symbol) return;

    const trail  = parseInt(document.getElementById('sw-trail')?.value  || '90',  10);
    const period = parseInt(document.getElementById('sw-period')?.value || '14', 10);

    _swSetLoading(true);

    try {
        const data = await apiFetch(
            `${API}/swirligram/${encodeURIComponent(symbol)}?trail=${trail}&period=${period}`
        );

        _swRenderCombinedBadge(data.combined);
        _swUpdateHeaderStats(data.daily, data.weekly, data.kama);

        _swRenderRsiPhaseChart ('sw-daily-phase',    data.daily,  'daily',  'dailyPhase');
        _swRenderSignalBox     ('sw-daily-signal',   data.daily?.signal);
        _swRenderRsiTimeline   ('sw-daily-timeline', data.daily,  'dailyTimeline');

        if (data.weekly) {
            _swRenderRsiPhaseChart ('sw-weekly-phase',    data.weekly, 'weekly', 'weeklyPhase');
            _swRenderSignalBox     ('sw-weekly-signal',   data.weekly?.signal);
            _swRenderRsiTimeline   ('sw-weekly-timeline', data.weekly, 'weeklyTimeline');
        }

        if (data.kama) {
            _swRenderKamaPhaseChart('sw-kama-fast-phase',  data.kama.fast,  'fast',  'kamaFastPhase');
            _swRenderSignalBox     ('sw-kama-fast-signal', data.kama.fast?.signal);
            _swRenderKamaTimeline  ('sw-kama-fast-tl',     data.kama.fast,  'kamaFastTL');

            _swRenderKamaPhaseChart('sw-kama-trend-phase',  data.kama.trend, 'trend', 'kamaTrendPhase');
            _swRenderSignalBox     ('sw-kama-trend-signal', data.kama.trend?.signal);
            _swRenderKamaTimeline  ('sw-kama-trend-tl',     data.kama.trend, 'kamaTrendTL');
        }
    } catch (e) {
        toast('Swirligram: ' + e.message, 'error');
    } finally {
        _swSetLoading(false);
    }
}

// ── Combined badge ─────────────────────────────────────────────────────────────
function _swRenderCombinedBadge(combined) {
    const badge = document.getElementById('sw-combined-badge');
    const lbl   = document.getElementById('sw-combined-label');
    const score = document.getElementById('sw-combined-score');
    if (!badge || !lbl) return;

    badge.className = 'sw-combined-badge ' + (SW_BADGE_CLASS[combined?.color] || 'sw-badge-gray');
    lbl.textContent   = combined?.label  ?? '—';
    if (score) score.textContent = combined?.score != null ? `${combined.score}/100` : '';
}

function _swUpdateHeaderStats(daily, weekly, kama) {
    const dRsi   = daily?.current?.rsi;
    const dDrsi  = daily?.current?.drsi;
    const wRsi   = weekly?.current?.rsi;
    const wDrsi  = weekly?.current?.drsi;
    const kfPct  = kama?.fast?.current?.pct;
    const kfDpct = kama?.fast?.current?.dpct;
    const ktPct  = kama?.trend?.current?.pct;
    const ktDpct = kama?.trend?.current?.dpct;

    const setEl = (id, text, color) => {
        const el = document.getElementById(id);
        if (el) { el.textContent = text; if (color) el.style.color = color; }
    };

    const fmtD = (v, dp) => v == null ? '—' : (v >= 0 ? `↑ +${v.toFixed(dp)}` : `↓ ${v.toFixed(dp)}`);
    const dCol = v => v == null ? '' : v > 0 ? 'var(--green)' : v < 0 ? 'var(--red)' : '';

    setEl('sw-daily-rsi-val',   dRsi  != null ? dRsi.toFixed(1)  : '—');
    setEl('sw-weekly-rsi-val',  wRsi  != null ? wRsi.toFixed(1)  : '—');
    setEl('sw-daily-drsi-val',  fmtD(dDrsi, 1),  dCol(dDrsi));
    setEl('sw-weekly-drsi-val', fmtD(wDrsi, 2),  dCol(wDrsi));
    setEl('sw-kama-fast-val',   kfPct  != null ? kfPct.toFixed(0)  + '%' : '—');
    setEl('sw-kama-trend-val',  ktPct  != null ? ktPct.toFixed(0)  + '%' : '—');
    setEl('sw-kama-fast-dir',   fmtD(kfDpct, 1), dCol(kfDpct));
    setEl('sw-kama-trend-dir',  fmtD(ktDpct, 1), dCol(ktDpct));
}

// ── Generic phase-space chart ──────────────────────────────────────────────────
/**
 * Renders a phase-space scatter+trail chart.
 * @param {string}   canvasId   - id of <canvas> element
 * @param {number[]} xArr       - X values (time-ordered)
 * @param {number[]} yArr       - Y values (Δ per bar)
 * @param {string[]} dates      - ISO date strings (for tooltip)
 * @param {object}   signal     - {color, label, ...} for current-position dot colour
 * @param {string}   stateKey   - key in swState.charts to store instance
 * @param {object}   opts       - {xLabel, yLabel, xMin, xMax, trailColor, buyZones, xBands}
 */
function _swRenderPhaseChart(canvasId, xArr, yArr, dates, signal, stateKey, opts = {}) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !xArr?.length) return;

    if (swState.charts[stateKey]) {
        try { swState.charts[stateKey].destroy(); } catch (_) {}
        swState.charts[stateKey] = null;
    }

    const {
        xLabel     = 'X',
        yLabel     = 'Δ / bar',
        xMin       = 0,
        xMax       = 100,
        trailColor = '59,130,246',
        buyZones   = [],
        xBands     = [],
    } = opts;

    const pts = [];
    for (let i = 0; i < xArr.length; i++) {
        if (xArr[i] != null && yArr[i] != null && !isNaN(xArr[i]) && !isNaN(yArr[i])) {
            pts.push({ x: xArr[i], y: yArr[i], date: dates[i] });
        }
    }
    if (pts.length < 3) return;

    const n        = pts.length;
    const sigColor = SW_SIG_COLORS[signal?.color] || '#64748b';

    const ptColors = pts.map((_, i) => {
        const t = i / (n - 1);
        return `rgba(${trailColor},${(0.08 + t * 0.85).toFixed(2)})`;
    });

    // Zone background + zero-line plugin (per chart)
    const zoneBgPlugin = {
        id: 'swZoneBg_' + canvasId,
        beforeDraw(chart) {
            const ca = chart.chartArea;
            const sx = chart.scales?.x;
            const sy = chart.scales?.y;
            if (!ca || !sx || !sy) return;
            const { ctx } = chart;
            ctx.save();
            ctx.beginPath();
            ctx.rect(ca.left, ca.top, ca.width, ca.height);
            ctx.clip();

            xBands.forEach(b => {
                const x1 = sx.getPixelForValue(b.xMin);
                const x2 = sx.getPixelForValue(b.xMax);
                ctx.fillStyle = b.color;
                ctx.fillRect(x1, ca.top, x2 - x1, ca.height);
                if (b.label) {
                    ctx.fillStyle = 'rgba(255,255,255,0.18)';
                    ctx.font = '8px Inter, sans-serif';
                    ctx.textAlign = 'center';
                    ctx.fillText(b.label, (x1 + x2) / 2, ca.top + 10);
                }
            });

            const y0 = sy.getPixelForValue(0);
            if (y0 >= ca.top && y0 <= ca.bottom) {
                ctx.strokeStyle = 'rgba(148,163,184,0.35)';
                ctx.lineWidth   = 1;
                ctx.setLineDash([4, 3]);
                ctx.beginPath();
                ctx.moveTo(ca.left, y0);
                ctx.lineTo(ca.right, y0);
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.fillStyle = 'rgba(148,163,184,0.4)';
                ctx.font = '8px Inter, sans-serif';
                ctx.textAlign = 'left';
                ctx.fillText('Δ=0', ca.left + 2, y0 - 3);
            }
            ctx.restore();
        },
    };

    // Buy-zone rectangle overlay plugin
    const buyZonePlugin = {
        id: 'swBuyZone_' + canvasId,
        afterDatasetsDraw(chart) {
            if (!buyZones.length) return;
            const ca = chart.chartArea;
            const sx = chart.scales?.x;
            const sy = chart.scales?.y;
            if (!ca || !sx || !sy) return;
            const { ctx } = chart;
            ctx.save();
            ctx.beginPath();
            ctx.rect(ca.left, ca.top, ca.width, ca.height);
            ctx.clip();

            buyZones.forEach(z => {
                const x1 = Math.max(sx.getPixelForValue(z.xMin), ca.left);
                const x2 = Math.min(sx.getPixelForValue(z.xMax), ca.right);
                const y1 = z.yFloor ? Math.min(sy.getPixelForValue(0), ca.bottom) : ca.bottom;
                const y2 = ca.top;
                ctx.strokeStyle = z.color;
                ctx.lineWidth   = 1.5;
                ctx.setLineDash([5, 3]);
                ctx.strokeRect(x1, y2, x2 - x1, y1 - y2);
                ctx.setLineDash([]);
                ctx.fillStyle = z.color;
                ctx.font = 'bold 9px Inter, sans-serif';
                ctx.textAlign = 'left';
                ctx.fillText(z.label || '', x1 + 4, y2 + 14);
            });
            ctx.restore();
        },
    };

    swState.charts[stateKey] = new Chart(canvas, {
        type: 'line',
        data: {
            datasets: [
                {
                    data:               pts.map(p => ({ x: p.x, y: p.y })),
                    borderColor:        `rgba(${trailColor},0.5)`,
                    borderWidth:        1.5,
                    fill:               false,
                    tension:            0.25,
                    showLine:           true,
                    pointRadius:        pts.map((_, i) => i === n - 1 ? 0 : i >= n - 8 ? 3 : 1.5),
                    pointBackgroundColor: ptColors,
                    pointBorderColor:   'transparent',
                    segment: {
                        borderColor: ctx => {
                            const t = ctx.p0DataIndex / Math.max(n - 2, 1);
                            return `rgba(${trailColor},${(0.06 + t * 0.94).toFixed(2)})`;
                        },
                        borderWidth: ctx => (ctx.p0DataIndex >= n - 3 ? 2.5 : 1.5),
                    },
                },
                {
                    data:             [{ x: pts[n - 1].x, y: pts[n - 1].y }],
                    borderColor:      sigColor,
                    backgroundColor:  sigColor,
                    pointRadius:      10,
                    pointHoverRadius: 12,
                    borderWidth:      2,
                    showLine:         false,
                    fill:             false,
                },
            ],
        },
        options: {
            responsive:          true,
            maintainAspectRatio: false,
            animation:           false,
            scales: {
                x: {
                    type:  'linear',
                    min:   xMin,
                    max:   xMax,
                    title: { display: true, text: xLabel, color: '#475569', font: { size: 10 } },
                    ticks: { color: '#475569', font: { size: 9 }, stepSize: 10 },
                    grid:  { color: 'rgba(255,255,255,0.04)' },
                },
                y: {
                    type:  'linear',
                    title: { display: true, text: yLabel, color: '#475569', font: { size: 10 } },
                    ticks: { color: '#475569', font: { size: 9 } },
                    grid:  { color: 'rgba(255,255,255,0.04)' },
                },
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    mode:      'nearest',
                    intersect: true,
                    filter:    item => item.datasetIndex === 0,
                    callbacks: {
                        label: ctx => {
                            const p = pts[ctx.dataIndex];
                            return p
                                ? `${p.date}  ${xLabel}: ${ctx.parsed.x.toFixed(1)}  Δ: ${ctx.parsed.y.toFixed(1)}`
                                : '';
                        },
                    },
                },
            },
        },
        plugins: [zoneBgPlugin, buyZonePlugin],
    });
}

// ── RSI phase-space wrapper ────────────────────────────────────────────────────
function _swRenderRsiPhaseChart(canvasId, data, freq, stateKey) {
    if (!data?.rsi?.length) return;
    const buyZones = freq === 'daily'
        ? [{ xMin: 25, xMax: 45, yFloor: true,  color: 'rgba(34,197,94,0.85)',  label: '↑ Daily Buy Zone' }]
        : [{ xMin: 50, xMax: 62, yFloor: false, color: 'rgba(59,130,246,0.85)', label: 'Weekly Anchor'    }];
    _swRenderPhaseChart(canvasId, data.rsi, data.drsi, data.dates, data.signal, stateKey, {
        xLabel: 'RSI', yLabel: 'Δ RSI / bar',
        xMin: 0, xMax: 100, trailColor: '59,130,246',
        buyZones,
        xBands: [
            { xMin: 0,   xMax: 20,  color: 'rgba(239,68,68,0.15)',   label: 'Deeply OS'  },
            { xMin: 20,  xMax: 30,  color: 'rgba(249,115,22,0.11)',  label: 'Oversold'   },
            { xMin: 30,  xMax: 50,  color: 'rgba(234,179,8,0.09)',   label: 'Recovering' },
            { xMin: 50,  xMax: 70,  color: 'rgba(34,197,94,0.09)',   label: 'Healthy'    },
            { xMin: 70,  xMax: 100, color: 'rgba(239,68,68,0.12)',   label: 'Overbought' },
        ],
    });
}

// ── KAMA percentile phase-space wrapper ───────────────────────────────────────
function _swRenderKamaPhaseChart(canvasId, kamaData, kind, stateKey) {
    if (!kamaData?.pct?.length) return;
    const isFast = (kind === 'fast');
    const tc     = isFast ? '168,85,247' : '245,158,11';   // purple vs amber
    const buyZones = isFast
        ? [{ xMin: 30, xMax: 60, yFloor: true,  color: 'rgba(168,85,247,0.85)', label: '↑ Recovery Zone' }]
        : [{ xMin: 50, xMax: 80, yFloor: false, color: 'rgba(245,158,11,0.85)', label: '↑ Uptrend Zone'  }];
    const xBands = isFast ? [
        { xMin: 0,   xMax: 25,  color: 'rgba(239,68,68,0.15)',   label: 'Depressed' },
        { xMin: 25,  xMax: 50,  color: 'rgba(249,115,22,0.10)',  label: 'Low'       },
        { xMin: 50,  xMax: 75,  color: 'rgba(34,197,94,0.09)',   label: 'Above Avg' },
        { xMin: 75,  xMax: 100, color: 'rgba(239,68,68,0.10)',   label: 'Stretched' },
    ] : [
        { xMin: 0,   xMax: 25,  color: 'rgba(239,68,68,0.15)',   label: 'Bearish'  },
        { xMin: 25,  xMax: 50,  color: 'rgba(249,115,22,0.10)',  label: 'Weak'     },
        { xMin: 50,  xMax: 75,  color: 'rgba(34,197,94,0.09)',   label: 'Bullish'  },
        { xMin: 75,  xMax: 100, color: 'rgba(34,197,94,0.14)',   label: 'Strong'   },
    ];
    _swRenderPhaseChart(
        canvasId, kamaData.pct, kamaData.dpct, kamaData.dates, kamaData.signal, stateKey,
        { xLabel: 'Pct Rank', yLabel: 'Δ Pct / bar', xMin: 0, xMax: 100, trailColor: tc, buyZones, xBands }
    );
}

// ── Signal details box ─────────────────────────────────────────────────────────
function _swRenderSignalBox(containerId, signal) {
    const el = document.getElementById(containerId);
    if (!el || !signal) return;

    const color = SW_SIG_COLORS[signal.color] || '#64748b';
    const score = signal.score ?? 0;
    const pct   = Math.min(score, 100);

    el.innerHTML =
        `<div class="sw-sig-header">` +
        `  <span class="sw-sig-label" style="color:${color}">${signal.label}</span>` +
        `  <span class="sw-sig-score">${score}/100</span>` +
        `</div>` +
        `<div class="sw-sig-bar-track"><div class="sw-sig-bar-fill" style="width:${pct}%;background:${color}"></div></div>` +
        `<ul class="sw-sig-details">` +
        (signal.details || []).map(d => `<li>${d}</li>`).join('') +
        `</ul>`;
}

// ── Generic timeline chart ─────────────────────────────────────────────────────
/**
 * @param {string}   canvasId
 * @param {number[]} yArr      - values to plot
 * @param {string[]} dates
 * @param {string}   stateKey
 * @param {object}   opts      - {yMin, yMax, stepSize, bandColor, hBands, keyLevels, dotPred}
 */
function _swRenderTimeline(canvasId, yArr, dates, stateKey, opts = {}) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !yArr?.length || !dates?.length) return;

    if (swState.charts[stateKey]) {
        try { swState.charts[stateKey].destroy(); } catch (_) {}
        swState.charts[stateKey] = null;
    }

    const {
        yMin      = 0,
        yMax      = 100,
        stepSize  = 20,
        bandColor = v => {
            if (v == null) return '#64748b';
            if (v < 20)   return '#ef4444';
            if (v < 30)   return '#f97316';
            if (v < 50)   return '#eab308';
            if (v <= 70)  return '#22c55e';
            return '#ef4444';
        },
        hBands = [
            { yMin: 0,  yMax: 20,  color: 'rgba(239,68,68,0.14)'  },
            { yMin: 20, yMax: 30,  color: 'rgba(249,115,22,0.10)' },
            { yMin: 30, yMax: 50,  color: 'rgba(234,179,8,0.07)'  },
            { yMin: 50, yMax: 70,  color: 'rgba(34,197,94,0.07)'  },
            { yMin: 70, yMax: 100, color: 'rgba(239,68,68,0.11)'  },
        ],
        keyLevels = [20, 30, 50, 70],
        dotPred   = (v, i, n) => i === n - 1 || (v != null && v < 25),
    } = opts;

    const n        = yArr.length;
    const ptColors = yArr.map(v => bandColor(v));

    const tlZonePlugin = {
        id: 'tlZones_' + canvasId,
        beforeDraw(chart) {
            const ca = chart.chartArea;
            const sy = chart.scales?.y;
            if (!ca || !sy) return;
            const { ctx } = chart;
            ctx.save();

            hBands.forEach(b => {
                const y1 = sy.getPixelForValue(b.yMax);
                const y2 = sy.getPixelForValue(b.yMin);
                ctx.fillStyle = b.color;
                ctx.fillRect(ca.left, y1, ca.width, y2 - y1);
            });

            keyLevels.forEach(level => {
                const yPx = sy.getPixelForValue(level);
                ctx.strokeStyle = 'rgba(148,163,184,0.25)';
                ctx.lineWidth   = 1;
                ctx.setLineDash([3, 3]);
                ctx.beginPath();
                ctx.moveTo(ca.left, yPx);
                ctx.lineTo(ca.right, yPx);
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.fillStyle = 'rgba(148,163,184,0.35)';
                ctx.font = '8px Inter, sans-serif';
                ctx.textAlign = 'left';
                ctx.fillText(level, ca.left + 2, yPx - 2);
            });
            ctx.restore();
        },
    };

    swState.charts[stateKey] = new Chart(canvas, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [{
                data:               yArr,
                borderColor:        'rgba(59,130,246,0.8)',
                borderWidth:        1.5,
                fill:               false,
                tension:            0.2,
                pointRadius:        yArr.map((v, i) => dotPred(v, i, n) ? (i === n - 1 ? 5 : 3) : 0),
                pointBackgroundColor: ptColors,
                pointBorderColor:   'transparent',
                segment: {
                    borderColor: ctx => ptColors[ctx.p0DataIndex] || 'rgba(59,130,246,0.8)',
                },
            }],
        },
        options: {
            responsive:          true,
            maintainAspectRatio: false,
            animation:           false,
            scales: {
                x: {
                    ticks: { color: '#475569', font: { size: 8 }, maxTicksLimit: 6, maxRotation: 0 },
                    grid:  { display: false },
                },
                y: {
                    min:   yMin,
                    max:   yMax,
                    ticks: { color: '#475569', font: { size: 8 }, stepSize },
                    grid:  { color: 'rgba(255,255,255,0.03)' },
                },
            },
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ctx => `${ctx.parsed.y?.toFixed(1) ?? '—'}` } },
            },
        },
        plugins: [tlZonePlugin],
    });
}

// ── RSI timeline wrapper ───────────────────────────────────────────────────────
function _swRenderRsiTimeline(canvasId, data, stateKey) {
    if (!data?.rsi?.length) return;
    _swRenderTimeline(canvasId, data.rsi, data.dates, stateKey, {
        yMin: 0, yMax: 100, stepSize: 20,
        bandColor: v => {
            if (v == null) return '#64748b';
            if (v < 20)   return '#ef4444';
            if (v < 30)   return '#f97316';
            if (v < 50)   return '#eab308';
            if (v <= 70)  return '#22c55e';
            return '#ef4444';
        },
        hBands: [
            { yMin: 0,  yMax: 20,  color: 'rgba(239,68,68,0.14)'  },
            { yMin: 20, yMax: 30,  color: 'rgba(249,115,22,0.10)' },
            { yMin: 30, yMax: 50,  color: 'rgba(234,179,8,0.07)'  },
            { yMin: 50, yMax: 70,  color: 'rgba(34,197,94,0.07)'  },
            { yMin: 70, yMax: 100, color: 'rgba(239,68,68,0.11)'  },
        ],
        keyLevels: [20, 30, 50, 70],
        dotPred: (v, i, n) => i === n - 1 || (v != null && v < 25),
    });
}

// ── KAMA percentile timeline wrapper ──────────────────────────────────────────
function _swRenderKamaTimeline(canvasId, kamaData, stateKey) {
    if (!kamaData?.pct?.length) return;
    _swRenderTimeline(canvasId, kamaData.pct, kamaData.dates, stateKey, {
        yMin: 0, yMax: 100, stepSize: 25,
        bandColor: v => {
            if (v == null) return '#64748b';
            if (v < 25)   return '#ef4444';
            if (v < 50)   return '#f97316';
            if (v < 75)   return '#22c55e';
            return '#06b6d4';
        },
        hBands: [
            { yMin: 0,  yMax: 25,  color: 'rgba(239,68,68,0.14)'  },
            { yMin: 25, yMax: 50,  color: 'rgba(249,115,22,0.09)' },
            { yMin: 50, yMax: 75,  color: 'rgba(34,197,94,0.08)'  },
            { yMin: 75, yMax: 100, color: 'rgba(6,182,212,0.10)'  },
        ],
        keyLevels: [25, 50, 75],
        dotPred: (v, i, n) => i === n - 1 || (v != null && v < 20),
    });
}

// ── Loading helper ─────────────────────────────────────────────────────────────
function _swSetLoading(on) {
    const el  = document.getElementById('sw-loading');
    const btn = document.getElementById('btn-sw-run');
    if (el) el.style.display = on ? '' : 'none';
    if (btn) {
        btn.disabled    = on;
        btn.textContent = on ? '⏳ Computing…' : '↻ Refresh';
    }
}
