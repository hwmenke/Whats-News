// pro-screener.jsx — FinViz-style abilities in Daily Brief clothing:
// sector performance groups, top movers, filterable/sortable screener,
// and a ticker detail drawer. Composed into <MarketsView/>.

const { useState, useMemo, useEffect: scrUseEffect } = React;

// ============================================================
// Sector performance (cap-weighted, per period)
// ============================================================
function sectorPerf(period) {
  const by = {};
  SCR_STOCKS.forEach(s => {
    const b = by[s.sector] = by[s.sector] || { w: 0, sum: 0 };
    b.w += s.mcap; b.sum += scrChg(s.sym, period) * s.mcap;
  });
  return SCR_SECTOR_ORDER.map(sec => ({ sector: sec, chg: by[sec].sum / by[sec].w }))
    .sort((a, b) => b.chg - a.chg);
}

function SectorBars({ period }) {
  const rows = sectorPerf(period);
  const max = Math.max(...rows.map(r => Math.abs(r.chg)), 0.1);
  return (
    <div className="chart">
      <h3 className="chart-title">Sector performance</h3>
      <p className="chart-sub">Cap-weighted {period === 'YTD' ? 'year-to-date' : period} change by sector, %</p>
      <div className="sb-rows">
        {rows.map(r => {
          const up = r.chg >= 0;
          const w = Math.abs(r.chg) / max * 50;
          return (
            <div className="sb-row" key={r.sector}>
              <span className="sb-name">{r.sector}</span>
              <span className="sb-track">
                <span className="sb-zero"></span>
                <span className={'sb-bar ' + (up ? 'is-up-bg' : 'is-down-bg')}
                      style={up ? { left: '50%', width: w + '%' } : { right: '50%', width: w + '%' }}></span>
              </span>
              <span className={'sb-val ' + (up ? 'is-up' : 'is-down')}>{scrFmtChg(r.chg)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ============================================================
// Top movers
// ============================================================
function Movers({ period, onPick }) {
  const ranked = SCR_STOCKS.map(s => ({ ...s, chg: scrChg(s.sym, period) })).sort((a, b) => b.chg - a.chg);
  const gain = ranked.slice(0, 5), lose = ranked.slice(-5).reverse();
  const List = ({ title, rows }) => (
    <div className="mv-col">
      <p className="mv-title">{title}</p>
      {rows.map(s => (
        <button key={s.sym} type="button" className="mv-row" onClick={() => onPick(s.sym)}>
          <span className="mv-sym">{s.sym}</span>
          <span className="mv-name">{s.name}</span>
          <span className="mv-px">${scrFmtPx(s.px)}</span>
          <span className={'mv-chg ' + (s.chg >= 0 ? 'is-up' : 'is-down')}>{scrFmtChg(s.chg)}</span>
        </button>
      ))}
    </div>
  );
  return (
    <div className="chart">
      <h3 className="chart-title">Top movers</h3>
      <p className="chart-sub">Biggest {period === 'YTD' ? 'year-to-date' : period} moves in the universe</p>
      <div className="mv-grid">
        <List title="GAINERS" rows={gain} />
        <List title="LOSERS" rows={lose} />
      </div>
    </div>
  );
}

// ============================================================
// Screener
// ============================================================
const CAP_BUCKETS = { 'Any': null, 'Mega (>$200B)': [200, 1e9], 'Large ($10–200B)': [10, 200], 'Mid (<$10B)': [0, 10] };
const PE_BUCKETS = { 'Any': null, 'Under 15': [0, 15], '15–30': [15, 30], 'Over 30': [30, 1e9] };
const YLD_BUCKETS = { 'Any': null, 'Pays dividend': [0.01, 100], 'Over 2%': [2, 100], 'Over 4%': [4, 100] };

function SparkCell({ sym }) {
  const d = useMemo(() => scrSeries(sym, 60), [sym]);
  const lo = Math.min(...d), hi = Math.max(...d);
  const up = d[d.length - 1] >= d[0];
  const pts = d.map((v, i) => [(i / 59) * 96 + 2, 26 - ((v - lo) / ((hi - lo) || 1)) * 22 - 2]);
  const path = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join('');
  return (
    <svg className="scr-spark" viewBox="0 0 100 28" aria-hidden="true">
      <path d={path} className={up ? 'line-up' : 'line-dn'} style={{ strokeWidth: 1.6 }} />
    </svg>
  );
}

const SCR_COLS = [
  { key: 'sym', label: 'Ticker', num: false },
  { key: 'name', label: 'Company', num: false },
  { key: 'sector', label: 'Sector', num: false },
  { key: 'px', label: 'Price', num: true },
  { key: 'mcap', label: 'Mkt cap', num: true },
  { key: 'pe', label: 'P/E', num: true },
  { key: 'yld', label: 'Div %', num: true },
  { key: 'c1d', label: '1D %', num: true },
  { key: 'c1w', label: '1W %', num: true },
  { key: 'c1m', label: '1M %', num: true },
  { key: 'cytd', label: 'YTD %', num: true },
  { key: 'spark', label: '90 days', num: false, nosort: true },
];

function Screener({ onPick }) {
  const [q, setQ] = useState('');
  const [sector, setSector] = useState('All');
  const [cap, setCap] = useState('Any');
  const [pe, setPe] = useState('Any');
  const [yld, setYld] = useState('Any');
  const [sort, setSort] = useState({ key: 'mcap', dir: -1 });

  const rows = useMemo(() => {
    let list = SCR_STOCKS.map(s => ({
      ...s, c1d: scrChg(s.sym, '1D'), c1w: scrChg(s.sym, '1W'),
      c1m: scrChg(s.sym, '1M'), cytd: scrChg(s.sym, 'YTD'),
    }));
    const needle = q.trim().toLowerCase();
    if (needle) list = list.filter(s => s.sym.toLowerCase().includes(needle) || s.name.toLowerCase().includes(needle));
    if (sector !== 'All') list = list.filter(s => s.sector === sector);
    const inB = (v, b) => !b || (v !== null && v >= b[0] && v <= b[1]);
    list = list.filter(s => inB(s.mcap, CAP_BUCKETS[cap]) && inB(s.pe, PE_BUCKETS[pe]) && inB(s.yld, YLD_BUCKETS[yld]));
    const { key, dir } = sort;
    list.sort((a, b) => {
      const av = a[key], bv = b[key];
      if (av === null) return 1; if (bv === null) return -1;
      return (typeof av === 'string' ? av.localeCompare(bv) : av - bv) * dir;
    });
    return list;
  }, [q, sector, cap, pe, yld, sort]);

  const active = (sector !== 'All') + (cap !== 'Any') + (pe !== 'Any') + (yld !== 'Any') + (q.trim() !== '');
  const Sel = ({ label, value, onChange, options }) => (
    <label className="scr-filter">
      <span>{label}</span>
      <select value={value} onChange={e => onChange(e.target.value)}>
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );

  return (
    <div className="scr" data-screen-label="Screener">
      <div className="scr-head">
        <div>
          <h3 className="chart-title">Screener</h3>
          <p className="chart-sub">{rows.length} of {SCR_STOCKS.length} companies{active ? ' · ' + active + ' filter' + (active > 1 ? 's' : '') + ' active' : ''}</p>
        </div>
        <div className="scr-filters">
          <input className="scr-q" type="text" placeholder="Ticker or name…" value={q} onChange={e => setQ(e.target.value)} />
          <Sel label="Sector" value={sector} onChange={setSector} options={['All'].concat(SCR_SECTOR_ORDER)} />
          <Sel label="Mkt cap" value={cap} onChange={setCap} options={Object.keys(CAP_BUCKETS)} />
          <Sel label="P/E" value={pe} onChange={setPe} options={Object.keys(PE_BUCKETS)} />
          <Sel label="Dividend" value={yld} onChange={setYld} options={Object.keys(YLD_BUCKETS)} />
          {active ? <button type="button" className="scr-reset" onClick={() => { setQ(''); setSector('All'); setCap('Any'); setPe('Any'); setYld('Any'); }}>Reset</button> : null}
        </div>
      </div>
      <div className="scr-tablewrap">
        <table className="scr-table">
          <thead>
            <tr>
              {SCR_COLS.map(c => (
                <th key={c.key} className={c.num ? 'is-num' : ''}>
                  {c.nosort ? <span>{c.label}</span> : (
                    <button type="button" className="scr-sort" onClick={() => setSort(s => ({ key: c.key, dir: s.key === c.key ? -s.dir : (c.num ? -1 : 1) }))}>
                      {c.label}{sort.key === c.key ? <span className="scr-arrow">{sort.dir > 0 ? '▲' : '▼'}</span> : null}
                    </button>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(s => (
              <tr key={s.sym} onClick={() => onPick(s.sym)}>
                <td className="scr-sym">{s.sym}</td>
                <td className="scr-name">{s.name}</td>
                <td className="scr-sector">{s.sector}</td>
                <td className="is-num">${scrFmtPx(s.px)}</td>
                <td className="is-num">${scrFmtCap(s.mcap)}</td>
                <td className="is-num">{s.pe === null ? '—' : s.pe.toFixed(1)}</td>
                <td className="is-num">{s.yld ? s.yld.toFixed(1) : '—'}</td>
                {['c1d', 'c1w', 'c1m', 'cytd'].map(k => (
                  <td key={k} className={'is-num ' + (s[k] >= 0 ? 'is-up' : 'is-down')}>{scrFmtChg(s[k])}</td>
                ))}
                <td><SparkCell sym={s.sym} /></td>
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr><td colSpan={SCR_COLS.length} className="scr-empty">No matches — loosen a filter.</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ============================================================
// Ticker detail drawer
// ============================================================
const SECTOR_TOPIC = {
  Technology: 'tech', Communications: 'tech', Financials: 'markets', Energy: 'markets',
  Materials: 'markets', 'Health Care': 'business', Industrials: 'business',
  'Consumer Cyclical': 'business', 'Consumer Defensive': 'business', Utilities: 'business', 'Real Estate': 'business',
};

function TickerDrawer({ sym, onClose }) {
  const s = SCR_STOCKS.find(x => x.sym === sym);
  scrUseEffect(() => {
    const fn = e => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', fn);
    return () => window.removeEventListener('keydown', fn);
  }, [onClose]);
  if (!s) return null;
  const series = scrSeries(sym, 90);
  const lo = Math.min(...series), hi = Math.max(...series);
  const W = 380, H = 170, M = { t: 12, r: 50, b: 8, l: 8 };
  const sx = v => M.l + (v / 89) * (W - M.l - M.r);
  const sy = v => (H - M.b) - ((v - lo) / ((hi - lo) || 1)) * (H - M.t - M.b);
  const pts = series.map((v, i) => sx(i).toFixed(1) + ',' + sy(v).toFixed(1));
  const c1d = scrChg(sym, '1D'), up = c1d >= 0;
  const related = (window.CLUSTERS || []).filter(c => c.topic === (SECTOR_TOPIC[s.sector] || 'business')).slice(0, 2);
  return (
    <div className="drawer-scrim" onClick={onClose}>
      <aside className="drawer" data-screen-label="Ticker detail" onClick={e => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <p className="drawer-sym">{s.sym} <span className="drawer-sector">{s.sector}</span></p>
            <h3 className="drawer-name">{s.name}</h3>
          </div>
          <button type="button" className="drawer-x" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="drawer-px-row">
          <span className="drawer-px">${scrFmtPx(s.px)}</span>
          <span className={'drawer-chg ' + (up ? 'is-up' : 'is-down')}>{scrFmtChg(c1d)} today</span>
        </div>
        <svg viewBox={`0 0 ${W} ${H}`} className="drawer-chart" role="img" aria-label={s.name + ' 90-day price chart'}>
          <line x1={M.l} x2={W - M.r} y1={sy(series[0])} y2={sy(series[0])} className="grid" strokeDasharray="3 3" />
          <polyline points={pts.join(' ')} className={up ? 'line-up' : 'line-dn'} fill="none" />
          <text x={W - M.r + 4} y={sy(series[89]) + 4} className="end-label-mini">${scrFmtPx(s.px)}</text>
          <text x={M.l} y={H - 0} className="tick">90 days</text>
        </svg>
        <dl className="drawer-stats">
          <div><dt>Mkt cap</dt><dd>${scrFmtCap(s.mcap)}</dd></div>
          <div><dt>P/E</dt><dd>{s.pe === null ? '—' : s.pe.toFixed(1)}</dd></div>
          <div><dt>Div yield</dt><dd>{s.yld ? s.yld.toFixed(1) + '%' : '—'}</dd></div>
          <div><dt>1W</dt><dd className={scrChg(sym, '1W') >= 0 ? 'is-up' : 'is-down'}>{scrFmtChg(scrChg(sym, '1W'))}</dd></div>
          <div><dt>1M</dt><dd className={scrChg(sym, '1M') >= 0 ? 'is-up' : 'is-down'}>{scrFmtChg(scrChg(sym, '1M'))}</dd></div>
          <div><dt>YTD</dt><dd className={scrChg(sym, 'YTD') >= 0 ? 'is-up' : 'is-down'}>{scrFmtChg(scrChg(sym, 'YTD'))}</dd></div>
          <div><dt>52W range</dt><dd>${scrFmtPx(lo)}–${scrFmtPx(hi)}</dd></div>
        </dl>
        {related.length ? (
          <div className="drawer-news">
            <p className="coverage-label">Related coverage</p>
            {related.map(c => (
              <a key={c.id} href="#" className="drawer-news-item" onClick={e => e.preventDefault()}>
                <span className="rail-title">{c.headline}</span>
                <span className="card-meta">{c.stories.length} sources · {c.hours}h ago</span>
              </a>
            ))}
          </div>
        ) : null}
        <p className="chart-source">FIGURES ILLUSTRATIVE · NOT INVESTMENT ADVICE</p>
      </aside>
    </div>
  );
}

// ============================================================
// Markets view
// ============================================================
function MarketsView() {
  const [period, setPeriod] = useState('1D');
  const [picked, setPicked] = useState(null);
  return (
    <div className="markets-view" data-screen-label="Markets view">
      <section className="desk" style={{ borderBottom: 0, paddingBottom: 0 }}>
        <div className="desk-head">
          <h2 className="section-hed">Markets</h2>
          <p className="section-sub">Heatmap, movers, and a full screener — every figure illustrative</p>
        </div>
      </section>
      <Heatmap period={period} onPeriod={setPeriod} onPick={setPicked} />
      <section className="mk-duo">
        <Movers period={period} onPick={setPicked} />
        <SectorBars period={period} />
      </section>
      <Screener onPick={setPicked} />
      {picked ? <TickerDrawer sym={picked} onClose={() => setPicked(null)} /> : null}
    </div>
  );
}

Object.assign(window, { MarketsView, Screener, Movers, SectorBars, TickerDrawer });
