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

async function loadJournal() {
    const tbody = document.getElementById('journal-body');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="10" class="jnl-muted"><span class="spinner"></span> Loading…</td></tr>';
    try {
        const entries = await apiFetch(`${API}/journal`);
        if (!Array.isArray(entries) || entries.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" class="jnl-muted">No journal entries yet.</td></tr>';
            return;
        }
        tbody.innerHTML = entries.map(e => {
            const rg     = e.review_grade || '';
            const rgCls  = rg === 'A+' || rg === 'A' ? 'jnl-pos' : rg === 'D' || rg === 'F' ? 'jnl-neg' : '';
            const rgHtml = rg ? `<span class="${rgCls}" title="${_jnlEsc(e.review_lesson||'')} ${_jnlEsc(e.review_mistakes||'')}">${rg}</span>` : '—';
            return `<tr>
                <td><strong data-hover-symbol="${_jnlEsc(e.symbol)}">${_jnlEsc(e.symbol)}</strong></td>
                <td class="${e.direction === 'short' ? 'jnl-neg' : 'jnl-pos'}">${_jnlEsc(e.direction)}</td>
                <td>${_jnlEsc(e.entry_date)}</td>
                <td>${Number(e.entry_price).toFixed(2)}</td>
                <td>${e.stop_loss != null ? Number(e.stop_loss).toFixed(2) : '—'}</td>
                <td>${e.exit_price != null ? Number(e.exit_price).toFixed(2) : '—'}</td>
                <td>${_jnlR(e)}</td>
                <td>${_jnlPnl(e)}</td>
                <td>${rgHtml}</td>
                <td><button class="btn btn-ghost btn-icon" title="Delete" onclick="deleteJournalEntry(${e.id})">✕</button></td>
            </tr>`;
        }).join('');
    } catch (err) {
        tbody.innerHTML = `<tr><td colspan="10" class="jnl-muted">Failed: ${_jnlEsc(err.message || err)}</td></tr>`;
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
        await apiFetch(`${API}/journal`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        toast('Journal entry added', 'success');
        ['jnl-symbol','jnl-entry-price','jnl-stop-loss','jnl-exit-price','jnl-exit-date',
         'jnl-qty','jnl-setup','jnl-tags','jnl-thesis',
         'jnl-review-mistakes','jnl-review-lesson']
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
