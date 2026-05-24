/**
 * social_trends.js — Social-media trend radar + pure-play stock ideas
 *
 * Pulls aggregated movers from Google / TikTok / Twitter / Instagram (via
 * /api/social-trends) and renders two panels:
 *   • Trending Words  — biggest 30d movers, each with a sparkline + momentum.
 *   • Pure-Play Ideas — the listed stocks most concentrated on each theme,
 *                       ranked by purity × trend momentum.
 */

const socialState = {
    data:    null,
    days:    30,
    sources: { google: true, tiktok: true, twitter: true, instagram: true },
};

const SOURCE_LABELS = {
    google: 'Google', tiktok: 'TikTok', twitter: 'Twitter/X', instagram: 'Instagram',
};

// ── Controls ──────────────────────────────────────────────────────────
function setSocialDays(days) {
    socialState.days = days;
    document.querySelectorAll('.social-days-btn').forEach(b =>
        b.classList.toggle('social-toggle-on', Number(b.dataset.days) === days));
    loadSocialTrends();
}

function toggleSocialSource(id) {
    socialState.sources[id] = !socialState.sources[id];
    // Never allow zero sources selected — re-enable if user turned the last one off.
    if (!Object.values(socialState.sources).some(Boolean)) socialState.sources[id] = true;
    document.querySelectorAll('.social-src-btn').forEach(b =>
        b.classList.toggle('social-toggle-on', socialState.sources[b.dataset.src]));
    loadSocialTrends();
}

// ── Data loading ──────────────────────────────────────────────────────
async function loadSocialTrends() {
    const loadEl = document.getElementById('social-loading');
    const btn    = document.getElementById('btn-social-scan');
    if (loadEl) loadEl.style.display = 'flex';
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Scanning…'; }

    const active = Object.keys(socialState.sources).filter(k => socialState.sources[k]);
    const params = new URLSearchParams({ days: socialState.days });
    if (active.length && active.length < 4) params.set('sources', active.join(','));

    try {
        const data = await apiFetch(`${API}/social-trends?${params.toString()}`);
        socialState.data = data;
        renderSocialTrends(data);
    } catch (e) {
        toast('Social trends error: ' + e.message, 'error');
    } finally {
        if (loadEl) loadEl.style.display = 'none';
        if (btn) { btn.disabled = false; btn.innerHTML = '⟳ Scan Trends'; }
    }
}

// ── Render ────────────────────────────────────────────────────────────
function renderSocialTrends(d) {
    renderSocialStatus(d);
    renderTrendGrid(d.trends || []);
    renderIdeaTable(d.ideas || []);
}

function renderSocialStatus(d) {
    const el = document.getElementById('social-status');
    if (!el) return;
    const badges = (d.sources || []).map(s => {
        const cls = s.live ? 'social-badge-live' : 'social-badge-seed';
        const tag = s.live ? 'LIVE' : 'SEED';
        return `<span class="social-badge ${cls}" title="${s.count} terms">${s.name}: ${tag}</span>`;
    }).join('');
    const when = d.generated_at ? new Date(d.generated_at).toLocaleTimeString() : '';
    const note = d.any_live ? '' :
        `<span class="social-seed-note">Showing curated sample data — add API keys / run locally for live feeds.</span>`;
    el.innerHTML =
        `<div class="social-badges">${badges}</div>` +
        `<div class="social-status-right">${note}<span class="scanner-ts">${d.lookback_days}d · updated ${when}</span></div>`;
}

function renderTrendGrid(trends) {
    const grid  = document.getElementById('social-trend-grid');
    const empty = document.getElementById('social-trend-empty');
    if (!grid) return;
    grid.innerHTML = '';
    if (!trends.length) { if (empty) empty.style.display = 'flex'; return; }
    if (empty) empty.style.display = 'none';

    trends.forEach(t => grid.appendChild(buildTrendCard(t)));
}

function buildTrendCard(t) {
    const card = document.createElement('div');
    card.className = 'social-trend-card';

    const dirCls   = t.direction === 'rising' ? 'dir-up'
                   : t.direction === 'falling' ? 'dir-down' : 'dir-flat';
    const arrow    = t.direction === 'rising' ? '▲' : t.direction === 'falling' ? '▼' : '◆';
    const sparkCol = t.direction === 'falling' ? 'var(--red)'
                   : t.direction === 'flat' ? 'var(--text-muted)' : 'var(--green)';
    const chg = (t.change_pct >= 0 ? '+' : '') + Math.round(t.change_pct) + '%';

    const srcChips = (t.sources || [])
        .map(s => `<span class="social-src-chip src-${s}">${SOURCE_LABELS[s] || s}</span>`).join('');
    const plays = (t.tickers || []).length
        ? `<div class="social-trend-plays">Plays: ${
            t.tickers.map(tk => `<span class="social-play-chip" onclick="socialViewTicker('${tk}')">${tk}</span>`).join(' ')
          }</div>`
        : '';

    card.innerHTML = `
        <div class="social-trend-top">
          <div class="social-trend-term" title="${t.term}">${t.term}</div>
          <div class="social-trend-chg ${dirCls}">${arrow} ${chg}</div>
        </div>
        <div class="social-trend-mid">
          ${sparkline(t.spark || [], 116, 30, sparkCol)}
          <div class="social-mom-block">
            <div class="social-mom-label">momentum</div>
            <div class="social-mom-bar"><div class="social-mom-fill ${dirCls}" style="width:${t.momentum}%"></div></div>
            <div class="social-mom-val">${t.momentum}</div>
          </div>
        </div>
        <div class="social-trend-bot">
          <div class="social-src-chips">${srcChips}</div>
          <div class="social-trend-cat">${t.category || '—'}</div>
        </div>
        ${plays}
    `;
    return card;
}

function renderIdeaTable(ideas) {
    const tbody = document.getElementById('social-ideas-tbody');
    const empty = document.getElementById('social-ideas-empty');
    if (!tbody) return;
    tbody.innerHTML = '';
    if (!ideas.length) { if (empty) empty.style.display = 'flex'; return; }
    if (empty) empty.style.display = 'none';

    ideas.forEach((it, i) => tbody.appendChild(buildIdeaRow(it, i + 1)));
}

function buildIdeaRow(it, rank) {
    const tr = document.createElement('tr');
    tr.className = 'social-idea-row';

    const purCls = it.purity >= 0.85 ? 'pur-pure'
                 : it.purity >= 0.65 ? 'pur-high'
                 : it.purity >= 0.45 ? 'pur-mod' : 'pur-low';

    const drivers = (it.drivers || []).slice(0, 3)
        .map(dv => `<span class="social-driver" title="${dv.change_pct >= 0 ? '+' : ''}${Math.round(dv.change_pct)}% · momentum ${dv.momentum}">${dv.term}</span>`)
        .join('');

    const action = it.in_watchlist
        ? `<button class="social-add-btn in-list" onclick="socialViewTicker('${it.ticker}')" title="Already tracked — open chart">✓ View</button>`
        : `<button class="social-add-btn" onclick="socialAddTicker('${it.ticker}')" title="Add to watchlist & fetch data">+ Add</button>`;

    tr.innerHTML = `
        <td class="si-rank">${rank}</td>
        <td class="si-ticker">
          <span class="si-sym" onclick="socialViewTicker('${it.ticker}')">${it.ticker}</span>
          <span class="si-name">${it.name}</span>
          <div class="si-drivers">${drivers}</div>
        </td>
        <td class="si-theme">${it.theme}<div class="si-note">${it.note || ''}</div></td>
        <td class="si-purity"><span class="social-pur ${purCls}">${it.purity_label}</span></td>
        <td class="si-mom">${it.trend_momentum}</td>
        <td class="si-score">
          <div class="si-score-bar"><div class="si-score-fill" style="width:${Math.min(100, it.score)}%"></div></div>
          <span class="si-score-val">${it.score.toFixed(0)}</span>
        </td>
        <td class="si-action">${action}</td>
    `;
    return tr;
}

// ── Inline SVG sparkline ──────────────────────────────────────────────
function sparkline(arr, w, h, color) {
    if (!arr || arr.length < 2) return `<svg class="social-spark" width="${w}" height="${h}"></svg>`;
    const min = Math.min(...arr), max = Math.max(...arr);
    const rng = (max - min) || 1;
    const pad = 2;
    const step = (w - pad * 2) / (arr.length - 1);
    const pts = arr.map((v, i) => {
        const x = pad + i * step;
        const y = h - pad - ((v - min) / rng) * (h - pad * 2);
        return `${x.toFixed(1)},${y.toFixed(1)}`;
    });
    const line = pts.join(' ');
    const area = `${pad},${h - pad} ${line} ${(pad + (arr.length - 1) * step).toFixed(1)},${h - pad}`;
    const id = 'sg' + Math.random().toString(36).slice(2, 8);
    return `<svg class="social-spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
        <defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="${color}" stop-opacity="0.30"/>
          <stop offset="100%" stop-color="${color}" stop-opacity="0"/>
        </linearGradient></defs>
        <polygon points="${area}" fill="url(#${id})"/>
        <polyline points="${line}" fill="none" stroke="${color}" stroke-width="1.6"
                  stroke-linejoin="round" stroke-linecap="round"/>
      </svg>`;
}

// ── Ticker actions (reuse app.js watchlist plumbing) ──────────────────
function socialViewTicker(ticker) {
    if (typeof state === 'object' && state) state.activeSymbol = ticker;
    if (typeof switchTab === 'function')       switchTab('charts');   // loads the chart
    else if (typeof selectSymbol === 'function') selectSymbol(ticker);
    if (typeof renderSymbolList === 'function') renderSymbolList();
}

async function socialAddTicker(ticker) {
    try {
        await apiFetch(`${API}/symbols`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: ticker }),
        });
        toast(`${ticker} added to watchlist`, 'success');
        if (typeof fetchSymbolData === 'function') await fetchSymbolData(ticker);
        if (typeof loadSymbols === 'function')     await loadSymbols();
        // Reflect new watchlist state in the ideas table without a full re-scan.
        if (socialState.data) {
            (socialState.data.ideas || []).forEach(i => { if (i.ticker === ticker) i.in_watchlist = true; });
            renderIdeaTable(socialState.data.ideas);
        }
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}
