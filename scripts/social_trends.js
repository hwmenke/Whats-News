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
    data:        null,
    days:        30,
    sources:     { google: true, tiktok: true, twitter: true, instagram: true },
    sortKey:     'score',     // score | catch_up | purity | ret_20d | trend_momentum
    sortDir:     -1,          // -1 = descending
    catchUpOnly: false,       // show only ideas the stock hasn't caught up to
    themeFilter: null,        // when set, only show ideas for this theme
};

const SOURCE_LABELS = {
    google: 'Google', tiktok: 'TikTok', twitter: 'Twitter/X', instagram: 'Instagram',
};

// Catch-up status → badge metadata
const STATUS_META = {
    catch_up: { icon: '🚀', label: 'Trend hot · stock cold', cls: 'st-catchup' },
    moved:    { icon: '✅', label: 'Stock already moved',     cls: 'st-moved'   },
    fading:   { icon: '❄️', label: 'Trend fading',            cls: 'st-fading'  },
    neutral:  { icon: '•',  label: 'In line',                 cls: 'st-neutral' },
    no_data:  { icon: '–',  label: 'No price data — add to fetch', cls: 'st-nodata' },
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
// force=true bypasses the server-side trend cache (re-runs the providers).
async function loadSocialTrends(force = false) {
    const loadEl = document.getElementById('social-loading');
    const btn    = document.getElementById('btn-social-scan');
    if (loadEl) loadEl.style.display = 'flex';
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Scanning…'; }

    const active = Object.keys(socialState.sources).filter(k => socialState.sources[k]);
    const params = new URLSearchParams({ days: socialState.days });
    if (active.length && active.length < 4) params.set('sources', active.join(','));
    if (force) params.set('force', 'true');

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
    if (socialState.themeFilter && t.category === socialState.themeFilter) {
        card.classList.add('social-trend-card-active');
    }
    // Click a card to filter the ideas table to this theme (toggle off on re-click).
    if (t.category && t.category !== '—') {
        card.style.cursor = 'pointer';
        card.title = `Filter ideas → ${t.category}`;
        card.onclick = (e) => {
            if (e.target.closest('.social-play-chip')) return;  // let ticker chips win
            socialState.themeFilter = socialState.themeFilter === t.category ? null : t.category;
            renderSocialTrends(socialState.data);
        };
    }

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

// Sort + filter the ideas, then render. Header toggles update socialState.
function renderIdeaTable(ideas) {
    const tbody = document.getElementById('social-ideas-tbody');
    const empty = document.getElementById('social-ideas-empty');
    if (!tbody) return;

    updateIdeaHeaderSortUI();
    renderThemeFilterChip();

    let rows = ideas.slice();
    if (socialState.themeFilter) rows = rows.filter(i => i.theme === socialState.themeFilter);
    if (socialState.catchUpOnly) rows = rows.filter(i => i.status === 'catch_up');

    const k = socialState.sortKey, dir = socialState.sortDir;
    rows.sort((a, b) => {
        const va = a[k] == null ? -Infinity : a[k];
        const vb = b[k] == null ? -Infinity : b[k];
        return va === vb ? 0 : (va < vb ? -1 : 1) * dir;
    });

    tbody.innerHTML = '';
    if (!rows.length) { if (empty) empty.style.display = 'flex'; return; }
    if (empty) empty.style.display = 'none';
    rows.forEach((it, i) => tbody.appendChild(buildIdeaRow(it, i + 1)));
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

    const sm = STATUS_META[it.status] || STATUS_META.neutral;
    const statusBadge = `<span class="social-status-pill ${sm.cls}" title="${sm.label}">${sm.icon} ${sm.label}</span>`;

    // 20-day stock move
    const ret = it.ret_20d;
    const retHtml = ret == null
        ? `<span class="si-ret-na">—</span>`
        : `<span class="si-ret ${ret >= 0 ? 'ret-up' : 'ret-down'}">${ret >= 0 ? '+' : ''}${ret.toFixed(0)}%</span>`;

    // Catch-up: number + bar (only meaningful when we have price data)
    const cu = it.catch_up;
    const cuHtml = cu == null
        ? `<span class="si-ret-na" title="Add to watchlist to fetch price data">—</span>`
        : `<div class="si-cu-bar"><div class="si-cu-fill st-${it.status}" style="width:${cu}%"></div></div>
           <span class="si-cu-val">${cu}</span>`;

    const action = it.in_watchlist
        ? `<button class="social-add-btn in-list" onclick="socialViewTicker('${it.ticker}')" title="Already tracked — open chart">✓ View</button>`
        : `<button class="social-add-btn" onclick="socialAddTicker('${it.ticker}')" title="Add to watchlist & fetch data">+ Add</button>`;

    tr.innerHTML = `
        <td class="si-rank">${rank}</td>
        <td class="si-ticker">
          <span class="si-sym" onclick="socialViewTicker('${it.ticker}')">${it.ticker}</span>
          <span class="si-name">${it.name}</span>
          <div class="si-status">${statusBadge}</div>
          <div class="si-drivers">${drivers}</div>
        </td>
        <td class="si-theme">${it.theme}<div class="si-note">${it.note || ''}</div></td>
        <td class="si-purity"><span class="social-pur ${purCls}">${it.purity_label}</span></td>
        <td class="si-score">
          <div class="si-score-bar"><div class="si-score-fill" style="width:${Math.min(100, it.score)}%"></div></div>
          <span class="si-score-val">${it.score.toFixed(0)}</span>
        </td>
        <td class="si-catchup">${cuHtml}</td>
        <td class="si-ret-cell">${retHtml}</td>
        <td class="si-action">
          ${action}
          <button class="social-grp-btn" onclick="socialAddTheme('${it.theme.replace(/'/g, "\\'")}')" title="Add all '${it.theme}' pure plays as a watchlist group">+ Theme</button>
        </td>
    `;
    return tr;
}

// ── Ideas table: sort + filter controls ──────────────────────────────
function sortSocialIdeas(key) {
    if (socialState.sortKey === key) socialState.sortDir *= -1;
    else { socialState.sortKey = key; socialState.sortDir = -1; }
    if (socialState.data) renderIdeaTable(socialState.data.ideas || []);
}

function toggleCatchUpOnly() {
    socialState.catchUpOnly = !socialState.catchUpOnly;
    const btn = document.getElementById('btn-catchup-only');
    if (btn) btn.classList.toggle('social-toggle-on', socialState.catchUpOnly);
    if (socialState.data) renderIdeaTable(socialState.data.ideas || []);
}

function updateIdeaHeaderSortUI() {
    document.querySelectorAll('#social-ideas-table th[data-sort]').forEach(th => {
        const active = th.dataset.sort === socialState.sortKey;
        th.classList.toggle('si-sort-active', active);
        const ind = th.querySelector('.si-sort-ind');
        if (ind) ind.textContent = active ? (socialState.sortDir < 0 ? ' ▼' : ' ▲') : '';
    });
}

function renderThemeFilterChip() {
    const el = document.getElementById('social-theme-filter');
    if (!el) return;
    if (!socialState.themeFilter) { el.innerHTML = ''; el.style.display = 'none'; return; }
    el.style.display = 'inline-flex';
    el.innerHTML = `Theme: <strong>${socialState.themeFilter}</strong>
        <span class="social-filter-x" onclick="clearThemeFilter()" title="Clear filter">×</span>`;
}

function clearThemeFilter() {
    socialState.themeFilter = null;
    renderSocialTrends(socialState.data);
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

// Add every pure-play for a theme as a tagged watchlist group.
async function socialAddTheme(theme) {
    const ideas = (socialState.data && socialState.data.ideas) || [];
    const tickers = [...new Set(ideas.filter(i => i.theme === theme).map(i => i.ticker))];
    if (!tickers.length) { toast('No tickers for that theme', 'warning'); return; }
    try {
        await apiFetch(`${API}/symbols/bulk`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbols: tickers, group_tag: theme }),
        });
        toast(`Added ${tickers.length} '${theme}' plays as a group`, 'success');
        ideas.forEach(i => { if (i.theme === theme) i.in_watchlist = true; });
        renderIdeaTable(ideas);
        if (typeof loadSymbols === 'function') await loadSymbols();
    } catch (e) {
        toast('Error: ' + e.message, 'error');
    }
}

// ── Top-movers banner (always-visible topbar strip) ───────────────────
async function loadTopMovers() {
    const strip = document.getElementById('topmovers');
    if (!strip) return;
    try {
        const d = await apiFetch(`${API}/social-trends/top?limit=6`);
        const movers = d.movers || [];
        if (!movers.length) { strip.style.display = 'none'; return; }
        strip.style.display = 'flex';
        strip.innerHTML =
            `<span class="tm-label" onclick="switchTab('social')" title="Open Social Trends">🔥 Trending</span>` +
            movers.map(m => {
                const dirCls = m.direction === 'rising' ? 'dir-up'
                             : m.direction === 'falling' ? 'dir-down' : 'dir-flat';
                const arrow  = m.direction === 'rising' ? '▲' : m.direction === 'falling' ? '▼' : '◆';
                const chg    = (m.change_pct >= 0 ? '+' : '') + Math.round(m.change_pct) + '%';
                const tk     = (m.tickers || [])[0];
                const tkHtml = tk ? `<span class="tm-tk" onclick="socialViewTicker('${tk}')" title="Open ${tk}">${tk}</span>` : '';
                return `<span class="tm-item" onclick="switchTab('social')">
                          <span class="tm-term">${m.term}</span>
                          <span class="tm-chg ${dirCls}">${arrow}${chg}</span>${tkHtml}
                        </span>`;
            }).join('');
    } catch (e) {
        strip.style.display = 'none';   // stay quiet if the feed isn't available
    }
}
