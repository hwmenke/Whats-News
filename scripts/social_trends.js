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
    data:           null,
    days:           30,
    sources:        { google: true, tiktok: true, twitter: true, instagram: true },
    sortKey:        'score',         // score | catch_up | purity | ret_20d | trend_momentum
    sortDir:        -1,              // -1 = descending
    catchUpOnly:    false,           // ideas where the stock hasn't caught up
    watchlistOnly:  false,           // ideas already in the watchlist
    themeFilter:    null,            // when set, only show ideas for this theme
    moversOnly:     false,           // trend panel: just new/accelerating
    search:         '',              // applies to trends + ideas (free text)
    primed:         false,           // have we already kicked the price sweep?
    primeTimer:     null,            // setInterval id for prime-status polling
    bannerTimer:    null,            // setInterval id for banner auto-refresh
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
    no_data:  { icon: '–',  label: 'No price data',           cls: 'st-nodata'  },
};

// Trend-phase badge metadata (from scoring v2)
const PHASE_META = {
    building: { label: 'building', cls: 'ph-building' },
    peaking:  { label: 'peaking',  cls: 'ph-peaking'  },
    fading:   { label: 'fading',   cls: 'ph-fading'   },
    flat:     { label: 'flat',     cls: 'ph-flat'     },
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
        // Kick the background price sweep once per session so catch-up is
        // populated for ideas the user hasn't explicitly fetched.
        if (!socialState.primed) {
            socialState.primed = true;
            kickPrimePrices().catch(() => {});
        }
    } catch (e) {
        toast('Social trends error: ' + e.message, 'error');
    } finally {
        if (loadEl) loadEl.style.display = 'none';
        if (btn) { btn.disabled = false; btn.innerHTML = '⟳ Scan Trends'; }
    }
}

// Kick the server-side OHLCV sweep + poll its status so the table updates
// as data lands. Bails out gracefully if the API isn't reachable.
async function kickPrimePrices() {
    let res;
    try { res = await apiFetch(`${API}/social-trends/prime`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ limit: 20 }),
    }); } catch (e) { return; }
    if (!res || !res.started) return;
    toast(`Priming prices for ${res.queued} top ideas…`, 'info', 4000);
    renderPrimeBadge({ queued: res.queued, done: 0, failed: 0, running: true });
    if (socialState.primeTimer) clearInterval(socialState.primeTimer);
    socialState.primeTimer = setInterval(async () => {
        try {
            const s = await apiFetch(`${API}/social-trends/prime/status`);
            renderPrimeBadge(s);
            if (!s.running) {
                clearInterval(socialState.primeTimer);
                socialState.primeTimer = null;
                // Refetch with cache (cheap) — DB-backed catch-up will refresh.
                loadSocialTrends(false);
                toast(`Price sweep done: ${s.done} ok, ${s.failed} failed.`, 'success', 3500);
            }
        } catch (e) {
            clearInterval(socialState.primeTimer); socialState.primeTimer = null;
        }
    }, 2500);
}

function renderPrimeBadge(s) {
    const el = document.getElementById('social-prime-badge');
    if (!el) return;
    if (!s.running && (!s.done && !s.failed)) { el.style.display = 'none'; return; }
    el.style.display = 'inline-flex';
    const total = s.queued || (s.done + s.failed);
    const txt = s.running
        ? `Priming prices ${s.done + s.failed}/${total}${s.current ? ' · ' + s.current : ''}`
        : `Priced ${s.done}/${total}`;
    el.innerHTML = `<span class="spinner-mini"></span>${txt}`;
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

    let rows = trends.slice();
    const q = socialState.search.trim().toLowerCase();
    if (q) rows = rows.filter(t => (t.term + ' ' + (t.category||'')).toLowerCase().includes(q));
    if (socialState.moversOnly) rows = rows.filter(t => t.new_today || t.accelerating);

    grid.innerHTML = '';
    if (!rows.length) { if (empty) empty.style.display = 'flex'; return; }
    if (empty) empty.style.display = 'none';

    rows.forEach(t => grid.appendChild(buildTrendCard(t)));
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
            if (e.target.closest('.social-spark-wrap')) return;  // let tooltip work
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
        .map(s => {
            const isDriver = t.driven_by === s;
            const sm = (t.source_mom || {})[s];
            const tip = sm != null ? `${SOURCE_LABELS[s] || s} momentum ${sm}` : (SOURCE_LABELS[s] || s);
            return `<span class="social-src-chip src-${s}${isDriver?' src-driver':''}" title="${tip}">${SOURCE_LABELS[s] || s}${isDriver?' ▸':''}</span>`;
        }).join('');
    const plays = (t.tickers || []).length
        ? `<div class="social-trend-plays">Plays: ${
            t.tickers.map(tk => `<span class="social-play-chip" onclick="socialViewTicker('${tk}')">${tk}</span>`).join(' ')
          }</div>`
        : '';

    // Phase badge + anomaly badges
    const ph = PHASE_META[t.phase] || PHASE_META.flat;
    const phaseChip = `<span class="social-phase-chip ${ph.cls}" title="Phase: ${ph.label}">${ph.label}</span>`;
    const anomalies = [];
    if (t.new_today)    anomalies.push(`<span class="social-anom-chip anom-new" title="Not in yesterday's top movers">🆕 new</span>`);
    if (t.accelerating) anomalies.push(`<span class="social-anom-chip anom-acc" title="Momentum jumped >20% vs 7d ago">🔥 accel</span>`);
    if (t.fading_fast)  anomalies.push(`<span class="social-anom-chip anom-fade" title="Momentum dropped >20% vs 7d ago">💤 fading</span>`);

    card.innerHTML = `
        <div class="social-trend-top">
          <div class="social-trend-term" title="${t.term} — click to drill into history">${t.term}</div>
          <button class="social-explain-btn" onclick="event.stopPropagation(); explainTrend('${(t.term||'').replace(/'/g,"\\'")}')" title="Why is this trending?">?</button>
          <div class="social-trend-chg ${dirCls}">${arrow} ${chg}</div>
        </div>
        <div class="social-trend-badges">${phaseChip}${anomalies.join('')}</div>
        <div class="social-trend-mid">
          <div class="social-spark-wrap" data-series='${JSON.stringify(t.spark || [])}' data-term="${escapeAttr(t.term)}">
            ${sparkline(t.spark || [], 116, 30, sparkCol)}
            <div class="social-spark-tip"></div>
          </div>
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
    if (socialState.themeFilter)   rows = rows.filter(i => i.theme === socialState.themeFilter);
    if (socialState.catchUpOnly)   rows = rows.filter(i => i.status === 'catch_up');
    if (socialState.watchlistOnly) rows = rows.filter(i => i.in_watchlist);
    const q = socialState.search.trim().toLowerCase();
    if (q) rows = rows.filter(i =>
        (i.ticker + ' ' + i.name + ' ' + i.theme).toLowerCase().includes(q));

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
        ? `<button class="si-fetch-now" onclick="socialFetchPrices('${it.ticker}')" title="Fetch OHLCV so catch-up can be computed">Fetch</button>`
        : `<div class="si-cu-bar"><div class="si-cu-fill st-${it.status}" style="width:${cu}%"></div></div>
           <span class="si-cu-val">${cu}</span>`;

    const action = it.in_watchlist
        ? `<button class="social-add-btn in-list" onclick="socialViewTicker('${it.ticker}')" title="Already tracked — open chart">✓ View</button>`
        : `<button class="social-add-btn" onclick="socialAddTicker('${it.ticker}')" title="Add to watchlist & fetch data">+ Add</button>`;

    const themeSafe = it.theme.replace(/'/g, "\\'");
    tr.innerHTML = `
        <td class="si-rank">${rank}</td>
        <td class="si-ticker">
          <span class="si-sym" onclick="socialViewTicker('${it.ticker}')">${it.ticker}</span>
          <span class="si-name">${it.name}</span>
          <div class="si-status">${statusBadge}</div>
          <div class="si-drivers">${drivers}</div>
        </td>
        <td class="si-theme">
          <span class="si-theme-link" onclick="openThemeDrillDown('${themeSafe}')" title="Open theme detail">${it.theme}</span>
          <div class="si-note">${it.note || ''}</div>
        </td>
        <td class="si-purity"><span class="social-pur ${purCls}">${it.purity_label}</span></td>
        <td class="si-score">
          <div class="si-score-bar"><div class="si-score-fill" style="width:${Math.min(100, it.score)}%"></div></div>
          <span class="si-score-val">${it.score.toFixed(0)}</span>
        </td>
        <td class="si-catchup">${cuHtml}</td>
        <td class="si-ret-cell">${retHtml}</td>
        <td class="si-action">
          ${action}
          <button class="social-grp-btn" onclick="socialAddTheme('${themeSafe}')" title="Add all '${it.theme}' pure plays as a watchlist group">+ Theme</button>
          <button class="social-grp-btn" onclick="critiqueIdea('${it.ticker}')" title="Why might this idea be wrong?">? Critique</button>
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

// HTML-attribute escape for term names embedded into data attrs.
function escapeAttr(s) {
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
                    .replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Single delegated mousemove handler — shows the value at the hovered day.
function _initSparkTooltips() {
    const grid = document.getElementById('social-trend-grid');
    if (!grid || grid._tipBound) return;
    grid._tipBound = true;
    grid.addEventListener('mousemove', e => {
        const wrap = e.target.closest('.social-spark-wrap');
        if (!wrap) return;
        const tip = wrap.querySelector('.social-spark-tip');
        if (!tip) return;
        let arr; try { arr = JSON.parse(wrap.dataset.series || '[]'); } catch { arr = []; }
        if (!arr.length) return;
        const r = wrap.getBoundingClientRect();
        const x = Math.max(0, Math.min(r.width, e.clientX - r.left));
        const idx = Math.round((x / r.width) * (arr.length - 1));
        const days = arr.length;
        const ago = days - 1 - idx;
        tip.textContent = `d-${ago}: ${arr[idx]}`;
        tip.style.left = `${x}px`;
        tip.style.display = 'block';
    });
    grid.addEventListener('mouseleave', () => {
        grid.querySelectorAll('.social-spark-tip').forEach(t => t.style.display = 'none');
    }, true);
    // Open drill-down when the term text is clicked.
    grid.addEventListener('click', e => {
        const term = e.target.closest('.social-trend-term');
        if (!term) return;
        const card = term.closest('.social-trend-card');
        const wrap = card && card.querySelector('.social-spark-wrap');
        if (!wrap) return;
        openTermDrillDown(wrap.dataset.term);
    });
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

// ── Search + filter pills (trends & ideas share a single search box) ──
function setSocialSearch(value) {
    socialState.search = value || '';
    if (socialState.data) renderSocialTrends(socialState.data);
}

function toggleMoversOnly() {
    socialState.moversOnly = !socialState.moversOnly;
    const btn = document.getElementById('btn-movers-only');
    if (btn) btn.classList.toggle('social-toggle-on', socialState.moversOnly);
    if (socialState.data) renderTrendGrid(socialState.data.trends || []);
}

function toggleWatchlistOnly() {
    socialState.watchlistOnly = !socialState.watchlistOnly;
    const btn = document.getElementById('btn-watchlist-only');
    if (btn) btn.classList.toggle('social-toggle-on', socialState.watchlistOnly);
    if (socialState.data) renderIdeaTable(socialState.data.ideas || []);
}

// ── Per-row "Fetch now" — pulls OHLCV for a single ticker. ────────────
async function socialFetchPrices(ticker) {
    try {
        toast(`Fetching ${ticker}…`, 'info', 2500);
        await apiFetch(`${API}/fetch/${ticker}`, { method: 'POST' });
        // Refresh the ideas to pick up the new ret_20d / catch_up values.
        await loadSocialTrends(false);
    } catch (e) { toast(`Fetch failed for ${ticker}: ${e.message}`, 'error'); }
}

// ── Banner: auto-refresh every 5 min (uses server cache, ~free). ─────
function startBannerAutoRefresh() {
    if (socialState.bannerTimer) return;
    socialState.bannerTimer = setInterval(() => {
        if (typeof loadTopMovers === 'function') loadTopMovers();
    }, 5 * 60 * 1000);
}

// ── Drill-down modal: full theme detail or term-history view ──────────
function openTermDrillDown(term) {
    const m = ensureSocialModal();
    m.body.innerHTML = `<div class="social-modal-loading">Loading history for <b>${term}</b>…</div>`;
    m.overlay.style.display = 'flex';
    m.title.textContent = `Trend · ${term}`;
    apiFetch(`${API}/social-trends/history?term=${encodeURIComponent(term)}&days=90`)
        .then(d => {
            const rows = d.history || [];
            const series = rows.map(r => r.momentum || 0);
            const sparkSvg = sparkline(series.length >= 2 ? series : [0, 0], 540, 110, 'var(--accent-bright)');
            const latest = rows[rows.length - 1];
            const oldest = rows[0];
            m.body.innerHTML = `
                <div class="dd-spark">${sparkSvg}</div>
                <div class="dd-meta">
                  <div><b>${rows.length}</b> snapshots over the past 90 days</div>
                  ${latest ? `<div>Latest: <b>${latest.date}</b> — momentum ${latest.momentum} (${latest.phase || '—'})</div>` : ''}
                  ${oldest ? `<div>Oldest: <b>${oldest.date}</b> — momentum ${oldest.momentum}</div>` : ''}
                </div>
                <div class="dd-hint">Snapshots accumulate as the app runs daily — keep it open or run a daily cron.</div>`;
        })
        .catch(() => { m.body.innerHTML = '<div class="dd-err">No history yet for this term.</div>'; });
}

async function openThemeDrillDown(theme) {
    const m = ensureSocialModal();
    m.body.innerHTML = `<div class="social-modal-loading">Loading cohort for <b>${theme}</b>…</div>`;
    m.overlay.style.display = 'flex';
    m.title.textContent = `Theme · ${theme}`;
    try {
        const c = await apiFetch(`${API}/social-trends/theme/${encodeURIComponent(theme)}`);
        const memberRows = (c.members || []).map(s => {
            const r5  = s.ret_5d  == null ? '—' : (s.ret_5d  >= 0 ? '+' : '') + s.ret_5d.toFixed(1) + '%';
            const r20 = s.ret_20d == null ? '—' : (s.ret_20d >= 0 ? '+' : '') + s.ret_20d.toFixed(1) + '%';
            return `<tr>
                <td class="dd-sym" onclick="socialViewTicker('${s.ticker}')">${s.ticker}</td>
                <td>${s.name}</td>
                <td>${s.purity_label}</td>
                <td>${r5}</td>
                <td>${r20}</td>
                <td class="dd-note">${s.note || ''}</td>
            </tr>`;
        }).join('');
        const cohort = `Cohort coverage <b>${c.coverage}</b>` +
            (c.avg_ret_20d != null ? ` · avg 20d <b>${c.avg_ret_20d.toFixed(1)}%</b>` : '');
        m.body.innerHTML = `
            <div class="dd-cohort-line">${cohort}</div>
            <table class="dd-table">
              <thead><tr><th>Ticker</th><th>Name</th><th>Purity</th><th>5d</th><th>20d</th><th>Note</th></tr></thead>
              <tbody>${memberRows}</tbody>
            </table>`;
    } catch (e) {
        m.body.innerHTML = `<div class="dd-err">Failed to load cohort: ${e.message}</div>`;
    }
}

function ensureSocialModal() {
    let overlay = document.getElementById('social-modal');
    if (overlay) {
        return {
            overlay,
            title: overlay.querySelector('.social-modal-title'),
            body:  overlay.querySelector('.social-modal-body'),
        };
    }
    overlay = document.createElement('div');
    overlay.id = 'social-modal';
    overlay.className = 'social-modal-overlay';
    overlay.innerHTML = `
        <div class="social-modal-card" role="dialog" aria-modal="true">
          <div class="social-modal-header">
            <span class="social-modal-title"></span>
            <button class="social-modal-close" onclick="closeSocialModal()">×</button>
          </div>
          <div class="social-modal-body"></div>
        </div>`;
    overlay.addEventListener('click', e => { if (e.target === overlay) closeSocialModal(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeSocialModal(); });
    document.body.appendChild(overlay);
    return {
        overlay,
        title: overlay.querySelector('.social-modal-title'),
        body:  overlay.querySelector('.social-modal-body'),
    };
}

function closeSocialModal() {
    const overlay = document.getElementById('social-modal');
    if (overlay) overlay.style.display = 'none';
}

// Patch renderSocialTrends so sparkline tooltips bind on every render.
const _origRenderSocialTrends = renderSocialTrends;
renderSocialTrends = function (d) {
    _origRenderSocialTrends(d);
    _initSparkTooltips();
};
