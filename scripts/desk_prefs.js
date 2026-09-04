/**
 * Desk prefs — localStorage only. No secrets. Shared keys with the iPhone client.
 */
/* global API, apiFetch, loadSymbols, loadChartData, loadNewsData, loadFractalScan, toast */

const DESK_PREFS_KEY = 'whats-news-desk-prefs';

const _deskPrefDefaults = {
    familyFilter: '',
    newsScope: 'symbol',
    rightFreq: 'weekly',
    refreshSec: 0,
    scanLens: 'trend',
    edgeTag: '',
    qullaLens: 'all',
    finvizPreset: 'qulla_momentum',
};

function readDeskPrefs() {
    try {
        const raw = JSON.parse(localStorage.getItem(DESK_PREFS_KEY) || '{}');
        return { ..._deskPrefDefaults, ...(raw && typeof raw === 'object' ? raw : {}) };
    } catch {
        return { ..._deskPrefDefaults };
    }
}

function writeDeskPrefs(patch) {
    const next = { ...readDeskPrefs(), ...patch };
    try {
        localStorage.setItem(DESK_PREFS_KEY, JSON.stringify(next));
    } catch { /* quota */ }
    return next;
}

let _deskRefreshTimer = null;

function applyDeskRefreshInterval(sec) {
    const n = Number(sec) || 0;
    writeDeskPrefs({ refreshSec: n });
    if (_deskRefreshTimer) {
        clearInterval(_deskRefreshTimer);
        _deskRefreshTimer = null;
    }
    if (n < 15) return;
    _deskRefreshTimer = setInterval(() => {
        if (typeof loadSymbols === 'function') loadSymbols();
        if (typeof window.loadMacroBoard === 'function') window.loadMacroBoard();
        if (typeof state !== 'undefined' && state.activeSymbol && typeof loadChartData === 'function') {
            loadChartData(state.activeSymbol);
        }
    }, n * 1000);
}

function applyScanLens(lens) {
    const id = lens || 'trend';
    writeDeskPrefs({ scanLens: id });
    const trend = document.getElementById('desk-trend-scan');
    const fractal = document.getElementById('fractal-scan-panel');
    const finviz = document.getElementById('finviz-scan-panel');
    const hmm = document.getElementById('hmm-scan-panel');
    const setup = document.querySelector('#scanner-area .setup-scanner-panel:not(.fractal-scan-panel):not(.desk-trend-scan):not(.finviz-scan-panel):not(.hmm-scan-panel)');
    const metrics = document.getElementById('scanner-table');
    const metricsWrap = metrics && metrics.closest('.scanner-table-wrap');
    const metricsControls = document.querySelector('#scanner-area .scanner-controls');
    const showTrend = id === 'trend';
    const showQullaOrSetups = id === 'qulla' || id === 'setups';
    const showMetrics = id === 'metrics';
    const showFractal = id === 'fractal';
    const showFinviz = id === 'finviz';
    const showHmm = id === 'hmm';
    if (trend) trend.style.display = showTrend ? '' : 'none';
    if (fractal) fractal.style.display = showFractal ? '' : 'none';
    if (finviz) finviz.style.display = showFinviz ? '' : 'none';
    if (hmm) hmm.style.display = showHmm ? '' : 'none';
    if (setup) setup.style.display = showQullaOrSetups ? '' : 'none';
    if (metricsWrap) metricsWrap.style.display = showMetrics ? '' : 'none';
    if (metricsControls) metricsControls.style.display = showMetrics ? '' : 'none';
    document.querySelectorAll('#scan-lens-bar .scan-lens-btn').forEach(btn => {
        btn.classList.toggle('on', btn.dataset.lens === id);
    });
    if (id === 'trend' && typeof loadDeskTrendScan === 'function') loadDeskTrendScan();
    if (id === 'fractal' && typeof loadFractalScan === 'function') loadFractalScan();
    if (id === 'finviz' && typeof loadFinvizScreener === 'function') {
        loadFinvizScreener({ preset: readDeskPrefs().finvizPreset });
    }
    if (id === 'hmm' && typeof loadHmmScan === 'function') loadHmmScan();
    if (id === 'qulla' && typeof window.setQullaLens === 'function') {
        window.setQullaLens(readDeskPrefs().qullaLens || 'qulla');
    }
}

async function loadDeskTrendScan() {
    const tbody = document.getElementById('desk-trend-tbody');
    const empty = document.getElementById('desk-trend-empty');
    const meta = document.getElementById('desk-trend-meta');
    if (!tbody) return;
    if (meta) meta.textContent = 'GET /api/trend-scan…';
    try {
        const data = await apiFetch(`${API}/trend-scan?desk=1&freq=daily`);
        const rows = Array.isArray(data) ? data : (data.rows || data.results || []);
        tbody.innerHTML = '';
        rows.forEach(row => {
            const tr = document.createElement('tr');
            tr.dataset.symbol = row.symbol || '';
            tr.innerHTML = `
                <td class="macro-sym">${row.symbol || ''}</td>
                <td>${row.signal ?? row.trend_signal ?? '—'}</td>
                <td>${row.rsi != null ? Number(row.rsi).toFixed(1) : '—'}</td>
                <td>${row.kama10_pct != null ? Number(row.kama10_pct).toFixed(1) : '—'}</td>
                <td>${row.kama20_pct != null ? Number(row.kama20_pct).toFixed(1) : '—'}</td>
                <td>${row.kama50_pct != null ? Number(row.kama50_pct).toFixed(1) : '—'}</td>`;
            tr.addEventListener('click', () => {
                if (row.symbol && typeof selectSymbol === 'function') selectSymbol(row.symbol);
            });
            tbody.appendChild(tr);
        });
        if (empty) empty.style.display = rows.length ? 'none' : 'block';
        if (meta) meta.textContent = `${rows.length} rows`;
    } catch (err) {
        if (meta) meta.textContent = 'error';
        if (empty) {
            empty.style.display = 'block';
            const p = empty.querySelector('p');
            if (p) p.textContent = err.message || 'Trend scan unavailable';
        }
    }
}

function bindDeskPrefs() {
    const prefs = readDeskPrefs();
    if (typeof state !== 'undefined') {
        state.familyFilter = prefs.familyFilter || '';
        state.newsScope = prefs.newsScope || 'symbol';
        state.rightFreq = prefs.rightFreq || 'weekly';
    }
    document.querySelectorAll('#desk-family-filters .family-chip').forEach(btn => {
        btn.classList.toggle('on', (btn.dataset.family || '') === (prefs.familyFilter || ''));
    });
    document.querySelectorAll('#news-scope .news-scope-btn').forEach(btn => {
        btn.classList.toggle('on', btn.dataset.scope === (prefs.newsScope || 'symbol'));
    });
    document.querySelectorAll('#chart-right-freq .chart-right-freq-btn').forEach(btn => {
        btn.classList.toggle('on', btn.dataset.freq === (prefs.rightFreq || 'weekly'));
    });
    const title = document.getElementById('chart-right-title');
    if (title) {
        const freq = prefs.rightFreq === 'monthly' ? 'Monthly' : 'Weekly';
        title.firstChild && (title.firstChild.textContent = freq + ' ');
    }
    const refreshEl = document.getElementById('desk-refresh-sec');
    if (refreshEl) refreshEl.value = String(prefs.refreshSec || 0);
    const scanDef = document.getElementById('desk-scan-default');
    if (scanDef) scanDef.value = prefs.scanLens || 'trend';
    applyDeskRefreshInterval(prefs.refreshSec || 0);
    applyScanLens(prefs.scanLens || 'trend');

    document.getElementById('desk-refresh-sec')?.addEventListener('change', e => {
        applyDeskRefreshInterval(e.target.value);
    });
    document.getElementById('desk-scan-default')?.addEventListener('change', e => {
        applyScanLens(e.target.value);
    });
    document.querySelectorAll('#scan-lens-bar .scan-lens-btn').forEach(btn => {
        btn.addEventListener('click', () => applyScanLens(btn.dataset.lens));
    });
    document.getElementById('btn-desk-trend-scan')?.addEventListener('click', () => loadDeskTrendScan());
    if (typeof bindFinvizDesk === 'function') bindFinvizDesk();
    if (typeof bindHmmScan === 'function') bindHmmScan();
    document.querySelectorAll('#news-scope .news-scope-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            writeDeskPrefs({ newsScope: btn.dataset.scope });
            if (typeof state !== 'undefined') state.newsScope = btn.dataset.scope;
            document.querySelectorAll('#news-scope .news-scope-btn').forEach(b => {
                b.classList.toggle('on', b === btn);
            });
            if (typeof loadNewsData === 'function') loadNewsData(state && state.activeSymbol);
        });
    });
    document.querySelectorAll('#chart-right-freq .chart-right-freq-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            writeDeskPrefs({ rightFreq: btn.dataset.freq });
            if (typeof state !== 'undefined') state.rightFreq = btn.dataset.freq;
            document.querySelectorAll('#chart-right-freq .chart-right-freq-btn').forEach(b => {
                b.classList.toggle('on', b === btn);
            });
            const hdr = document.getElementById('chart-right-title');
            if (hdr) hdr.firstChild && (hdr.firstChild.textContent = (btn.dataset.freq === 'monthly' ? 'Monthly' : 'Weekly') + ' ');
            if (typeof applyRightPaneFreq === 'function') applyRightPaneFreq(btn.dataset.freq);
        });
    });
}

window.readDeskPrefs = readDeskPrefs;
window.writeDeskPrefs = writeDeskPrefs;
window.bindDeskPrefs = bindDeskPrefs;
window.applyScanLens = applyScanLens;
window.loadDeskTrendScan = loadDeskTrendScan;
window.applyDeskRefreshInterval = applyDeskRefreshInterval;
