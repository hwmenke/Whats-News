/**
 * Compact always-on OHLC legend stats (not gated on overlay pills).
 *
 * ADR% = mean of ((high − low) / close) * 100 over the last 20 daily bars
 * that have high, low, close > 0. Omit if fewer than 5 such bars.
 * Stock statistic from the latest daily series — not the hovered window.
 *
 * RVOL = hovered bar volume / average volume of the prior 20 bars
 * (not including the hovered bar). Same window as _avg20Vol in charts.js.
 * Omit if that average is missing or 0. Daily legend only.
 *
 * Dist to SMA200 = (close / sma200 − 1) * 100 using the hovered bar's close
 * and that bar's SMA200 from maCache. Omit if SMA200 is null at that index.
 *
 * 52H gap = (close / high52 − 1) * 100 at the hovered bar. high52 is the
 * max high over the 252 sessions ending at that bar (including it) — the
 * same 252-session window applySessionLevels uses for the latest daily bar,
 * evaluated per hovered index rather than only the last print. Daily only.
 *
 * Daily legend: ADR + RVOL + 52H gap + SMA200 distance when computable.
 * Weekly legend: SMA200 distance only (if weekly SMA200 exists). ADR stays daily.
 * RVOL and 52H are daily-only too.
 */
const ADR_LOOKBACK = 20;
const ADR_MIN_BARS = 5;
const LEGEND_RVOL_LOOKBACK = 20;
const LEGEND_52W_BARS = 252;
const LEGEND_MINUS = '\u2212';
const LEGEND_TIMES = '\u00d7';

function _legendStatNum(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : NaN;
}

function _adrBarRangePct(bar) {
    if (!bar) return null;
    const high = _legendStatNum(bar.high);
    const low = _legendStatNum(bar.low);
    const close = _legendStatNum(bar.close);
    if (!(high > 0 && low > 0 && close > 0)) return null;
    return ((high - low) / close) * 100;
}

function computeAdrPct(rows, lookback, minBars) {
    const nLook = lookback == null ? ADR_LOOKBACK : lookback;
    const nMin = minBars == null ? ADR_MIN_BARS : minBars;
    const ranges = [];
    const list = rows || [];
    for (let i = list.length - 1; i >= 0 && ranges.length < nLook; i--) {
        const pct = _adrBarRangePct(list[i]);
        if (pct == null) continue;
        ranges.push(pct);
    }
    if (ranges.length < nMin) return null;
    let sum = 0;
    for (let i = 0; i < ranges.length; i++) sum += ranges[i];
    return sum / ranges.length;
}

function distToSma200Pct(close, sma200) {
    const c = _legendStatNum(close);
    const s = _legendStatNum(sma200);
    if (!(c > 0 && s > 0)) return null;
    return (c / s - 1) * 100;
}

// Same formula as _avg20Vol in charts.js: mean of prior 20 bars' volume
// (slice [i-20, i), not including bar i). Missing volume counts as 0.
function _legendAvg20Vol(rows, i) {
    if (!rows || i == null || i < 0) return null;
    const windowVols = rows.slice(Math.max(0, i - 20), i).map(r => r.volume || 0);
    if (!windowVols.length) return null;
    return windowVols.reduce((a, b) => a + b, 0) / windowVols.length;
}

function computeRvol(rows, i) {
    const avg = _legendAvg20Vol(rows, i);
    if (avg == null || !(avg > 0)) return null;
    const bar = rows && i != null ? rows[i] : null;
    if (bar == null || bar.volume == null || bar.volume === '') return null;
    const vol = _legendStatNum(bar.volume);
    if (!Number.isFinite(vol) || vol < 0) return null;
    return vol / avg;
}

function high52AsOfBar(rows, i, lookback) {
    if (!rows || i == null || i < 0 || i >= rows.length) return null;
    const nLook = lookback == null ? LEGEND_52W_BARS : lookback;
    const start = Math.max(0, i + 1 - nLook);
    let hi = null;
    for (let j = start; j <= i; j++) {
        const h = _legendStatNum(rows[j] && rows[j].high);
        if (!Number.isFinite(h)) continue;
        hi = hi == null ? h : Math.max(hi, h);
    }
    return hi;
}

function gapFrom52hPct(close, high52) {
    const c = _legendStatNum(close);
    const h = _legendStatNum(high52);
    if (!(c > 0 && h > 0)) return null;
    return (c / h - 1) * 100;
}

function formatAdrLegend(adr) {
    if (adr == null || !Number.isFinite(Number(adr))) return '';
    return `ADR ${Number(adr).toFixed(2)}%`;
}

function formatSma200DistLegend(pct) {
    if (pct == null || !Number.isFinite(Number(pct))) return '';
    const n = Number(pct);
    const sign = n >= 0 ? '+' : LEGEND_MINUS;
    return `200 ${sign}${Math.abs(n).toFixed(1)}%`;
}

function formatRvolLegend(rvol) {
    if (rvol == null || !Number.isFinite(Number(rvol))) return '';
    return `RVOL ${Number(rvol).toFixed(1)}${LEGEND_TIMES}`;
}

function format52hGapLegend(pct) {
    if (pct == null || !Number.isFinite(Number(pct))) return '';
    const n = Number(pct);
    const mag = Math.abs(n).toFixed(1);
    if (mag === '0.0') return '52H 0.0%';
    const sign = n > 0 ? '+' : LEGEND_MINUS;
    return `52H ${sign}${mag}%`;
}

function _legendStatDailyRows(opts) {
    if (opts && Object.prototype.hasOwnProperty.call(opts, 'dailyRows')) return opts.dailyRows;
    return (typeof rawRows !== 'undefined' && rawRows) ? rawRows.daily : null;
}

function _legendStatRows(freq, opts) {
    if (opts && Object.prototype.hasOwnProperty.call(opts, 'rows')) return opts.rows;
    return (typeof rawRows !== 'undefined' && rawRows) ? rawRows[freq] : null;
}

function _legendStatSma200Series(freq, opts) {
    if (opts && Object.prototype.hasOwnProperty.call(opts, 'sma200Series')) return opts.sma200Series;
    return (typeof maCache !== 'undefined' && maCache && maCache[freq])
        ? maCache[freq].sma?.[200]
        : null;
}

function legendStatHtmlBits(freq, idx, opts) {
    const o = opts || {};
    const bits = [];
    const rows = _legendStatRows(freq, o);
    if (freq === 'daily') {
        const adrTxt = formatAdrLegend(computeAdrPct(_legendStatDailyRows(o)));
        if (adrTxt) bits.push(`<span class="lg-stat">${adrTxt}</span>`);
        const rvolTxt = formatRvolLegend(computeRvol(rows, idx));
        if (rvolTxt) bits.push(`<span class="lg-stat">${rvolTxt}</span>`);
    }
    const smaSeries = _legendStatSma200Series(freq, o);
    const close = (rows && idx != null && rows[idx]) ? rows[idx].close : o.close;
    if (freq === 'daily') {
        const gapTxt = format52hGapLegend(gapFrom52hPct(close, high52AsOfBar(rows, idx)));
        if (gapTxt) bits.push(`<span class="lg-stat">${gapTxt}</span>`);
    }
    const sma = (smaSeries && idx != null) ? smaSeries[idx] : o.sma200;
    const distTxt = formatSma200DistLegend(distToSma200Pct(close, sma));
    if (distTxt) bits.push(`<span class="lg-stat">${distTxt}</span>`);
    return bits.join(' ');
}
