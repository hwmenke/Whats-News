/**
 * Color volume histogram bars vs the 20-bar volume SMA already drawn on
 * the pane. Above the SMA = brighter / up-volume emphasis; at or below =
 * muted. 1.5× surge and 2× climax colors from charts.js stay solid so pops
 * are not washed out. Uses bars already on the chart — no extra fetch.
 * Daily and weekly share the same vs-SMA rule. Always-on and subtle —
 * not a published rating.
 *
 * Isolated so chart specialists can keep editing SMA / VWAP / Last /
 * overlay persist without a rewrite here. charts.js calls
 * colorVolumeBarsByRvol() on volume setData for each freq.
 */
const VOL_RVOL_ABOVE_UP = '#22c55e88';
const VOL_RVOL_ABOVE_DOWN = '#ef444488';
const VOL_RVOL_BELOW_UP = '#22c55e22';
const VOL_RVOL_BELOW_DOWN = '#ef444422';

const VOL_RVOL_POP_COLORS = {
    '#fb923c': true,
    '#fb7185': true,
    '#fdba74': true,
    '#fda4af': true,
};

function isVolPopColor(color) {
    if (color == null || color === '') return false;
    if (typeof C === 'object' && C) {
        if (color === C.vol_surge_up || color === C.vol_surge_down
            || color === C.vol_climax_up || color === C.vol_climax_down) {
            return true;
        }
    }
    return !!VOL_RVOL_POP_COLORS[String(color).toLowerCase()];
}

function volumeBarVsSma(volume, smaValue) {
    const vol = Number(volume);
    const sma = Number(smaValue);
    if (!Number.isFinite(vol) || !Number.isFinite(sma) || sma <= 0) return null;
    return vol > sma ? 'above' : 'below';
}

function _volumeRvolBarIsUp(row) {
    if (!row) return true;
    const close = Number(row.close);
    const open = Number(row.open);
    if (!Number.isFinite(close) || !Number.isFinite(open)) return true;
    return close >= open;
}

function _volumeRvolSmaValue(smaPoints, index, time) {
    const sma = Array.isArray(smaPoints) ? smaPoints : [];
    const at = sma[index];
    if (at && at.value != null && Number.isFinite(Number(at.value))) {
        return Number(at.value);
    }
    if (time == null) return null;
    for (let i = 0; i < sma.length; i++) {
        const p = sma[i];
        if (p && p.time === time && p.value != null && Number.isFinite(Number(p.value))) {
            return Number(p.value);
        }
    }
    return null;
}

function volumeRvolColorForTone(tone, up) {
    if (tone === 'above') return up ? VOL_RVOL_ABOVE_UP : VOL_RVOL_ABOVE_DOWN;
    if (tone === 'below') return up ? VOL_RVOL_BELOW_UP : VOL_RVOL_BELOW_DOWN;
    return null;
}

function volumeRvolColors() {
    return {
        aboveUp: VOL_RVOL_ABOVE_UP,
        aboveDown: VOL_RVOL_ABOVE_DOWN,
        belowUp: VOL_RVOL_BELOW_UP,
        belowDown: VOL_RVOL_BELOW_DOWN,
    };
}

function colorVolumeBarsByRvol(volData, smaPoints, rows) {
    const data = Array.isArray(volData) ? volData : [];
    const list = Array.isArray(rows) ? rows : [];
    for (let i = 0; i < data.length; i++) {
        const bar = data[i];
        if (!bar) continue;
        if (isVolPopColor(bar.color)) continue;
        const smaVal = _volumeRvolSmaValue(smaPoints, i, bar.time);
        const vol = bar.value != null ? bar.value : (list[i] ? list[i].volume : 0);
        const tone = volumeBarVsSma(vol, smaVal);
        if (!tone) continue;
        const painted = volumeRvolColorForTone(tone, _volumeRvolBarIsUp(list[i]));
        if (painted) bar.color = painted;
    }
    return data;
}
