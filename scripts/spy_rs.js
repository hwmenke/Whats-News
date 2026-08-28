/**
 * Optional vs-SPY comparison line on the daily price pane.
 *
 * close/SPY close, rebased to the last symbol print so the line sits on
 * price. Off by default. Comparison only — not a published rating.
 *
 * Isolated so chart specialists can keep editing packs / legend / prefetch
 * without a rewrite here. charts.js only calls applySpyRsIfOn().
 */
const SPY_RS_COLOR = '#67e8f9';
let spyRsOn = false;
let _spyRsSeries = null;
let _spyRsHost = null;
let _spyRsSeq = 0;

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

function ensureSpyRsSeries() {
    const chart = (typeof charts !== 'undefined' && charts.daily) ? charts.daily.main : null;
    if (!chart) return null;
    if (_spyRsHost === chart && _spyRsSeries) return _spyRsSeries;
    const dash = (typeof LWC !== 'undefined' && LWC.LineStyle) ? LWC.LineStyle.Dashed : 2;
    _spyRsHost = chart;
    _spyRsSeries = chart.addLineSeries({
        color: SPY_RS_COLOR,
        lineWidth: 1.5,
        lineStyle: dash,
        priceLineVisible: false,
        lastValueVisible: true,
        visible: false,
        title: 'vs SPY',
    });
    return _spyRsSeries;
}

function _spyRsHide() {
    if (_spyRsSeries) {
        try { _spyRsSeries.applyOptions({ visible: false }); } catch (_) {}
    }
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
    const series = ensureSpyRsSeries();
    if (!sym || sym === 'SPY') {
        if (series) {
            series.setData([]);
            series.applyOptions({ visible: false });
        }
        return;
    }
    try {
        const data = await _spyRsGet(`${_spyRsApi()}/spy-rs/${encodeURIComponent(sym)}`);
        if (seq !== _spyRsSeq) return;
        const line = (data && data.points ? data.points : [])
            .filter(p => p && p.date != null && p.value != null)
            .map(p => ({ time: p.date, value: p.value }));
        const s = ensureSpyRsSeries();
        if (!s) return;
        s.setData(line);
        s.applyOptions({
            visible: !!(data && data.ready && line.length),
            lastValueVisible: true,
        });
    } catch (_) {
        if (seq !== _spyRsSeq) return;
        const s = ensureSpyRsSeries();
        if (s) {
            s.setData([]);
            s.applyOptions({ visible: false });
        }
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
