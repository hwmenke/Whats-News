/**
 * compare.js — Normalized multi-symbol comparison chart (LightweightCharts)
 */
let _cmpChart = null;
const _CMP_COLORS = ['#3b82f6','#f97316','#22c55e','#a855f7','#ef4444','#06b6d4','#eab308','#ec4899'];

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
                background: { color: '#0d1117' },
                textColor: '#8b949e',
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: 10,
            },
            grid: { vertLines: { color: '#1c2230' }, horzLines: { color: '#1c2230' } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            rightPriceScale: { borderColor: '#30363d' },
            timeScale: { borderColor: '#30363d', timeVisible: true },
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
                    <span style="color:${l.chg >= 0 ? '#22c55e' : '#ef4444'}">${l.chg >= 0 ? '+' : ''}${l.chg.toFixed(2)}%</span>
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
