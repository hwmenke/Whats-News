/**
 * hover_preview.js — Ticker-cell hover mini-chart popover
 *
 * Any element with data-hover-symbol="AAPL" gets a mini price chart
 * popover on mouseenter. Lightweight Charts renders 60 daily bars.
 * Cache avoids re-fetching the same symbol within the session.
 */

const _hoverCache  = new Map();   // symbol → {candles, fetched}
let _hoverTimer    = null;
let _hideTimer     = null;
let _hoverChart    = null;
let _hoverSeries   = null;
let _currentSym    = null;

function _initHoverPopover() {
    // Build popover DOM once
    if (document.getElementById('hover-popover')) return;
    const el = document.createElement('div');
    el.id = 'hover-popover';
    el.className = 'hover-popover';
    el.innerHTML = `
        <div class="hp-header">
            <span id="hp-sym" class="hp-sym"></span>
            <span id="hp-chg" class="hp-chg"></span>
        </div>
        <div id="hp-chart" class="hp-chart"></div>
        <div id="hp-stats" class="hp-stats"></div>`;
    document.body.appendChild(el);

    // Initialise chart once (reuse on every show)
    if (window.LightweightCharts) {
        _hoverChart = LightweightCharts.createChart(
            document.getElementById('hp-chart'),
            {
                width: 260, height: 130,
                layout: { background: { color: 'transparent' }, textColor: '#9ca3af' },
                grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
                rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.1, bottom: 0.1 } },
                timeScale: { borderVisible: false, timeVisible: false },
                crosshair: { mode: 0 },
                handleScale: false,
                handleScroll: false,
            }
        );
        _hoverSeries = _hoverChart.addAreaSeries({
            lineColor: '#029FD5',
            topColor: 'rgba(2,159,213,0.22)',
            bottomColor: 'rgba(2,159,213,0)',
            lineWidth: 1.5,
            priceLineVisible: false,
            lastValueVisible: false,
        });
    }

    // Keep popover alive when mouse enters it
    el.addEventListener('mouseenter', () => clearTimeout(_hideTimer));
    el.addEventListener('mouseleave', _scheduleHide);
}

// ── Show / hide ───────────────────────────────────────────────────────────────

function _showPopover(sym, anchorEl) {
    const pop = document.getElementById('hover-popover');
    if (!pop) return;

    // Position near anchor
    const rect = anchorEl.getBoundingClientRect();
    const scrollY = window.scrollY || 0;
    const scrollX = window.scrollX || 0;
    let top  = rect.bottom + scrollY + 6;
    let left = rect.left  + scrollX;
    // Keep inside viewport
    if (left + 280 > window.innerWidth) left = window.innerWidth - 290;
    pop.style.top    = top  + 'px';
    pop.style.left   = left + 'px';
    pop.style.display = 'block';

    document.getElementById('hp-sym').textContent = sym;
    document.getElementById('hp-chg').textContent = '';
    document.getElementById('hp-stats').textContent = '';

    // Load from cache or fetch
    _loadHoverData(sym);
}

function _hidePopover() {
    const pop = document.getElementById('hover-popover');
    if (pop) pop.style.display = 'none';
    _currentSym = null;
}

function _scheduleHide() {
    clearTimeout(_hideTimer);
    _hideTimer = setTimeout(_hidePopover, 200);
}

// ── Data loading ──────────────────────────────────────────────────────────────

async function _loadHoverData(sym) {
    if (_hoverCache.has(sym)) {
        _renderHover(sym, _hoverCache.get(sym));
        return;
    }
    try {
        const data = await apiFetch(`${API}/ohlcv/${sym}?freq=daily&limit=60`);
        if (!Array.isArray(data) || !data.length) return;
        _hoverCache.set(sym, data);
        if (_currentSym === sym) _renderHover(sym, data);
    } catch (_) {}
}

function _renderHover(sym, data) {
    if (_currentSym !== sym) return;

    if (_hoverSeries && data.length) {
        const candles = data
            .map(d => ({ time: d.date, value: d.close }))
            .sort((a, b) => a.time < b.time ? -1 : 1);
        _hoverSeries.setData(candles);
        _hoverChart.timeScale().fitContent();

        const first = candles[0].value;
        const last  = candles[candles.length - 1].value;
        const chg   = ((last - first) / first * 100);
        const chgEl = document.getElementById('hp-chg');
        if (chgEl) {
            chgEl.textContent = `$${last.toFixed(2)}  ${chg >= 0 ? '+' : ''}${chg.toFixed(1)}%`;
            chgEl.className   = 'hp-chg ' + (chg >= 0 ? 'hp-pos' : 'hp-neg');
        }
    }
}

// ── Event delegation ──────────────────────────────────────────────────────────

function initHoverPreview() {
    _initHoverPopover();

    document.addEventListener('mouseover', e => {
        const target = e.target.closest('[data-hover-symbol]');
        if (!target) return;
        const sym = target.dataset.hoverSymbol;
        if (!sym) return;

        clearTimeout(_hideTimer);
        if (_currentSym === sym) return;    // already showing for this symbol

        clearTimeout(_hoverTimer);
        _currentSym = sym;
        _hoverTimer = setTimeout(() => _showPopover(sym, target), 350);
    });

    document.addEventListener('mouseout', e => {
        const target = e.target.closest('[data-hover-symbol]');
        if (!target) return;
        clearTimeout(_hoverTimer);
        _scheduleHide();
    });
}
