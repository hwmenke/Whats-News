/**
 * compare.js — Normalized multi-symbol comparison chart (LightweightCharts)
 */
let _cmpChart = null;
const _CMP_COLORS = ['#029FD5','#F68B42','#4DAF88','#9B89C4','#E05252','#56B4E9','#E8C44A','#6CC3D5'];

function initCompare() {
    const input = document.getElementById('cmp-symbols-input');
    if (input && !input.value && state.activeSymbol) {
        input.value = state.activeSymbol;
    }
}

async function runCompare() {
    const input   = document.getElementById('cmp-symbols-input');
    const freq    = document.getElementById('cmp-freq')?.value || 'daily';
    const legend  = document.getElementById('cmp-legend');
    const chartEl = document.getElementById('cmp-chart');
    if (!input || !chartEl) return;

    const syms = input.value
        .split(/[\s,;]+/)
        .map(s => s.trim().toUpperCase())
        .filter(s => /^[A-Z]/.test(s));
    if (syms.length < 2) { toast('Enter at least 2 symbols to compare', 'warning'); return; }

    if (legend) legend.innerHTML = '<span class="spinner"></span>';
    if (_cmpChart) { try { _cmpChart.remove(); } catch (_) {} _cmpChart = null; }

    try {
        const datasets = await Promise.all(
            syms.slice(0, 8).map(s =>
                apiFetch(`${API}/ohlcv/${s}?freq=${freq}&limit=500`).catch(() => null)
            )
        );

        _cmpChart = LightweightCharts.createChart(chartEl, {
            width:  chartEl.clientWidth,
            height: chartEl.clientHeight || 400,
            layout: {
                background: { color: (window._CT||{}).bg||'#0b101a' },
                textColor:  (window._CT||{}).text||'#9aafc4',
                fontFamily: (window._CT||{}).font||"'Inter', -apple-system, 'Helvetica Neue', sans-serif",
                fontSize: 11,
            },
            grid: { vertLines: { visible: false }, horzLines: { color: (window._CT||{}).grid||'#1c2638' } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            rightPriceScale: { borderColor: (window._CT||{}).grid||'#1c2638' },
            timeScale: { borderColor: (window._CT||{}).grid||'#1c2638', timeVisible: true },
        });

        const legendItems = [];
        syms.slice(0, 8).forEach((sym, idx) => {
            const rows = datasets[idx];
            if (!rows?.length) return;
            const base = rows[0].close;
            if (!base || base === 0) return;
            const color = _CMP_COLORS[idx % _CMP_COLORS.length];
            const line  = _cmpChart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
            line.setData(rows.map(r => ({
                time:  r.date,
                value: parseFloat(((r.close / base) * 100).toFixed(3)),
            })));
            const chg = ((rows[rows.length - 1].close / base) - 1) * 100;
            legendItems.push({ sym, color, chg });
        });

        if (legend) {
            legend.innerHTML = legendItems.map(l =>
                `<span class="cmp-legend-item" style="border-left:3px solid ${l.color};">
                    <span style="color:${l.color}; font-weight:700;">${l.sym}</span>
                    <span style="color:${l.chg >= 0 ? '#4DAF88' : '#E05252'}">${l.chg >= 0 ? '+' : ''}${l.chg.toFixed(2)}%</span>
                </span>`
            ).join('');
        }
        _cmpChart.timeScale().fitContent();
        new ResizeObserver(() => {
            if (_cmpChart) _cmpChart.resize(chartEl.clientWidth, chartEl.clientHeight || 400);
        }).observe(chartEl);
    } catch (e) {
        toast('Compare failed: ' + e.message, 'error');
        if (legend) legend.innerHTML = '';
    }
}
