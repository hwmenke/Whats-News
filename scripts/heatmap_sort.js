/**
 * heatmap_sort.js — compact Desk vs Day% sort on the regime heatmap.
 * Wraps renderRegimeHeatmap after app.js. Client-side only; cell click still selectSymbol.
 * not a published rating.
 */
const HEATMAP_SORT_KEY = 'whats-news-heatmap-sort';
let heatmapSort = 'desk';
let lastHeatmapData = null;

function normalizeHeatmapSort(value) {
    return String(value == null ? '' : value).trim().toLowerCase() === 'day' ? 'day' : 'desk';
}

function readHeatmapSort() {
    try {
        return normalizeHeatmapSort(localStorage.getItem(HEATMAP_SORT_KEY));
    } catch {
        return 'desk';
    }
}

function writeHeatmapSort(mode) {
    try {
        localStorage.setItem(HEATMAP_SORT_KEY, normalizeHeatmapSort(mode));
    } catch { /* ignore quota */ }
}

function persistHeatmapSort() {
    writeHeatmapSort(heatmapSort);
}

function heatmapChangePct(row) {
    const v = row && row.change_pct;
    if (v == null || v === '') return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
}

function sortHeatmapRows(rows) {
    const list = Array.isArray(rows) ? rows.slice() : [];
    if (heatmapSort !== 'day') return list;
    return list.sort((a, b) => {
        const va = heatmapChangePct(a);
        const vb = heatmapChangePct(b);
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        return vb - va;
    });
}

function syncHeatmapSortButtons() {
    const mode = heatmapSort;
    document.querySelectorAll('.heatmap-sort-btn').forEach(btn => {
        const on = btn.dataset.sort === mode;
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
}

function restoreHeatmapSort() {
    heatmapSort = readHeatmapSort();
    syncHeatmapSortButtons();
    return heatmapSort;
}

function rerenderHeatmap() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    const meta = (typeof state !== 'undefined' && state) ? state.portfolioMeta : null;
    const data = (meta && typeof meta === 'object') ? meta : lastHeatmapData;
    if (typeof g.renderRegimeHeatmap === 'function') {
        g.renderRegimeHeatmap(data && typeof data === 'object' ? data : {});
    }
}

function setHeatmapSort(mode) {
    heatmapSort = normalizeHeatmapSort(mode);
    persistHeatmapSort();
    syncHeatmapSortButtons();
    rerenderHeatmap();
}

function bindHeatmapSortUi() {
    document.querySelectorAll('.heatmap-sort-btn').forEach(btn => {
        if (btn._heatmapSortBound) return;
        btn._heatmapSortBound = true;
        btn.addEventListener('click', () => setHeatmapSort(btn.dataset.sort));
    });
}

function wrapRenderRegimeHeatmap() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.renderRegimeHeatmap !== 'function' || g.renderRegimeHeatmap._heatmapSortWrapped) return;
    const orig = g.renderRegimeHeatmap;
    function renderRegimeHeatmapSorted(data) {
        const src = data && typeof data === 'object' ? data : {};
        lastHeatmapData = src;
        const payload = Object.assign({}, src, {
            heatmap: sortHeatmapRows(src.heatmap || []),
        });
        const args = Array.prototype.slice.call(arguments, 1);
        return orig.apply(this, [payload].concat(args));
    }
    renderRegimeHeatmapSorted._heatmapSortWrapped = true;
    g.renderRegimeHeatmap = renderRegimeHeatmapSorted;
}

function bootHeatmapSort() {
    wrapRenderRegimeHeatmap();
    bindHeatmapSortUi();
    restoreHeatmapSort();
}

if (typeof document !== 'undefined' && document.addEventListener) {
    bootHeatmapSort();
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootHeatmapSort);
    }
}
