/**
 * phase3.js — Advanced features: Strategy Lab, Trade Journal, Portfolio Analytics,
 *              Pair Trading, Replay Mode, Macro Overlay, Volume Profile, Multi-TF Grid,
 *              Drawing Tools, Macro Calendar, Live Polling, Crosshair Tooltip,
 *              Saved Chart State, Screenshot.
 */

// ═══════════════════════════════════════════════════════════════════════════════
// STATE
// ═══════════════════════════════════════════════════════════════════════════════

let _replayActive    = false;
let _replayData      = null;
let _replayIdx       = 0;
let _livePolling     = null;
let _macroCharts     = {};
let _spreadLwc       = null;
let _spreadZLwc      = null;
let _mtfLwcList      = [];
let _analyticsChart  = null;
let _drawings        = {};
let _crosshairBound  = false;
let _volProfileOn    = false;
let _macroOverlayOn  = false;

// ── Called by app.js after a symbol is selected ─────────────────────────────
function _p3OnSymbolLoad(symbol) {
    if (!symbol) return;
    loadSavedChartState(symbol);
    loadDrawingsForSymbol(symbol);
    _crosshairBound = false;
    setTimeout(() => {
        if (!_crosshairBound) _attachCrosshair();
    }, 300);
}

// ═══════════════════════════════════════════════════════════════════════════════
// SAVED CHART STATE
// ═══════════════════════════════════════════════════════════════════════════════

function saveChartStateForSymbol(symbol) {
    if (!symbol || typeof kamaPeriods === 'undefined') return;
    try {
        const kama = Object.keys(kamaPeriods).map(Number);
        const bbOn = typeof activeOverlays !== 'undefined' ? activeOverlays.bb : true;
        localStorage.setItem(`chartState_${symbol}`, JSON.stringify({ kama, bbOn }));
    } catch (_) {}
}

function loadSavedChartState(symbol) {
    if (!symbol) return;
    try {
        const raw = localStorage.getItem(`chartState_${symbol}`);
        if (!raw) return;
        const { kama, bbOn } = JSON.parse(raw);
        if (Array.isArray(kama) && kama.length && typeof kamaPeriods !== 'undefined') {
            const cur = Object.keys(kamaPeriods).map(Number);
            cur.forEach(p => { if (!kama.includes(p) && typeof removeKamaPeriod === 'function') removeKamaPeriod(p); });
            kama.forEach(p => { if (!kamaPeriods[p] && typeof addKamaPeriod === 'function') addKamaPeriod(p); });
            if (typeof renderKamaPills === 'function') renderKamaPills();
        }
        if (typeof bbOn === 'boolean' && typeof activeOverlays !== 'undefined' && bbOn !== activeOverlays.bb) {
            if (typeof toggleOverlay === 'function') toggleOverlay('bb');
            const bbPill = document.getElementById('pill-bb');
            if (bbPill) bbPill.classList.toggle('active-bb', activeOverlays.bb);
        }
    } catch (_) {}
}

// ═══════════════════════════════════════════════════════════════════════════════
// LIVE POLLING
// ═══════════════════════════════════════════════════════════════════════════════

function startLivePolling() {
    stopLivePolling();
    _livePolling = setInterval(() => {
        if (typeof state !== 'undefined' && state.activeTab === 'charts'
                && state.activeSymbol && !_replayActive
                && typeof loadChartData === 'function') {
            loadChartData(state.activeSymbol);
        }
    }, 60000);
}

function stopLivePolling() {
    if (_livePolling) { clearInterval(_livePolling); _livePolling = null; }
}

// ═══════════════════════════════════════════════════════════════════════════════
// CROSSHAIR TOOLTIP
// ═══════════════════════════════════════════════════════════════════════════════

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
            ? ((ohlc.close / ohlc.open - 1) * 100).toFixed(2) : null;
        const chgColor = chg !== null ? (chg >= 0 ? '#22c55e' : '#ef4444') : '';

        tooltip.innerHTML = [
            `<span style="color:var(--text-dim)">O</span>&nbsp;${ohlc.open?.toFixed(2) ?? '–'}`,
            `<span style="color:#22c55e">H</span>&nbsp;${ohlc.high?.toFixed(2) ?? '–'}`,
            `<span style="color:#ef4444">L</span>&nbsp;${ohlc.low?.toFixed(2) ?? '–'}`,
            `<span style="color:#3b82f6">C</span>&nbsp;${ohlc.close?.toFixed(2) ?? '–'}`,
            chg !== null ? `<span style="color:${chgColor}">${chg >= 0 ? '+' : ''}${chg}%</span>` : '',
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

// ═══════════════════════════════════════════════════════════════════════════════
// REPLAY MODE
// ═══════════════════════════════════════════════════════════════════════════════

async function startReplay() {
    const sym = typeof state !== 'undefined' ? state.activeSymbol : null;
    if (!sym) { toast('Select a symbol first', 'warning'); return; }

    const startDate = document.getElementById('replay-start-date')?.value;
    try {
        const rows = await apiFetch(`${API}/ohlcv/${sym}?freq=daily&limit=2000`);
        if (!rows?.length) { toast('No data for replay', 'warning'); return; }

        let startIdx = Math.max(50, rows.findIndex(r => startDate && r.date >= startDate));
        if (startIdx < 50) startIdx = 50;

        _replayData   = rows;
        _replayIdx    = startIdx;
        _replayActive = true;

        _renderReplayFrame();
        document.getElementById('replay-controls')?.classList.remove('hidden');
        document.getElementById('btn-replay')?.setAttribute('disabled', '');
        document.getElementById('btn-replay-stop')?.classList.remove('hidden');
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
    if (lbl) lbl.textContent = `${slice[slice.length - 1]?.date ?? '–'} · bar ${_replayIdx + 1}/${_replayData.length}`;
}

function replayNext(n = 1) {
    if (!_replayActive || !_replayData) return;
    _replayIdx = Math.min(_replayIdx + n, _replayData.length - 1);
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
    document.getElementById('btn-replay-stop')?.classList.add('hidden');
    document.getElementById('btn-replay')?.removeAttribute('disabled');
    const lbl = document.getElementById('replay-bar-label');
    if (lbl) lbl.textContent = '';
    if (typeof state !== 'undefined' && state.activeSymbol && typeof loadChartData === 'function') {
        loadChartData(state.activeSymbol);
    }
    toast('Replay stopped', 'info');
}

// ═══════════════════════════════════════════════════════════════════════════════
// VOLUME PROFILE OVERLAY
// ═══════════════════════════════════════════════════════════════════════════════

async function toggleVolProfile() {
    _volProfileOn = !_volProfileOn;
    const btn   = document.getElementById('btn-vol-profile');
    const panel = document.getElementById('vol-profile-panel');
    if (!panel) return;

    if (btn) btn.classList.toggle('trend-active', _volProfileOn);

    if (!_volProfileOn) {
        panel.style.display = 'none';
        return;
    }

    const sym = typeof state !== 'undefined' ? state.activeSymbol : null;
    if (!sym) {
        toast('Select a symbol first', 'warning');
        _volProfileOn = false;
        if (btn) btn.classList.remove('trend-active');
        return;
    }

    panel.style.display = 'flex';
    panel.innerHTML     = '<span class="spinner" style="margin:auto;"></span>';

    try {
        const { buckets } = await apiFetch(`${API}/volume-profile/${sym}?bins=30&limit=252`);
        const maxVol = Math.max(...buckets.map(b => b.volume));
        panel.innerHTML = '<div class="vp-inner">' + buckets.slice().reverse().map(b => {
            const w = maxVol > 0 ? Math.round(b.volume / maxVol * 100) : 0;
            return `<div class="vp-row" title="$${b.price_mid?.toFixed(2)} — ${b.volume_pct?.toFixed(1)}%">
                <span class="vp-price">${b.price_mid?.toFixed(1)}</span>
                <div class="vp-bar" style="width:${w}%"></div>
            </div>`;
        }).join('') + '</div>';
    } catch (e) {
        panel.innerHTML = `<div style="color:var(--red); padding:8px; font-size:11px;">${e.message}</div>`;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// DRAWING TOOLS (Horizontal Price Levels)
// ═══════════════════════════════════════════════════════════════════════════════

function loadDrawingsForSymbol(symbol) {
    if (!symbol) return;
    try {
        const raw = localStorage.getItem(`drawings_${symbol}`);
        _drawings[symbol] = raw ? JSON.parse(raw) : [];
    } catch (_) {
        _drawings[symbol] = [];
    }
    setTimeout(() => _applyDrawingsToChart(symbol), 400);
    renderDrawingsList(symbol);
}

function _saveDrawings(symbol) {
    try {
        localStorage.setItem(`drawings_${symbol}`,
            JSON.stringify((_drawings[symbol] || []).map(({ price, label, color }) => ({ price, label, color }))));
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
    const label = document.getElementById('drawing-label-input')?.value?.trim() || '';
    const color = document.getElementById('drawing-color-input')?.value || '#f97316';

    if (!sym)        { toast('Select a symbol first', 'warning'); return; }
    if (isNaN(price)){ toast('Enter a valid price', 'warning');   return; }

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
    document.getElementById('drawing-price-input').value = '';
    document.getElementById('drawing-label-input').value = '';
    saveChartStateForSymbol(sym);
}

function removeDrawingLevel(id) {
    const sym = typeof state !== 'undefined' ? state.activeSymbol : null;
    if (!sym || !_drawings[sym]) return;
    const idx = _drawings[sym].findIndex(d => d.id === id);
    if (idx === -1) return;
    const d = _drawings[sym][idx];
    if (d.lwcLine) {
        const candle = typeof series !== 'undefined' ? series.daily?.candle : null;
        if (candle) try { candle.removePriceLine(d.lwcLine); } catch (_) {}
    }
    _drawings[sym].splice(idx, 1);
    _saveDrawings(sym);
    renderDrawingsList(sym);
}

function renderDrawingsList(symbol) {
    const c = document.getElementById('drawings-list');
    if (!c) return;
    const items = _drawings[symbol] || [];
    if (!items.length) {
        c.innerHTML = '<span style="color:var(--text-dim); font-size:11px;">No levels</span>';
        return;
    }
    c.innerHTML = items.map(d =>
        `<span class="drawing-item">
            <span class="drawing-dot" style="background:${d.color};"></span>
            <span>$${d.price.toFixed(2)}${d.label ? ' ' + _esc(d.label) : ''}</span>
            <button class="drawing-rm" onclick="removeDrawingLevel(${d.id})">×</button>
        </span>`
    ).join('');
}

// ═══════════════════════════════════════════════════════════════════════════════
// MACRO ECONOMIC CALENDAR
// ═══════════════════════════════════════════════════════════════════════════════

async function loadMacroCalendar() {
    const c = document.getElementById('calendar-list');
    if (!c) return;
    c.innerHTML = '<div style="padding:24px; text-align:center;"><span class="spinner"></span></div>';
    try {
        const events = await apiFetch(`${API}/calendar`);
        renderCalendar(events);
    } catch (e) {
        c.innerHTML = `<div style="color:var(--red); padding:16px;">${e.message}</div>`;
    }
}

function renderCalendar(events) {
    const c = document.getElementById('calendar-list');
    if (!events.length) {
        c.innerHTML = '<div style="color:var(--text-muted); padding:16px;">No upcoming events found.</div>';
        return;
    }
    const today = new Date().toISOString().slice(0, 10);
    c.innerHTML = `<table class="scanner-table">
        <thead><tr><th>Date</th><th>Type</th><th>Event</th><th>Status</th></tr></thead>
        <tbody>${events.map(e => {
            const past    = e.date < today;
            const isToday = e.date === today;
            const status  = isToday ? '<span style="color:#f97316; font-weight:700;">TODAY</span>'
                          : past    ? '<span style="color:var(--text-dim);">Past</span>'
                                    : '<span style="color:#22c55e;">Upcoming</span>';
            return `<tr style="${past ? 'opacity:0.45;' : ''}">
                <td>${e.date}</td>
                <td><span class="signal-pill" style="background:${e.color}20; border-color:${e.color}; color:${e.color};">${e.type}</span></td>
                <td>${_esc(e.label)}</td>
                <td>${status}</td>
            </tr>`;
        }).join('')}</tbody>
    </table>`;
}

// ═══════════════════════════════════════════════════════════════════════════════
// MACRO OVERLAY
// ═══════════════════════════════════════════════════════════════════════════════

async function toggleMacroOverlay() {
    _macroOverlayOn = !_macroOverlayOn;
    const btn   = document.getElementById('btn-macro-overlay');
    const panel = document.getElementById('macro-overlay-panel');
    if (!panel) return;
    if (btn) btn.classList.toggle('trend-active', _macroOverlayOn);
    panel.style.display = _macroOverlayOn ? 'block' : 'none';
    if (_macroOverlayOn) await loadMacroOverlay();
}

async function loadMacroOverlay() {
    const panel = document.getElementById('macro-overlay-panel');
    if (!panel) return;
    panel.innerHTML = '<div style="padding:8px; font-size:11px; color:var(--text-muted);"><span class="spinner"></span> Loading macro…</div>';
    try {
        const data   = await apiFetch(`${API}/macro`);
        const labels = Object.keys(data);
        if (!labels.length) {
            panel.innerHTML = '<div style="padding:8px; font-size:11px; color:var(--text-muted);">No macro data. Fetch ^VIX, DX-Y.NYB, ^TNX, CL=F first.</div>';
            return;
        }
        Object.values(_macroCharts).forEach(c => { try { c.remove(); } catch (_) {} });
        _macroCharts = {};
        const colors = { VIX: '#ef4444', DXY: '#3b82f6', US10Y: '#f97316', OIL: '#22c55e' };
        panel.innerHTML = `<div class="macro-grid">${labels.map(k =>
            `<div class="macro-card"><div class="macro-card-label">${k}</div><div id="macro-c-${k}" style="width:100%;height:70px;"></div></div>`
        ).join('')}</div>`;
        for (const [key, sd] of Object.entries(data)) {
            const el = document.getElementById(`macro-c-${key}`);
            if (!el || !sd.length) continue;
            const c = LightweightCharts.createChart(el, {
                width: el.clientWidth, height: 70,
                layout: { background: { color: 'transparent' }, textColor: '#8b949e', fontSize: 9 },
                grid: { vertLines: { color: 'transparent' }, horzLines: { color: '#1c2230' } },
                rightPriceScale: { borderColor: 'transparent', visible: true },
                timeScale: { borderColor: 'transparent', visible: false },
                crosshair: { mode: 0 }, handleScroll: false, handleScale: false,
            });
            const s = c.addLineSeries({ color: colors[key] || '#8b949e', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true });
            s.setData(sd.map(d => ({ time: d.date, value: d.value })));
            c.timeScale().fitContent();
            _macroCharts[key] = c;
        }
    } catch (e) {
        panel.innerHTML = `<div style="padding:8px; color:var(--red); font-size:11px;">${e.message}</div>`;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// MULTI-TIMEFRAME GRID
// ═══════════════════════════════════════════════════════════════════════════════

async function loadMultiTF(symbol) {
    const sym = symbol || (typeof state !== 'undefined' ? state.activeSymbol : null);
    const c   = document.getElementById('mtf-grid');
    if (!c) return;
    if (!sym) {
        c.innerHTML = '<div style="color:var(--text-muted); padding:32px; text-align:center;">Select a symbol first</div>';
        return;
    }
    c.innerHTML = '<div style="padding:32px; text-align:center;"><span class="spinner"></span></div>';
    _mtfLwcList.forEach(ch => { try { ch.remove(); } catch (_) {} });
    _mtfLwcList = [];

    const cfgs = [
        { label: '60-Day',   freq: 'daily',  limit:  60 },
        { label: '1-Year',   freq: 'daily',  limit: 252 },
        { label: '2Y Weekly',freq: 'weekly', limit: 104 },
        { label: '5Y Weekly',freq: 'weekly', limit: 260 },
    ];
    try {
        const datasets = await Promise.all(cfgs.map(cfg =>
            apiFetch(`${API}/ohlcv/${sym}?freq=${cfg.freq}&limit=${cfg.limit}`).catch(() => [])
        ));
        c.innerHTML = `<div class="mtf-grid-inner">${cfgs.map((cfg, i) =>
            `<div class="mtf-panel"><div class="mtf-panel-label">${cfg.label}</div><div id="mtf-c${i}" style="width:100%;height:160px;"></div></div>`
        ).join('')}</div>`;
        cfgs.forEach((cfg, i) => {
            const rows = datasets[i];
            const el   = document.getElementById(`mtf-c${i}`);
            if (!el || !rows?.length) return;
            const chart = LightweightCharts.createChart(el, {
                width: el.clientWidth, height: 160,
                layout: { background: { color: '#0d1117' }, textColor: '#8b949e', fontSize: 9 },
                grid: { vertLines: { color: '#1c2230' }, horzLines: { color: '#1c2230' } },
                rightPriceScale: { borderColor: '#30363d' },
                timeScale: { borderColor: '#30363d', visible: true },
                crosshair: { mode: 1 }, handleScroll: true, handleScale: true,
            });
            const candle = chart.addCandlestickSeries({
                upColor: '#22c55e', downColor: '#ef4444',
                borderUpColor: '#22c55e', borderDownColor: '#ef4444',
                wickUpColor: '#22c55e', wickDownColor: '#ef4444',
            });
            candle.setData(rows.map(r => ({ time: r.date, open: r.open, high: r.high, low: r.low, close: r.close })));
            chart.timeScale().fitContent();
            _mtfLwcList.push(chart);
            new ResizeObserver(() => chart.resize(el.clientWidth, 160)).observe(el);
        });
    } catch (e) {
        c.innerHTML = `<div style="color:var(--red); padding:16px;">${e.message}</div>`;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// PAIR TRADING / SPREAD
// ═══════════════════════════════════════════════════════════════════════════════

async function loadSpread() {
    const sym1 = document.getElementById('pair-sym1')?.value.trim().toUpperCase();
    const sym2 = document.getElementById('pair-sym2')?.value.trim().toUpperCase();
    const win  = document.getElementById('pair-window')?.value || 20;
    const c    = document.getElementById('spread-container');
    if (!c) return;
    if (!sym1 || !sym2) { toast('Enter both symbols', 'warning'); return; }

    c.innerHTML = '<div style="padding:32px; text-align:center;"><span class="spinner"></span></div>';
    if (_spreadLwc)  { try { _spreadLwc.remove();  } catch (_) {} _spreadLwc  = null; }
    if (_spreadZLwc) { try { _spreadZLwc.remove(); } catch (_) {} _spreadZLwc = null; }

    try {
        const data = await apiFetch(`${API}/spread?sym1=${sym1}&sym2=${sym2}&window=${win}`);
        const zColor = data.signal === 'mean_revert_long' ? '#22c55e'
                     : data.signal === 'mean_revert_short' ? '#ef4444' : 'var(--text-muted)';
        const sigTxt = data.signal === 'mean_revert_long'  ? `↑ LONG ${sym1}` :
                       data.signal === 'mean_revert_short' ? `↓ SHORT ${sym1}` : 'Neutral';
        c.innerHTML = `
            <div class="pair-info-row">
                <span class="pair-kpi">Z-Score <strong style="color:${zColor}">${data.last_zscore?.toFixed(2) ?? '–'}</strong></span>
                <span class="pair-kpi">Signal <strong style="color:${zColor}">${sigTxt}</strong></span>
                <span class="pair-kpi">Window <strong>${data.window}d</strong></span>
            </div>
            <div id="pair-ratio-el" style="height:200px; width:100%;"></div>
            <div id="pair-z-el"     style="height:140px; width:100%; margin-top:8px;"></div>`;

        const ratioEl = document.getElementById('pair-ratio-el');
        const zEl     = document.getElementById('pair-z-el');
        const valid   = data.series.filter(d => d.ratio !== null);

        _spreadLwc = LightweightCharts.createChart(ratioEl, {
            width: ratioEl.clientWidth, height: 200,
            layout: { background: { color: '#0d1117' }, textColor: '#8b949e', fontSize: 9 },
            grid: { vertLines: { color: '#1c2230' }, horzLines: { color: '#1c2230' } },
            rightPriceScale: { borderColor: '#30363d' },
            timeScale: { borderColor: '#30363d' }, crosshair: { mode: 1 },
            handleScroll: true, handleScale: true,
        });
        const rs = _spreadLwc.addLineSeries({ color: '#3b82f6', lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
        rs.setData(valid.map(d => ({ time: d.date, value: d.ratio })));
        _spreadLwc.timeScale().fitContent();

        _spreadZLwc = LightweightCharts.createChart(zEl, {
            width: zEl.clientWidth, height: 140,
            layout: { background: { color: '#0d1117' }, textColor: '#8b949e', fontSize: 9 },
            grid: { vertLines: { color: '#1c2230' }, horzLines: { color: '#1c2230' } },
            rightPriceScale: { borderColor: '#30363d', autoScale: false, scaleMargins: { top: 0.1, bottom: 0.1 } },
            timeScale: { borderColor: '#30363d' }, crosshair: { mode: 1 },
            handleScroll: true, handleScale: true,
        });
        const zs = _spreadZLwc.addLineSeries({ color: '#a855f7', lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true });
        const validZ = data.series.filter(d => d.zscore !== null);
        zs.setData(validZ.map(d => ({ time: d.date, value: d.zscore })));
        zs.createPriceLine({ price:  2, color: '#ef444480', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '+2σ' });
        zs.createPriceLine({ price: -2, color: '#22c55e80', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '-2σ' });
        zs.createPriceLine({ price:  0, color: '#4a556880', lineWidth: 1, lineStyle: 1 });
        _spreadZLwc.timeScale().fitContent();

        new ResizeObserver(() => { _spreadLwc.resize(ratioEl.clientWidth, 200); }).observe(ratioEl);
        new ResizeObserver(() => { _spreadZLwc.resize(zEl.clientWidth, 140);    }).observe(zEl);
    } catch (e) {
        c.innerHTML = `<div style="color:var(--red); padding:16px;">${e.message}</div>`;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// PORTFOLIO ANALYTICS
// ═══════════════════════════════════════════════════════════════════════════════

async function loadPortfolioAnalytics() {
    const c = document.getElementById('analytics-content');
    if (!c) return;
    if (_analyticsChart) { _analyticsChart.destroy(); _analyticsChart = null; }
    c.innerHTML = '<div style="padding:32px; text-align:center;"><span class="spinner"></span></div>';
    try {
        const data = await apiFetch(`${API}/analytics`);
        if (!data.trade_count) {
            c.innerHTML = '<div style="padding:32px; text-align:center; color:var(--text-muted);">No closed positions yet.</div>';
            return;
        }
        const fp  = v => v !== null ? v.toFixed(2) : '–';
        const fpp = v => v !== null ? (v * 100).toFixed(2) + '%' : '–';
        c.innerHTML = `
            <div class="kpi-row" style="flex-wrap:wrap; margin-bottom:20px;">
                <div class="kpi-card"><div class="kpi-label">Trades</div><div class="kpi-value">${data.trade_count}</div></div>
                <div class="kpi-card"><div class="kpi-label">Win Rate</div>
                    <div class="kpi-value" style="color:${data.win_rate > 0.5 ? '#22c55e':'#ef4444'}">${fpp(data.win_rate)}</div></div>
                <div class="kpi-card"><div class="kpi-label">Profit Factor</div><div class="kpi-value">${fp(data.profit_factor)}</div></div>
                <div class="kpi-card"><div class="kpi-label">Sharpe</div><div class="kpi-value">${fp(data.sharpe)}</div></div>
                <div class="kpi-card"><div class="kpi-label">Max DD</div>
                    <div class="kpi-value" style="color:#ef4444">${fpp(data.max_drawdown)}</div></div>
                <div class="kpi-card"><div class="kpi-label">Avg Win</div>
                    <div class="kpi-value" style="color:#22c55e">$${fp(data.avg_win)}</div></div>
                <div class="kpi-card"><div class="kpi-label">Avg Loss</div>
                    <div class="kpi-value" style="color:#ef4444">$${fp(data.avg_loss)}</div></div>
            </div>
            <div class="stats-card">
                <div class="stats-card-header">Equity Curve (Closed Positions P&amp;L)</div>
                <div class="chart-container-js" style="height:260px;"><canvas id="analytics-eq-canvas"></canvas></div>
            </div>`;
        const canvas = document.getElementById('analytics-eq-canvas');
        if (canvas && data.equity_curve.length > 1) {
            _analyticsChart = new Chart(canvas, {
                type: 'line',
                data: { labels: data.equity_curve.map(d => d.date),
                    datasets: [{ label: 'Cumulative P&L', data: data.equity_curve.map(d => d.equity),
                        borderColor: '#4facfe', backgroundColor: 'rgba(79,172,254,0.08)',
                        borderWidth: 2, pointRadius: 0, tension: 0.15, fill: true }] },
                options: { responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { grid: { display: false }, ticks: { color: '#8b949e', font: { size: 10 }, maxTicksLimit: 10 } },
                        y: { grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: '#8b949e', font: { size: 10 } } },
                    } },
            });
        }
    } catch (e) {
        c.innerHTML = `<div style="color:var(--red); padding:16px;">${e.message}</div>`;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// TRADE JOURNAL
// ═══════════════════════════════════════════════════════════════════════════════

let _journalTagFilter = '';

async function loadJournal() {
    const c = document.getElementById('journal-table-wrap');
    if (!c) return;
    c.innerHTML = '<span class="spinner" style="display:block; margin:32px auto;"></span>';
    try {
        const entries = await apiFetch(`${API}/journal`);
        renderJournal(entries);
    } catch (e) {
        c.innerHTML = `<div style="color:var(--red); padding:16px;">${e.message}</div>`;
    }
}

function renderJournal(entries) {
    const c = document.getElementById('journal-table-wrap');
    const filtered = _journalTagFilter
        ? entries.filter(e => (e.tags || '').toLowerCase().includes(_journalTagFilter.toLowerCase()))
        : entries;

    // Win-rate by setup
    const setups = {};
    for (const e of entries) {
        if (!e.exit_price) continue;
        const mult = e.direction === 'short' ? -1 : 1;
        const pnl  = (e.exit_price - e.entry_price) * mult * e.qty;
        const key  = e.setup || 'Other';
        if (!setups[key]) setups[key] = { wins: 0, total: 0 };
        setups[key].total++;
        if (pnl > 0) setups[key].wins++;
    }
    const kpi = document.getElementById('journal-kpi-row');
    if (kpi) kpi.innerHTML = Object.entries(setups).map(([setup, { wins, total }]) =>
        `<div class="kpi-card"><div class="kpi-label">${_esc(setup)}</div>
         <div class="kpi-value">${(wins/total*100).toFixed(0)}%</div>
         <div style="font-size:10px; color:var(--text-dim)">${total} trades</div></div>`
    ).join('');

    if (!filtered.length) {
        c.innerHTML = '<div style="color:var(--text-muted); padding:32px; text-align:center;">No entries yet. Click + Add Trade to start.</div>';
        return;
    }
    const fmtP = v => v != null ? `$${parseFloat(v).toFixed(2)}` : '–';
    const fmtPnl = e => {
        if (!e.exit_price) return '<span style="color:var(--text-dim)">Open</span>';
        const mult = e.direction === 'short' ? -1 : 1;
        const pnl  = (e.exit_price - e.entry_price) * mult * e.qty;
        const pct  = ((e.exit_price / e.entry_price - 1) * mult * 100).toFixed(2);
        const col  = pnl >= 0 ? '#22c55e' : '#ef4444';
        return `<span style="color:${col}">${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} (${pct}%)</span>`;
    };
    c.innerHTML = `<div style="overflow-x:auto;"><table class="scanner-table">
        <thead><tr><th>Date</th><th>Symbol</th><th>Dir</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Setup</th><th>Tags</th><th></th></tr></thead>
        <tbody>${filtered.map(e => `<tr>
            <td>${e.entry_date}</td>
            <td><strong style="cursor:pointer;" onclick="selectSymbol('${e.symbol}')">${e.symbol}</strong></td>
            <td><span class="signal-pill ${e.direction === 'long' ? 'bull' : 'bear'}">${e.direction.toUpperCase()}</span></td>
            <td>${e.qty}</td><td>${fmtP(e.entry_price)}</td><td>${fmtP(e.exit_price)}</td>
            <td>${fmtPnl(e)}</td>
            <td>${_esc(e.setup || '')}</td>
            <td style="font-size:10px; color:var(--text-dim);">${_esc(e.tags || '')}</td>
            <td style="white-space:nowrap;">
                <button class="btn btn-ghost btn-sm" onclick="openJournalModal(${e.id})">✎</button>
                <button class="btn btn-ghost btn-sm" style="color:#ef4444" onclick="deleteJournalEntry(${e.id})">×</button>
            </td>
        </tr>`).join('')}</tbody>
    </table></div>`;
}

function openJournalModal(entryId) {
    const modal = document.getElementById('journal-modal');
    if (!modal) return;
    ['jnl-id','jnl-symbol','jnl-entry-date','jnl-exit-date','jnl-entry-price','jnl-exit-price','jnl-qty','jnl-setup','jnl-tags','jnl-thesis']
        .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    document.getElementById('jnl-direction')?.value !== undefined &&
        (document.getElementById('jnl-direction').value = 'long');

    if (entryId) {
        apiFetch(`${API}/journal`).then(entries => {
            const e = entries.find(x => x.id === entryId);
            if (!e) return;
            [['jnl-id', e.id],['jnl-symbol', e.symbol],['jnl-direction', e.direction],
             ['jnl-entry-date', e.entry_date],['jnl-exit-date', e.exit_date || ''],
             ['jnl-entry-price', e.entry_price],['jnl-exit-price', e.exit_price || ''],
             ['jnl-qty', e.qty],['jnl-setup', e.setup || ''],
             ['jnl-tags', e.tags || ''],['jnl-thesis', e.thesis || '']
            ].forEach(([id, val]) => { const el = document.getElementById(id); if (el) el.value = val; });
        }).catch(() => {});
    } else {
        if (typeof state !== 'undefined' && state.activeSymbol) {
            const s = document.getElementById('jnl-symbol');
            if (s) s.value = state.activeSymbol;
        }
        const d = document.getElementById('jnl-entry-date');
        if (d) d.value = new Date().toISOString().slice(0, 10);
        const q = document.getElementById('jnl-qty');
        if (q) q.value = '1';
    }
    modal.style.display = 'flex';
}

function closeJournalModal() {
    const m = document.getElementById('journal-modal');
    if (m) m.style.display = 'none';
}

async function submitJournalEntry() {
    const g = id => document.getElementById(id)?.value;
    const id = g('jnl-id');
    const body = {
        symbol:      (g('jnl-symbol') || '').trim().toUpperCase(),
        direction:   g('jnl-direction') || 'long',
        entry_date:  g('jnl-entry-date'),
        exit_date:   g('jnl-exit-date') || null,
        entry_price: parseFloat(g('jnl-entry-price')),
        exit_price:  g('jnl-exit-price') ? parseFloat(g('jnl-exit-price')) : null,
        qty:         parseFloat(g('jnl-qty')) || 1,
        setup:       (g('jnl-setup') || '').trim(),
        tags:        (g('jnl-tags') || '').trim(),
        thesis:      (g('jnl-thesis') || '').trim(),
    };
    if (!body.symbol || !body.entry_date || isNaN(body.entry_price)) {
        toast('Symbol, Entry Date, and Entry Price are required', 'warning'); return;
    }
    try {
        if (id) {
            await apiFetch(`${API}/journal/${id}`, { method: 'PUT',
                headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        } else {
            await apiFetch(`${API}/journal`, { method: 'POST',
                headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
        }
        closeJournalModal();
        toast(id ? 'Entry updated' : 'Entry added', 'success');
        loadJournal();
    } catch (e) {
        toast('Save failed: ' + e.message, 'error');
    }
}

async function deleteJournalEntry(id) {
    if (!confirm('Delete this journal entry?')) return;
    try {
        await apiFetch(`${API}/journal/${id}`, { method: 'DELETE' });
        toast('Entry deleted', 'warning');
        loadJournal();
    } catch (e) {
        toast('Delete failed: ' + e.message, 'error');
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// STRATEGY LAB
// ═══════════════════════════════════════════════════════════════════════════════

async function loadStrategyLab() {
    const c = document.getElementById('strategy-list');
    if (!c) return;
    c.innerHTML = '<span class="spinner" style="display:block; margin:32px auto;"></span>';
    try {
        const strategies = await apiFetch(`${API}/strategies`);
        renderStrategyLab(strategies);
    } catch (e) {
        c.innerHTML = `<div style="color:var(--red); padding:16px;">${e.message}</div>`;
    }
}

function renderStrategyLab(strategies) {
    const c = document.getElementById('strategy-list');
    if (!strategies.length) {
        c.innerHTML = '<div style="color:var(--text-muted); padding:24px; text-align:center;">No strategies saved yet. Create one below.</div>';
        return;
    }
    c.innerHTML = strategies.map(s => {
        let conds = [];
        try { conds = typeof s.conditions === 'string' ? JSON.parse(s.conditions) : s.conditions; } catch (_) {}
        return `<div class="strategy-card">
            <div class="strategy-card-header">
                <span class="strategy-name">${_esc(s.name)}</span>
                <span style="color:var(--text-dim); font-size:10px; margin-left:8px;">${conds.length} condition${conds.length !== 1 ? 's' : ''}</span>
                <div style="margin-left:auto; display:flex; gap:6px;">
                    <button class="btn btn-primary btn-sm" onclick="runStrategy(${s.id})">▶ Run</button>
                    <button class="btn btn-ghost btn-sm" style="color:#ef4444" onclick="deleteStrategyEntry(${s.id})">×</button>
                </div>
            </div>
            <div class="strategy-conditions">${
                conds.map(c2 => `<span class="signal-pill neutral">${c2.field} ${c2.op} ${c2.value}${c2.value2 !== undefined ? '…'+c2.value2 : ''}</span>`).join(' AND ')
            }</div>
        </div>`;
    }).join('');
}

function openStrategyModal() {
    const m = document.getElementById('strategy-modal');
    if (!m) return;
    document.getElementById('strat-name').value = '';
    const list = document.getElementById('strat-conds');
    if (list) list.innerHTML = '';
    _addStratCond();
    m.style.display = 'flex';
}

function closeStrategyModal() {
    const m = document.getElementById('strategy-modal');
    if (m) m.style.display = 'none';
}

function _addStratCond() {
    const list = document.getElementById('strat-conds');
    if (!list) return;
    const row = document.createElement('div');
    row.className = 'strat-cond-row';
    row.innerHTML = `
        <select class="alert-select sc-field">
            <option value="price">Price</option>
            <option value="rsi">RSI (14)</option>
            <option value="kama10_pct">vs KAMA-10 (%)</option>
            <option value="kama20_pct">vs KAMA-20 (%)</option>
            <option value="kama50_pct">vs KAMA-50 (%)</option>
        </select>
        <select class="alert-select sc-op">
            <option value="above">above</option>
            <option value="below">below</option>
            <option value="between">between</option>
        </select>
        <input type="number" class="alert-input sc-val" placeholder="Value" step="any" style="width:72px;" />
        <input type="number" class="alert-input sc-val2" placeholder="–" step="any" style="width:72px; display:none;" />
        <button class="btn btn-ghost btn-sm" onclick="this.closest('.strat-cond-row').remove()" style="color:#ef4444;">×</button>`;
    const op   = row.querySelector('.sc-op');
    const val2 = row.querySelector('.sc-val2');
    op.addEventListener('change', () => { val2.style.display = op.value === 'between' ? 'inline-block' : 'none'; });
    list.appendChild(row);
}

async function saveStrategy() {
    const name = document.getElementById('strat-name')?.value.trim();
    if (!name) { toast('Name required', 'warning'); return; }
    const rows = document.querySelectorAll('#strat-conds .strat-cond-row');
    const conditions = Array.from(rows).map(row => {
        const field = row.querySelector('.sc-field')?.value;
        const op    = row.querySelector('.sc-op')?.value;
        const val   = parseFloat(row.querySelector('.sc-val')?.value);
        const val2  = parseFloat(row.querySelector('.sc-val2')?.value);
        return { field, op, value: val, value2: op === 'between' ? val2 : undefined };
    }).filter(c => c.field && c.op && !isNaN(c.value));
    if (!conditions.length) { toast('Add at least one condition', 'warning'); return; }
    try {
        await apiFetch(`${API}/strategies`, { method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, conditions }) });
        closeStrategyModal();
        toast('Strategy saved', 'success');
        loadStrategyLab();
    } catch (e) {
        toast('Save failed: ' + e.message, 'error');
    }
}

async function runStrategy(id) {
    const rc = document.getElementById('strategy-results');
    if (!rc) return;
    rc.innerHTML = '<span class="spinner"></span> Scanning…';
    try {
        const results = await apiFetch(`${API}/strategies/${id}/run`, { method: 'POST' });
        if (!results.length) {
            rc.innerHTML = '<div style="color:var(--text-muted); padding:8px;">No matches found.</div>';
        } else {
            rc.innerHTML = `<div style="font-size:12px; color:var(--text-muted); margin-bottom:6px;">${results.length} match${results.length !== 1 ? 'es' : ''}</div>
                <div style="display:flex; flex-wrap:wrap; gap:6px;">
                    ${results.map(r => `<div class="strategy-match" onclick="selectSymbol('${r.symbol}')">
                        <strong>${r.symbol}</strong> $${r.price?.toFixed(2)} RSI:${r.rsi?.toFixed(1)}</div>`).join('')}
                </div>`;
        }
    } catch (e) {
        rc.innerHTML = `<div style="color:var(--red);">${e.message}</div>`;
    }
}

async function deleteStrategyEntry(id) {
    if (!confirm('Delete this strategy?')) return;
    try {
        await apiFetch(`${API}/strategies/${id}`, { method: 'DELETE' });
        toast('Strategy deleted', 'warning');
        loadStrategyLab();
    } catch (e) {
        toast('Delete failed: ' + e.message, 'error');
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCREENSHOT
// ═══════════════════════════════════════════════════════════════════════════════

async function takeScreenshot() {
    toast('Capturing screenshot…', 'info', 1500);
    try {
        if (typeof html2canvas !== 'undefined') {
            const target = document.querySelector('.main') || document.body;
            const canvas = await html2canvas(target, { backgroundColor: '#0d1117', scale: 1.5, useCORS: true });
            const a = document.createElement('a');
            a.href     = canvas.toDataURL('image/png');
            a.download = `findash-${(typeof state !== 'undefined' && state.activeSymbol) || 'chart'}-${new Date().toISOString().slice(0,10)}.png`;
            a.click();
            toast('Screenshot saved!', 'success');
        } else {
            window.print();
        }
    } catch (e) {
        window.print();
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// DOMContentLoaded
// ═══════════════════════════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    startLivePolling();

    document.getElementById('btn-screenshot')?.addEventListener('click', takeScreenshot);

    // Replay keyboard shortcuts
    document.addEventListener('keydown', e => {
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (_replayActive) {
            if (e.key === 'ArrowRight') { e.preventDefault(); replayNext(); }
            if (e.key === 'ArrowLeft')  { e.preventDefault(); replayPrev(); }
            if (e.key === 'Escape')     { stopReplay(); }
        }
        if (!_replayActive && e.key === 'v' && typeof state !== 'undefined' && state.activeTab === 'charts') {
            toggleVolProfile();
        }
    });

    document.getElementById('btn-add-strat-cond')?.addEventListener('click', _addStratCond);
    document.getElementById('btn-replay')?.addEventListener('click', startReplay);
    document.getElementById('btn-replay-stop')?.addEventListener('click', stopReplay);
    document.getElementById('btn-replay-next')?.addEventListener('click', () => replayNext(1));
    document.getElementById('btn-replay-prev')?.addEventListener('click', replayPrev);

    // ? key → shortcuts panel
    document.addEventListener('keydown', e => {
        const tag = document.activeElement?.tagName;
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (e.key === '?') { e.preventDefault(); toggleShortcutsPanel(); }
    });
});

// ═══════════════════════════════════════════════════════════════════════════════
// KEYBOARD SHORTCUTS PANEL
// ═══════════════════════════════════════════════════════════════════════════════

function toggleShortcutsPanel() {
    const m = document.getElementById('shortcuts-modal');
    if (!m) return;
    m.style.display = m.style.display === 'none' ? 'flex' : 'none';
}

// ═══════════════════════════════════════════════════════════════════════════════
// EARNINGS MARKERS ON CHART
// ═══════════════════════════════════════════════════════════════════════════════

async function loadEarningsMarkers(symbol) {
    if (!symbol) return;
    try {
        const data = await apiFetch(`${API}/earnings/${symbol}`);
        _applyEarningsMarkers(symbol, data.dates || []);
    } catch (_) {}
}

function _applyEarningsMarkers(symbol, dates) {
    const candle = typeof series !== 'undefined' ? series.daily?.candle : null;
    if (!candle) return;

    const eMarkers = dates.map(d => ({
        time:     d.date,
        position: 'aboveBar',
        color:    '#a855f7',
        shape:    'circle',
        size:     1,
        text:     'E',
    }));

    // Merge with any existing markers already set on the candle series
    window._earningsMarkers = window._earningsMarkers || {};
    window._earningsMarkers[symbol] = eMarkers;

    const prior = (window._priorCandleMarkers && window._priorCandleMarkers[symbol]) || [];
    const merged = [...prior, ...eMarkers].sort((a, b) => String(a.time).localeCompare(String(b.time)));
    try { candle.setMarkers(merged); } catch (_) {}
}

// ═══════════════════════════════════════════════════════════════════════════════
// SECTOR SUB-TAB SWITCH
// ═══════════════════════════════════════════════════════════════════════════════

function switchSectorTab(tab) {
    ['heat', 'rrg'].forEach(t => {
        const panel = document.getElementById(`sector-panel-${t}`);
        const btn   = document.getElementById(`sector-stab-${t}`);
        if (panel) panel.style.display = t === tab ? '' : 'none';
        if (btn)   btn.classList.toggle('knn-stab-active', t === tab);
    });
    if (tab === 'rrg') loadRRG();
}

// ═══════════════════════════════════════════════════════════════════════════════
// RELATIVE ROTATION GRAPH (RRG)
// ═══════════════════════════════════════════════════════════════════════════════

async function loadRRG() {
    const benchmark = document.getElementById('rrg-benchmark')?.value.trim().toUpperCase() || 'SPY';
    const period    = document.getElementById('rrg-period')?.value || 10;
    const loading   = document.getElementById('rrg-loading');
    const canvas    = document.getElementById('rrg-canvas');

    if (loading) loading.style.display = 'block';
    if (canvas)  canvas.style.display  = 'none';

    try {
        const data = await apiFetch(`${API}/rrg?benchmark=${benchmark}&period=${period}&trail=5`);
        renderRRG(data);
    } catch (e) {
        toast('RRG failed: ' + e.message, 'error');
    } finally {
        if (loading) loading.style.display = 'none';
        if (canvas)  canvas.style.display  = 'block';
    }
}

function renderRRG(data) {
    const canvas = document.getElementById('rrg-canvas');
    const legend = document.getElementById('rrg-legend');
    if (!canvas) return;

    const symbols = data.symbols || [];
    const W = canvas.offsetWidth || 640;
    const H = Math.min(W * 0.75, 520);
    canvas.width  = W;
    canvas.height = H;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, W, H);

    // ── Find data range ──────────────────────────────────────────
    const allX = symbols.flatMap(s => s.trail.map(p => p.rs_ratio));
    const allY = symbols.flatMap(s => s.trail.map(p => p.rs_mom));
    if (!allX.length) {
        ctx.fillStyle = '#8b949e';
        ctx.font = '14px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('No data — fetch symbols and benchmark first', W / 2, H / 2);
        return;
    }

    const pad   = 48;
    const cx    = W / 2;
    const cy    = H / 2;
    const xMin  = Math.min(...allX, 97)  - 1;
    const xMax  = Math.max(...allX, 103) + 1;
    const yMin  = Math.min(...allY, 97)  - 1;
    const yMax  = Math.max(...allY, 103) + 1;

    const toX = v => pad + (v - xMin) / (xMax - xMin) * (W - pad * 2);
    const toY = v => H - pad - (v - yMin) / (yMax - yMin) * (H - pad * 2);
    const x100 = toX(100);
    const y100 = toY(100);

    // ── Quadrant fills ────────────────────────────────────────────
    const quads = [
        { x: x100, y: pad,  w: W - pad - x100, h: y100 - pad, color: 'rgba(34,197,94,0.08)',  label: 'Leading'   },
        { x: x100, y: y100, w: W - pad - x100, h: H - pad - y100, color: 'rgba(234,179,8,0.08)',  label: 'Weakening' },
        { x: pad,  y: y100, w: x100 - pad,     h: H - pad - y100, color: 'rgba(239,68,68,0.08)', label: 'Lagging'   },
        { x: pad,  y: pad,  w: x100 - pad,     h: y100 - pad, color: 'rgba(59,130,246,0.08)', label: 'Improving' },
    ];
    const qColors = { Leading: '#22c55e', Weakening: '#eab308', Lagging: '#ef4444', Improving: '#3b82f6' };
    quads.forEach(q => {
        ctx.fillStyle = q.color;
        ctx.fillRect(q.x, q.y, q.w, q.h);
        ctx.fillStyle = q.color.replace(/0\.08/, '0.5');
        ctx.font = 'bold 11px monospace';
        ctx.textAlign = q.x < cx ? 'left' : 'right';
        ctx.fillText(q.label, q.x < cx ? q.x + 6 : q.x + q.w - 6,
                               q.y < cy ? q.y + 16 : q.y + q.h - 6);
    });

    // ── Axes ───────────────────────────────────────────────────────
    ctx.strokeStyle = 'rgba(255,255,255,0.2)';
    ctx.lineWidth   = 1;
    ctx.setLineDash([4, 4]);
    ctx.beginPath(); ctx.moveTo(x100, pad); ctx.lineTo(x100, H - pad); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(pad, y100); ctx.lineTo(W - pad, y100); ctx.stroke();
    ctx.setLineDash([]);

    // Axis labels
    ctx.fillStyle   = '#8b949e';
    ctx.font        = '10px monospace';
    ctx.textAlign   = 'center';
    ctx.fillText('RS-Ratio →', W / 2, H - 6);
    ctx.save();
    ctx.translate(12, H / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.fillText('RS-Momentum ↑', 0, 0);
    ctx.restore();

    // ── Symbols ────────────────────────────────────────────────────
    const qMap = { leading: '#22c55e', weakening: '#eab308', lagging: '#ef4444', improving: '#3b82f6' };

    symbols.forEach(sym => {
        const color = qMap[sym.quadrant] || '#8b949e';
        const trail = sym.trail;
        if (trail.length < 2) return;

        // Trail line (faded)
        ctx.beginPath();
        ctx.strokeStyle = color + '60';
        ctx.lineWidth   = 1.5;
        trail.forEach((p, i) => {
            const px = toX(p.rs_ratio);
            const py = toY(p.rs_mom);
            i === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
        });
        ctx.stroke();

        // Current dot
        const last = trail[trail.length - 1];
        const px   = toX(last.rs_ratio);
        const py   = toY(last.rs_mom);
        ctx.beginPath();
        ctx.arc(px, py, 6, 0, Math.PI * 2);
        ctx.fillStyle   = color;
        ctx.fill();
        ctx.strokeStyle = '#0d1117';
        ctx.lineWidth   = 1.5;
        ctx.stroke();

        // Label
        ctx.fillStyle  = '#e6edf3';
        ctx.font       = 'bold 10px monospace';
        ctx.textAlign  = 'left';
        ctx.fillText(sym.symbol, px + 8, py + 4);
    });

    // ── Legend ─────────────────────────────────────────────────────
    if (legend) {
        const counts = { leading: 0, weakening: 0, lagging: 0, improving: 0 };
        symbols.forEach(s => { if (counts[s.quadrant] !== undefined) counts[s.quadrant]++; });
        legend.innerHTML = Object.entries(qMap).map(([q, c]) =>
            `<span class="rrg-chip" style="border-color:${c}; color:${c};">
              ${q.charAt(0).toUpperCase() + q.slice(1)}: ${counts[q]}
            </span>`
        ).join('');
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// KNN FEATURE IMPORTANCE
// ═══════════════════════════════════════════════════════════════════════════════

async function loadKNNImportance() {
    if (!state.activeSymbol) { toast('Select a symbol first', 'warn'); return; }
    const loading = document.getElementById('knn-imp-loading');
    const results = document.getElementById('knn-imp-results');
    const status  = document.getElementById('knn-imp-status');
    if (loading) loading.style.display = 'flex';
    if (results) results.style.display = 'none';
    if (status)  status.textContent    = '';

    try {
        const data = await apiFetch(`${API}/knn/feature-importance/${state.activeSymbol}?k=15&n_perms=20`);
        renderKNNImportance(data);
        if (status) status.textContent = `Base dist: ${data.base_dist?.toFixed(3)} · ${state.activeSymbol}`;
    } catch (e) {
        toast('Feature importance failed: ' + e.message, 'error');
    } finally {
        if (loading) loading.style.display = 'none';
    }
}

function renderKNNImportance(data) {
    const results = document.getElementById('knn-imp-results');
    const header  = document.getElementById('knn-imp-header');
    const bars    = document.getElementById('knn-imp-bars');
    if (!results || !bars) return;

    results.style.display = '';
    if (header) header.textContent = `Feature Importance — ${data.symbol}`;

    const features = data.features || [];
    const maxImp   = Math.max(...features.map(f => Math.max(f.importance, 0)), 0.01);

    bars.innerHTML = features.map(f => {
        const pct   = Math.max(0, f.importance) / maxImp * 100;
        const color = f.importance > 0 ? '#3b82f6' : '#8b949e';
        const sign  = f.importance >= 0 ? '+' : '';
        return `<div class="imp-row">
            <div class="imp-label">${f.label}</div>
            <div class="imp-bar-wrap">
                <div class="imp-bar" style="width:${pct.toFixed(1)}%; background:${color};"></div>
            </div>
            <div class="imp-value">${sign}${f.importance.toFixed(4)}</div>
            <div class="imp-cur" style="color:var(--text-muted);">(${f.value >= 0 ? '+' : ''}${f.value.toFixed(3)})</div>
        </div>`;
    }).join('');
}
