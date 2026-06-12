/**
 * chart_helpers.js — In-place Chart.js update helper.
 *
 * updateOrCreate(stateKey, canvasEl, config)
 *   If a Chart for stateKey already exists and the dataset count matches,
 *   mutates data + options in-place and calls chart.update('none') — no flicker.
 *   Otherwise destroys the old chart and creates a new one.
 *
 * destroyChart(stateKey)
 *   Destroys the chart and removes it from the registry.
 */

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
