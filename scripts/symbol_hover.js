/**
 * symbol_hover.js — Quick-view hover card for any [data-hover-symbol] element.
 *
 * Shows grade factors, KAMA alignment, and recent trade history without
 * leaving the current view. 400 ms delay avoids flicker on casual cursor movement.
 */

(function () {
    let _card = null;
    let _timer = null;
    let _pinned = false;

    function _esc(s) {
        return String(s ?? '').replace(/[&<>"']/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    }

    function _hide() {
        clearTimeout(_timer);
        if (_card && !_pinned) { _card.remove(); _card = null; }
    }

    function _pos(anchor) {
        const r = anchor.getBoundingClientRect();
        const vw = window.innerWidth, vh = window.innerHeight;
        let left = r.right + 10;
        let top  = r.top;
        // flip left if too close to right edge
        if (left + 280 > vw) left = Math.max(4, r.left - 290);
        // clamp vertical
        top = Math.max(4, Math.min(top, vh - 360));
        return { left, top };
    }

    async function _show(anchor, sym) {
        _hide();
        const { left, top } = _pos(anchor);

        _card = document.createElement('div');
        _card.id = 'shc-card';
        _card.className = 'shc-card';
        _card.style.cssText = `left:${left}px;top:${top}px;`;
        _card.innerHTML = `<div class="shc-loading"><span class="spinner"></span> ${_esc(sym)}</div>`;
        document.body.appendChild(_card);

        _card.addEventListener('mouseenter', () => clearTimeout(_timer));
        _card.addEventListener('mouseleave', _hide);

        try {
            const [grade, journal, reactions] = await Promise.all([
                (typeof apiFetch === 'function' ? apiFetch(`${API}/setup-grade/${sym}`) : fetch(`/api/setup-grade/${sym}`).then(r => r.json())).catch(() => null),
                (typeof apiFetch === 'function' ? apiFetch(`${API}/journal?symbol=${sym}`) : fetch(`/api/journal?symbol=${sym}`).then(r => r.json())).catch(() => []),
                (typeof apiFetch === 'function' ? apiFetch(`${API}/earnings-reactions/${sym}`) : fetch(`/api/earnings-reactions/${sym}`).then(r => r.json())).catch(() => []),
            ]);
            if (!_card) return;  // closed while loading

            const g    = grade?.grade  || '—';
            const gCls = g === 'A' ? 'grade-a' : g === 'B' ? 'grade-b' : 'grade-c';
            const sc   = grade?.score  ?? '—';
            const ka   = grade?.kama_alignment ?? '—';
            const rvol = grade?.rvol   != null ? grade.rvol.toFixed(1) + '×' : '—';
            const lod  = grade?.lod_dist_atr != null ? grade.lod_dist_atr.toFixed(2) + '×' : '—';
            const vcp  = grade?.vcp_score  != null ? grade.vcp_score.toFixed(2) : '—';
            const ext  = grade?.atr_mult_50ma != null ? grade.atr_mult_50ma.toFixed(1) + '×' : '—';
            const price = grade?.last_close  != null ? '$' + grade.last_close.toFixed(2) : '—';
            const ret20 = grade?.ret_20d     != null
                ? `<span class="${grade.ret_20d >= 0 ? 'shc-pos' : 'shc-neg'}">${grade.ret_20d >= 0 ? '+' : ''}${grade.ret_20d.toFixed(1)}%</span>`
                : '—';

            // Grade factor rows
            const factors = (grade?.factors || []).map(f => `
                <div class="shc-factor ${f.bull ? 'shc-bull' : f.bull === false ? 'shc-bear' : 'shc-neutral'}">
                    <span class="shc-factor-icon">${f.bull ? '▲' : f.bull === false ? '▼' : '·'}</span>
                    <span class="shc-factor-lbl">${_esc(f.label)}</span>
                    <span class="shc-factor-pts">${f.pts > 0 ? '+' : ''}${f.pts}</span>
                </div>`).join('');

            // Recent trades
            const trades = (Array.isArray(journal) ? journal : []).slice(-4).reverse();
            const tradeHtml = trades.length
                ? trades.map(t => {
                    const rVal  = (t.exit_price != null && t.stop_loss != null && Math.abs(t.entry_price - t.stop_loss) > 1e-6)
                        ? ((t.exit_price - t.entry_price) / Math.abs(t.entry_price - t.stop_loss)).toFixed(2)
                        : null;
                    const rCls  = rVal == null ? '' : parseFloat(rVal) > 0 ? 'shc-pos' : 'shc-neg';
                    const label = t.exit_price != null ? `${rVal != null ? rVal + 'R' : '?'}` : 'open';
                    return `<div class="shc-trade">
                        <span class="shc-trade-date">${(t.entry_date || '').slice(5)}</span>
                        <span class="shc-trade-setup">${_esc(t.setup || t.setup_grade || '')}</span>
                        <span class="${rCls} shc-trade-r">${label}</span>
                    </div>`;
                }).join('')
                : '<div class="shc-no-trades">No trades logged</div>';

            // Earnings reactions strip (up to 6 most recent events by abs gap)
            const rxList = Array.isArray(reactions) ? reactions.slice(0, 6) : [];
            const rxHtml = rxList.length
                ? rxList.map(rx => {
                    const cls  = rx.gap_pct >= 0 ? 'shc-rx-up' : 'shc-rx-dn';
                    const sign = rx.gap_pct >= 0 ? '+' : '';
                    return `<span class="shc-rx ${cls}" title="${rx.date}">${sign}${rx.gap_pct.toFixed(1)}%</span>`;
                }).join('')
                : '<span class="shc-rx shc-rx-none">—</span>';

            _card.innerHTML = `
                <div class="shc-header">
                    <span class="shc-sym">${_esc(sym)}</span>
                    <span class="shc-grade-badge shc-grade-${g.toLowerCase()}">${g}</span>
                    <span class="shc-score">score ${sc}</span>
                    <span class="shc-price-lbl">${price}</span>
                    <span class="shc-ret">${ret20} 20d</span>
                </div>
                <div class="shc-metrics">
                    <span class="shc-metric"><span class="shc-ml">KAMA</span>${ka}/3</span>
                    <span class="shc-metric"><span class="shc-ml">RVOL</span>${rvol}</span>
                    <span class="shc-metric"><span class="shc-ml">LoD</span>${lod}</span>
                    <span class="shc-metric"><span class="shc-ml">VCP</span>${vcp}</span>
                    <span class="shc-metric"><span class="shc-ml">Ext</span>${ext}</span>
                </div>
                ${factors ? `<div class="shc-factors">${factors}</div>` : ''}
                <div class="shc-rx-row">
                    <span class="shc-section-label" style="margin-right:6px;">Earnings gaps</span>${rxHtml}
                </div>
                <div class="shc-divider"></div>
                <div class="shc-trades-section">
                    <div class="shc-section-label">Trade History</div>
                    ${tradeHtml}
                </div>
                <div class="shc-actions">
                    <button class="shc-btn" onclick="shcChart('${_esc(sym)}')">Chart →</button>
                    <button class="shc-btn" onclick="shcAlert('${_esc(sym)}')">🔔 Alert</button>
                    <button class="shc-btn" onclick="shcSize('${_esc(sym)}', ${grade?.last_close ?? 0}, ${grade?.atr_14 ?? 0})">⚖ Size</button>
                </div>`;
        } catch (e) {
            if (_card) _card.innerHTML = `<div class="shc-error">Failed to load</div>`;
        }
    }

    // Delegated hover listeners
    document.addEventListener('mouseover', e => {
        const el = e.target.closest('[data-hover-symbol]');
        if (!el || _pinned) return;
        const sym = el.dataset.hoverSymbol;
        if (!sym) return;
        clearTimeout(_timer);
        _timer = setTimeout(() => _show(el, sym), 420);
    });

    document.addEventListener('mouseout', e => {
        const el = e.target.closest('[data-hover-symbol]');
        if (!el || _pinned) return;
        const related = e.relatedTarget;
        if (related && related.closest('#shc-card')) return;
        clearTimeout(_timer);
        _timer = setTimeout(_hide, 120);
    });

    // Exposed action handlers (called from card buttons)
    window.shcChart = function (sym) {
        _hide();
        if (typeof selectSymbol === 'function') selectSymbol(sym);
        if (typeof switchTab    === 'function') switchTab('charts');
    };
    window.shcAlert = function (sym) {
        _hide();
        if (typeof selectSymbol === 'function') selectSymbol(sym);
        if (typeof toggleAlertsPanel === 'function') toggleAlertsPanel();
    };
    window.shcSize = function (sym, price, atr14) {
        _hide();
        if (typeof selectSymbol === 'function') selectSymbol(sym);
        if (typeof jeffSizeIt   === 'function') jeffSizeIt(sym, price, price, atr14);
        else if (typeof switchTab === 'function') switchTab('risk-calc');
    };
})();
