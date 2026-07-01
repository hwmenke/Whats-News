/**
 * chart_extras.js — Crosshair tooltip, drawing tools, replay mode,
 *                   live polling, volume profile overlay, earnings markers,
 *                   theme toggle, focus mode.
 */

let _replayActive   = false;
let _replayData     = null;
let _replayIdx      = 0;
let _livePolling    = null;
let _volProfileOn   = false;
let _drawings       = {};
let _crosshairBound = false;

// Called by app.js after a symbol loads
function _extrasOnSymbolLoad(symbol) {
    if (!symbol) return;
    loadDrawingsForSymbol(symbol);
    _crosshairBound = false;
    setTimeout(() => { if (!_crosshairBound) _attachCrosshair(); }, 400);
    loadEarningsMarkers(symbol);
    if (typeof _swingWidgetOnSymbolLoad === 'function') _swingWidgetOnSymbolLoad(symbol);
}

// ─── Theme ────────────────────────────────────────────────────────────────────

function toggleTheme() {
    const root  = document.documentElement;
    const light = root.dataset.theme !== 'light';
    root.dataset.theme = light ? 'light' : 'dark';
    try { localStorage.setItem('theme', root.dataset.theme); } catch (_) {}
    const btn = document.getElementById('btn-theme-toggle');
    if (btn) btn.title = light ? 'Switch to dark mode' : 'Switch to light mode';
    btn && (btn.textContent = light ? '🌙' : '☀️');
}

function _initTheme() {
    try {
        const saved = localStorage.getItem('theme') || 'dark';
        document.documentElement.dataset.theme = saved;
        const btn = document.getElementById('btn-theme-toggle');
        if (btn) btn.textContent = saved === 'light' ? '🌙' : '☀️';
    } catch (_) {}
}

// ─── Focus Mode ───────────────────────────────────────────────────────────────

let _focusMode = false;
let _focusHintEl = null;

function toggleFocusMode() {
    _focusMode = !_focusMode;
    document.body.classList.toggle('focus-mode', _focusMode);
    const btn = document.getElementById('btn-focus-mode');
    if (btn) btn.style.color = _focusMode ? 'var(--amber)' : '';

    if (_focusMode) {
        // Show a small persistent restore hint
        if (!_focusHintEl) {
            _focusHintEl = document.createElement('div');
            _focusHintEl.id = 'focus-restore-hint';
            _focusHintEl.innerHTML = 'Focus mode — press <kbd>F</kbd> to restore';
            _focusHintEl.style.cssText =
                'position:fixed;bottom:8px;right:12px;z-index:9999;' +
                'font-size:11px;color:rgba(240,163,47,0.7);pointer-events:none;' +
                'font-family:var(--font-mono);letter-spacing:0.04em;';
            document.body.appendChild(_focusHintEl);
        }
        _focusHintEl.style.display = 'block';
    } else {
        if (_focusHintEl) _focusHintEl.style.display = 'none';
    }
}

// ─── Live Polling ─────────────────────────────────────────────────────────────

function _startLivePolling() {
    _stopLivePolling();
    _livePolling = setInterval(() => {
        if (typeof state !== 'undefined'
                && state.activeTab === 'charts'
                && state.activeSymbol
                && !_replayActive
                && typeof loadChartData === 'function') {
            loadChartData(state.activeSymbol);
        }
    }, 60000);
}

function _stopLivePolling() {
    if (_livePolling) { clearInterval(_livePolling); _livePolling = null; }
}

// ─── Crosshair Tooltip ────────────────────────────────────────────────────────

function _attachCrosshair() {
    if (typeof charts === 'undefined' || !charts.daily?.main) return;
    if (typeof series === 'undefined' || !series.daily?.candle) return;
    _crosshairBound = true;

    const tooltip = document.getElementById('crosshair-tooltip');
    if (!tooltip) return;

    charts.daily.main.subscribeCrosshairMove(param => {
        if (!param || !param.time || !param.point) {
            tooltip.style.display = 'none';
            return;
        }
        const ohlc = param.seriesData.get(series.daily.candle);
        if (!ohlc) { tooltip.style.display = 'none'; return; }

        const chg = (ohlc.open && ohlc.open > 0)
            ? ((ohlc.close / ohlc.open - 1) * 100).toFixed(2)
            : null;
        const chgColor = chg !== null
            ? (parseFloat(chg) >= 0 ? '#22c55e' : '#ef4444')
            : '';

        tooltip.innerHTML = [
            `<span style="color:#6b7280">O</span> ${ohlc.open?.toFixed(2) ?? '–'}`,
            `<span style="color:#22c55e">H</span> ${ohlc.high?.toFixed(2) ?? '–'}`,
            `<span style="color:#ef4444">L</span> ${ohlc.low?.toFixed(2) ?? '–'}`,
            `<span style="color:#3b82f6">C</span> ${ohlc.close?.toFixed(2) ?? '–'}`,
            chg !== null
                ? `<span style="color:${chgColor}">${parseFloat(chg) >= 0 ? '+' : ''}${chg}%</span>`
                : '',
        ].filter(Boolean).join(' · ');

        const wrap = document.getElementById('chart-daily-main');
        if (wrap) {
            const r = wrap.getBoundingClientRect();
            tooltip.style.top  = (r.top  + window.scrollY + 6) + 'px';
            tooltip.style.left = (r.left + 6) + 'px';
        }
        tooltip.style.display = 'block';
    });
}

// ─── Replay Mode ──────────────────────────────────────────────────────────────

async function startReplay() {
    const sym = typeof state !== 'undefined' ? state.activeSymbol : null;
    if (!sym) { toast('Select a symbol first', 'warning'); return; }

    const startDate = document.getElementById('replay-start-date')?.value;
    try {
        const rows = await apiFetch(`${API}/ohlcv/${sym}?freq=daily&limit=2000`);
        if (!rows?.length) { toast('No data for replay', 'warning'); return; }

        let startIdx = startDate ? Math.max(50, rows.findIndex(r => r.date >= startDate)) : 50;
        if (startIdx < 50) startIdx = 50;

        _replayData   = rows;
        _replayIdx    = startIdx;
        _replayActive = true;

        _renderReplayFrame();
        document.getElementById('replay-controls')?.classList.remove('hidden');
        document.getElementById('btn-replay-start')?.setAttribute('disabled', '');
        toast(`Replay from ${rows[_replayIdx]?.date ?? startDate}`, 'info');
    } catch (e) {
        toast('Replay failed: ' + e.message, 'error');
    }
}

function _renderReplayFrame() {
    if (!_replayData || !_replayActive) return;
    const slice = _replayData.slice(0, _replayIdx + 1);
    if (typeof series !== 'undefined' && series.daily?.candle) {
        series.daily.candle.setData(slice.map(r => ({
            time: r.date, open: r.open, high: r.high, low: r.low, close: r.close,
        })));
        if (typeof charts !== 'undefined' && charts.daily?.main) {
            charts.daily.main.timeScale().scrollToRealTime();
        }
    }
    const lbl = document.getElementById('replay-bar-label');
    if (lbl) lbl.textContent = `${slice[slice.length - 1]?.date ?? '–'} · bar ${_replayIdx + 1} / ${_replayData.length}`;
}

function replayNext(n) {
    if (!_replayActive || !_replayData) return;
    _replayIdx = Math.min(_replayIdx + (n || 1), _replayData.length - 1);
    _renderReplayFrame();
    if (_replayIdx >= _replayData.length - 1) toast('End of replay data', 'info');
}

function replayPrev() {
    if (!_replayActive || !_replayData) return;
    _replayIdx = Math.max(_replayIdx - 1, 50);
    _renderReplayFrame();
}

function stopReplay() {
    _replayActive = false;
    _replayData   = null;
    document.getElementById('replay-controls')?.classList.add('hidden');
    document.getElementById('btn-replay-start')?.removeAttribute('disabled');
    const lbl = document.getElementById('replay-bar-label');
    if (lbl) lbl.textContent = '';
    if (typeof state !== 'undefined' && state.activeSymbol && typeof loadChartData === 'function') {
        loadChartData(state.activeSymbol);
    }
    toast('Replay stopped', 'info');
}

// ─── Volume Profile ───────────────────────────────────────────────────────────

async function toggleVolProfile() {
    _volProfileOn = !_volProfileOn;
    const btn   = document.getElementById('btn-vol-profile');
    const panel = document.getElementById('vol-profile-panel');
    if (!panel) return;

    if (btn) btn.classList.toggle('active', _volProfileOn);

    if (!_volProfileOn) {
        panel.style.display = 'none';
        return;
    }

    const sym = typeof state !== 'undefined' ? state.activeSymbol : null;
    if (!sym) {
        toast('Select a symbol first', 'warning');
        _volProfileOn = false;
        if (btn) btn.classList.remove('active');
        return;
    }

    panel.style.display = 'flex';
    panel.innerHTML = '<span class="spinner" style="margin:auto;"></span>';

    try {
        const { buckets } = await apiFetch(`${API}/volume-profile/${sym}?bins=30&limit=252`);
        const maxVol = Math.max(...buckets.map(b => b.volume));
        panel.innerHTML = '<div class="vp-inner">'
            + buckets.slice().reverse().map(b => {
                const w = maxVol > 0 ? Math.round(b.volume / maxVol * 100) : 0;
                return `<div class="vp-row" title="$${b.price_mid?.toFixed(2)} — ${b.volume_pct?.toFixed(1)}%">
                    <span class="vp-price">${b.price_mid?.toFixed(1)}</span>
                    <div class="vp-bar" style="width:${w}%"></div>
                </div>`;
            }).join('')
            + '</div>';
    } catch (e) {
        panel.innerHTML = `<div style="color:var(--red); padding:8px; font-size:11px;">${e.message}</div>`;
    }
}

// ─── Drawing Tools ────────────────────────────────────────────────────────────

function loadDrawingsForSymbol(symbol) {
    if (!symbol) return;
    try {
        const raw = localStorage.getItem(`drawings_${symbol}`);
        _drawings[symbol] = raw ? JSON.parse(raw) : [];
    } catch (_) {
        _drawings[symbol] = [];
    }
    setTimeout(() => _applyDrawingsToChart(symbol), 500);
    renderDrawingsList(symbol);
}

function _saveDrawings(symbol) {
    try {
        localStorage.setItem(`drawings_${symbol}`,
            JSON.stringify((_drawings[symbol] || []).map(
                ({ price, label, color }) => ({ price, label, color })
            ))
        );
    } catch (_) {}
}

function _applyDrawingsToChart(symbol) {
    const candle = typeof series !== 'undefined' ? series.daily?.candle : null;
    if (!candle) return;
    for (const d of (_drawings[symbol] || [])) {
        if (!d.lwcLine) {
            try {
                d.lwcLine = candle.createPriceLine({
                    price: d.price, color: d.color || '#f97316', lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: true, title: d.label || '',
                });
            } catch (_) {}
        }
    }
}

function addDrawingLevel() {
    const sym   = typeof state !== 'undefined' ? state.activeSymbol : null;
    const price = parseFloat(document.getElementById('drawing-price-input')?.value);
    const label = (document.getElementById('drawing-label-input')?.value || '').trim();
    const color = document.getElementById('drawing-color-input')?.value || '#f97316';

    if (!sym)         { toast('Select a symbol first', 'warning'); return; }
    if (isNaN(price)) { toast('Enter a valid price', 'warning');   return; }

    if (!_drawings[sym]) _drawings[sym] = [];

    const candle  = typeof series !== 'undefined' ? series.daily?.candle : null;
    let lwcLine   = null;
    if (candle) {
        try {
            lwcLine = candle.createPriceLine({
                price, color, lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Dashed,
                axisLabelVisible: true, title: label,
            });
        } catch (_) {}
    }

    _drawings[sym].push({ price, label, color, lwcLine, id: Date.now() });
    _saveDrawings(sym);
    renderDrawingsList(sym);
    const pi = document.getElementById('drawing-price-input');
    const li = document.getElementById('drawing-label-input');
    if (pi) pi.value = '';
    if (li) li.value = '';
}

function removeDrawingLevel(id) {
    const sym = typeof state !== 'undefined' ? state.activeSymbol : null;
    if (!sym || !_drawings[sym]) return;
    const idx = _drawings[sym].findIndex(d => d.id === id);
    if (idx === -1) return;
    const d      = _drawings[sym][idx];
    const candle = typeof series !== 'undefined' ? series.daily?.candle : null;
    if (d.lwcLine && candle) try { candle.removePriceLine(d.lwcLine); } catch (_) {}
    _drawings[sym].splice(idx, 1);
    _saveDrawings(sym);
    renderDrawingsList(sym);
}

function renderDrawingsList(symbol) {
    const c     = document.getElementById('drawings-list');
    if (!c) return;
    const items = _drawings[symbol] || [];
    if (!items.length) {
        c.innerHTML = '<span style="color:var(--text-dim); font-size:11px;">No levels set</span>';
        return;
    }
    c.innerHTML = items.map(d =>
        `<span class="drawing-item">
            <span class="drawing-dot" style="background:${d.color};"></span>
            <span>$${d.price.toFixed(2)}${d.label ? ' ' + d.label : ''}</span>
            <button class="drawing-rm" onclick="removeDrawingLevel(${d.id})">×</button>
        </span>`
    ).join('');
}

// ─── Earnings Markers ─────────────────────────────────────────────────────────

async function loadEarningsMarkers(symbol) {
    if (!symbol) return;
    try {
        const data = await apiFetch(`${API}/earnings/${symbol}`);
        _applyEarningsMarkers(symbol, data.dates || []);
    } catch (_) {}
}

function _applyEarningsMarkers(symbol, dates) {
    const candle = typeof series !== 'undefined' ? series.daily?.candle : null;
    if (!candle || !dates.length) return;

    const markers = dates.map(d => ({
        time:     d.date,
        position: 'aboveBar',
        color:    '#a855f7',
        shape:    'circle',
        size:     1,
        text:     'E',
    }));

    try { candle.setMarkers(markers); } catch (_) {}
}

// ─── Init ─────────────────────────────────────────────────────────────────────

(function () {
    document.addEventListener('DOMContentLoaded', () => {
        _initTheme();
        _startLivePolling();
    });

    document.addEventListener('keydown', e => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
        if (e.key === 'f' || e.key === 'F') toggleFocusMode();
    });
})();
