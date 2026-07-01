// ════════════════════════════════════════════════════════════
// regime.js — Market regime + breadth dashboard
// ════════════════════════════════════════════════════════════

const REGIME_CLASS = {
    Offensive:    'rg-offensive',
    Constructive: 'rg-constructive',
    Choppy:       'rg-choppy',
    Defensive:    'rg-defensive',
    Unknown:      'rg-unknown',
};

async function loadRegime() {
    const body = document.getElementById('regime-body');
    body.innerHTML = `<p style="color:#888;">Computing regime…</p>`;
    let r;
    try { r = await apiFetch(`${API}/regime`); }
    catch (e) { body.innerHTML = `<p style="color:#e66;">${e.message}</p>`; return; }
    renderRegime(r);
}

function rgFmt(v, dp = 1) { return (v == null) ? '—' : Number(v).toFixed(dp); }

function renderRegime(r) {
    const body = document.getElementById('regime-body');
    const cls = REGIME_CLASS[r.regime] || 'rg-unknown';
    const s = r.suggested || {};

    let banner = `<div class="regime-banner ${cls}">
        <div class="regime-label">${r.regime}</div>
        <div class="regime-sub">${r.reason ? r.reason : 'Index score ' + r.index_score}</div>
        <div class="regime-suggest">
            Suggested exposure <b>${s.exposure_pct}%</b> ·
            max risk/trade <b>${s.max_risk_pct}%</b> ·
            max positions <b>${s.max_positions}</b>
        </div>
    </div>`;

    // Index cards
    let idx = '<div class="regime-cards">';
    for (const sym of Object.keys(r.index || {})) {
        const ix = r.index[sym];
        if (!ix) { idx += `<div class="regime-card muted"><h4>${sym}</h4><div>no data</div></div>`; continue; }
        idx += `<div class="regime-card">
            <h4>${sym} <span class="${ix.score > 0 ? 'pos' : ix.score < 0 ? 'neg' : ''}">score ${ix.score}</span></h4>
            <div>Price ${rgFmt(ix.price, 2)}</div>
            <div>SMA50 ${rgFmt(ix.sma50, 2)} ${ix.above_50 ? '✅' : '❌'}</div>
            <div>SMA200 ${rgFmt(ix.sma200, 2)} ${ix.above_200 ? '✅' : '❌'}</div>
            <div>50-MA slope ${ix.slope50_up ? '↑ up' : '↓ down'}</div>
        </div>`;
    }
    idx += '</div>';

    // Breadth
    const b = r.breadth || {};
    let breadth = '';
    if (b.total) {
        const gauge = (lbl, pct) => `<div class="bg-row">
            <span class="bg-lbl">${lbl}</span>
            <span class="bg-track"><span class="bg-fill" style="width:${pct}%;"></span></span>
            <span class="bg-val">${rgFmt(pct)}%</span></div>`;
        breadth = `<div class="regime-breadth">
            <h3>Breadth (${b.total} symbols)</h3>
            ${gauge('% above 20-MA', b.pct_above_20)}
            ${gauge('% above 50-MA', b.pct_above_50)}
            ${gauge('% above 200-MA', b.pct_above_200)}
            <div class="breadth-counts">
                <span class="pos">↑ 4%+ on vol: <b>${b.up4_count}</b></span>
                <span class="neg">↓ 4%+ on vol: <b>${b.down4_count}</b></span>
                <span>New highs: <b>${b.new_highs}</b></span>
            </div>
        </div>`;
    } else {
        breadth = `<p style="color:#888;">No breadth data — fetch your watchlist first.</p>`;
    }

    body.innerHTML = banner + idx + breadth;
}
