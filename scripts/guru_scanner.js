/**
 * guru_scanner.js — Multi-strategy "Guru" scanner
 *
 * Strategies (match backend guru_scanner.py):
 *   qullamaggie  VCP breakout: Stage 2, tight base, near pivot, ATR ext < 5×
 *   minervini    Trend Template: 6-condition MA stack
 *   stockbee_4   4% Daily Mover: 1-day gain ≥ 4%
 *   stockbee_20  20% Weekly Mover: 5-day move ≥ 20%
 *   stockbee_9m  9-Million Dollar Mover
 *   canslim      O'Neil L + S + M + N (technical proxy)
 *
 * Integrated as "Guru" mode in the existing scanner.
 * Renders inside #scanner-table with a dedicated strategy-tab header.
 */

// ── State ─────────────────────────────────────────────────────────────────────

const _guruState = {
    strategy: 'qullamaggie',
    data:     null,
};

const _GURU_STRATEGIES = [
    { id: 'qullamaggie', label: 'Qullamaggie',    icon: '🔥', desc: 'VCP breakout setup — Stage 2, tight base, near pivot'          },
    { id: 'minervini',   label: 'Minervini TTM',  icon: '📐', desc: '6-condition Trend Template — MA stack + 52W proximity'         },
    { id: 'stockbee_4',  label: '4% Daily',       icon: '⚡', desc: 'Stocks up ≥ 4% on the day with volume'                         },
    { id: 'stockbee_20', label: '20% Weekly',     icon: '🚀', desc: '5-day move ≥ 20% (either direction) — momentum explosion'       },
    { id: 'stockbee_9m', label: '9M Movers',      icon: '💰', desc: 'Avg 20-day dollar volume > $9M with significant recent move'   },
    { id: 'canslim',     label: "O'Neil CANSLIM", icon: '🏆', desc: 'Leader RS ≥ 70 + Stage 2 + near 52W high + volume'            },
];

// ── Initialise ────────────────────────────────────────────────────────────────

function initGuruScanner() {
    _renderGuruStrategyTabs();
    loadGuruScan(_guruState.strategy);
}

function setGuruStrategy(id) {
    if (_guruState.strategy === id && _guruState.data) return;
    _guruState.strategy = id;
    _guruState.data = null;
    _renderGuruStrategyTabs();
    loadGuruScan(id);
}

// ── Data loading ──────────────────────────────────────────────────────────────

async function loadGuruScan(strategy) {
    const loadEl  = document.getElementById('scanner-loading');
    const btnScan = document.getElementById('btn-scan');
    const tsEl    = document.getElementById('scanner-ts');

    if (loadEl)  loadEl.style.display = 'flex';
    if (btnScan) { btnScan.disabled = true; btnScan.innerHTML = '<span class="spinner"></span> Scanning…'; }

    try {
        const d = await apiFetch(`${API}/guru-scan/${strategy}`);
        _guruState.data = d.rows || [];
        _renderGuruTable(_guruState.strategy, _guruState.data);
        if (tsEl) tsEl.textContent = `Updated ${new Date().toLocaleTimeString()} · ${d.count} match${d.count === 1 ? '' : 'es'}`;
    } catch (e) {
        toast('Guru scan error: ' + e.message, 'error');
    } finally {
        if (loadEl)  loadEl.style.display = 'none';
        if (btnScan) { btnScan.disabled = false; btnScan.innerHTML = '⟳ Scan All'; }
    }
}

// ── Strategy tab bar ─────────────────────────────────────────────────────────

function _renderGuruStrategyTabs() {
    const el = document.getElementById('guru-strategy-tabs');
    if (!el) return;
    el.innerHTML = _GURU_STRATEGIES.map(s =>
        `<button class="guru-tab ${_guruState.strategy === s.id ? 'guru-tab-on' : ''}"
                 title="${s.desc}"
                 onclick="setGuruStrategy('${s.id}')">
            <span class="guru-tab-icon">${s.icon}</span>
            <span class="guru-tab-label">${s.label}</span>
         </button>`
    ).join('');
}

// ── Stage badge helper ─────────────────────────────────────────────────────────

function _stageBadge(stageStr) {
    if (!stageStr) return '<span class="gs-stage gs-stage-na">—</span>';
    const n = parseInt(stageStr[0]);
    const cls = n === 2 ? 'gs-stage-2' : n === 1 ? 'gs-stage-1' : n === 3 ? 'gs-stage-3' : 'gs-stage-4';
    return `<span class="gs-stage ${cls}" title="Weinstein Stage ${stageStr}">${stageStr}</span>`;
}

// ── ATR extension badge ───────────────────────────────────────────────────────

function _extBadge(ext) {
    if (ext == null) return '—';
    const cls = ext >= 4 ? 'gs-ext-red' : ext >= 2.5 ? 'gs-ext-warn' : 'gs-ext-ok';
    return `<span class="gs-ext ${cls}" title="ATR extension from SMA50: ${ext.toFixed(2)}×">${ext.toFixed(1)}×</span>`;
}

// ── R:R badge ─────────────────────────────────────────────────────────────────

function _rrBadge(rr) {
    if (rr == null) return '—';
    const cls = rr >= 3 ? 'gs-rr-good' : rr >= 1.5 ? 'gs-rr-ok' : 'gs-rr-low';
    return `<span class="gs-rr ${cls}">${rr.toFixed(2)}</span>`;
}

// ── Table rendering ───────────────────────────────────────────────────────────

function _renderGuruTable(strategy, rows) {
    const wrap = document.querySelector('.scanner-table-wrap');
    if (!wrap) return;

    if (!rows.length) {
        wrap.innerHTML = `
            <div class="feat-empty" style="margin:40px auto;">
                No matches for this strategy against your watchlist.
                <br><span style="color:var(--text-muted);font-size:11px;">
                    Fetch more OHLCV data or relax the criteria.
                </span>
            </div>`;
        return;
    }

    // Strategy-specific extra columns
    const { head, cell } = _guruExtraCols(strategy);

    const body = rows.map((r, i) => {
        const retCls = (v) => v == null ? '' : v >= 0 ? 'gs-pos' : 'gs-neg';
        const pct    = (v, dec = 1) => v == null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(dec)}%`;

        return `<tr class="gs-row gs-stage${r.stage || 0}-row"
                    style="cursor:pointer"
                    onclick="selectSymbol('${r.symbol}'); switchTab('charts')">
            <td class="gs-sym-cell">
                <strong data-hover-symbol="${r.symbol}">${r.symbol}</strong>
                ${r.tier && r.tier !== 'watchlist'
                    ? `<span class="gs-tier" title="${r.tier}">${{'focus':'🔥','stalk':'🎯','active':'⚡'}[r.tier]||''}</span>`
                    : ''}
            </td>
            <td class="gs-muted">${r.sector || '—'}</td>
            <td>${_stageBadge(r.stage_str)}</td>
            <td class="gs-num">${r.price != null ? '$' + r.price.toFixed(2) : '—'}</td>
            <td class="gs-num">${r.atr_pct != null ? r.atr_pct.toFixed(2) + '%' : '—'}</td>
            <td>${_extBadge(r.atr_ext)}</td>
            ${cell(r)}
            <td>${_rrBadge(r.rr)}</td>
            <td class="gs-actions">
                <button class="jf-act jf-act-fetch" title="Chart"
                    onclick="event.stopPropagation(); selectSymbol('${r.symbol}'); switchTab('charts')">⟶</button>
                <button class="jf-act" title="Alert"
                    onclick="event.stopPropagation(); jeffSetAlert('${r.symbol}', ${r.trigger ?? r.price ?? 'null'})">🔔</button>
                <button class="jf-act" title="Size it"
                    onclick="event.stopPropagation(); jeffSizeIt('${r.symbol}', ${r.trigger ?? r.price ?? 0}, ${r.price ?? 0}, ${r.atr14 ?? 0})">⚖</button>
            </td>
        </tr>`;
    }).join('');

    wrap.innerHTML = `
        <table id="scanner-table" class="feat-table gs-table">
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Sector</th>
                    <th title="Weinstein stage 1–4 with sub-stage A/B/C">Stage</th>
                    <th>Price</th>
                    <th title="ATR-14 as % of price">ATR%</th>
                    <th title="Distance from SMA50 in ATR units — cap at 5×">Ext</th>
                    ${head}
                    <th title="Upside to 52W high / 1.5× ATR stop">R:R</th>
                    <th></th>
                </tr>
            </thead>
            <tbody>${body}</tbody>
        </table>`;
}

function _guruExtraCols(strategy) {
    switch (strategy) {
        case 'qullamaggie':
            return {
                head: `<th title="Trigger = 20-bar high">Trigger</th>
                       <th title="Distance to pivot">Dist%</th>
                       <th title="Volatility contraction ratio (recent/prior range)">VCP</th>`,
                cell: r => `
                    <td class="gs-num">${r.trigger != null ? '$' + r.trigger.toFixed(2) : '—'}</td>
                    <td>
                        <span class="jf-tstat jf-ts-${(r.trigger_status||'').toLowerCase()}">${r.trigger_status || '—'}</span>
                        ${r.trigger_dist_pct != null ? `<span class="gs-muted"> ${r.trigger_dist_pct.toFixed(1)}%</span>` : ''}
                    </td>
                    <td class="gs-num ${r.vcp_ratio < 0.7 ? 'gs-pos' : ''}">${r.vcp_ratio != null ? r.vcp_ratio.toFixed(2) : '—'}</td>`,
            };

        case 'minervini':
            return {
                head: `<th title="Trend Template conditions met (out of 6)">TTM</th>
                       <th title="20-day RS rank within watchlist">RS</th>`,
                cell: r => {
                    const flags = r.ttm_flags || {};
                    const dots  = Object.entries({
                        '>200': flags.above_200,
                        '200↑': flags['200_slope_up'],
                        'Stack': flags.ma_stack,
                        '>50':  flags.above_50,
                        '52H':  flags.near_52hi,
                        '52L':  flags.above_52lo,
                    }).map(([l, v]) =>
                        `<span class="ttm-dot ${v ? 'ttm-dot-on' : 'ttm-dot-off'}" title="${l}">${l[0]}</span>`
                    ).join('');
                    const rsCls = (r.rs_rank || 0) >= 80 ? 'gs-pos' : '';
                    return `<td><div class="ttm-dots">${dots}</div></td>
                            <td class="gs-num ${rsCls}">${r.rs_rank != null ? r.rs_rank + '%ile' : '—'}</td>`;
                },
            };

        case 'stockbee_4':
            return {
                head: `<th title="Today's return">1D</th>
                       <th title="Relative volume">RVOL</th>`,
                cell: r => {
                    const retCls = (r.ret_1d || 0) >= 0 ? 'gs-pos' : 'gs-neg';
                    const rvolCls = (r.rvol || 0) >= 1.5 ? 'jf-rvol-hi' : (r.rvol || 0) >= 1.0 ? 'jf-rvol-ok' : 'jf-rvol-lo';
                    return `<td class="gs-num ${retCls}">${r.ret_1d != null ? (r.ret_1d > 0 ? '+' : '') + r.ret_1d.toFixed(1) + '%' : '—'}</td>
                            <td class="gs-num ${rvolCls}">${r.rvol != null ? r.rvol.toFixed(1) + '×' : '—'}</td>`;
                },
            };

        case 'stockbee_20':
            return {
                head: `<th title="5-day return">5D</th>
                       <th title="Average 20-day dollar volume (M)">$Vol</th>`,
                cell: r => {
                    const retCls = (r.ret_5d || 0) >= 0 ? 'gs-pos' : 'gs-neg';
                    return `<td class="gs-num ${retCls}">${r.ret_5d != null ? (r.ret_5d > 0 ? '+' : '') + r.ret_5d.toFixed(1) + '%' : '—'}</td>
                            <td class="gs-num">${r.avg_dollar_vol != null ? '$' + r.avg_dollar_vol.toFixed(0) + 'M' : '—'}</td>`;
                },
            };

        case 'stockbee_9m':
            return {
                head: `<th title="Average 20-day dollar volume (M)">$Vol</th>
                       <th title="Today's return">1D</th>
                       <th title="Relative volume">RVOL</th>`,
                cell: r => {
                    const retCls = (r.ret_1d || 0) >= 0 ? 'gs-pos' : 'gs-neg';
                    const rvolCls = (r.rvol || 0) >= 1.5 ? 'jf-rvol-hi' : 'jf-rvol-ok';
                    return `<td class="gs-num">${r.avg_dollar_vol != null ? '$' + r.avg_dollar_vol.toFixed(0) + 'M' : '—'}</td>
                            <td class="gs-num ${retCls}">${r.ret_1d != null ? (r.ret_1d > 0 ? '+' : '') + r.ret_1d.toFixed(1) + '%' : '—'}</td>
                            <td class="gs-num ${rvolCls}">${r.rvol != null ? r.rvol.toFixed(1) + '×' : '—'}</td>`;
                },
            };

        case 'canslim':
            return {
                head: `<th title="20-day RS rank">RS</th>
                       <th title="Trigger distance">Trigger</th>`,
                cell: r => {
                    const rsCls  = (r.rs_rank || 0) >= 80 ? 'gs-pos' : '';
                    const tStat  = (r.trigger_status || '').toLowerCase();
                    return `<td class="gs-num ${rsCls}">${r.rs_rank != null ? r.rs_rank + '%ile' : '—'}</td>
                            <td><span class="jf-tstat jf-ts-${tStat}">${r.trigger_status || '—'}</span>
                                ${r.trigger_dist_pct != null ? `<span class="gs-muted"> ${r.trigger_dist_pct.toFixed(1)}%</span>` : ''}
                            </td>`;
                },
            };

        default:
            return { head: '', cell: () => '' };
    }
}

// ── Stage distribution widget ─────────────────────────────────────────────────

async function loadStageDistribution() {
    const el = document.getElementById('guru-stage-dist');
    if (!el) return;
    try {
        const d = await apiFetch(`${API}/stage-distribution`);
        _renderStageDistribution(d, el);
    } catch (_) {}
}

function _renderStageDistribution(d, el) {
    if (!d.total) { el.innerHTML = ''; return; }
    const bars = [1, 2, 3, 4].map(s => {
        const pct  = d.pct[s] || 0;
        const cnt  = d.stage_totals[s] || 0;
        const cls  = s === 2 ? 'gs-dist-2' : s === 1 ? 'gs-dist-1' : s === 3 ? 'gs-dist-3' : 'gs-dist-4';
        const subs = Object.entries(d.counts)
            .filter(([k]) => k.startsWith(String(s)))
            .map(([k, v]) => `<span class="gs-dist-sub">${k}: ${v}</span>`)
            .join('');
        return `<div class="gs-dist-col">
            <div class="gs-dist-bar-wrap" title="Stage ${s}: ${cnt} (${pct}%)">
                <div class="gs-dist-bar ${cls}" style="height:${Math.max(4, pct * 1.8)}px;"></div>
            </div>
            <div class="gs-dist-label">S${s}</div>
            <div class="gs-dist-pct">${pct}%</div>
            <div class="gs-dist-subs">${subs}</div>
        </div>`;
    }).join('');

    el.innerHTML = `
        <div class="gs-dist-title">Stage Distribution <span class="gs-dist-total">(${d.total} symbols)</span></div>
        <div class="gs-dist-bars">${bars}</div>
        <div class="gs-dist-note">
            <span class="gs-dist-2 gs-dist-chip">Stage 2 = uptrend</span>
            <span class="gs-dist-1 gs-dist-chip">Stage 1 = base</span>
            <span class="gs-dist-3 gs-dist-chip">Stage 3 = topping</span>
            <span class="gs-dist-4 gs-dist-chip">Stage 4 = decline</span>
        </div>`;
}
