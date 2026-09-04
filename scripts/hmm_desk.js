/* SPY Gaussian HMM — research label, not edge. Desk inherits SPY. */
/* global API, apiFetch, selectSymbol */

function _hmmProb(probs, i) {
    if (!Array.isArray(probs) || probs[i] == null) return '—';
    return `${(Number(probs[i]) * 100).toFixed(0)}%`;
}

function _hmmPathBars(path) {
    if (!Array.isArray(path) || !path.length) return '';
    const last = path.slice(-40);
    return `<div class="hmm-path" aria-label="Filtered state probabilities">${last.map(pt => {
        const p = (pt.probs || [])[pt.state_id] ?? 0;
        const h = Math.max(12, Math.round(Number(p) * 28));
        return `<span class="hmm-bar hmm-${pt.label || 'na'}" title="${pt.date || ''} ${pt.label || ''} ${Math.round(p * 100)}%" style="height:${h}px"></span>`;
    }).join('')}</div>`;
}

async function loadHmmScan() {
    const meta = document.getElementById('hmm-scan-meta');
    const note = document.getElementById('hmm-scan-note');
    const tbody = document.getElementById('hmm-scan-tbody');
    const empty = document.getElementById('hmm-scan-empty');
    const statesEl = document.getElementById('hmm-states');
    const spyEl = document.getElementById('hmm-spy-label');
    const statesSel = document.getElementById('hmm-states-n');
    const filterSel = document.getElementById('hmm-state-filter');
    const viewSel = document.getElementById('hmm-view');
    if (!tbody) return;
    const n = (statesSel && statesSel.value) || '2';
    const filt = (filterSel && filterSel.value) || '';
    const view = (viewSel && viewSel.value) || 'all';
    if (meta) meta.textContent = 'GET /api/hmm/scan…';
    try {
        const q = new URLSearchParams({ desk: '1', states: n, view });
        if (filt) q.set('state', filt);
        const data = await apiFetch(`${API}/hmm/scan?${q}`);
        const spy = data.spy || {};
        if (spyEl) {
            spyEl.textContent = data.available
                ? `SPY ${spy.current_read || spy.current_label || '—'} · as-of ${spy.as_of || '—'} · flip ${spy.flipped ? 'yes' : 'no'} · ${data.note || 'research label, not edge'}`
                : (data.reason || 'SPY HMM unavailable');
        }
        if (statesEl) {
            const states = spy.states || [];
            statesEl.innerHTML = states.map(st => `
                <div class="hmm-state-card">
                    <strong>${st.label || 'state ' + st.id}</strong>
                    <span>mean ${st.mean ?? '—'}</span>
                    <span>σ ${st.vol ?? '—'}</span>
                    <span>realized ${st.realized_vol ?? '—'}</span>
                    <span class="hmm-occ">${st.occupancy != null ? (Number(st.occupancy) * 100).toFixed(0) + '% of window' : ''}</span>
                    <em>${st.occupancy_note || 'not a win rate'}</em>
                </div>`).join('') + _hmmPathBars(spy.path || []);
        }
        if (filterSel && filterSel.options.length <= 1) {
            const seen = new Set(['']);
            (spy.states || []).forEach(st => {
                if (st.label && !seen.has(st.label)) {
                    seen.add(st.label);
                    const opt = document.createElement('option');
                    opt.value = st.label;
                    opt.textContent = `SPY state = ${st.label}`;
                    filterSel.appendChild(opt);
                }
            });
        }
        const rows = Array.isArray(data.rows) ? data.rows : [];
        tbody.innerHTML = '';
        rows.forEach(row => {
            const tr = document.createElement('tr');
            tr.dataset.symbol = row.symbol || '';
            tr.innerHTML = `
                <td class="macro-sym">${row.symbol || ''}</td>
                <td>${row.inherited ? 'inherit SPY' : 'SPY fit'}</td>
                <td>${row.spy_read || row.spy_state || '—'}${row.flipped ? ' · flip' : ''}${row.high_vol ? ' · high-vol' : ''}</td>
                <td>${row.spy_prob == null ? '—' : (Number(row.spy_prob) * 100).toFixed(0) + '%'}</td>
                <td>${row.tag || ''}</td>
                <td>${row.note || 'research label, not edge'}</td>`;
            tr.addEventListener('click', () => {
                if (row.symbol && typeof selectSymbol === 'function') selectSymbol(row.symbol);
            });
            tbody.appendChild(tr);
        });
        if (empty) empty.style.display = rows.length ? 'none' : 'block';
        if (meta) meta.textContent = data.available ? `${rows.length} desk tags` : 'unavailable';
        if (note) note.textContent = data.message || data.note || data.reason || '';
    } catch (err) {
        if (meta) meta.textContent = 'error';
        if (note) note.textContent = err.message || 'HMM unavailable';
        if (empty) empty.style.display = 'block';
    }
}

async function loadComboScan() {
    const meta = document.getElementById('combo-scan-meta');
    const note = document.getElementById('combo-scan-note');
    const tbody = document.getElementById('combo-scan-tbody');
    const empty = document.getElementById('combo-scan-empty');
    if (!tbody) return;
    if (meta) meta.textContent = 'GET /api/hmm/combo…';
    try {
        const data = await apiFetch(`${API}/hmm/combo?desk=1`);
        const rows = Array.isArray(data.rows) ? data.rows : [];
        tbody.innerHTML = '';
        rows.forEach(row => {
            const tr = document.createElement('tr');
            tr.dataset.symbol = row.symbol || '';
            tr.innerHTML = `
                <td class="macro-sym">${row.symbol || ''}</td>
                <td>${row.spy_read || row.spy_state || '—'}</td>
                <td>${row.fragile ? 'FRAGILE' : '—'}</td>
                <td>${(row.setups || []).join(', ') || '—'}</td>
                <td>${(row.flags || []).join(' · ')}</td>
                <td>${row.note || 'AND of real flags'}</td>`;
            tr.addEventListener('click', () => {
                if (row.symbol && typeof selectSymbol === 'function') selectSymbol(row.symbol);
            });
            tbody.appendChild(tr);
        });
        if (empty) {
            empty.style.display = rows.length ? 'none' : 'block';
            const p = empty.querySelector('p');
            if (p && !rows.length) p.textContent = data.reason || 'No combo hits. Empty is honest.';
        }
        if (meta) meta.textContent = `${data.count || 0} AND hits`;
        if (note) note.textContent = data.message || data.note || data.reason || '';
    } catch (err) {
        if (meta) meta.textContent = 'error';
        if (note) note.textContent = err.message || 'Combo unavailable';
        if (empty) empty.style.display = 'block';
    }
}

function bindHmmScan() {
    document.getElementById('btn-hmm-scan')?.addEventListener('click', () => loadHmmScan());
    document.getElementById('hmm-states-n')?.addEventListener('change', () => loadHmmScan());
    document.getElementById('hmm-state-filter')?.addEventListener('change', () => loadHmmScan());
    document.getElementById('hmm-view')?.addEventListener('change', () => loadHmmScan());
    document.getElementById('btn-combo-scan')?.addEventListener('click', () => loadComboScan());
}

window.loadHmmScan = loadHmmScan;
window.loadComboScan = loadComboScan;
window.bindHmmScan = bindHmmScan;
