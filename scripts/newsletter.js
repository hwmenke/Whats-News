/**
 * newsletter.js — Daily Edge Newsletter Tab
 *
 * Patches the global switchTab() from app.js to handle the newsletter tab,
 * fetches /api/newsletter/data, and renders chart cards via Chart.js.
 */

// ── Section metadata ──────────────────────────────────────────
const NL_SECTIONS = {
    rates:     'Rates & Fixed Income',
    equities:  'Equities',
    fx:        'FX & Currency',
    commodity: 'Commodities',
    em:        'Emerging Markets',
    credit:    'Credit',
    vol:       'Volatility',
    macro:     'Macro',
};

const NL_SECTION_ORDER = ['rates', 'equities', 'fx', 'commodity', 'em', 'credit', 'vol', 'macro'];

// ── Module state ──────────────────────────────────────────────
let nlState = {
    loading: false,
    charts:  {},   // chartId -> Chart.js instance
};

// Register annotation plugin (CDN auto-registers, but be explicit)
if (window.Chart && window.ChartAnnotation) {
    try { Chart.register(window.ChartAnnotation); } catch (_) {}
}

// ── Native tab entry point (app.js switchTab dispatches here) ──
function initNewsletter() {
    loadNewsletterData();
    _nlLoadMorningBrief();
    _nlLoadSetups();
    _nlLoadBreakoutWatch();
}

// ── Morning Brief ─────────────────────────────────────────────
async function _nlLoadMorningBrief() {
    const set = (id, val, cls) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.textContent = val;
        if (cls) el.className = `nl-brief-value ${cls}`;
    };

    try {
        const breadth = await apiFetch(`${API}/breadth`).catch(() => null);
        if (breadth) {
            const pct20 = breadth.pct_above_20ma ?? null;
            const pct50 = breadth.pct_above_50ma ?? null;
            const hl    = `${breadth.new_highs ?? 0} / ${breadth.new_lows ?? 0}`;
            const ad    = breadth.ad_ratio != null ? breadth.ad_ratio.toFixed(2) : '—';
            set('nl-brief-20ma', pct20 != null ? `${pct20}%` : '—',
                pct20 >= 60 ? 'nl-bull' : pct20 <= 30 ? 'nl-bear' : '');
            set('nl-brief-50ma', pct50 != null ? `${pct50}%` : '—',
                pct50 >= 60 ? 'nl-bull' : pct50 <= 30 ? 'nl-bear' : '');
            set('nl-brief-hl',  hl);
            set('nl-brief-ad',  ad, parseFloat(ad) >= 1 ? 'nl-bull' : 'nl-bear');
        }
    } catch (_) {}

    try {
        const regime = await apiFetch(`${API}/market-regime`).catch(() => null);
        if (regime && regime.current) {
            const state = regime.current.state || '—';
            const score = regime.current.score ?? '';
            const cls   = state.toLowerCase().includes('bull') ? 'nl-bull'
                        : state.toLowerCase().includes('bear') ? 'nl-bear' : '';
            set('nl-brief-regime-val', `${state}${score !== '' ? ` (${score}/10)` : ''}`, cls);
        }
    } catch (_) {}
}

// ── Best Setups ───────────────────────────────────────────────
async function _nlLoadSetups() {
    const $grid = document.getElementById('nl-setups-grid');
    if (!$grid) return;
    $grid.innerHTML = '<div class="nl-setup-loading">Loading setups…</div>';
    try {
        const data = await apiFetch(`${API}/jeff-scan`).catch(() => null);
        const rows = (data?.rows || [])
            .filter(r => !r.error && r.grade)
            .sort((a, b) => (b.opp_score ?? 0) - (a.opp_score ?? 0))
            .slice(0, 8);
        if (!rows.length) {
            $grid.innerHTML = '<div class="nl-setup-empty">No graded setups. Fetch data and run scanner first.</div>';
            return;
        }
        $grid.innerHTML = rows.map(r => {
            const g    = (r.grade || '').toUpperCase();
            const gCls = g === 'A' ? 'grade-a' : g === 'B' ? 'grade-b' : 'grade-c';
            const chk  = r.checks || {};
            const gates = [
                chk.rvol ? '✓ RVOL' : '✗ RVOL',
                chk.ext  ? '✓ EXT'  : '✗ EXT',
                chk.kama ? '✓ KAMA' : '✗ KAMA',
                chk.vcp  ? '✓ VCP'  : '',
            ].filter(Boolean).join('  ');
            const distStr = r.trigger_dist_pct != null
                ? `${r.trigger_dist_pct > 0 ? '+' : ''}${r.trigger_dist_pct.toFixed(1)}% to trigger`
                : '';
            return `<div class="nl-setup-card" onclick="selectSymbol('${_esc(r.symbol)}');switchTab('charts');">
                <div class="nl-setup-top">
                    <strong class="nl-setup-sym">${_esc(r.symbol)}</strong>
                    <span class="nl-setup-grade ${gCls}">${g}</span>
                    <span class="nl-setup-sector">${_esc(r.sector || '')}</span>
                </div>
                <div class="nl-setup-pattern">${_esc(r.pattern || '—')}</div>
                <div class="nl-setup-dist">${_esc(distStr)}</div>
                <div class="nl-setup-gates">${_esc(gates)}</div>
                <div class="nl-setup-score">Score ${r.opp_score ?? 0} · Ready ${r.readiness ?? 0}/5</div>
            </div>`;
        }).join('');
    } catch (e) {
        $grid.innerHTML = `<div class="nl-setup-empty">Could not load setups: ${_esc(e.message)}</div>`;
    }
}

// ── Breakout Watch (pipeline candidates near trigger) ─────────
async function _nlLoadBreakoutWatch() {
    const $section = document.getElementById('nl-bb-section');
    const $grid    = document.getElementById('nl-bb-grid');
    if (!$section || !$grid) return;
    try {
        const data = await apiFetch(`${API}/breakout-board`).catch(() => null);
        const rows = (data?.rows || [])
            .filter(r => !r.error && ['TRIGGERED','BREAKING','AT PIVOT','NEAR'].includes(r.status))
            .slice(0, 6);
        if (!rows.length) return;   // hide section if nothing near trigger

        $section.style.display = '';
        $grid.innerHTML = rows.map(r => {
            const statusCls = {
                TRIGGERED: 'bb-triggered', BREAKING: 'bb-breaking',
                'AT PIVOT': 'bb-at', NEAR: 'bb-near',
            }[r.status] || '';
            const distStr = r.dist_pct != null ? `${r.dist_pct.toFixed(1)}% away` : '';
            return `<div class="nl-setup-card" onclick="selectSymbol('${_esc(r.symbol)}');switchTab('charts');">
                <div class="nl-setup-top">
                    <strong class="nl-setup-sym">${_esc(r.symbol)}</strong>
                    <span class="nl-setup-grade ${statusCls}">${_esc(r.status)}</span>
                    <span class="nl-setup-sector">${_esc(r.tier || '')}</span>
                </div>
                <div class="nl-setup-pattern">Pivot: $${r.pivot != null ? r.pivot.toFixed(2) : '—'} (${_esc(r.pivot_source || '')})</div>
                <div class="nl-setup-dist">${_esc(distStr)}</div>
                <div class="nl-setup-gates">${r.pocket_pivot ? '✓ PP ' : ''}${r.vol_dryup ? '✓ DU ' : ''}${r.too_extended ? '⚠ EXT ' : ''}${r.lod_too_far ? '⚠ LoD' : ''}</div>
            </div>`;
        }).join('');
    } catch (_) {}
}

// ── Main loader ───────────────────────────────────────────────
async function loadNewsletterData() {
    if (nlState.loading) return;
    nlState.loading = true;
    // Refresh all sections in parallel
    _nlLoadMorningBrief();
    _nlLoadSetups();
    _nlLoadBreakoutWatch();

    const $loading = document.getElementById('newsletter-loading');
    const $error   = document.getElementById('nl-error');
    const $empty   = document.getElementById('nl-empty');
    const $grid    = document.getElementById('nl-chart-grid');
    const $lead    = document.getElementById('nl-lead-stories');
    const $btn     = document.getElementById('btn-nl-refresh');

    if ($loading) $loading.style.display = 'flex';
    if ($error)   $error.style.display   = 'none';
    if ($empty)   $empty.style.display   = 'none';
    if ($grid)    $grid.innerHTML        = '';
    if ($lead)    $lead.innerHTML        = '';
    if ($btn)     $btn.disabled          = true;

    // Destroy existing Chart.js instances to free memory
    Object.values(nlState.charts).forEach(c => { try { c.destroy(); } catch (_) {} });
    nlState.charts = {};

    try {
        const data = await apiFetch('/api/newsletter/data');

        if (data.error) {
            _nlShowError(data.error);
            return;
        }

        const charts = data.charts || [];
        if (!charts.length) {
            if ($empty) $empty.style.display = 'flex';
            return;
        }

        // Update header
        const $edition = document.getElementById('nl-edition');
        const $count   = document.getElementById('nl-universe-count');
        if ($edition) $edition.textContent = data.edition_date ? `Edition: ${data.edition_date}` : '';
        if ($count)   $count.textContent   = `${data.total_symbols || 0} symbols`;

        // Lead stories: top 5 by interest score
        const sorted = [...charts].sort((a, b) => (b.interest_score || 0) - (a.interest_score || 0));
        _nlRenderLeadStories(sorted.slice(0, 5));

        // Full chart grid
        _nlRenderChartGrid(charts);

    } catch (e) {
        _nlShowError(e.message || 'Unexpected error');
    } finally {
        nlState.loading = false;
        if ($loading) $loading.style.display = 'none';
        if ($btn)     $btn.disabled          = false;
    }
}

function _nlShowError(msg) {
    const $e = document.getElementById('nl-error');
    const $m = document.getElementById('nl-error-msg');
    if ($e) $e.style.display = 'flex';
    if ($m) $m.textContent   = msg;
}

// ── Lead stories ──────────────────────────────────────────────
function _nlRenderLeadStories(charts) {
    const $c = document.getElementById('nl-lead-stories');
    if (!$c) return;
    $c.innerHTML = '';

    charts.forEach((c, i) => {
        const el       = document.createElement('div');
        el.className   = 'nl-lead-card';
        const secLabel = NL_SECTIONS[c.asset_class] || c.asset_class || '';
        const scorePct = Math.min(100, Math.round((c.interest_score || 0) * 10));
        const chgCls   = _nlChgClass(c.chg);

        el.innerHTML = `
            <div class="nl-lead-rank">#${i + 1}</div>
            <div class="nl-lead-body">
                <div class="nl-lead-section-badge">${_esc(secLabel)}</div>
                <div class="nl-lead-title">${_esc(c.label || c.symbol)}</div>
                <div class="nl-lead-subtitle">${_esc(c.subtitle || '')}</div>
                <div class="nl-lead-kpi">
                    <span class="nl-kpi-last">${_esc(c.last || '--')}</span>
                    <span class="nl-kpi-chg ${chgCls}">${_esc(c.chg || '')}</span>
                </div>
            </div>
            <div class="nl-lead-score-wrap">
                <div class="nl-score-label">Score</div>
                <div class="nl-score-bar-outer">
                    <div class="nl-score-bar-inner" style="width:${scorePct}%"></div>
                </div>
                <div class="nl-score-num">${(c.interest_score || 0).toFixed(1)}</div>
            </div>
        `;
        $c.appendChild(el);
    });
}

// ── Chart grid ────────────────────────────────────────────────
function _nlRenderChartGrid(charts) {
    const $c = document.getElementById('nl-chart-grid');
    if (!$c) return;
    $c.innerHTML = '';

    // Group by asset_class
    const sections = {};
    charts.forEach(c => {
        const ac = c.asset_class || 'other';
        (sections[ac] = sections[ac] || []).push(c);
    });

    const keys = [
        ...NL_SECTION_ORDER.filter(k => sections[k]),
        ...Object.keys(sections).filter(k => !NL_SECTION_ORDER.includes(k)),
    ];

    // Collect {chartId, config} for batch init after DOM is ready
    const toInit = [];

    keys.forEach(ac => {
        const group = sections[ac];
        if (!group || !group.length) return;

        // Section header
        const hdr = document.createElement('div');
        hdr.className = 'nl-section-header';
        hdr.innerHTML = `
            <span class="nl-section-badge nl-badge-${_esc(ac)}">${_esc(NL_SECTIONS[ac] || ac)}</span>
            <span class="nl-section-count">${group.length} chart${group.length !== 1 ? 's' : ''}</span>
        `;
        $c.appendChild(hdr);

        // Cards grid
        const grid = document.createElement('div');
        grid.className = 'nl-cards-grid';

        group.forEach((c, idx) => {
            const chartId = _nlChartId(c.symbol, ac, idx);
            grid.appendChild(_nlBuildCard(c, chartId));
            if (c.chartjs_config) toInit.push({ chartId, config: c.chartjs_config });
        });

        $c.appendChild(grid);
    });

    // Init all Chart.js instances after layout pass
    requestAnimationFrame(() => {
        toInit.forEach(({ chartId, config }) => {
            const canvas = document.getElementById(chartId);
            if (!canvas) return;
            try {
                nlState.charts[chartId] = new Chart(canvas, config);
            } catch (e) {
                console.error('[Daily Edge] Chart init failed:', chartId, e);
            }
        });
    });
}

function _nlBuildCard(c, chartId) {
    const card      = document.createElement('div');
    card.className  = 'nl-chart-card';

    const scorePct  = Math.min(100, Math.round((c.interest_score || 0) * 10));
    const chgCls    = _nlChgClass(c.chg);
    const typeLabel = (c.chart_type || 'line').replace(/_/g, ' ');

    // Metric badges
    const badges = [];
    if (c.rsi_14         != null)                   badges.push(`RSI ${c.rsi_14.toFixed(0)}`);
    if (c.pct_rank_1y    != null)                   badges.push(`${(c.pct_rank_1y * 100).toFixed(0)}th %ile`);
    if (c.streak         != null && c.streak !== 0) badges.push(`${c.streak > 0 ? '+' : ''}${c.streak}d streak`);
    if (c.realized_vol_1m != null)                  badges.push(`Vol ${(c.realized_vol_1m * 100).toFixed(1)}%`);
    if (c.current_dd_1y  != null && c.current_dd_1y < -0.005)
                                                    badges.push(`DD ${(c.current_dd_1y * 100).toFixed(1)}%`);

    const badgesHtml = badges.map(b => `<span class="nl-badge">${_esc(b)}</span>`).join('');

    card.innerHTML = `
        <div class="nl-card-header">
            <div class="nl-card-type-badge">${_esc(typeLabel)}</div>
            <div class="nl-card-score">
                <div class="nl-score-bar-outer sm">
                    <div class="nl-score-bar-inner" style="width:${scorePct}%"></div>
                </div>
                <span>${(c.interest_score || 0).toFixed(1)}</span>
            </div>
        </div>
        <div class="nl-card-title">${_esc(c.label || c.symbol)}</div>
        <div class="nl-card-subtitle">${_esc(c.subtitle || '')}</div>
        <div class="nl-card-kpi">
            <span class="nl-kpi-last">${_esc(c.last || '--')}</span>
            <span class="nl-kpi-chg ${chgCls}">${_esc(c.chg || '')}</span>
            <span class="nl-kpi-date">${_esc(c.date_last || '')}</span>
        </div>
        <div class="nl-canvas-wrap">
            <canvas id="${chartId}"></canvas>
        </div>
        <div class="nl-card-badges">${badgesHtml}</div>
    `;

    return card;
}

// ── Helpers ───────────────────────────────────────────────────
function _nlChartId(symbol, ac, idx) {
    return `nlc_${(symbol || '').replace(/[^a-zA-Z0-9]/g, '_')}_${ac}_${idx}`;
}

function _nlChgClass(chgStr) {
    const s = String(chgStr || '').trim();
    if (s.startsWith('+')) return 'nl-pos';
    if (s.startsWith('-')) return 'nl-neg';
    return '';
}

function _esc(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}
