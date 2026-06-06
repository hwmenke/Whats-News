/**
 * pair.js — Pair Trading / Spread analysis
 * Fetches /api/spread?sym1=&sym2= and renders the ratio z-score series with
 * a Chart.js line plus a mean-reversion signal badge.
 */

let _pairChart = null;

function _pairEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

function _pairSignalBadge(signal, z) {
    const map = {
        mean_revert_short: ['Short Spread', 'pair-bear'],
        mean_revert_long:  ['Long Spread',  'pair-bull'],
        neutral:           ['Neutral',      'pair-neutral'],
    };
    const [label, cls] = map[signal] || ['—', 'pair-neutral'];
    const zTxt = (z === null || z === undefined) ? '' : ` (z = ${Number(z).toFixed(2)})`;
    return `<span class="pair-badge ${cls}">${label}${zTxt}</span>`;
}

async function runPairAnalysis() {
    const s1 = (document.getElementById('pair-sym1')?.value || '').trim().toUpperCase();
    const s2 = (document.getElementById('pair-sym2')?.value || '').trim().toUpperCase();
    const win = parseInt(document.getElementById('pair-window')?.value || '20', 10);
    const status = document.getElementById('pair-status');
    if (!s1 || !s2) { if (status) status.textContent = 'Enter two symbols.'; return; }
    if (s1 === s2)  { if (status) status.textContent = 'Symbols must differ.'; return; }
    if (status) status.innerHTML = '<span class="spinner"></span> Computing spread…';

    try {
        const d = await apiFetch(`${API}/spread?sym1=${encodeURIComponent(s1)}&sym2=${encodeURIComponent(s2)}&window=${win}`);
        if (status) status.innerHTML = `${_pairEsc(s1)} / ${_pairEsc(s2)} &nbsp; ${_pairSignalBadge(d.signal, d.last_zscore)}`;

        const ctx = document.getElementById('pair-chart');
        if (ctx && window.Chart) {
            if (_pairChart) _pairChart.destroy();
            _pairChart = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: d.series.map(p => p.date),
                    datasets: [{
                        label: 'Z-score',
                        data: d.series.map(p => p.zscore),
                        borderColor: '#a855f7',
                        backgroundColor: 'rgba(168,85,247,0.10)',
                        fill: true, tension: 0.1, pointRadius: 0, spanGaps: true,
                    }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { ticks: { maxTicksLimit: 8 } },
                        y: { suggestedMin: -3, suggestedMax: 3 },
                    },
                },
            });
        }
    } catch (e) {
        if (status) status.textContent = `Failed: ${e.message || e}`;
    }
}

function initPair() {
    const s1 = document.getElementById('pair-sym1');
    if (s1 && !s1.value && state.activeSymbol) s1.value = state.activeSymbol;
}
