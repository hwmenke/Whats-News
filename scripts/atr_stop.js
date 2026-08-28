/**
 * Optional ATR Stop overlay — full-width horizontal line on the daily pane.
 *
 * When process-tools stop mode is ATR, the line sits at last close minus
 * the same ATR multiple the risk box uses (1.5 × ATR(14)). For shorts, last
 * close plus that multiple (Stop S) — the desk already publishes both sides.
 * Box / user stop modes hide the overlay even if the pill is on. Weekly pane is skipped in v1.
 * Off by default. Overlay only — not a published rating.
 * No extra market-data fetch — uses rawRows.daily already on the desk.
 *
 * Isolated so chart specialists can keep editing packs / legend / prefetch
 * without a rewrite here. charts.js calls applyAtrStopIfOn() on daily load
 * only, persistOverlays / applySavedOverlays via atrStopIsOn / setAtrStopOn,
 * and forgetAtrStopLines() on destroy.
 */
const ATR_STOP_COLOR = '#fb7185';
const ATR_STOP_PERIOD = 14;
const ATR_STOP_MULT = 1.5; // same multiple as the risk box (position_size / stop_long_1_5atr)
let atrStopOn = false;
let atrStopLines = [];
let _atrStopHost = null;

function atrStopIsOn() {
    return !!atrStopOn;
}

function getAtrStopOn() {
    return atrStopIsOn();
}

function setAtrStopOn(on, opts) {
    opts = opts || {};
    atrStopOn = !!on;
    _syncAtrStopPill();
    if (opts.apply !== false) applyAtrStopIfOn();
    if (opts.persist && typeof persistOverlays === 'function') persistOverlays();
    return atrStopOn;
}

function processToolsStopMode() {
    const checked = (typeof document !== 'undefined' && document.querySelector)
        ? document.querySelector('input[name="stop-mode"]:checked')
        : null;
    if (checked && checked.value) return String(checked.value).toLowerCase();
    try {
        if (typeof state !== 'undefined' && state && state.stopMode != null && String(state.stopMode).trim() !== '') {
            return String(state.stopMode).toLowerCase();
        }
    } catch (_) {}
    return 'atr';
}

function atrStopModeIsActive() {
    return processToolsStopMode() === 'atr';
}

function lastDailyClose(rows) {
    const list = Array.isArray(rows) ? rows : [];
    for (let i = list.length - 1; i >= 0; i--) {
        const row = list[i];
        if (!row) continue;
        const close = Number(row.close);
        if (!Number.isFinite(close)) continue;
        return {
            time: row.date != null ? row.date : null,
            value: close,
        };
    }
    return null;
}

function trueRangeAt(rows, i) {
    const list = Array.isArray(rows) ? rows : [];
    const row = list[i];
    if (!row) return null;
    const high = Number(row.high);
    const low = Number(row.low);
    if (!Number.isFinite(high) || !Number.isFinite(low)) return null;
    const hl = Math.abs(high - low);
    if (i <= 0) return hl;
    const prevClose = Number(list[i - 1] && list[i - 1].close);
    if (!Number.isFinite(prevClose)) return hl;
    return Math.max(hl, Math.abs(high - prevClose), Math.abs(low - prevClose));
}

function wilderAtrLast(rows, period) {
    const n = (period != null && Number.isFinite(Number(period)) && Number(period) > 0)
        ? Number(period)
        : ATR_STOP_PERIOD;
    const list = Array.isArray(rows) ? rows : [];
    if (list.length < n) return null;
    let seed = 0;
    let seeded = 0;
    let i = 0;
    let atr = null;
    for (; i < list.length; i++) {
        const tr = trueRangeAt(list, i);
        if (tr == null || !Number.isFinite(tr)) continue;
        seed += tr;
        seeded += 1;
        if (seeded === n) {
            atr = seed / n;
            i += 1;
            break;
        }
    }
    if (atr == null) return null;
    for (; i < list.length; i++) {
        const tr = trueRangeAt(list, i);
        if (tr == null || !Number.isFinite(tr)) continue;
        atr = (atr * (n - 1) + tr) / n;
    }
    return atr;
}

function atrStopLevels(rows, opts) {
    opts = opts || {};
    const period = opts.period != null ? opts.period : ATR_STOP_PERIOD;
    const mult = opts.mult != null ? Number(opts.mult) : ATR_STOP_MULT;
    const list = Array.isArray(rows) ? rows : [];
    const last = lastDailyClose(list);
    const atr = wilderAtrLast(list, period);
    if (!last || last.value == null || !Number.isFinite(last.value)) return null;
    if (atr == null || !(atr > 0) || !Number.isFinite(mult)) return null;
    const dist = atr * mult;
    return {
        last: last.value,
        time: last.time,
        atr,
        mult,
        long: last.value - dist,
        short: last.value + dist,
    };
}

function atrStopLineOptions(price, title) {
    const dashed = (typeof LWC !== 'undefined' && LWC.LineStyle) ? LWC.LineStyle.Dashed : 2;
    return {
        price,
        color: ATR_STOP_COLOR,
        lineWidth: 1,
        lineStyle: dashed,
        axisLabelVisible: true,
        title: title || 'Stop',
    };
}

function forgetAtrStopLines() {
    atrStopLines = [];
    _atrStopHost = null;
}

function _clearAtrStopLines() {
    const s = (typeof series !== 'undefined' && series.daily) ? series.daily.candle : null;
    if (s && s === _atrStopHost) {
        atrStopLines.forEach(line => {
            try { s.removePriceLine(line); } catch (_) {}
        });
    }
    atrStopLines = [];
    _atrStopHost = null;
}

function _syncAtrStopPill() {
    const pill = document.getElementById('pill-atr-stop');
    if (!pill) return;
    pill.classList.toggle('active-atr-stop', atrStopOn);
    pill.setAttribute('aria-pressed', atrStopOn ? 'true' : 'false');
}

function applyAtrStopIfOn() {
    _syncAtrStopPill();
    _clearAtrStopLines();
    if (!atrStopOn || !atrStopModeIsActive()) return;
    const s = (typeof series !== 'undefined' && series.daily) ? series.daily.candle : null;
    if (!s || typeof s.createPriceLine !== 'function') return;
    const rows = (typeof rawRows !== 'undefined' && rawRows && rawRows.daily)
        ? rawRows.daily
        : [];
    const levels = atrStopLevels(rows);
    if (!levels) return;
    const drawn = [];
    drawn.push(s.createPriceLine(atrStopLineOptions(levels.long, 'Stop')));
    if (levels.short != null && Number.isFinite(levels.short)) {
        drawn.push(s.createPriceLine(atrStopLineOptions(levels.short, 'Stop S')));
    }
    atrStopLines = drawn;
    _atrStopHost = s;
}

function toggleAtrStop() {
    return setAtrStopOn(!atrStopOn, { persist: true });
}

if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
        const pill = document.getElementById('pill-atr-stop');
        if (pill) {
            pill.addEventListener('click', () => toggleAtrStop());
            _syncAtrStopPill();
        }
        const radios = document.querySelectorAll('input[name="stop-mode"]');
        radios.forEach(radio => {
            radio.addEventListener('change', () => applyAtrStopIfOn());
        });
    });
}
