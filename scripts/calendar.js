/**
 * calendar.js — Macro & Earnings Calendar
 * Fetches /api/calendar and renders upcoming events grouped by month.
 */

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

async function initCalendar() {
    const wrap = document.getElementById('calendar-list');
    if (!wrap) return;
    wrap.innerHTML = '<div class="cal-muted"><span class="spinner"></span> Loading events…</div>';

    try {
        const events = await apiFetch(`${API}/calendar`);
        if (!Array.isArray(events) || events.length === 0) {
            wrap.innerHTML = '<div class="cal-muted">No upcoming events.</div>';
            return;
        }
        const today = new Date().toISOString().slice(0, 10);
        const byMonth = {};
        for (const e of events) {
            const ym = (e.date || '').slice(0, 7);
            (byMonth[ym] = byMonth[ym] || []).push(e);
        }
        wrap.innerHTML = Object.keys(byMonth).sort().map(ym => {
            const rows = byMonth[ym].map(e => {
                const isPast = e.date < today;
                return `
                    <div class="cal-event ${isPast ? 'cal-past' : ''}">
                        <span class="cal-dot" style="background:${_calEsc(e.color || '#888')}"></span>
                        <span class="cal-date">${_calEsc(e.date)}</span>
                        <span class="cal-type" style="color:${_calEsc(e.color || '#888')}">${_calEsc(e.type)}</span>
                        <span class="cal-label">${_calEsc(e.label)}</span>
                    </div>`;
            }).join('');
            return `<div class="cal-month"><div class="cal-month-head">${_monthLabel(ym)}</div>${rows}</div>`;
        }).join('');
    } catch (e) {
        wrap.innerHTML = `<div class="cal-muted">Failed to load: ${_calEsc(e.message || e)}</div>`;
    }
}
