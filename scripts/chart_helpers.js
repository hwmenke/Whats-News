/**
 * chart_helpers.js — In-place Chart.js update helper + shared chart theme.
 *
 * updateOrCreate(stateKey, canvasEl, config)
 *   If a Chart for stateKey already exists and the dataset count matches,
 *   mutates data + options in-place and calls chart.update('none') — no flicker.
 *   Otherwise destroys the old chart and creates a new one.
 *
 * destroyChart(stateKey)
 *   Destroys the chart and removes it from the registry.
 */

// ── 538-inspired chart theme ──────────────────────────────────
// Applied to all Chart.js and LightweightCharts instances.
window._CT = {
    up:     '#4DAF88',   // teal-green  (up candles, positive bars)
    dn:     '#E05252',   // coral-red   (down candles, negative bars)
    blue:   '#029FD5',   // 538 blue    (primary line, RSI14)
    orange: '#F68B42',   // 538 orange  (MACD signal, secondary)
    purple: '#9B89C4',   // muted purple (RSI21, tertiary)
    sky:    '#56B4E9',   // sky blue    (RSI7, accents)
    yellow: '#E8C44A',   // muted yellow
    teal:   '#6CC3D5',   // teal variant
    slate:  '#5B6B7E',   // neutral slate
    // LWC layout
    bg:     '#0b101a',
    text:   '#9aafc4',
    grid:   '#1c2638',
    cross:  '#4d6080',
    font:   "'Inter', -apple-system, 'Helvetica Neue', sans-serif",
};

// Apply global Chart.js defaults so every instance inherits 538 typography
if (typeof Chart !== 'undefined') {
    Chart.defaults.font.family = window._CT.font;
    Chart.defaults.font.size   = 11;
    Chart.defaults.color       = window._CT.text;
}

window._chartRegistry = window._chartRegistry || new Map();

function updateOrCreate(stateKey, canvasEl, config) {
    const existing = window._chartRegistry.get(stateKey);

    if (existing && existing.canvas === canvasEl) {
        const sameShape =
            existing.data.datasets.length === config.data.datasets.length;

        if (sameShape) {
            existing.data.labels = config.data.labels;
            existing.data.datasets.forEach((ds, i) => {
                const src = config.data.datasets[i];
                if (!src) return;
                ds.data = src.data;
                ['backgroundColor', 'borderColor', 'label',
                 'fill', 'tension', 'pointRadius', 'borderWidth',
                 'borderDash', 'pointBackgroundColor'].forEach(k => {
                    if (src[k] !== undefined) ds[k] = src[k];
                });
            });
            if (config.options) {
                // Merge only top-level options keys to avoid full replace
                Object.assign(existing.options, config.options);
            }
            existing.update('none');
            return existing;
        }
    }

    // Destroy stale chart before recreating
    if (existing) {
        try { existing.destroy(); } catch (_) {}
    }

    const chart = new Chart(canvasEl, config);
    window._chartRegistry.set(stateKey, chart);
    return chart;
}

function destroyChart(stateKey) {
    const c = window._chartRegistry.get(stateKey);
    if (c) {
        try { c.destroy(); } catch (_) {}
        window._chartRegistry.delete(stateKey);
    }
}
