// ════════════════════════════════════════════════════════════
// momentum.js — Momentum setup scanner UI (4 setups + grading)
// ════════════════════════════════════════════════════════════

let momData = [];

const SETUP_LABELS = {
    continuation:   'Continuation',
    momentum_burst: 'Momentum Burst',
    episodic_pivot: 'Episodic Pivot',
    parabolic:      'Parabolic',
};
const GRADE_RANK = { 'A+': 3, 'A': 2, 'B': 1 };

async function loadMomentumScan() {
    const t = document.getElementById('mom-table');
    t.innerHTML = `<tbody><tr><td style="padding:20px;color:#888;">Scanning watchlist…</td></tr></tbody>`;
    try {
        momData = await apiFetch(`${API}/momentum-scan`);
    } catch (e) {
        t.innerHTML = `<tbody><tr><td style="padding:20px;color:#e66;">${e.message}</td></tr></tbody>`;
        return;
    }
    renderMomentum();
}

function momFmt(v, dp = 2) { return (v == null) ? '—' : Number(v).toFixed(dp); }

function gradeBadge(g) {
    const cls = g === 'A+' ? 'g-aplus' : g === 'A' ? 'g-a' : 'g-b';
    return `<span class="grade-badge ${cls}">${g}</span>`;
}

function renderMomentum() {
    const setupF = document.getElementById('mom-setup').value;
    const gradeF = document.getElementById('mom-grade').value;
    const minRank = gradeF ? GRADE_RANK[gradeF] : 0;
    const t = document.getElementById('mom-table');

    const rows = [];
    momData.forEach(r => {
        if (r.error || !r.setups) return;
        let setups = r.setups;
        if (setupF) setups = setups.filter(s => s.type === setupF);
        if (gradeF) setups = setups.filter(s => GRADE_RANK[s.grade] >= minRank);
        if (!setups.length) return;
        rows.push({ ...r, _setups: setups, _best: setups[0] });
    });

    if (!rows.length) {
        t.innerHTML = `<tbody><tr><td style="padding:20px;color:#888;">No candidates match the filter. Try ↻ Rescan after fetching data.</td></tr></tbody>`;
        return;
    }
    rows.sort((a, b) => (GRADE_RANK[b._best.grade] - GRADE_RANK[a._best.grade]) || (b._best.score - a._best.score));

    const head = `<thead><tr>
        <th>Symbol</th><th>Best</th><th>Setups</th><th>Price</th><th>ADR%</th>
        <th>1M%</th><th>3M%</th><th>Vol×</th><th>Gap%</th><th>RSI</th><th>Up d</th><th>From Hi%</th>
      </tr></thead>`;
    const cls = v => v == null ? '' : (v > 0 ? 'pos' : (v < 0 ? 'neg' : ''));
    const body = rows.map(r => {
        const m = r.metrics;
        const setups = r._setups.map(s =>
            `${gradeBadge(s.grade)} ${SETUP_LABELS[s.type] || s.type} <span class="mom-score">${s.score}</span>`
        ).join('<br>');
        return `<tr>
            <td><b>${r.symbol}</b><br><button class="btn btn-ghost btn-sm" onclick="addToJournalFromScan('${r.symbol}','${SETUP_LABELS[r._best.type] || r._best.type}',${m.price})">＋ Journal</button></td>
            <td>${gradeBadge(r._best.grade)}</td>
            <td style="text-align:left;">${setups}</td>
            <td>${momFmt(m.price)}</td>
            <td>${momFmt(m.adr_pct, 1)}</td>
            <td class="${cls(m.perf_1m)}">${momFmt(m.perf_1m, 1)}</td>
            <td class="${cls(m.perf_3m)}">${momFmt(m.perf_3m, 1)}</td>
            <td>${momFmt(m.vol_ratio, 1)}</td>
            <td class="${cls(m.gap_pct)}">${momFmt(m.gap_pct, 1)}</td>
            <td>${momFmt(m.rsi14, 0)}</td>
            <td>${m.up_days == null ? '—' : m.up_days}</td>
            <td class="${cls(m.dist_from_high)}">${momFmt(m.dist_from_high, 1)}</td>
        </tr>`;
    }).join('');
    t.innerHTML = head + `<tbody>${body}</tbody>`;
}
