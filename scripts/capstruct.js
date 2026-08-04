/**
 * capstruct.js — Capital Structure tab.
 *
 * Summons the capstruct extractor (SEC filings) for the active watchlist
 * symbol and renders the result with its provenance intact: every figure
 * shows the tag or footnote it came from, the filing, and a confidence, and
 * every field that could NOT be extracted is shown as an explicit gap rather
 * than being omitted.
 */

let _capstructLast = null;

function initCapstruct() {
    const subj = document.getElementById('capstruct-subject');
    if (subj) {
        subj.textContent = state.activeSymbol
            ? `Subject: ${state.activeSymbol}`
            : 'No symbol selected';
    }
}

async function capstructRun() {
    if (!state.activeSymbol) {
        toast('Select a watchlist symbol first', 'warning');
        return;
    }
    const btn   = document.getElementById('btn-capstruct-run');
    const load  = document.getElementById('capstruct-loading');
    const asOf  = document.getElementById('capstruct-asof')?.value || '';
    if (btn)  btn.disabled = true;
    if (load) load.style.display = 'inline-flex';

    try {
        const qs  = asOf ? `?as_of=${encodeURIComponent(asOf)}` : '';
        const res = await apiFetch(`${API}/capstruct/${state.activeSymbol}${qs}`);
        _capstructLast = res;
        renderCapstruct(res);
    } catch (e) {
        toast('Capital structure failed: ' + e.message, 'error');
    } finally {
        if (btn)  btn.disabled = false;
        if (load) load.style.display = 'none';
    }
}

function _csMoney(v) {
    if (v == null) return '—';
    const abs = Math.abs(v);
    if (abs >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
    if (abs >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
    if (abs >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
    return `$${v.toFixed(0)}`;
}

function _csShares(v) {
    return v == null ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

/** One row: value + its audit trail, or an explicit MISSING with what was tried. */
function _csRow(label, field, fmt) {
    if (!field) {
        return `<tr class="cs-row-missing"><td>${label}</td>
                <td class="cs-val">—</td><td class="cs-prov">not extracted</td></tr>`;
    }
    if (field.reason !== undefined && field.value === undefined) {
        const tried = (field.tried || []).join(', ');
        return `<tr class="cs-row-missing">
            <td>${label}</td>
            <td class="cs-val">MISSING</td>
            <td class="cs-prov" title="${tried}">${field.reason}</td>
        </tr>`;
    }
    const conf = field.confidence || 'high';
    const link = field.url
        ? `<a href="${field.url}" target="_blank" rel="noopener">${field.accession_number}</a>`
        : (field.accession_number || '');
    return `<tr>
        <td>${label}</td>
        <td class="cs-val">${fmt(field.value)}</td>
        <td class="cs-prov">
            <span class="cs-conf cs-conf-${conf}">${conf}</span>
            <code>${field.locator || field.source_type}</code>
            ${link} · period ${field.period_end}
        </td>
    </tr>`;
}

function renderCapstruct(res) {
    const body  = document.getElementById('capstruct-body');
    const empty = document.getElementById('capstruct-empty');
    if (!body) return;

    if (!res.ok) {
        if (empty) empty.style.display = 'none';
        const detail = res.detail || '';
        const titles = {
            sec_unreachable:   'Could not reach SEC',
            config_required:   'Configuration needed',
            unknown_identifier:'Unknown ticker or CIK',
            capstruct_unavailable: 'Extractor unavailable',
        };
        const notes = {
            sec_unreachable:
                'The extractor is installed and working — this is a network restriction ' +
                'on this environment, not a fault in the tool. <code>data.sec.gov</code> ' +
                'and <code>www.sec.gov</code> must be reachable.',
            config_required:
                'SEC refuses requests without a contact email in the User-Agent. Set it ' +
                'once in the server environment and re-run.',
        };
        body.innerHTML = `
            <div class="cs-error">
                <div class="cs-error-title">${titles[res.error] || 'Extraction failed'}</div>
                <p>${res.hint || detail}</p>
                <pre class="cs-error-detail">${detail}</pre>
                ${notes[res.error] ? `<p class="cs-error-note">${notes[res.error]}</p>` : ''}
            </div>`;
        return;
    }

    const s = res.snapshot;
    if (empty) empty.style.display = 'none';

    const f = s.source_filing;
    const filingLine = f
        ? `${f.form} · ${f.accession_number} · filed ${f.filing_date} · period ${f.period_end}`
        : 'no governing 10-K/10-Q found for this date';

    const nd = s.net_debt || {};
    const bridgeRows = (nd.components || []).map(c => `
        <tr class="${c.available ? '' : 'cs-row-missing'}">
            <td>${c.sign > 0 ? '+' : '−'} ${c.label}</td>
            <td class="cs-val">${c.available ? _csMoney(c.value) : 'MISSING'}</td>
            <td class="cs-prov">${c.available
                ? `<span class="cs-conf cs-conf-${c.confidence}">${c.confidence}</span> <code>${c.locator || ''}</code>`
                : (c.reason || '')}</td>
        </tr>`).join('');

    body.innerHTML = `
        <div class="cs-header">
            <div class="cs-company">${s.company_name || s.ticker} <span class="cs-cik">CIK ${s.cik}</span></div>
            <div class="cs-filing">${filingLine}</div>
            <div class="cs-mode">${s.point_in_time ? 'point-in-time' : 'period-based'}
                ${s.as_of ? `· as of ${s.as_of}` : '· latest'}</div>
        </div>

        ${(s.warnings || []).map(w => `<div class="cs-warning">⚠ ${w}</div>`).join('')}

        <div class="cs-section">
            <div class="cs-section-title">Net Debt Bridge</div>
            <table class="cs-table">${bridgeRows}
                <tr class="cs-total">
                    <td>= Net debt</td>
                    <td class="cs-val">${_csMoney(nd.net_debt)}</td>
                    <td class="cs-prov">${nd.incomplete ? '⚠ incomplete — see notes' : 'derived'}</td>
                </tr>
            </table>
            ${(nd.notes || []).map(n => `<div class="cs-note">· ${n}</div>`).join('')}
        </div>

        <div class="cs-section">
            <div class="cs-section-title">Liquidity</div>
            <table class="cs-table">
                ${_csRow('Cash and equivalents', s.liquidity.cash_and_equivalents, _csMoney)}
                ${_csRow('Short-term investments', s.liquidity.short_term_investments, _csMoney)}
                ${_csRow('Restricted cash (current)', s.liquidity.restricted_cash_current, _csMoney)}
                ${_csRow('Restricted cash (non-current)', s.liquidity.restricted_cash_noncurrent, _csMoney)}
                ${_csRow('Revolver commitment', s.liquidity.revolver_commitment, _csMoney)}
                ${_csRow('Revolver drawn', s.liquidity.revolver_drawn, _csMoney)}
                ${_csRow('Revolver available', s.liquidity.revolver_available, _csMoney)}
            </table>
        </div>

        <div class="cs-section">
            <div class="cs-section-title">Common Equity</div>
            <table class="cs-table">
                ${_csRow('Shares outstanding (cover page)', s.common_equity.cover_page_shares_outstanding, _csShares)}
                ${_csRow('Shares outstanding (balance sheet)', s.common_equity.balance_sheet_shares_outstanding, _csShares)}
                ${_csRow('Diluted shares (as reported)', s.common_equity.diluted_shares_reported, _csShares)}
            </table>
        </div>

        <div class="cs-section cs-pending">
            <div class="cs-section-title">Instrument detail</div>
            <p>Straight debt tranches, convertibles (with capped-call offset),
               warrants and preferred are extracted from the debt/equity footnotes
               and exhibits — that layer is not wired up yet, so these are
               deliberately empty rather than guessed.</p>
        </div>
    `;
}
