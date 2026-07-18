// pro-charts.jsx — 538-grade SVG chart components for News Desk Pro.
// Conventions: horizontal gridlines only, direct labeling (no legends),
// annotation callouts with thin leaders, mono figures, source line below.

// ---------- helpers ----------
function pcScale(d0, d1, r0, r1) { const m = (r1 - r0) / ((d1 - d0) || 1); return v => r0 + (v - d0) * m; }
function pcLine(pts) { return pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(2) + ',' + p[1].toFixed(2)).join(' '); }
function pcArea(pts, y0) {
  if (!pts.length) return '';
  return pcLine(pts) + ' L' + pts[pts.length - 1][0].toFixed(2) + ',' + y0.toFixed(2) +
    ' L' + pts[0][0].toFixed(2) + ',' + y0.toFixed(2) + ' Z';
}
// interpolate keypoints [[x,v],...] into n samples with a small deterministic wiggle
function pcInterp(keys, n, wiggle, seed) {
  const out = [];
  const x0 = keys[0][0], x1 = keys[keys.length - 1][0];
  for (let i = 0; i < n; i++) {
    const x = x0 + (x1 - x0) * (i / (n - 1));
    let k = 0;
    while (k < keys.length - 2 && keys[k + 1][0] < x) k++;
    const [ax, av] = keys[k], [bx, bv] = keys[k + 1];
    const t = bx === ax ? 0 : (x - ax) / (bx - ax);
    const tt = t * t * (3 - 2 * t); // smoothstep
    let v = av + (bv - av) * tt;
    v += Math.sin(x * 2.61 + (seed || 0)) * wiggle * 0.6 + Math.sin(x * 7.13 + (seed || 0) * 2.7) * wiggle * 0.4;
    out.push([x, v]);
  }
  return out;
}

// ---------- shared frame ----------
function ChartFrame({ title, sub, source, children, className }) {
  return (
    <figure className={'chart ' + (className || '')}>
      {title ? <h3 className="chart-title">{title}</h3> : null}
      {sub ? <p className="chart-sub">{sub}</p> : null}
      {children}
      {source ? <p className="chart-source">{source}</p> : null}
    </figure>
  );
}

function Anno({ x, y, tx, ty, label, anchor, bold }) {
  // leader from (x,y) to (tx,ty), label at (tx,ty)
  const lines = Array.isArray(label) ? label : [label];
  return (
    <g className="anno">
      <line x1={x} y1={y} x2={tx} y2={ty} className="anno-leader" />
      <circle cx={x} cy={y} r="3" className="anno-dot" />
      {lines.map((ln, i) => (
        <text key={i} x={tx} y={ty + i * 14 + (ty > y ? 12 : -4 - (lines.length - 1 - i) * 0)}
              textAnchor={anchor || 'start'} className={'anno-text' + (bold && i === 0 ? ' anno-bold' : '')}>{ln}</text>
      ))}
    </g>
  );
}

// ============================================================
// 1) HERO — 2s/10s Treasury spread, 2021 → today
// ============================================================
const YS_KEYS = [
  [0, 0.82], [4, 1.02], [8, 1.21], [12, 1.08], [16, 0.84], [20, 0.55], [24, 0.31],
  [28, 0.18], [32, 0.08], [36, 0.02], [37, -0.04], [40, -0.42], [43, -0.78],
  [45, -0.96], [48, -0.84], [51, -0.70], [54, -0.55], [57, -0.40], [60, -0.25],
  [62, -0.14], [64, -0.05], [65, 0.04],
];
const YS_DATA = pcInterp(YS_KEYS, 240, 0.035, 3.1);
// pin the endpoints the annotations reference
YS_DATA[YS_DATA.length - 1][1] = 0.04;

function YieldSpreadChart({ showAnno }) {
  const W = 760, H = 430, M = { t: 18, r: 64, b: 34, l: 14 };
  const sx = pcScale(0, 65, M.l, W - M.r);
  const sy = pcScale(-1.2, 1.4, H - M.b, M.t);
  const pts = YS_DATA.map(d => [sx(d[0]), sy(d[1])]);
  const zero = sy(0);
  // split into above/below zero for coloring the inversion
  const yTicks = [-1.0, -0.5, 0, 0.5, 1.0];
  const xTicks = [0, 12, 24, 36, 48, 60].map(m => ({ x: sx(m), label: "'" + (21 + Math.round(m / 12)) }));
  const last = pts[pts.length - 1];
  const troughX = sx(45), troughY = sy(-0.96);
  const crossX = sx(37), crossY = sy(0);
  return (
    <ChartFrame className="chart-hero"
      title="After 28 months underwater, the yield curve is back"
      sub="Spread between 10-year and 2-year U.S. Treasury yields, percentage points, Jan. 2021 to today"
      source="SOURCE: DAILY TREASURY PAR YIELD CURVE RATES · DAILY BRIEF CALCULATIONS">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Line chart of the 2s10s Treasury spread un-inverting">
        <defs>
          <clipPath id="ys-below"><rect x="0" y={zero} width={W} height={H - zero} /></clipPath>
          <clipPath id="ys-above"><rect x="0" y="0" width={W} height={zero} /></clipPath>
        </defs>
        {yTicks.map(t => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r + 30} y1={sy(t)} y2={sy(t)} className={t === 0 ? 'grid-zero' : 'grid'} />
            {t !== 0 ? <text x={W - M.r + 34} y={sy(t) + 4} className="tick">{t > 0 ? '+' + t.toFixed(1) : t.toFixed(1)}</text> : null}
          </g>
        ))}
        {xTicks.map(t => (
          <text key={t.label} x={t.x} y={H - 10} className="tick" textAnchor="middle">{t.label}</text>
        ))}
        {/* shaded inversion region */}
        <path d={pcArea(pts, zero)} clipPath="url(#ys-below)" className="ys-inv-fill" />
        <path d={pcLine(pts)} clipPath="url(#ys-below)" className="line-down" />
        <path d={pcLine(pts)} clipPath="url(#ys-above)" className="line-accent" />
        <circle cx={last[0]} cy={last[1]} r="4.5" className="end-dot" />
        <text x={last[0] + 9} y={last[1] - 12} className="end-label">+4bp</text>
        <text x={last[0] + 9} y={last[1] + 16} className="end-label-sub">today</text>
        {showAnno ? (
          <g>
            <Anno x={crossX} y={crossY} tx={crossX - 12} ty={crossY - 56} anchor="end" bold
                  label={["Inversion begins", "Feb. 2024"]} />
            <Anno x={troughX} y={troughY} tx={troughX + 26} ty={troughY - 6} bold
                  label={["Deepest point: −96bp", "Oct. 2024 — the widest gap", "since 1981"]} />
            <text x={sx(10)} y={sy(1.18) - 14} className="anno-text anno-bold">Post-pandemic steepening</text>
          </g>
        ) : null}
      </svg>
    </ChartFrame>
  );
}

// ============================================================
// 2) Dumbbell — Street recession calls, before vs. after
// ============================================================
const DUMBBELL = [
  { name: 'Barclays', before: 55, after: 38 },
  { name: 'Bank of America', before: 50, after: 35 },
  { name: 'JPMorgan', before: 45, after: 25 },
  { name: 'Wells Fargo', before: 45, after: 28 },
  { name: 'Morgan Stanley', before: 40, after: 30 },
  { name: 'Citi', before: 40, after: 22 },
  { name: 'Goldman Sachs', before: 35, after: 20 },
  { name: 'UBS', before: 30, after: 18 },
];

function RecessionCallsChart({ showAnno }) {
  const W = 440, H = 330, M = { t: 34, r: 38, b: 26, l: 118 };
  const sx = pcScale(0, 60, M.l, W - M.r);
  const rowH = (H - M.t - M.b) / DUMBBELL.length;
  return (
    <ChartFrame
      title="The Street rips up its recession scripts"
      sub="12-month U.S. recession probability by bank — last month vs. this week, %"
      source="SOURCE: PUBLISHED STRATEGIST NOTES, COMPILED BY DAILY BRIEF">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Dumbbell chart of bank recession probabilities falling">
        {[0, 20, 40, 60].map(t => (
          <g key={t}>
            <line x1={sx(t)} x2={sx(t)} y1={M.t - 8} y2={H - M.b} className="grid" />
            <text x={sx(t)} y={H - 8} className="tick" textAnchor="middle">{t}</text>
          </g>
        ))}
        {DUMBBELL.map((d, i) => {
          const y = M.t + rowH * i + rowH / 2;
          return (
            <g key={d.name}>
              <text x={M.l - 10} y={y + 4} className="row-label" textAnchor="end">{d.name}</text>
              <line x1={sx(d.after)} x2={sx(d.before)} y1={y} y2={y} className="db-link" />
              <circle cx={sx(d.before)} cy={y} r="5" className="db-before" />
              <circle cx={sx(d.after)} cy={y} r="5.5" className="db-after" />
            </g>
          );
        })}
        {showAnno ? (
          <g>
            <text x={sx(55)} y={M.t + rowH / 2 - 12} className="anno-text" textAnchor="middle">last month</text>
            <text x={sx(38)} y={M.t + rowH / 2 - 12} className="anno-text anno-accent" textAnchor="middle">now</text>
          </g>
        ) : null}
      </svg>
    </ChartFrame>
  );
}

// ============================================================
// 3) Deal volume bars — the M&A thaw
// ============================================================
const DEALS = [22, 18, 25, 31, 19, 24, 28, 35, 30, 26, 33, 38, 42, 36, 58, 96];
function DealVolumeChart({ showAnno }) {
  const W = 440, H = 330, M = { t: 30, r: 14, b: 40, l: 36 };
  const sx = pcScale(0, DEALS.length, M.l, W - M.r);
  const sy = pcScale(0, 100, H - M.b, M.t);
  const bw = (W - M.l - M.r) / DEALS.length - 5;
  const lastX = sx(DEALS.length - 1) + bw / 2;
  return (
    <ChartFrame
      title="Bankers call it the thaw"
      sub="U.S. M&A announced deal value by week, $ billions, past 16 weeks"
      source="SOURCE: DEAL LEAGUE TABLES, COMPILED BY DAILY BRIEF">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Bar chart of weekly M&A volume spiking in the latest week">
        {[0, 25, 50, 75, 100].map(t => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r} y1={sy(t)} y2={sy(t)} className={t === 0 ? 'grid-zero' : 'grid'} />
            <text x={M.l - 6} y={sy(t) + 4} className="tick" textAnchor="end">{t}</text>
          </g>
        ))}
        {DEALS.map((v, i) => (
          <rect key={i} x={sx(i)} y={sy(v)} width={bw} height={sy(0) - sy(v)}
                className={i === DEALS.length - 1 ? 'bar-hot' : 'bar'} />
        ))}
        <text x={M.l} y={H - 12} className="tick">16 wks ago</text>
        <text x={W - M.r} y={H - 12} className="tick" textAnchor="end">this week</text>
        {showAnno ? (
          <Anno x={lastX} y={sy(96)} tx={lastX - 18} ty={sy(96) - 22} anchor="end" bold
                label={["$96B — best week since 2021;", "three $20B+ deals in 72 hours"]} />
        ) : null}
      </svg>
    </ChartFrame>
  );
}

// ============================================================
// 4) Probability with uncertainty band — recession odds market
// ============================================================
const ODDS_KEYS = [[0, 38], [14, 36], [25, 33], [38, 34], [50, 29], [62, 26], [74, 22], [84, 19], [90, 17]];
const ODDS = pcInterp(ODDS_KEYS, 120, 0.8, 7.7);
ODDS[ODDS.length - 1][1] = 17;
function RecessionOddsChart({ showAnno }) {
  const W = 440, H = 330, M = { t: 26, r: 60, b: 34, l: 34 };
  const sx = pcScale(0, 90, M.l, W - M.r);
  const sy = pcScale(0, 50, H - M.b, M.t);
  const pts = ODDS.map(d => [sx(d[0]), sy(d[1])]);
  const upper = ODDS.map(d => [sx(d[0]), sy(d[1] + 4 + d[0] * 0.01)]);
  const lower = ODDS.map(d => [sx(d[0]), sy(Math.max(2, d[1] - 4 - d[0] * 0.01))]).reverse();
  const band = pcLine(upper) + ' ' + pcLine(lower).replace(/^M/, 'L') + ' Z';
  const last = pts[pts.length - 1];
  return (
    <ChartFrame
      title="Prediction markets got there first"
      sub="“U.S. recession in 2026” — implied probability, %, past 90 days, with 80% band"
      source="SOURCE: AGGREGATED PREDICTION-MARKET PRICING · DAILY BRIEF">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Probability line falling from 38 to 17 percent">
        {[0, 10, 20, 30, 40, 50].map(t => (
          <g key={t}>
            <line x1={M.l} x2={W - M.r + 26} y1={sy(t)} y2={sy(t)} className={t === 0 ? 'grid-zero' : 'grid'} />
            <text x={W - M.r + 30} y={sy(t) + 4} className="tick">{t}</text>
          </g>
        ))}
        {[['MAR', 0], ['APR', 30], ['MAY', 60], ['JUN', 88]].map(([l, d]) => (
          <text key={l} x={sx(d)} y={H - 12} className="tick">{l}</text>
        ))}
        <path d={band} className="band" />
        <path d={pcLine(pts)} className="line-accent" />
        <circle cx={last[0]} cy={last[1]} r="4.5" className="end-dot" />
        <text x={last[0] + 9} y={last[1] + 4} className="end-label">17%</text>
        {showAnno ? (
          <Anno x={sx(50)} y={sy(29)} tx={sx(50) + 14} ty={sy(29) - 40} bold
                label={["Odds slid for six straight", "weeks before the Street", "moved its forecasts"]} />
        ) : null}
      </svg>
    </ChartFrame>
  );
}

// ============================================================
// 5) Small multiples — sector performance, 90 days
// ============================================================
function seeded(seed) { let s = seed >>> 0; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
function sectorSeries(seed, drift, n) {
  const r = seeded(seed); const out = []; let v = 100;
  for (let i = 0; i < n; i++) { out.push(v); v += drift / n + (r() - 0.5) * 1.15; }
  // force the end value to land on the drift target
  const adj = (100 + drift) - out[n - 1];
  return out.map((x, i) => x + adj * (i / (n - 1)));
}
const SECTORS = [
  { name: 'Tech', chg: 8.4, seed: 11 },
  { name: 'Financials', chg: 4.1, seed: 22 },
  { name: 'Industrials', chg: 3.0, seed: 33 },
  { name: 'Health care', chg: 1.2, seed: 44 },
  { name: 'Consumer', chg: -1.8, seed: 55 },
  { name: 'Energy', chg: -6.2, seed: 66 },
];
const SP_BASE = sectorSeries(99, 2.5, 64);

function SectorPanel({ s }) {
  const W = 218, H = 130, M = { t: 26, r: 40, b: 8, l: 8 };
  const data = sectorSeries(s.seed, s.chg, 64);
  const lo = Math.min(...data, ...SP_BASE) - 1, hi = Math.max(...data, ...SP_BASE) + 1;
  const sx = pcScale(0, 63, M.l, W - M.r);
  const sy = pcScale(lo, hi, H - M.b, M.t);
  const pts = data.map((v, i) => [sx(i), sy(v)]);
  const base = SP_BASE.map((v, i) => [sx(i), sy(v)]);
  const up = s.chg >= 0;
  return (
    <div className="sm-panel">
      <div className="sm-head">
        <span className="sm-name">{s.name}</span>
        <span className={'sm-chg ' + (up ? 'is-up' : 'is-down')}>{(up ? '+' : '') + s.chg.toFixed(1) + '%'}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H - 24}`} role="img" aria-label={s.name + ' sector, 90 days'}>
        <line x1={M.l} x2={W - M.r + 8} y1={sy(100)} y2={sy(100)} className="grid-zero" />
        <path d={pcLine(base)} className="line-base" />
        <path d={pcLine(pts)} className={up ? 'line-up' : 'line-dn'} />
        <circle cx={pts[63][0]} cy={pts[63][1]} r="3" className={up ? 'dot-up' : 'dot-dn'} />
      </svg>
    </div>
  );
}

function SectorMultiples() {
  return (
    <ChartFrame className="chart-sm"
      title="Where the rotation went"
      sub="Sector total return vs. the S&P 500 (gray), indexed to 100, past 90 days"
      source="SOURCE: EXCHANGE DATA, INDEXED BY DAILY BRIEF">
      <div className="sm-grid">
        {SECTORS.map(s => <SectorPanel key={s.name} s={s} />)}
      </div>
    </ChartFrame>
  );
}

// ============================================================
// 6) Mini inline chart for story cards
// ============================================================
function MiniLine({ keys, dir, label, w, h }) {
  const W = w || 300, H = h || 84, M = { t: 10, r: 52, b: 6, l: 2 };
  const data = pcInterp(keys, 80, Math.abs(keys[0][1] - keys[keys.length - 1][1]) * 0.02, keys[0][1]);
  const vals = data.map(d => d[1]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const sx = pcScale(data[0][0], data[data.length - 1][0], M.l, W - M.r);
  const sy = pcScale(lo - (hi - lo) * 0.08, hi + (hi - lo) * 0.08, H - M.b, M.t);
  const pts = data.map(d => [sx(d[0]), sy(d[1])]);
  const last = pts[pts.length - 1];
  return (
    <svg className="mini-line" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
      <path d={pcLine(pts)} className={dir === 'down' ? 'line-dn' : 'line-up'} />
      <circle cx={last[0]} cy={last[1]} r="3" className={dir === 'down' ? 'dot-dn' : 'dot-up'} />
      <text x={last[0] + 7} y={last[1] + 4} className="end-label-mini">{label}</text>
    </svg>
  );
}

Object.assign(window, {
  ChartFrame, YieldSpreadChart, RecessionCallsChart, DealVolumeChart,
  RecessionOddsChart, SectorMultiples, MiniLine,
});
