/**
 * calendar.js — Macro & Earnings Calendar
 *
 * Fetches /api/calendar (econ_calendar backend: FOMC, CPI, NFP, GDP, PCE,
 * ISM, OPEX… plus watchlist earnings) and renders events grouped by month
 * with category filters, importance dots, and a next-major-event banner.
 */

const _CAL_FILTER_KEY = 'calendar_filters_v1';

const _CAL_CATEGORIES = [
    ['all',       'All'],
    ['fed',       'Fed'],
    ['inflation', 'Inflation'],
    ['jobs',      'Jobs'],
    ['growth',    'Growth'],
    ['market',    'OPEX'],
    ['earnings',  'Earnings'],
];

let _calState = { events: [], category: 'all', highOnly: false };

function _calEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

function _monthLabel(ym) {
    const [y, m] = ym.split('-');
    const names = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return `${names[parseInt(m, 10) - 1]} ${y}`;
}

function _calImpDots(imp) {
    const on = '●'.repeat(imp || 1);
    const off = '○'.repeat(Math.max(0, 3 - (imp || 1)));
    const cls = imp >= 3 ? 'cal-imp-hi' : imp === 2 ? 'cal-imp-med' : 'cal-imp-lo';
    return `<span class="cal-imp ${cls}" title="Importance ${imp}/3">${on}${off}</span>`;
}

function _calDayLabel(ds) {
    const d = new Date(ds + 'T12:00:00');
    return d.toLocaleDateString('en-US', { weekday: 'short' });
}

function setCalCategory(cat) {
    _calState.category = cat;
    _calPersist();
    _renderCalendar();
}

function toggleCalHighOnly() {
    _calState.highOnly = !_calState.highOnly;
    _calPersist();
    _renderCalendar();
}

function _calPersist() {
    try {
        localStorage.setItem(_CAL_FILTER_KEY, JSON.stringify({
            category: _calState.category, highOnly: _calState.highOnly,
        }));
    } catch (_) {}
}

function _calRestore() {
    try {
        const saved = JSON.parse(localStorage.getItem(_CAL_FILTER_KEY) || '{}');
        if (saved.category) _calState.category = saved.category;
        if (saved.highOnly != null) _calState.highOnly = saved.highOnly;
    } catch (_) {}
}

async function initCalendar() {
    const wrap = document.getElementById('calendar-list');
    if (!wrap) return;
    _calRestore();
    wrap.innerHTML = '<div class="cal-muted"><span class="spinner"></span> Loading events…</div>';

    try {
        const events = await apiFetch(`${API}/calendar`);
        if (!Array.isArray(events) || events.length === 0) {
            wrap.innerHTML = '<div class="cal-muted">No upcoming events.</div>';
            return;
        }
        _calState.events = events;
        _renderCalendar();
    } catch (e) {
        wrap.innerHTML = `<div class="cal-muted">Failed to load: ${_calEsc(e.message || e)}</div>`;
    }
}

function _renderCalendar() {
    const wrap = document.getElementById('calendar-list');
    if (!wrap) return;

    const today = new Date().toISOString().slice(0, 10);
    const all   = _calState.events;

    // Next high-importance upcoming event → banner
    const nextMajor = all.find(e => e.date >= today && e.importance >= 3);
    let banner = '';
    if (nextMajor) {
        const days = Math.round((new Date(nextMajor.date) - new Date(today)) / 86400000);
        const when = days === 0 ? 'TODAY' : days === 1 ? 'tomorrow' : `in ${days} days`;
        const urg  = days <= 1 ? 'cal-banner-hot' : days <= 3 ? 'cal-banner-warm' : '';
        banner = `<div class="cal-banner ${urg}">
            <span class="cal-banner-icon">⚡</span>
            <span class="cal-banner-text">Next major event: <strong style="color:${_calEsc(nextMajor.color)}">${_calEsc(nextMajor.label)}</strong> ${when}</span>
            <span class="cal-banner-date">${_calEsc(nextMajor.date)}</span>
        </div>`;
    }

    // Filter chips
    const chips = _CAL_CATEGORIES.map(([id, label]) =>
        `<button class="cal-chip ${_calState.category === id ? 'cal-chip-on' : ''}"
                 onclick="setCalCategory('${id}')">${label}</button>`).join('');
    const highChip = `<button class="cal-chip cal-chip-imp ${_calState.highOnly ? 'cal-chip-on' : ''}"
                              onclick="toggleCalHighOnly()" title="Show only high-importance events">● High only</button>`;

    // Apply filters
    const filtered = all.filter(e => {
        if (_calState.category !== 'all' && e.category !== _calState.category) return false;
        if (_calState.highOnly && (e.importance || 1) < 3) return false;
        return true;
    });

    const byMonth = {};
    for (const e of filtered) {
        const ym = (e.date || '').slice(0, 7);
        (byMonth[ym] = byMonth[ym] || []).push(e);
    }

    const monthsHtml = Object.keys(byMonth).sort().map(ym => {
        const rows = byMonth[ym].map(e => {
            const isPast  = e.date < today;
            const isToday = e.date === today;
            const approx  = e.approx ? '<span class="cal-approx" title="Estimated date — verify with the official release schedule (or add a FRED API key in Settings for exact dates)">~</span>' : '';
            const symAttr = e.symbol ? ` data-hover-symbol="${_calEsc(e.symbol)}" style="cursor:pointer"` : '';
            return `
                <div class="cal-event ${isPast ? 'cal-past' : ''} ${isToday ? 'cal-today' : ''}"${symAttr}>
                    <span class="cal-dot" style="background:${_calEsc(e.color || '#888')}"></span>
                    <span class="cal-date">${_calEsc(e.date)} <span class="cal-dow">${_calDayLabel(e.date)}</span></span>
                    ${_calImpDots(e.importance)}
                    <span class="cal-type" style="color:${_calEsc(e.color || '#888')}">${_calEsc(e.type)}</span>
                    <span class="cal-label">${approx}${_calEsc(e.label)}${isToday ? ' <span class="cal-today-badge">TODAY</span>' : ''}</span>
                </div>`;
        }).join('');
        return `<div class="cal-month"><div class="cal-month-head">${_monthLabel(ym)}</div>${rows}</div>`;
    }).join('');

    wrap.innerHTML = `
        ${banner}
        <div class="cal-filters">${chips}<span class="cal-chip-spacer"></span>${highChip}</div>
        ${monthsHtml || '<div class="cal-muted">No events match the current filters.</div>'}`;
}
