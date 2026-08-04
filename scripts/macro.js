/**
 * macro.js — Macro tab (FRED series)
 *
 * One card per series: latest value, a sparkline, and a trend badge comparing
 * the latest reading with roughly a quarter ago. Series flagged `invert` (credit
 * spreads, jobless claims, policy rate) are coloured the other way round, since
 * for those RISING is the risk-off signal.
 */

const MACRO_LOOKBACK = 63;          // ~3 months of business days
let   _macroCharts   = [];
let   _macroLoaded   = false;
let   _recessionCache = null;

async function initMacro() {
    if (_macroLoaded) return;
    await loadMacroData();
    _macroLoaded = true;
}

async function loadMacroData() {
    try {
        const payload = await apiFetch(`${API}/macro`);
        renderMacroCards(payload);
    } catch (e) {
        toast('Macro load failed: ' + e.message, 'error');
    }
}

async function macroRefresh() {
    const btn  = document.getElementById('btn-macro-refresh');
    const load = document.getElementById('macro-loading');
    if (btn)  btn.disabled = true;
    if (load) load.style.display = 'inline-flex';

    try {
        const results = await apiFetch(`${API}/macro/refresh`, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify({}),
        });
        const failed = results.filter(r => r.error);
        const okN    = results.length - failed.length;
        if (failed.length) {
            toast(`Macro: ${okN} updated, ${failed.length} failed (${failed.map(f => f.series).join(', ')})`,
                  'warning', 7000);
        } else {
            toast(`Macro: ${okN} series updated`, 'success');
        }
        _recessionCache = null;
        await loadMacroData();
    } catch (e) {
        toast('Macro refresh failed: ' + e.message, 'error');
    } finally {
        if (btn)  btn.disabled = false;
        if (load) load.style.display = 'none';
    }
}

function renderMacroCards(payload) {
    const host  = document.getElementById('macro-cards');
    const empty = document.getElementById('macro-empty');
    const tsEl  = document.getElementById('macro-ts');
    if (!host) return;

    _macroCharts.forEach(c => { try { c.destroy(); } catch (_) {} });
    _macroCharts = [];
    host.innerHTML = '';

    const catalogue = payload.series || [];
    const data      = payload.data   || {};
    const withData  = catalogue.filter(s => (data[s.id] || []).some(p => p.value != null));

    if (!withData.length) {
        if (empty) empty.style.display = 'flex';
        if (tsEl)  tsEl.textContent = '';
        return;
    }
    if (empty) empty.style.display = 'none';

    const latestDates = (payload.stored || []).map(s => s.latest).filter(Boolean).sort();
    if (tsEl && latestDates.length) {
        tsEl.textContent = 'Latest observation ' + latestDates[latestDates.length - 1];
    }

    withData.forEach(meta => {
        const obs = (data[meta.id] || []).filter(p => p.value != null);
        if (!obs.length) return;

        const latest = obs[obs.length - 1];
        const prior  = obs[Math.max(0, obs.length - 1 - MACRO_LOOKBACK)];
        const delta  = latest.value - prior.value;

        // For inverted series a rise is bad, so flip the colour, not the arrow.
        const rising = delta > 0;
        const good   = meta.invert ? !rising : rising;
        const cls    = Math.abs(delta) < 1e-9 ? 'macro-flat' : (good ? 'macro-good' : 'macro-bad');

        const card = document.createElement('div');
        card.className = 'macro-card';
        card.innerHTML = `
            <div class="macro-card-label">${meta.label}
                <span class="macro-series-id">${meta.id}</span>
            </div>
            <div class="macro-card-value">${_macroFmt(latest.value)}<span class="macro-unit">${meta.unit || ''}</span></div>
            <div class="macro-card-delta ${cls}">
                ${rising ? '▲' : (delta < 0 ? '▼' : '■')}
                ${_macroFmt(Math.abs(delta))} vs ${prior.date}
            </div>
            <div class="macro-spark"><canvas></canvas></div>
        `;
        host.appendChild(card);

        const canvas = card.querySelector('canvas');
        if (canvas && typeof Chart !== 'undefined') {
            const tail = obs.slice(-260);            // ~1y of observations
            _macroCharts.push(new Chart(canvas, {
                type: 'line',
                data: {
                    labels: tail.map(p => p.date),
                    datasets: [{
                        data: tail.map(p => p.value),
                        borderColor: good ? '#22c55e' : '#ef4444',
                        backgroundColor: good ? 'rgba(34,197,94,0.10)' : 'rgba(239,68,68,0.10)',
                        borderWidth: 1.5,
                        pointRadius: 0,
                        tension: 0.2,
                        fill: true,
                    }],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: { callbacks: { label: c => `${c.label}: ${_macroFmt(c.parsed.y)}` } },
                    },
                    scales: { x: { display: false }, y: { display: false } },
                },
            }));
        }
    });
}

function _macroFmt(v) {
    if (v == null || !isFinite(v)) return '—';
    if (Math.abs(v) >= 1000) return v.toLocaleString('en-US', { maximumFractionDigits: 0 });
    return v.toFixed(2);
}

/**
 * Recession ranges from FRED's USREC, cached. Exposed for chart shading —
 * returns [] (never throws) so callers can use it unconditionally.
 */
async function getRecessionRanges() {
    if (_recessionCache) return _recessionCache;
    try {
        const r = await apiFetch(`${API}/macro/recessions`);
        _recessionCache = Array.isArray(r) ? r : [];
    } catch (_) {
        _recessionCache = [];
    }
    return _recessionCache;
}
window.getRecessionRanges = getRecessionRanges;
