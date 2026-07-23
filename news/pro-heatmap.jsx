// pro-heatmap.jsx — sector treemap heatmap (size = market cap, color = % change).
// Squarified treemap, rendered as positioned divs for crisp text + hover.

// ---------- squarify ----------
function hmSquarify(items, rect) {
  const out = [];
  let list = items.filter(i => i.value > 0).slice().sort((a, b) => b.value - a.value);
  let x = rect.x, y = rect.y, w = rect.w, h = rect.h;
  const total = list.reduce((s, i) => s + i.value, 0);
  if (!total || w <= 0 || h <= 0) return out;
  list = list.map(i => ({ ...i, area: (i.value / total) * w * h }));

  function worst(row, l) {
    const s = row.reduce((a, b) => a + b.area, 0);
    const amax = Math.max(...row.map(r => r.area));
    const amin = Math.min(...row.map(r => r.area));
    return Math.max((l * l * amax) / (s * s), (s * s) / (l * l * amin));
  }
  function layoutRow(row) {
    const s = row.reduce((a, b) => a + b.area, 0);
    if (w >= h) {
      const cw = s / h; let cy = y;
      row.forEach(r => { const ch = r.area / cw; out.push({ ...r, x, y: cy, w: cw, h: ch }); cy += ch; });
      x += cw; w -= cw;
    } else {
      const ch = s / w; let cx = x;
      row.forEach(r => { const cw2 = r.area / ch; out.push({ ...r, x: cx, y, w: cw2, h: ch }); cx += cw2; });
      y += ch; h -= ch;
    }
  }
  let row = [];
  list.forEach(item => {
    const l = Math.min(w, h);
    if (row.length && worst(row, l) < worst(row.concat(item), l)) { layoutRow(row); row = [item]; }
    else row.push(item);
  });
  if (row.length) layoutRow(row);
  return out;
}

// ---------- color scale ----------
function hmColor(chg, cap) {
  const t = Math.max(-1, Math.min(1, chg / cap));
  if (Math.abs(t) < 0.045) return 'oklch(56% 0.008 250)';
  const hue = t < 0 ? 27 : 152;
  const c = (0.025 + Math.abs(t) * 0.105).toFixed(3);
  const L = (60 - Math.abs(t) * 13).toFixed(1);
  return `oklch(${L}% ${c} ${hue})`;
}

// ---------- heatmap ----------
function Heatmap({ period, onPeriod, onPick }) {
  const { useState, useRef } = React;
  const [tip, setTip] = useState(null);
  const boxRef = useRef(null);
  const W = 1272, H = 580, HEAD = 17;
  const cap = SCR_PERIODS[period].cap;

  // sector rects
  const bySector = {};
  SCR_STOCKS.forEach(s => { (bySector[s.sector] = bySector[s.sector] || []).push(s); });
  const sectorItems = SCR_SECTOR_ORDER
    .filter(sec => bySector[sec])
    .map(sec => ({ key: sec, value: bySector[sec].reduce((a, b) => a + b.mcap, 0) }));
  const sectorRects = hmSquarify(sectorItems, { x: 0, y: 0, w: W, h: H });

  const tiles = [];
  sectorRects.forEach(sr => {
    const inner = { x: sr.x + 1, y: sr.y + HEAD, w: sr.w - 2, h: sr.h - HEAD - 1 };
    const kids = hmSquarify(bySector[sr.key].map(s => ({ key: s.sym, value: s.mcap, stock: s })), inner);
    kids.forEach(k => tiles.push(k));
  });

  function showTip(e, stock) {
    const box = boxRef.current.getBoundingClientRect();
    const scale = box.width / W;
    setTip({
      stock,
      x: Math.min((e.clientX - box.left) / scale + 14, W - 190),
      y: Math.min((e.clientY - box.top) / scale + 14, H - 110),
    });
  }

  return (
    <div className="hm-wrap">
      <div className="hm-bar">
        <div>
          <h3 className="chart-title">Market heatmap</h3>
          <p className="chart-sub">S&amp;P 500 leaders — tile size is market cap, color is {period === 'YTD' ? 'year-to-date' : period} change. Click a tile for detail.</p>
        </div>
        <div className="seg" role="tablist" aria-label="Heatmap period">
          {Object.keys(SCR_PERIODS).map(p => (
            <button key={p} type="button" className={'seg-btn' + (p === period ? ' is-on' : '')}
                    onClick={() => onPeriod(p)}>{p}</button>
          ))}
        </div>
      </div>
      <div className="hm-box" ref={boxRef} style={{ aspectRatio: W + ' / ' + H }} onMouseLeave={() => setTip(null)}>
        {sectorRects.map(sr => (
          <div key={sr.key} className="hm-sector" style={{ left: pct(sr.x, W), top: pct(sr.y, H), width: pct(sr.w, W), height: pct(sr.h, H) }}>
            <span className="hm-sector-label">{sr.w > 90 ? sr.key.toUpperCase() : ''}</span>
          </div>
        ))}
        {tiles.map(t => {
          const chg = scrChg(t.stock.sym, period);
          const big = t.w > 58 && t.h > 34;
          const mid = t.w > 34 && t.h > 16;
          const fs = Math.max(9, Math.min(20, Math.sqrt(t.w * t.h) / 5.2));
          return (
            <button key={t.stock.sym} type="button" className="hm-tile"
                 style={{ left: pct(t.x, W), top: pct(t.y, H), width: pct(t.w, W), height: pct(t.h, H), background: hmColor(chg, cap) }}
                 onMouseMove={e => showTip(e, t.stock)}
                 onClick={() => onPick(t.stock.sym)}>
              {mid ? <span className="hm-sym" style={{ fontSize: fs }}>{t.stock.sym}</span> : null}
              {big ? <span className="hm-chg" style={{ fontSize: Math.max(8.5, fs * 0.62) }}>{scrFmtChg(chg)}</span> : null}
            </button>
          );
        })}
        {tip ? (
          <div className="hm-tip" style={{ left: pct(tip.x, W), top: pct(tip.y, H) }}>
            <div className="hm-tip-head"><b>{tip.stock.sym}</b><span>{tip.stock.name}</span></div>
            <div className="hm-tip-row"><span>Price</span><b>${scrFmtPx(tip.stock.px)}</b></div>
            <div className="hm-tip-row"><span>{period}</span><b className={scrChg(tip.stock.sym, period) >= 0 ? 'is-up' : 'is-down'}>{scrFmtChg(scrChg(tip.stock.sym, period))}</b></div>
            <div className="hm-tip-row"><span>Mkt cap</span><b>${scrFmtCap(tip.stock.mcap)}</b></div>
            <div className="hm-tip-row"><span>Sector</span><b>{tip.stock.sector}</b></div>
          </div>
        ) : null}
      </div>
      <div className="hm-legend">
        <span className="hm-leg-lab">−{cap}%</span>
        {[-1, -0.66, -0.33, 0, 0.33, 0.66, 1].map(t => (
          <span key={t} className="hm-leg-swatch" style={{ background: hmColor(t * cap, cap) }}></span>
        ))}
        <span className="hm-leg-lab">+{cap}%</span>
        <span className="chart-source" style={{ marginLeft: 'auto' }}>SOURCE: EXCHANGE DATA · FIGURES ILLUSTRATIVE</span>
      </div>
    </div>
  );
}
function pct(v, total) { return (v / total * 100).toFixed(3) + '%'; }

Object.assign(window, { Heatmap, hmColor });
