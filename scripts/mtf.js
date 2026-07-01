/**
 * mtf.js — Multi-timeframe candlestick grid (LightweightCharts)
 */
let _mtfCharts = [];

function initMtf() {
    if (state.activeSymbol) loadMultiTF(state.activeSymbol);
    else {
        const grid = document.getElementById('mtf-grid');
        if (grid) grid.innerHTML = '<div class="feat-empty">Select a symbol to view multi-timeframe grid.</div>';
    }
}

async function loadMultiTF(symbol) {
    const sym  = symbol || state.activeSymbol;
    const grid = document.getElementById('mtf-grid');
    if (!grid) return;
    if (!sym) {
        grid.innerHTML = '<div class="feat-empty">Select a symbol to view multi-timeframe grid.</div>';
        return;
    }

    grid.innerHTML = '<div class="feat-loading"><span class="spinner"></span></div>';
    _mtfCharts.forEach(ch => { try { ch.remove(); } catch (_) {} });
    _mtfCharts = [];

    const cfgs = [
        { label: '60-Day Daily',   freq: 'daily',  limit: 60  },
        { label: '1-Year Daily',   freq: 'daily',  limit: 252 },
        { label: '2Y Weekly',      freq: 'weekly', limit: 104 },
        { label: '5Y Weekly',      freq: 'weekly', limit: 260 },
    ];

    try {
        const datasets = await Promise.all(
            cfgs.map(cfg =>
                apiFetch(`${API}/ohlcv/${sym}?freq=${cfg.freq}&limit=${cfg.limit}`).catch(() => [])
            )
        );

        grid.innerHTML = `<div class="mtf-grid-inner">
            ${cfgs.map((cfg, i) =>
                `<div class="mtf-panel">
                    <div class="mtf-panel-label">${sym} · ${cfg.label}</div>
                    <div id="mtf-c${i}" class="mtf-canvas-wrap"></div>
                </div>`
            ).join('')}
        </div>`;

        cfgs.forEach((cfg, i) => {
            const rows = datasets[i];
            const el   = document.getElementById(`mtf-c${i}`);
            if (!el || !rows?.length) return;

            const chart = LightweightCharts.createChart(el, {
                width:  el.clientWidth,
                height: 200,
                layout: {
                    background: { color: (window._CT||{}).bg||'#0b101a' },
                    textColor:  (window._CT||{}).text||'#9aafc4',
                    fontFamily: (window._CT||{}).font||"'Inter', -apple-system, 'Helvetica Neue', sans-serif",
                    fontSize: 10,
                },
                grid:   { vertLines: { visible: false }, horzLines: { color: (window._CT||{}).grid||'#1c2638' } },
                rightPriceScale: { borderColor: (window._CT||{}).grid||'#1c2638' },
                timeScale: { borderColor: (window._CT||{}).grid||'#1c2638', visible: true },
                crosshair: { mode: 1 },
                handleScroll: true,
                handleScale:  true,
            });

            const candle = chart.addCandlestickSeries({
                upColor:        '#4DAF88',
                downColor:      '#E05252',
                borderUpColor:  '#4DAF88',
                borderDownColor:'#E05252',
                wickUpColor:    '#4DAF88',
                wickDownColor:  '#E05252',
            });
            candle.setData(rows.map(r => ({
                time: r.date, open: r.open, high: r.high, low: r.low, close: r.close,
            })));
            chart.timeScale().fitContent();
            _mtfCharts.push(chart);
            new ResizeObserver(() => chart.resize(el.clientWidth, 200)).observe(el);
        });
    } catch (e) {
        grid.innerHTML = `<div class="feat-empty" style="color:var(--red);">${e.message}</div>`;
    }
}
