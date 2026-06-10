/**
 * journal.js — Trade Journal + Analytics (sub-tabs)
 */

let _jnlActiveSubTab = 'log';

function _switchJournalTab(tab) {
    _jnlActiveSubTab = tab;
    const logPanel  = document.getElementById('jnl-log-panel');
    const anPanel   = document.getElementById('jnl-analytics-panel');
    const logBtn    = document.getElementById('jnl-tab-log');
    const anBtn     = document.getElementById('jnl-tab-analytics');
    if (logPanel)  logPanel.style.display  = tab === 'log'       ? '' : 'none';
    if (anPanel)   anPanel.style.display   = tab === 'analytics' ? '' : 'none';
    if (logBtn)    logBtn.classList.toggle('active', tab === 'log');
    if (anBtn)     anBtn.classList.toggle('active',  tab === 'analytics');
    // Highlight the Journal nav button regardless of sub-tab
    document.getElementById('tab-journal')?.classList.add('active');
}

function _jnlEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

function _jnlR(e) {
    if (e.exit_price == null || e.stop_loss == null) return '—';
    const entry = parseFloat(e.entry_price);
    const stop  = parseFloat(e.stop_loss);
    const exit_ = parseFloat(e.exit_price);
    const risk  = Math.abs(entry - stop);
    if (risk < 0.0001) return '—';
    const r = (e.direction === 'short')
        ? (entry - exit_) / risk
        : (exit_ - entry) / risk;
    const cls = r >= 0 ? 'jnl-pos' : 'jnl-neg';
    return `<span class="${cls}">${r >= 0 ? '+' : ''}${r.toFixed(2)}R</span>`;
}

function _jnlPnl(e) {
    if (e.exit_price == null) return '<span class="jnl-open">open</span>';
    const dir = e.direction === 'short' ? -1 : 1;
    const pnl = (e.exit_price - e.entry_price) * (e.qty || 1) * dir;
    const cls = pnl >= 0 ? 'jnl-pos' : 'jnl-neg';
    return `<span class="${cls}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)}</span>`;
}

function _tradingDaysBetween(fromStr, toDate) {
    // Weekday count from entry date (exclusive) to toDate (inclusive)
    const from = new Date(fromStr + 'T00:00:00');
    if (isNaN(from)) return null;
    let days = 0;
    const d = new Date(from);
    while (d < toDate) {
        d.setDate(d.getDate() + 1);
        const wd = d.getDay();
        if (wd !== 0 && wd !== 6) days++;
    }
    return days;
}

function _jnlDayBadge(e) {
    // Open trades: T+N risk-window badge (Jeff's T+3 rule).
    // Closed trades: holding period in trading days.
    const today = new Date(); today.setHours(0, 0, 0, 0);
    if (e.exit_price == null && e.entry_date) {
        const n = _tradingDaysBetween(e.entry_date, today);
        if (n == null) return '—';
        if (n <= 3) {
            const cls = n === 3 ? 'jnl-t3-now' : 'jnl-t3-early';
            const tip = n === 3
                ? 'T+3: reduce risk, move stop toward breakeven'
                : `T+${n}: early window — 3-stop layers active`;
            return `<span class="jnl-t3 ${cls}" title="${tip}">T+${n}</span>`;
        }
        return `<span class="jnl-t3 jnl-t3-late" title="Day ${n}: manage with 10-day MA">D${n}</span>`;
    }
    if (e.entry_date && e.exit_date) {
        const exitD = new Date(e.exit_date + 'T00:00:00');
        const n = isNaN(exitD) ? null : _tradingDaysBetween(e.entry_date, exitD);
        return n != null ? `<span class="jnl-muted-sm">${n}d</span>` : '—';
    }
    return '—';
}

function _jnlExcursion(e) {
    const mfe = e.mfe_r != null ? `<span class="jnl-pos">+${Number(e.mfe_r).toFixed(1)}</span>` : '';
    const mae = e.mae_r != null ? `<span class="jnl-neg">−${Math.abs(Number(e.mae_r)).toFixed(1)}</span>` : '';
    if (!mfe && !mae) return '—';
    return `${mfe || '·'}<span class="jnl-muted-sm">/</span>${mae || '·'}`;
}

async function _loadManagePanel() {
    const panel = document.getElementById('jnl-manage-panel');
    if (!panel) return;
    try {
        const d = await apiFetch(`${API}/journal/manage`);
        const trades = d.open_trades || [];
        if (!trades.length) { panel.style.display = 'none'; return; }
        panel.style.display = '';
        const lvlCls = { green: 'jm-hint-green', yellow: 'jm-hint-yellow',
                         red: 'jm-hint-red', info: 'jm-hint-info' };
        panel.innerHTML = `
            <div class="an-section-header">Open Positions — Management
                <span class="an-muted-inline">(T+3 / 10-MA / extension rules)</span>
            </div>
            <div class="jm-cards">` +
            trades.map(t => {
                const rCls = t.current_r == null ? '' : t.current_r >= 0 ? 'jnl-pos' : 'jnl-neg';
                const rTxt = t.current_r != null ? `${t.current_r >= 0 ? '+' : ''}${t.current_r}R` : '—';
                const hints = (t.hints || []).map(h =>
                    `<div class="jm-hint ${lvlCls[h.level] || 'jm-hint-info'}">${h.text}</div>`).join('');
                const meta = [
                    t.current_price != null ? `$${t.current_price}` : '',
                    t.atr_mult_50ma != null ? `${t.atr_mult_50ma}× ATR` : '',
                    t.below_10ma ? '<span class="jnl-neg">< 10-MA</span>' : '',
                ].filter(Boolean).join(' · ');
                return `<div class="jm-card">
                    <div class="jm-card-top">
                        <strong data-hover-symbol="${_jnlEsc(t.symbol)}">${_jnlEsc(t.symbol)}</strong>
                        <span class="jm-day">T+${t.days_held}</span>
                        <span class="${rCls}">${rTxt}</span>
                    </div>
                    <div class="jm-card-meta">${t.error ? 'no data' : meta}</div>
                    ${hints}
                </div>`;
            }).join('') + '</div>';
    } catch (_) {
        panel.style.display = 'none';
    }
}

async function loadJournal() {
    _loadManagePanel();
    const tbody = document.getElementById('journal-body');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="12" class="jnl-muted"><span class="spinner"></span> Loading…</td></tr>';
    try {
        const entries = await apiFetch(`${API}/journal`);
        if (!Array.isArray(entries) || entries.length === 0) {
            tbody.innerHTML = '<tr><td colspan="12" class="jnl-muted">No journal entries yet.</td></tr>';
            return;
        }
        tbody.innerHTML = entries.map(e => {
            const rg     = e.review_grade || '';
            const rgCls  = rg === 'A+' || rg === 'A' ? 'jnl-pos' : rg === 'D' || rg === 'F' ? 'jnl-neg' : '';
            const rgHtml = rg ? `<span class="${rgCls}" title="${_jnlEsc(e.review_lesson||'')} ${_jnlEsc(e.review_mistakes||'')}">${rg}</span>` : '—';
            const ctx    = [e.market_regime ? `Regime: ${e.market_regime}` : '',
                            e.entry_rvol   != null ? `RVOL: ${Number(e.entry_rvol).toFixed(1)}×` : '',
                            e.lod_dist_atr != null ? `LoD: ${Number(e.lod_dist_atr).toFixed(2)}×ATR` : '']
                            .filter(Boolean).join(' · ');
            return `<tr>
                <td><strong data-hover-symbol="${_jnlEsc(e.symbol)}" title="${_jnlEsc(ctx)}">${_jnlEsc(e.symbol)}</strong></td>
                <td class="${e.direction === 'short' ? 'jnl-neg' : 'jnl-pos'}">${_jnlEsc(e.direction)}</td>
                <td>${_jnlEsc(e.entry_date)}</td>
                <td>${_jnlDayBadge(e)}</td>
                <td>${Number(e.entry_price).toFixed(2)}</td>
                <td>${e.stop_loss != null ? Number(e.stop_loss).toFixed(2) : '—'}</td>
                <td>${e.exit_price != null ? Number(e.exit_price).toFixed(2) : '—'}</td>
                <td>${_jnlR(e)}</td>
                <td>${_jnlExcursion(e)}</td>
                <td>${_jnlPnl(e)}</td>
                <td>${rgHtml}</td>
                <td><button class="btn btn-ghost btn-icon" title="Delete" onclick="deleteJournalEntry(${e.id})">✕</button></td>
            </tr>`;
        }).join('');
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="12" class="jnl-muted">Failed: ${_jnlEsc(err.message || err)}</td></tr>`;
    }
}

async function submitJournalEntry() {
    const g = id => document.getElementById(id);
    const sym = (g('jnl-symbol')?.value || '').trim().toUpperCase();
    const body = {
        symbol:           sym,
        direction:        g('jnl-direction')?.value || 'long',
        entry_date:       g('jnl-entry-date')?.value || undefined,
        entry_price:      parseFloat(g('jnl-entry-price')?.value),
        stop_loss:        g('jnl-stop-loss')?.value    ? parseFloat(g('jnl-stop-loss').value)    : undefined,
        exit_price:       g('jnl-exit-price')?.value   ? parseFloat(g('jnl-exit-price').value)   : undefined,
        exit_date:        g('jnl-exit-date')?.value    || undefined,
        qty:              g('jnl-qty')?.value          ? parseFloat(g('jnl-qty').value)           : 1,
        setup:            g('jnl-setup')?.value        || '',
        tags:             g('jnl-tags')?.value         || '',
        thesis:           g('jnl-thesis')?.value       || '',
        review_grade:     g('jnl-review-grade')?.value    || '',
        review_mistakes:  g('jnl-review-mistakes')?.value || '',
        review_lesson:    g('jnl-review-lesson')?.value   || '',
        mae_r:            g('jnl-mae')?.value ? parseFloat(g('jnl-mae').value) : undefined,
        mfe_r:            g('jnl-mfe')?.value ? parseFloat(g('jnl-mfe').value) : undefined,
    };
    if (!body.symbol || !Number.isFinite(body.entry_price)) {
        toast('Symbol and entry price are required', 'warning');
        return;
    }

    // Earnings proximity warning
    if (sym && typeof state !== 'undefined' && state.symbols) {
        const symData = state.symbols.find(s => s.symbol === sym);
        if (symData?.next_earnings) {
            const earningsDate = new Date(symData.next_earnings);
            const today = new Date(); today.setHours(0,0,0,0);
            const diff  = Math.round((earningsDate - today) / 86400000);
            if (diff >= 0 && diff <= 5)
                toast(`⚠ ${sym} earnings in ${diff} day${diff === 1 ? '' : 's'} (${symData.next_earnings})`, 'warning', 5000);
        }
    }

    try {
        const res = await apiFetch(`${API}/journal`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        toast('Journal entry added', 'success');
        if (res && res.today_count > 3) {
            toast(`⚠ ${res.today_count} new trades today — hard rule is max 3 per session`, 'warning', 6000);
        }
        ['jnl-symbol','jnl-entry-price','jnl-stop-loss','jnl-exit-price','jnl-exit-date',
         'jnl-qty','jnl-setup','jnl-tags','jnl-thesis',
         'jnl-review-mistakes','jnl-review-lesson','jnl-mae','jnl-mfe']
            .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
        const gradeEl = document.getElementById('jnl-review-grade');
        if (gradeEl) gradeEl.value = '';
        loadJournal();
    } catch (e) {
        toastFromError(e, 'Journal');
    }
}

async function deleteJournalEntry(id) {
    try {
        await apiFetch(`${API}/journal/${id}`, { method: 'DELETE' });
        loadJournal();
    } catch (e) {
        toastFromError(e, 'Journal');
    }
}

function initJournal() {
    // Consume prefill from Jeff scanner "Log Trade" action
    const pf = window._jeffJournalPrefill;
    if (pf) {
        window._jeffJournalPrefill = null;
        const set = (id, v) => { const el = document.getElementById(id); if (el && v != null) el.value = v; };
        set('jnl-symbol',      pf.symbol);
        set('jnl-entry-price', pf.entry_price);
        set('jnl-stop-loss',   pf.stop_loss);
        set('jnl-qty',         pf.qty);
        set('jnl-setup',       pf.setup);
        set('jnl-thesis',      pf.thesis);
        const dirEl = document.getElementById('jnl-direction');
        if (dirEl && pf.direction) dirEl.value = pf.direction;
        loadJournal();
        return;
    }

    const sym = document.getElementById('jnl-symbol');
    if (sym && !sym.value && state.activeSymbol) sym.value = state.activeSymbol;

    // Auto-suggest stop from swing widget if data is available
    const stopEl = document.getElementById('jnl-stop-loss');
    if (stopEl && !stopEl.value && typeof _swGradeData !== 'undefined' && _swGradeData) {
        const d = _swGradeData;
        if (d.last_close && d.atr_14) {
            stopEl.value = (d.last_close - d.atr_14).toFixed(2);
            stopEl.title = `Auto-suggested: 1× ATR below close (${d.atr_14.toFixed(2)} ATR)`;
        }
    }

    loadJournal();
}
