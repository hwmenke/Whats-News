/**
 * Optional vs-SPY comparison line on the daily and weekly price panes.
 *
 * close/SPY close, rebased to the last print so the line sits on price.
 * Weekly uses the same daily SPY series: last daily ratio in each W-FRI
 * week, rebased to the last weekly print. Off by default. Comparison
 * only — not a published rating.
 *
 * Isolated so chart specialists can keep editing packs / legend / prefetch
 * without a rewrite here. charts.js calls applySpyRsIfOn() on daily and
 * weekly apply. If weekly alignment fails, the weekly line stays off;
 * daily can still work.
 */
const SPY_RS_COLOR = '#67e8f9';
let spyRsOn = false;
let _spyRsSeries = null;
let _spyRsHost = null;
let _spyRsWeeklySeries = null;
let _spyRsWeeklyHost = null;
let _spyRsSeq = 0;
let _spyRsCacheSym = '';
let _spyRsCacheData = null;

function spyRsIsOn() {
    return !!spyRsOn;
}

function _spyRsApi() {
    return (typeof API !== 'undefined' && API) ? API : '/api';
}

async function _spyRsGet(path) {
    if (typeof apiFetch === 'function') return apiFetch(path);
    const res = await fetch(path);
    if (!res.ok) {
        let msg = res.statusText;
        try {
            const body = await res.json();
            if (body && body.error) msg = body.error;
        } catch (_) {}
        throw new Error(msg || 'spy-rs fetch failed');
    }
    return res.json();
}

function _spyRsLineOptions() {
    const dash = (typeof LWC !== 'undefined' && LWC.LineStyle) ? LWC.LineStyle.Dashed : 2;
    return {
        color: SPY_RS_COLOR,
        lineWidth: 1.5,
        lineStyle: dash,
        priceLineVisible: false,
        lastValueVisible: true,
        visible: false,
        title: 'vs SPY',
    };
}

function ensureSpyRsSeries() {
    const chart = (typeof charts !== 'undefined' && charts.daily) ? charts.daily.main : null;
    if (!chart) return null;
    if (_spyRsHost === chart && _spyRsSeries) return _spyRsSeries;
    _spyRsHost = chart;
    _spyRsSeries = chart.addLineSeries(_spyRsLineOptions());
    return _spyRsSeries;
}

function ensureSpyRsWeeklySeries() {
    const chart = (typeof charts !== 'undefined' && charts.weekly) ? charts.weekly.main : null;
    if (!chart) return null;
    if (_spyRsWeeklyHost === chart && _spyRsWeeklySeries) return _spyRsWeeklySeries;
    _spyRsWeeklyHost = chart;
    _spyRsWeeklySeries = chart.addLineSeries(_spyRsLineOptions());
    return _spyRsWeeklySeries;
}

function forgetSpyRsSeries() {
    _spyRsSeries = null;
    _spyRsHost = null;
    _spyRsWeeklySeries = null;
    _spyRsWeeklyHost = null;
}

function _spyRsAddDays(iso, n) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
    if (!m) return '';
    const dt = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
    if (Number.isNaN(dt.getTime())) return '';
    dt.setUTCDate(dt.getUTCDate() + n);
    return dt.toISOString().slice(0, 10);
}

function spyRsWeeklyFromDailyPoints(dailyPoints, weeklyRows) {
    const empty = { ready: false, points: [], last_ratio: null, n: 0, freq: 'weekly' };
    const daily = [];
    for (const p of dailyPoints || []) {
        if (!p) continue;
        const day = String(p.date != null ? p.date : '').slice(0, 10);
        const ratio = Number(p.ratio);
        if (day && Number.isFinite(ratio) && ratio > 0) daily.push({ day, ratio });
    }
    daily.sort((a, b) => (a.day < b.day ? -1 : a.day > b.day ? 1 : 0));

    const weeks = [];
    for (const row of weeklyRows || []) {
        if (!row) continue;
        const day = String(row.date != null ? row.date : '').slice(0, 10);
        const px = Number(row.close);
        if (day && Number.isFinite(px) && px > 0) weeks.push({ day, close: px });
    }

    if (!daily.length || !weeks.length) return empty;

    const aligned = [];
    for (const w of weeks) {
        const weekStart = _spyRsAddDays(w.day, -6);
        if (!weekStart) continue;
        let hitRatio = null;
        for (let i = 0; i < daily.length; i++) {
            if (daily[i].day < weekStart) continue;
            if (daily[i].day > w.day) break;
            hitRatio = daily[i].ratio;
        }
        if (hitRatio == null) continue;
        aligned.push({ date: w.day, close: w.close, ratio: hitRatio });
    }

    if (!aligned.length) return empty;

    const lastClose = aligned[aligned.length - 1].close;
    const lastRatio = aligned[aligned.length - 1].ratio;
    const scale = lastRatio ? lastClose / lastRatio : 0;
    const points = aligned.map(a => ({
        date: a.date,
        ratio: Math.round(a.ratio * 1e6) / 1e6,
        value: Math.round(a.ratio * scale * 1e4) / 1e4,
    }));
    return {
        ready: true,
        points,
        last_ratio: Math.round(lastRatio * 1e6) / 1e6,
        n: points.length,
        freq: 'weekly',
    };
}

function _spyRsSetLine(series, line, visible) {
    if (!series) return;
    series.setData(line);
    series.applyOptions({
        visible: !!(visible && line.length),
        lastValueVisible: true,
    });
}

function _spyRsHide() {
    if (_spyRsSeries) {
        try { _spyRsSeries.applyOptions({ visible: false }); } catch (_) {}
    }
    if (_spyRsWeeklySeries) {
        try { _spyRsWeeklySeries.applyOptions({ visible: false }); } catch (_) {}
    }
}

function _spyRsPaint(data) {
    const dailyLine = (data && data.points ? data.points : [])
        .filter(p => p && p.date != null && p.value != null)
        .map(p => ({ time: p.date, value: p.value }));
    _spyRsSetLine(ensureSpyRsSeries(), dailyLine, !!(data && data.ready && dailyLine.length));

    const weeklyRows = (typeof rawRows !== 'undefined' && rawRows && rawRows.weekly)
        ? rawRows.weekly
        : [];
    let weeklyOut = { ready: false, points: [] };
    try {
        weeklyOut = spyRsWeeklyFromDailyPoints(data && data.points, weeklyRows);
    } catch (_) {
        weeklyOut = { ready: false, points: [] };
    }
    const weeklyLine = (weeklyOut.points || [])
        .filter(p => p && p.date != null && p.value != null)
        .map(p => ({ time: p.date, value: p.value }));
    _spyRsSetLine(
        ensureSpyRsWeeklySeries(),
        weeklyLine,
        !!(weeklyOut.ready && weeklyLine.length),
    );
}

function _syncSpyRsPill() {
    const pill = document.getElementById('pill-spy-rs');
    if (!pill) return;
    pill.classList.toggle('active-spy-rs', spyRsOn);
    pill.setAttribute('aria-pressed', spyRsOn ? 'true' : 'false');
}

async function applySpyRsIfOn() {
    const seq = ++_spyRsSeq;
    _syncSpyRsPill();
    if (!spyRsOn) {
        _spyRsHide();
        return;
    }
    const sym = (typeof state !== 'undefined' && state.activeSymbol)
        ? String(state.activeSymbol).toUpperCase()
        : '';
    const dailySeries = ensureSpyRsSeries();
    const weeklySeries = ensureSpyRsWeeklySeries();
    if (!sym || sym === 'SPY') {
        _spyRsSetLine(dailySeries, [], false);
        _spyRsSetLine(weeklySeries, [], false);
        return;
    }
    if (_spyRsCacheSym === sym && _spyRsCacheData) {
        if (seq !== _spyRsSeq) return;
        _spyRsPaint(_spyRsCacheData);
        return;
    }
    try {
        const data = await _spyRsGet(`${_spyRsApi()}/spy-rs/${encodeURIComponent(sym)}`);
        if (seq !== _spyRsSeq) return;
        _spyRsCacheSym = sym;
        _spyRsCacheData = data;
        _spyRsPaint(data);
    } catch (_) {
        if (seq !== _spyRsSeq) return;
        if (_spyRsCacheSym === sym) {
            _spyRsCacheSym = '';
            _spyRsCacheData = null;
        }
        _spyRsSetLine(ensureSpyRsSeries(), [], false);
        _spyRsSetLine(ensureSpyRsWeeklySeries(), [], false);
    }
}

function toggleSpyRs() {
    spyRsOn = !spyRsOn;
    _syncSpyRsPill();
    applySpyRsIfOn();
    return spyRsOn;
}

document.addEventListener('DOMContentLoaded', () => {
    const pill = document.getElementById('pill-spy-rs');
    if (!pill) return;
    pill.addEventListener('click', () => toggleSpyRs());
    _syncSpyRsPill();
});
