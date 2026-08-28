/**
 * Linked daily↔weekly OHLC readout.
 *
 * Range sync already exists (syncPanels). This file only paints the matching
 * bar on the other timeframe when the crosshair moves.
 *
 * Weekly bars are W-FRI (see data_fetcher.py). Matching:
 *   daily  → first weekly bar with date >= daily (covering Friday bar)
 *   weekly → last daily bar with date <= weekly (that week's last print)
 *
 * Isolated so other chart specialists can edit sticky legend / packs / prefetch
 * without a rewrite here.
 */
function _linkedBarDate(row) {
    if (!row) return '';
    return String(row.date).slice(0, 10);
}

function _linkedPx(v) {
    if (typeof _fmtPx === 'function') return _fmtPx(v);
    return (v == null || !Number.isFinite(Number(v))) ? '—' : Number(v).toFixed(2);
}

function _firstWeeklyOnOrAfter(rows, key) {
    if (!rows || !rows.length || !key) return null;
    for (let i = 0; i < rows.length; i++) {
        if (_linkedBarDate(rows[i]) >= key) return { row: rows[i], idx: i };
    }
    return { row: rows[rows.length - 1], idx: rows.length - 1 };
}

function _lastDailyOnOrBefore(rows, key) {
    if (!rows || !rows.length || !key) return null;
    let found = null;
    for (let i = 0; i < rows.length; i++) {
        if (_linkedBarDate(rows[i]) <= key) found = { row: rows[i], idx: i };
        else break;
    }
    return found;
}

function linkedBarFor(sourceFreq, dateKey) {
    const key = dateKey ? String(dateKey).slice(0, 10) : '';
    if (!key || typeof rawRows === 'undefined' || !rawRows) return null;
    if (sourceFreq === 'daily') return _firstWeeklyOnOrAfter(rawRows.weekly, key);
    return _lastDailyOnOrBefore(rawRows.daily, key);
}

function paintLinkedTwin(sourceFreq, dateKey) {
    const el = document.getElementById(`chart-legend-${sourceFreq}-twin`);
    if (!el) return;
    const hit = linkedBarFor(sourceFreq, dateKey);
    if (!hit || !hit.row) {
        el.textContent = '';
        return;
    }
    const row = hit.row;
    const up = Number(row.close) >= Number(row.open);
    const tone = up ? 'lg-up' : 'lg-down';
    const label = sourceFreq === 'daily' ? 'W' : 'D';
    el.classList.toggle('legend-up', up);
    el.classList.toggle('legend-down', !up);
    el.innerHTML = `<span class="lg-date">${label} ${row.date}</span>`
        + ` <span class="${tone}">O ${_linkedPx(row.open)}</span>`
        + ` <span class="lg-h">H ${_linkedPx(row.high)}</span>`
        + ` <span class="lg-l">L ${_linkedPx(row.low)}</span>`
        + ` <span class="${tone}">C ${_linkedPx(row.close)}</span>`;
}

function _refreshOtherTwin(sourceFreq) {
    const other = sourceFreq === 'daily' ? 'weekly' : 'daily';
    if (typeof lastLegend === 'undefined' || !lastLegend[other] || !lastLegend[other].time) return;
    paintLinkedTwin(other, lastLegend[other].time);
}

function paintLinkedTwinIfLive(freq) {
    const time = (typeof lastLegend !== 'undefined' && lastLegend[freq]) ? lastLegend[freq].time : null;
    paintLinkedTwin(freq, time);
    _refreshOtherTwin(freq);
}
