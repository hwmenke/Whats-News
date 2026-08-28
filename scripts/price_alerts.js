/**
 * User price-alert lines on the daily main pane.
 *
 * Shift+click (or ctrl/meta modifier-click) drops a horizontal line at the
 * Y-axis price. A second modifier-click near the same price toggles it off.
 * Weekly pane: do not add alerts in v1.
 *
 * These are USER price lines — not RSI tape alerts (tapeMode 'alerts'), and
 * not a published rating.
 *
 * Persistence: localStorage key whats-news-price-alerts, keyed by symbol.
 *
 * Price: series.coordinateToPrice(param.point.y) on the daily candle series.
 * If the library only supplies bar time (no point / no coordinateToPrice),
 * fall back to that bar's close.
 *
 * Isolated so charts.js only calls onDailyPriceAlertClick / applyPriceAlerts
 * / forgetPriceAlertLines when those hooks exist.
 */

const PRICE_ALERTS_KEY = 'whats-news-price-alerts';
const PRICE_ALERTS_MAX = 8;
const PRICE_ALERTS_NEAR = 0.0015; // 0.15%
const PRICE_ALERT_COLOR = '#c084fc'; // violet — distinct from risk/Darvas/session
const PRICE_ALERT_TITLE = 'Alert';

let _priceAlertLines = []; // { price, line }
let _lastNativeModifier = false;

(function bindPriceAlertModifierCapture() {
    const mark = e => {
        _lastNativeModifier = !!(e && (e.shiftKey || e.ctrlKey || e.metaKey));
    };
    document.addEventListener('pointerdown', mark, true);
    document.addEventListener('mousedown', mark, true);
    document.addEventListener('click', mark, true);
})();

function _alertSymbol() {
    if (typeof state !== 'undefined' && state.activeSymbol) {
        return String(state.activeSymbol).toUpperCase();
    }
    return '';
}

function _readAlertStore() {
    try {
        const raw = JSON.parse(localStorage.getItem(PRICE_ALERTS_KEY) || '{}');
        return (raw && typeof raw === 'object' && !Array.isArray(raw)) ? raw : {};
    } catch (_) {
        return {};
    }
}

function _writeAlertStore(store) {
    try { localStorage.setItem(PRICE_ALERTS_KEY, JSON.stringify(store)); } catch (_) {}
}

function _alertsForSymbol(sym) {
    if (!sym) return [];
    const list = _readAlertStore()[sym];
    if (!Array.isArray(list)) return [];
    return list.map(Number).filter(n => Number.isFinite(n));
}

function _snapAlertPrice(px) {
    return Math.round(Number(px) * 100) / 100;
}

function _alertPricesNear(a, b) {
    if (!Number.isFinite(a) || !Number.isFinite(b)) return false;
    const tol = Math.max(0.01, Math.abs(a) * PRICE_ALERTS_NEAR);
    return Math.abs(a - b) <= tol;
}

function _clickIsModifier(param) {
    const src = param && param.sourceEvent;
    if (src) return !!(src.shiftKey || src.ctrlKey || src.metaKey);
    return !!_lastNativeModifier;
}

function _priceFromClickParam(param) {
    const s = (typeof series !== 'undefined' && series.daily) ? series.daily.candle : null;
    const y = param && param.point ? param.point.y : null;
    if (s && y != null && typeof s.coordinateToPrice === 'function') {
        const px = s.coordinateToPrice(y);
        if (px != null && Number.isFinite(Number(px))) return Number(px);
    }
    // Fallback: library only gave bar time — use that bar's close.
    if (s && param && param.seriesData && typeof param.seriesData.get === 'function') {
        const bar = param.seriesData.get(s);
        if (bar && typeof bar === 'object' && bar.close != null && Number.isFinite(Number(bar.close))) {
            return Number(bar.close);
        }
        if (typeof bar === 'number' && Number.isFinite(bar)) return bar;
    }
    const key = (typeof _legendTimeKey === 'function') ? _legendTimeKey(param && param.time) : null;
    const rows = (typeof rawRows !== 'undefined' && rawRows.daily) ? rawRows.daily : [];
    if (key && rows.length) {
        const row = rows.find(r => String(r.date).slice(0, 10) === key);
        if (row && row.close != null && Number.isFinite(Number(row.close))) return Number(row.close);
    }
    return null;
}

function _dailyCandleStyle() {
    return (typeof LWC !== 'undefined' && LWC.LineStyle) ? LWC.LineStyle.Dashed : 2;
}

function forgetPriceAlertLines() {
    _priceAlertLines = [];
}

function clearDrawnPriceAlertLines() {
    const s = (typeof series !== 'undefined' && series.daily) ? series.daily.candle : null;
    _priceAlertLines.forEach(entry => {
        if (s && entry.line) {
            try { s.removePriceLine(entry.line); } catch (_) {}
        }
    });
    _priceAlertLines = [];
}

function _syncPriceAlertPill() {
    const pill = document.getElementById('pill-price-alerts');
    if (!pill) return;
    const on = _alertsForSymbol(_alertSymbol()).length > 0;
    pill.classList.toggle('active-price-alerts', on);
    pill.setAttribute('aria-pressed', on ? 'true' : 'false');
}

function renderPriceAlertChips() {
    const el = document.getElementById('price-alert-chips');
    const prices = _priceAlertLines.map(x => x.price);
    if (el) {
        if (!prices.length) {
            el.innerHTML = '';
            el.hidden = true;
        } else {
            el.hidden = false;
            el.innerHTML = prices.map(p => {
                const label = Number(p).toFixed(2);
                return `<button type="button" class="price-alert-chip" data-price="${label}" aria-label="Clear alert ${label}">Alert ${label} ×</button>`;
            }).join('');
        }
    }
    _syncPriceAlertPill();
}

function applyPriceAlerts() {
    _bindPriceAlertChrome();
    clearDrawnPriceAlertLines();
    const s = (typeof series !== 'undefined' && series.daily) ? series.daily.candle : null;
    const prices = _alertsForSymbol(_alertSymbol());
    if (s) {
        const dash = _dailyCandleStyle();
        prices.forEach(price => {
            try {
                const line = s.createPriceLine({
                    price,
                    color: PRICE_ALERT_COLOR,
                    lineWidth: 1,
                    lineStyle: dash,
                    axisLabelVisible: true,
                    title: PRICE_ALERT_TITLE,
                });
                _priceAlertLines.push({ price, line });
            } catch (_) {
                _priceAlertLines.push({ price, line: null });
            }
        });
    } else {
        prices.forEach(price => _priceAlertLines.push({ price, line: null }));
    }
    renderPriceAlertChips();
}

function _toggleAlertAt(price) {
    const snap = _snapAlertPrice(price);
    if (!Number.isFinite(snap)) return;
    const sym = _alertSymbol();
    if (!sym) {
        if (typeof toast === 'function') toast('Pick a symbol first', 'warning');
        return;
    }
    const store = _readAlertStore();
    const list = _alertsForSymbol(sym);
    const idx = list.findIndex(p => _alertPricesNear(p, snap));
    if (idx >= 0) {
        list.splice(idx, 1);
        if (list.length) store[sym] = list;
        else delete store[sym];
        _writeAlertStore(store);
        applyPriceAlerts();
        return;
    }
    if (list.length >= PRICE_ALERTS_MAX) {
        if (typeof toast === 'function') {
            toast(`Price alerts capped at ${PRICE_ALERTS_MAX} for ${sym}`, 'warning');
        }
        return;
    }
    list.push(snap);
    store[sym] = list;
    _writeAlertStore(store);
    applyPriceAlerts();
}

function removePriceAlert(price) {
    const snap = _snapAlertPrice(price);
    const sym = _alertSymbol();
    if (!sym || !Number.isFinite(snap)) return;
    const store = _readAlertStore();
    const next = _alertsForSymbol(sym).filter(p => !_alertPricesNear(p, snap));
    if (next.length) store[sym] = next;
    else delete store[sym];
    _writeAlertStore(store);
    applyPriceAlerts();
}

function clearPriceAlertsForSymbol() {
    const sym = _alertSymbol();
    if (!sym) return;
    const store = _readAlertStore();
    if (!(sym in store)) return;
    delete store[sym];
    _writeAlertStore(store);
    applyPriceAlerts();
}

/**
 * Daily subscribeClick hook from charts.js.
 * Returns true when this click was a modifier-click (journal must not open).
 * Plain click returns false so the bar-click journal path can run.
 */
function onDailyPriceAlertClick(param) {
    if (!_clickIsModifier(param)) return false;
    const raw = _priceFromClickParam(param);
    if (raw != null) _toggleAlertAt(raw);
    return true;
}

function _bindPriceAlertChrome() {
    const chips = document.getElementById('price-alert-chips');
    if (chips && !chips.dataset.bound) {
        chips.dataset.bound = '1';
        chips.addEventListener('click', e => {
            const chip = e.target.closest('.price-alert-chip[data-price]');
            if (!chip) return;
            const px = Number(chip.dataset.price);
            if (Number.isFinite(px)) removePriceAlert(px);
        });
    }
    const pill = document.getElementById('pill-price-alerts');
    if (pill && !pill.dataset.bound) {
        pill.dataset.bound = '1';
        pill.addEventListener('click', () => {
            const n = _alertsForSymbol(_alertSymbol()).length;
            if (n) {
                clearPriceAlertsForSymbol();
            } else if (typeof toast === 'function') {
                toast('Shift+click the daily price pane to drop an alert line', 'info');
            }
        });
        _syncPriceAlertPill();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    _bindPriceAlertChrome();
    applyPriceAlerts();
});
