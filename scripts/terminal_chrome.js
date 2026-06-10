/**
 * terminal_chrome.js — Terminal shell components
 * Ticker tape, bottom status bar (NY session clock, risk pedal,
 * data freshness), sidebar sparkline builder, 52-week range bar.
 */

/* ── Sparkline SVG ───────────────────────────────────────────── */
// Returns an inline SVG element drawing `values` as a polyline.
function sparkSVG(values, w = 56, h = 18) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'si-spark');
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    svg.setAttribute('width', w);
    svg.setAttribute('height', h);
    if (!values || values.length < 2) return svg;

    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = (max - min) || 1;
    const pad = 1.5;
    const pts = values.map((v, i) => {
        const x = pad + (i / (values.length - 1)) * (w - pad * 2);
        const y = pad + (1 - (v - min) / span) * (h - pad * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    const up = values[values.length - 1] >= values[0];
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    line.setAttribute('points', pts.join(' '));
    line.setAttribute('fill', 'none');
    line.setAttribute('stroke', up ? 'var(--green)' : 'var(--red)');
    line.setAttribute('stroke-width', '1.3');
    line.setAttribute('stroke-linejoin', 'round');
    line.setAttribute('stroke-linecap', 'round');
    line.setAttribute('opacity', '0.85');
    svg.appendChild(line);
    return svg;
}

/* ── Ticker tape ─────────────────────────────────────────────── */
function updateTickerTape() {
    const track = document.getElementById('tape-track');
    if (!track || typeof state === 'undefined') return;

    const syms = (state.symbols || []).filter(s => s.price != null);
    if (!syms.length) {
        track.innerHTML = '<span class="tape-empty">— add symbols to start the tape —</span>';
        track.style.animation = 'none';
        return;
    }

    const item = s => {
        const up  = (s.chg ?? 0) >= 0;
        const chg = s.chg != null ? `${up ? '+' : ''}${s.chg.toFixed(2)}%` : '—';
        const name = s.symbol.includes('~') ? s.symbol.replace('~', '/') : s.symbol;
        return `<span class="tape-item" data-symbol="${s.symbol}">` +
               `<span class="tape-sym">${name}</span>` +
               `<span class="tape-px">${s.price.toFixed(2)}</span>` +
               `<span class="tape-chg ${up ? 'positive' : 'negative'}">${up ? '▲' : '▼'} ${chg}</span>` +
               `</span>`;
    };

    // Two copies of the strip for a seamless -50% translateX loop
    const half = syms.map(item).join('');
    track.innerHTML = half + half;
    const secs = Math.max(25, syms.length * 4);
    track.style.animation = `tape-scroll ${secs}s linear infinite`;
}

/* ── 52-week range bar ───────────────────────────────────────── */
// Called from updateSymbolHeader with the full daily OHLCV series.
function renderRange52(series) {
    const wrap = document.getElementById('range-52w');
    if (!wrap) return;
    if (!series || series.length < 30) { wrap.style.display = 'none'; return; }

    const bars = series.slice(-252);
    let lo = Infinity, hi = -Infinity;
    bars.forEach(b => {
        if (b.low  != null && b.low  < lo) lo = b.low;
        if (b.high != null && b.high > hi) hi = b.high;
    });
    const close = bars[bars.length - 1]?.close;
    if (!isFinite(lo) || !isFinite(hi) || hi <= lo || close == null) {
        wrap.style.display = 'none';
        return;
    }

    const pct = Math.min(100, Math.max(0, (close - lo) / (hi - lo) * 100));
    document.getElementById('r52-lo').textContent = lo.toFixed(2);
    document.getElementById('r52-hi').textContent = hi.toFixed(2);
    const marker = document.getElementById('r52-marker');
    marker.style.left = pct + '%';
    marker.title = `${pct.toFixed(0)}% of 52-week range`;
    wrap.style.display = 'flex';
    wrap.title = `52-week range — currently at ${pct.toFixed(0)}%`;
}

/* ── Status bar: clocks & NYSE session ───────────────────────── */
const _ET_FMT = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false, weekday: 'short',
});

function _etParts(now) {
    const parts = Object.fromEntries(
        _ET_FMT.formatToParts(now).map(p => [p.type, p.value]));
    return {
        weekday: parts.weekday,
        h: parseInt(parts.hour, 10) % 24,
        m: parseInt(parts.minute, 10),
        s: parseInt(parts.second, 10),
        clock: `${parts.hour}:${parts.minute}:${parts.second}`,
    };
}

function _fmtCountdown(mins) {
    const h = Math.floor(mins / 60), m = mins % 60;
    return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
}

// NYSE session from ET wall-clock (ignores exchange holidays)
function _sessionInfo(et) {
    const mins = et.h * 60 + et.m;
    const isWeekend = et.weekday === 'Sat' || et.weekday === 'Sun';
    if (isWeekend)       return { label: 'CLOSED', cls: 'sb-closed', detail: 'weekend' };
    if (mins < 4 * 60)   return { label: 'CLOSED', cls: 'sb-closed', detail: `pre in ${_fmtCountdown(4 * 60 - mins)}` };
    if (mins < 570)      return { label: 'PRE',    cls: 'sb-pre',    detail: `open in ${_fmtCountdown(570 - mins)}` };
    if (mins < 960)      return { label: 'OPEN',   cls: 'sb-open',   detail: `close in ${_fmtCountdown(960 - mins)}` };
    if (mins < 20 * 60)  return { label: 'POST',   cls: 'sb-post',   detail: `ends in ${_fmtCountdown(20 * 60 - mins)}` };
    return { label: 'CLOSED', cls: 'sb-closed', detail: 'after hours' };
}

function _sbTickClocks() {
    const now = new Date();
    const etEl = document.getElementById('sb-et-clock');
    const sesEl = document.getElementById('sb-session');
    if (!etEl || !sesEl) return;

    const et = _etParts(now);
    etEl.textContent = et.clock;

    const ses = _sessionInfo(et);
    sesEl.textContent = `${ses.label} · ${ses.detail}`;
    sesEl.className = `sb-session ${ses.cls}`;
}

/* ── Status bar: risk pedal ──────────────────────────────────── */
const _PEDAL_META = {
    green:  { dot: '●', label: 'RISK ON',  cls: 'sb-pedal-green'  },
    yellow: { dot: '●', label: 'CAUTION',  cls: 'sb-pedal-yellow' },
    red:    { dot: '●', label: 'RISK OFF', cls: 'sb-pedal-red'    },
};

async function _sbLoadPedal() {
    const el = document.getElementById('sb-pedal');
    if (!el || typeof apiFetch !== 'function') return;
    try {
        const d = await apiFetch('/api/risk-pedal');
        const meta = _PEDAL_META[d.pedal] || _PEDAL_META.yellow;
        el.innerHTML = `<span class="sb-pedal-dot">${meta.dot}</span> ${meta.label}`;
        el.className = `sb-pedal ${meta.cls}`;
        el.title = (d.reasons || []).join('\n') || 'Risk pedal';
    } catch (_) {
        el.textContent = '';
    }
}

/* ── Status bar: setters called from app.js ──────────────────── */
function _sbSetSymbolCount(n) {
    const el = document.getElementById('sb-watch-count');
    if (el) el.textContent = n;
}

function _sbSetFreshness(latestDateStr) {
    const el = document.getElementById('sb-freshness');
    if (!el) return;
    if (!latestDateStr) { el.textContent = '—'; el.className = 'sb-item'; return; }
    const latest   = new Date(latestDateStr);
    const today    = new Date(); today.setHours(0, 0, 0, 0);
    const diffDays = Math.floor((today - latest) / 86400000);
    const dow      = today.getDay();
    const stale    = !(dow === 0 || dow === 6) && diffDays > 1;
    el.textContent = latestDateStr;
    el.className   = 'sb-item' + (stale ? ' sb-stale' : '');
    el.title       = stale ? `Data is ${diffDays} days old — refresh` : 'Data is current';
}

/* ── Boot ────────────────────────────────────────────────────── */
document.addEventListener('DOMContentLoaded', () => {
    // Tape click → select symbol (delegated)
    const tape = document.getElementById('ticker-tape');
    if (tape) {
        tape.addEventListener('click', e => {
            const item = e.target.closest('.tape-item');
            if (item && typeof selectSymbol === 'function') selectSymbol(item.dataset.symbol);
        });
    }

    _sbTickClocks();
    setInterval(_sbTickClocks, 1000);

    _sbLoadPedal();
    setInterval(_sbLoadPedal, 10 * 60 * 1000);
});
