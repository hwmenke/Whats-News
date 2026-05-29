/**
 * features.js — New feature implementations:
 *   News feed, Sector heatmap, Multi-symbol Compare chart,
 *   Signals dashboard, Export/Import, Risk calculator, Options chain.
 */

// ── Area visibility helpers ───────────────────────────────────────────────────
const ALL_AREAS = [
    'empty-state','chart-area','stats-area','knn-area','backtest-area',
    'trend-area','scanner-area','data-manager-area','portfolio-area',
    'news-area','sector-area','compare-area','signals-area',
    'regime-area','journal-area','analytics-area','pair-area','mtf-area',
    'calendar-area','strategy-area',
];

function showArea(id) {
    ALL_AREAS.forEach(a => {
        const el = document.getElementById(a);
        if (el) el.style.display = 'none';
    });
    const target = document.getElementById(id);
    if (target) target.style.display = 'block';
    const tabBar = document.querySelector('.tab-bar');
    if (tabBar) tabBar.style.display = 'none';
}

// ── News ──────────────────────────────────────────────────────────────────────
async function loadNews(symbol) {
    const sym  = symbol || state.activeSymbol;
    const list = document.getElementById('news-list');
    const lbl  = document.getElementById('news-sym-label');
    if (!list) return;
    if (lbl)  lbl.textContent = sym || '--';
    list.innerHTML = '<div class="news-loading"><span class="spinner"></span> Loading…</div>';
    try {
        const articles = await apiFetch(`${API}/news/${sym}`);
        renderNews(articles);
    } catch (e) {
        list.innerHTML = `<div style="color:var(--red); padding:16px;">Failed: ${e.message}</div>`;
    }
}

function renderNews(articles) {
    const list = document.getElementById('news-list');
    if (!articles.length) {
        list.innerHTML = '<div style="color:var(--text-muted); padding:16px;">No headlines found.</div>';
        return;
    }
    list.innerHTML = articles.map(a => {
        const sentClass = a.sentiment > 0 ? 'sentiment-bull' : a.sentiment < 0 ? 'sentiment-bear' : 'sentiment-neutral';
        const sentDot   = `<span class="sentiment-dot ${sentClass}" title="${a.sentiment > 0 ? 'Bullish' : a.sentiment < 0 ? 'Bearish' : 'Neutral'}"></span>`;
        return `
        <a class="news-item" href="${a.link}" target="_blank" rel="noopener">
          <div class="news-item-header">
            ${sentDot}
            <span class="news-source">${a.source || 'Yahoo Finance'}</span>
            <span class="news-date">${_fmtPubDate(a.pub_date)}</span>
          </div>
          <div class="news-title">${_esc(a.title)}</div>
          ${a.summary ? `<div class="news-summary">${_esc(a.summary)}</div>` : ''}
        </a>`;
    }).join('');
}

function _fmtPubDate(s) {
    if (!s) return '';
    try {
        return new Date(s).toLocaleString('en-US', {
            month: 'short', day: 'numeric',
            hour: '2-digit', minute: '2-digit', hour12: false,
        });
    } catch { return s; }
}

function _esc(s) {
    return (s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// ── Sector Heatmap ────────────────────────────────────────────────────────────
async function loadSectorHeatmap() {
    const container = document.getElementById('sector-heatmap-container');
    if (!container) return;
    container.innerHTML = '<div style="color:var(--text-muted); padding:16px;"><span class="spinner"></span> Loading…</div>';
    try {
        const data = await apiFetch(`${API}/sector-heatmap`);
        renderSectorHeatmap(data);
    } catch (e) {
        container.innerHTML = `<div style="color:var(--red);">Failed: ${e.message}</div>`;
    }
}

function renderSectorHeatmap(sectors) {
    const container = document.getElementById('sector-heatmap-container');
    if (!sectors.length) { container.innerHTML = '<div style="padding:16px; color:var(--text-muted);">No data.</div>'; return; }

    const colorCell = v => {
        if (v === null || !isFinite(v)) return 'background:var(--bg-secondary); color:var(--text-dim)';
        const pct = v * 100;
        const intensity = Math.min(Math.abs(pct) / 5, 1);
        if (pct >= 0) return `background:rgba(34,197,94,${(intensity * 0.6).toFixed(2)}); color:${intensity > 0.5 ? '#fff' : 'var(--text-primary)'}`;
        return `background:rgba(239,68,68,${(intensity * 0.6).toFixed(2)}); color:${intensity > 0.5 ? '#fff' : 'var(--text-primary)'}`;
    };
    const fmtPct = v => v !== null && isFinite(v) ? (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%' : '–';

    let html = '<div class="sector-grid">';
    for (const sector of sectors) {
        html += `
          <div class="sector-card">
            <div class="sector-card-header">
              <span class="sector-card-name">${_esc(sector.sector)}</span>
              <span class="sector-card-count">${sector.count} symbols</span>
            </div>
            <div class="sector-card-summary">
              <span style="${colorCell(sector.avg_1d)}" class="sector-perf-chip">1D ${fmtPct(sector.avg_1d)}</span>
              <span style="${colorCell(sector.avg_5d)}" class="sector-perf-chip">5D ${fmtPct(sector.avg_5d)}</span>
              <span style="${colorCell(sector.avg_20d)}" class="sector-perf-chip">20D ${fmtPct(sector.avg_20d)}</span>
              <span style="${colorCell(sector.avg_ytd)}" class="sector-perf-chip">YTD ${fmtPct(sector.avg_ytd)}</span>
            </div>
            <details class="sector-symbols-details">
              <summary class="sector-symbols-toggle">Show symbols</summary>
              <table class="sector-sym-table">
                <thead><tr><th>Symbol</th><th>Close</th><th>1D</th><th>5D</th><th>20D</th><th>YTD</th></tr></thead>
                <tbody>
                  ${sector.symbols.map(s => `
                    <tr style="cursor:pointer;" onclick="selectSymbol('${s.symbol}')">
                      <td><strong>${s.symbol}</strong></td>
                      <td>$${s.close.toFixed(2)}</td>
                      <td style="${colorCell(s.ret_1d)}">${fmtPct(s.ret_1d)}</td>
                      <td style="${colorCell(s.ret_5d)}">${fmtPct(s.ret_5d)}</td>
                      <td style="${colorCell(s.ret_20d)}">${fmtPct(s.ret_20d)}</td>
                      <td style="${colorCell(s.ret_ytd)}">${fmtPct(s.ret_ytd)}</td>
                    </tr>`).join('')}
                </tbody>
              </table>
            </details>
          </div>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

// ── Compare Chart ─────────────────────────────────────────────────────────────
let _compareChart = null;
let _compareSeries = {};
const COMPARE_COLORS = ['#3b82f6','#f97316','#22c55e','#a855f7','#ef4444','#06b6d4','#eab308','#ec4899'];

async function loadCompare() {
    const input = document.getElementById('compare-symbols-input');
    const freq  = document.getElementById('compare-freq')?.value || 'daily';
    if (!input) return;

    const syms = input.value.split(/[\s,;]+/).map(s => s.trim().toUpperCase()).filter(s => /^[A-Z]/.test(s));
    if (syms.length < 2) { toast('Enter at least 2 symbols to compare', 'warning'); return; }

    const legend = document.getElementById('compare-legend');
    if (legend) legend.innerHTML = '<span class="spinner"></span>';

    // Destroy existing chart
    if (_compareChart) { _compareChart.remove(); _compareChart = null; _compareSeries = {}; }

    try {
        const datasets = await Promise.all(syms.slice(0, 8).map(s =>
            apiFetch(`${API}/ohlcv/${s}?freq=${freq}&limit=500`).catch(() => null)
        ));

        const chartEl = document.getElementById('compare-chart');
        _compareChart = LightweightCharts.createChart(chartEl, {
            width: chartEl.clientWidth, height: chartEl.clientHeight,
            layout: { background: { color: '#0d1117' }, textColor: '#8b949e', fontFamily: "'JetBrains Mono', monospace", fontSize: 10 },
            grid: { vertLines: { color: '#1c2230' }, horzLines: { color: '#1c2230' } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            rightPriceScale: { borderColor: '#30363d' },
            timeScale: { borderColor: '#30363d', timeVisible: true, secondsVisible: false },
        });

        const legendItems = [];
        syms.slice(0, 8).forEach((sym, idx) => {
            const rows = datasets[idx];
            if (!rows || !rows.length) return;

            const base = rows[0].close;
            if (!base || base === 0) return;

            const color = COMPARE_COLORS[idx % COMPARE_COLORS.length];
            const series = _compareChart.addLineSeries({ color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true });
            series.setData(rows.map(r => ({ time: r.date, value: parseFloat(((r.close / base) * 100).toFixed(3)) })));
            _compareSeries[sym] = series;

            const lastVal = rows[rows.length - 1].close;
            const chg     = ((lastVal / base) - 1) * 100;
            legendItems.push({ sym, color, chg });
        });

        if (legend) {
            legend.innerHTML = legendItems.map(l => `
                <span class="compare-legend-item" style="border-color:${l.color}">
                  <span style="color:${l.color}; font-weight:700;">${l.sym}</span>
                  <span style="color:${l.chg >= 0 ? '#22c55e' : '#ef4444'}">${l.chg >= 0 ? '+' : ''}${l.chg.toFixed(2)}%</span>
                </span>`).join('');
        }

        _compareChart.timeScale().fitContent();

        // Performance statistics table
        renderCompareStats(syms.slice(0, 8), datasets, freq);

        new ResizeObserver(entries => {
            for (const e of entries) {
                const { width, height } = e.contentRect;
                if (_compareChart) _compareChart.resize(width, height);
            }
        }).observe(chartEl);

    } catch (e) {
        toast('Compare failed: ' + e.message, 'error');
        if (legend) legend.innerHTML = '';
    }
}

// Compute & render Sharpe / CAGR / drawdown / win-rate per symbol
function renderCompareStats(syms, datasets, freq) {
    const card  = document.getElementById('compare-stats-card');
    const tbody = document.getElementById('compare-stats-tbody');
    if (!card || !tbody) return;

    const periodsPerYear = freq === 'weekly' ? 52 : 252;
    const fmtPct = v => (v != null && isFinite(v)) ? (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%' : '—';
    const col    = v => (v != null && isFinite(v) && v >= 0) ? 'color:#22c55e' : 'color:#ef4444';

    const rows = [];
    syms.forEach((sym, idx) => {
        const data = datasets[idx];
        if (!data || data.length < 3) return;

        const closes = data.map(r => r.close).filter(c => c > 0);
        if (closes.length < 3) return;

        // Daily/weekly simple returns
        const rets = [];
        for (let i = 1; i < closes.length; i++) rets.push(closes[i] / closes[i - 1] - 1);

        const totalRet = closes[closes.length - 1] / closes[0] - 1;
        const years    = closes.length / periodsPerYear;
        const cagr     = years > 0 ? Math.pow(1 + totalRet, 1 / years) - 1 : null;

        const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
        const variance = rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length;
        const std  = Math.sqrt(variance);
        const annVol = std * Math.sqrt(periodsPerYear);
        const sharpe = std > 0 ? (mean / std) * Math.sqrt(periodsPerYear) : null;

        // Max drawdown
        let peak = closes[0], maxDD = 0;
        for (const c of closes) {
            if (c > peak) peak = c;
            const dd = c / peak - 1;
            if (dd < maxDD) maxDD = dd;
        }

        const winRate = rets.filter(r => r > 0).length / rets.length;

        rows.push({ sym, totalRet, cagr, annVol, sharpe, maxDD, winRate });
    });

    if (!rows.length) { card.style.display = 'none'; return; }

    tbody.innerHTML = rows.map(r => `
        <tr>
          <td><strong style="cursor:pointer" onclick="selectSymbol('${r.sym}')">${r.sym}</strong></td>
          <td style="${col(r.totalRet)}">${fmtPct(r.totalRet)}</td>
          <td style="${col(r.cagr)}">${fmtPct(r.cagr)}</td>
          <td>${r.annVol != null ? (r.annVol * 100).toFixed(1) + '%' : '—'}</td>
          <td style="${col(r.sharpe)}">${r.sharpe != null ? r.sharpe.toFixed(2) : '—'}</td>
          <td style="color:#ef4444">${fmtPct(r.maxDD)}</td>
          <td>${(r.winRate * 100).toFixed(0)}%</td>
        </tr>`).join('');
    card.style.display = 'block';
}

// ── Signals Dashboard ─────────────────────────────────────────────────────────
async function loadSignals() {
    const tbody  = document.getElementById('signals-tbody');
    const kpiRow = document.getElementById('signals-kpi-row');
    if (!tbody) return;
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding:20px;"><span class="spinner"></span> Scanning…</td></tr>';

    try {
        const [signals, anomalies] = await Promise.all([
            apiFetch(`${API}/signals`),
            document.getElementById('signals-anomalies-toggle')?.checked
                ? apiFetch(`${API}/anomalies`)
                : Promise.resolve([]),
        ]);

        renderSignals(signals, anomalies);
    } catch (e) {
        toast('Signals failed: ' + e.message, 'error');
        tbody.innerHTML = `<tr><td colspan="8" style="color:var(--red);">${e.message}</td></tr>`;
    }
}

function renderSignals(signals, anomalies = []) {
    const thead  = document.getElementById('signals-thead');
    const tbody  = document.getElementById('signals-tbody');
    const kpiRow = document.getElementById('signals-kpi-row');

    // Anomaly lookup by symbol
    const anomalyMap = {};
    for (const a of anomalies) {
        anomalyMap[a.symbol] = a.flags || [];
    }

    if (thead) thead.innerHTML = `<tr>
        <th>Symbol</th><th>Close</th><th>RSI</th><th>MACD</th><th>BB%</th><th>Vol Z</th><th>Signals</th><th>Score</th>
    </tr>`;

    const scoreColor = s => s > 1 ? '#22c55e' : s < -1 ? '#ef4444' : 'var(--text-muted)';
    const rsiColor   = r => r > 70 ? '#ef4444' : r < 30 ? '#22c55e' : 'var(--text-muted)';
    const fmtPct = v => (v * 100).toFixed(1) + '%';

    if (!signals.length) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--text-muted); padding:20px;">No data — scan your watchlist first.</td></tr>';
        return;
    }

    // KPI row
    const bullCount = signals.filter(s => s.score > 0).length;
    const bearCount = signals.filter(s => s.score < 0).length;
    const neutCount = signals.length - bullCount - bearCount;
    if (kpiRow) {
        kpiRow.innerHTML = `
            <div class="kpi-card"><div class="kpi-label">Total</div><div class="kpi-value">${signals.length}</div></div>
            <div class="kpi-card"><div class="kpi-label">Bullish</div><div class="kpi-value" style="color:#22c55e">${bullCount}</div></div>
            <div class="kpi-card"><div class="kpi-label">Bearish</div><div class="kpi-value" style="color:#ef4444">${bearCount}</div></div>
            <div class="kpi-card"><div class="kpi-label">Neutral</div><div class="kpi-value">${neutCount}</div></div>
        `;
    }

    tbody.innerHTML = signals.map(r => {
        const anomalyFlags = anomalyMap[r.symbol] || [];
        const signalPills  = r.signals.map(s =>
            `<span class="signal-pill ${s.bull === true ? 'bull' : s.bull === false ? 'bear' : 'neutral'}">${s.label}</span>`
        ).join('');
        const anomalyPills = anomalyFlags.map(f =>
            `<span class="signal-pill anomaly">${f.label}</span>`
        ).join('');

        return `<tr style="cursor:pointer;" onclick="selectSymbol('${r.symbol}')">
            <td><strong>${r.symbol}</strong><br><span style="font-size:10px; color:var(--text-dim);">${_esc(r.name)}</span></td>
            <td>$${r.close.toFixed(2)}</td>
            <td style="color:${rsiColor(r.rsi14)}">${r.rsi14.toFixed(1)}</td>
            <td style="color:${r.macd >= 0 ? '#22c55e' : '#ef4444'}">${r.macd >= 0 ? '+' : ''}${r.macd.toFixed(4)}</td>
            <td>${fmtPct(r.bb_pct)}</td>
            <td style="color:${Math.abs(r.vol_z) > 2 ? '#f97316' : 'var(--text-muted)'}">${r.vol_z >= 0 ? '+' : ''}${r.vol_z.toFixed(1)}σ</td>
            <td>${signalPills}${anomalyPills}</td>
            <td style="font-weight:700; color:${scoreColor(r.score)}">${r.score > 0 ? '+' : ''}${r.score}</td>
        </tr>`;
    }).join('');
}

// ── Regime Dashboard ──────────────────────────────────────────────────────────
let _regimeCache = [];

async function loadRegime() {
    const freq    = document.getElementById('regime-freq')?.value || 'daily';
    const loading = document.getElementById('regime-loading');
    const grid    = document.getElementById('regime-grid');
    if (loading) loading.style.display = 'block';
    if (grid)    grid.innerHTML = '';
    try {
        const data = await apiFetch(`${API}/trend-scan?freq=${freq}&method=kama`);
        _regimeCache = Array.isArray(data) ? data : [];
        renderRegimeFromCache();
    } catch (e) {
        toast('Regime load failed: ' + e.message, 'error');
    } finally {
        if (loading) loading.style.display = 'none';
    }
}

function renderRegimeFromCache() {
    const grid    = document.getElementById('regime-grid');
    const summary = document.getElementById('regime-summary');
    if (!grid) return;

    const sortVal = document.getElementById('regime-sort')?.value || 'signal_desc';
    const rows = _regimeCache.filter(r => !r.error);

    rows.sort((a, b) => {
        switch (sortVal) {
            case 'signal_asc':  return (a.signal ?? 0) - (b.signal ?? 0);
            case 'rsi_desc':    return (b.rsi ?? 0) - (a.rsi ?? 0);
            case 'rsi_asc':     return (a.rsi ?? 0) - (b.rsi ?? 0);
            case 'symbol':      return a.symbol.localeCompare(b.symbol);
            default:            return (b.signal ?? 0) - (a.signal ?? 0);
        }
    });

    // Summary KPIs
    if (summary) {
        const buckets = { 3:0, 2:0, 1:0, 0:0, '-1':0, '-2':0, '-3':0 };
        rows.forEach(r => { const s = r.signal ?? 0; if (buckets[s] !== undefined) buckets[s]++; });
        const strongBull = buckets[3] + buckets[2];
        const strongBear = buckets['-3'] + buckets['-2'];
        const neutral    = buckets[0] + buckets[1] + buckets['-1'];
        summary.innerHTML = `
            <div class="kpi-card"><div class="kpi-label">Symbols</div><div class="kpi-value">${rows.length}</div></div>
            <div class="kpi-card"><div class="kpi-label">Bullish (≥+2)</div><div class="kpi-value" style="color:#22c55e">${strongBull}</div></div>
            <div class="kpi-card"><div class="kpi-label">Bearish (≤−2)</div><div class="kpi-value" style="color:#ef4444">${strongBear}</div></div>
            <div class="kpi-card"><div class="kpi-label">Neutral</div><div class="kpi-value">${neutral}</div></div>`;
    }

    if (!rows.length) {
        grid.innerHTML = '<div style="padding:32px; text-align:center; color:var(--text-muted);">No data — fetch watchlist symbols first.</div>';
        return;
    }

    const sigMap = {
         3: ['STRONG LONG', '#16a34a'],  2: ['LONG', '#22c55e'],  1: ['LEAN LONG', '#86efac'],
         0: ['NEUTRAL', '#6b7280'],
        '-1': ['LEAN SHORT', '#fca5a5'], '-2': ['SHORT', '#ef4444'], '-3': ['STRONG SHORT', '#dc2626'],
    };
    const arrow = s => s > 0 ? '▲' : s < 0 ? '▼' : '–';
    const arrowColor = s => s > 0 ? '#22c55e' : s < 0 ? '#ef4444' : '#6b7280';

    grid.innerHTML = rows.map(r => {
        const sig = r.signal ?? 0;
        const [label, color] = sigMap[String(sig)] || ['—', '#6b7280'];
        const rsiC = r.rsi == null ? '#6b7280' : r.rsi > 70 ? '#ef4444' : r.rsi < 30 ? '#22c55e' : 'var(--text-muted)';
        return `<div class="regime-cell" style="border-left:4px solid ${color};" onclick="selectSymbol('${r.symbol}')">
            <div class="regime-cell-head">
                <span class="regime-sym">${r.symbol}</span>
                <span class="regime-badge" style="background:${color}22; color:${color};">${label}</span>
            </div>
            <div class="regime-states">
                <span title="Short">S <strong style="color:${arrowColor(r.short_state)}">${arrow(r.short_state)}</strong></span>
                <span title="Medium">M <strong style="color:${arrowColor(r.medium_state)}">${arrow(r.medium_state)}</strong></span>
                <span title="Long">L <strong style="color:${arrowColor(r.long_state)}">${arrow(r.long_state)}</strong></span>
            </div>
            <div class="regime-meta">
                <span>$${r.price?.toFixed(2) ?? '–'}</span>
                <span style="color:${rsiC}">RSI ${r.rsi?.toFixed(0) ?? '–'}</span>
                <span>R:R ${r.rr ?? '–'}</span>
            </div>
        </div>`;
    }).join('');
}

// ── Export / Import ───────────────────────────────────────────────────────────
async function exportWatchlist() {
    try {
        const data = await apiFetch(`${API}/export`);
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href     = url;
        a.download = `findash-export-${new Date().toISOString().slice(0,10)}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        toast('Watchlist exported', 'success');
    } catch (e) {
        toast('Export failed: ' + e.message, 'error');
    }
}

async function importWatchlist(input) {
    const file = input.files[0];
    if (!file) return;
    try {
        const text = await file.text();
        const data = JSON.parse(text);
        const res  = await apiFetch(`${API}/import`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        toast(`Imported ${res.imported} symbols`, 'success');
        await loadSymbols();
    } catch (e) {
        toast('Import failed: ' + e.message, 'error');
    } finally {
        input.value = '';
    }
}

// ── Risk Calculator ───────────────────────────────────────────────────────────
function openRiskModal(symbol) {
    const sym = symbol || state.activeSymbol;
    if (!sym) { toast('Select a symbol first', 'warning'); return; }
    document.getElementById('risk-symbol-label').textContent = sym;
    document.getElementById('risk-results').innerHTML = '';
    document.getElementById('risk-modal').style.display = 'flex';
}

function closeRiskModal() {
    document.getElementById('risk-modal').style.display = 'none';
}

async function calculateRisk() {
    const sym     = document.getElementById('risk-symbol-label').textContent;
    const account = document.getElementById('risk-account').value;
    const riskPct = document.getElementById('risk-pct').value;
    const atrMult = document.getElementById('risk-atr-mult').value;
    const results = document.getElementById('risk-results');
    results.innerHTML = '<span class="spinner"></span>';
    try {
        const d = await apiFetch(`${API}/risk/${sym}?account=${account}&risk_pct=${riskPct}&atr_mult=${atrMult}`);
        results.innerHTML = `
            <table class="backtest-table" style="margin-top:12px; width:100%">
              <tbody>
                <tr><td>Price</td><td>$${d.price.toFixed(2)}</td></tr>
                <tr><td>ATR (14)</td><td>${d.atr14.toFixed(3)}</td></tr>
                <tr><td>Stop Loss</td><td style="color:#ef4444">$${d.stop_loss.toFixed(2)} (–${(d.stop_pct*100).toFixed(2)}%)</td></tr>
                <tr><td>TP1 (1.5R)</td><td style="color:#22c55e">$${d.tp1.toFixed(2)}</td></tr>
                <tr><td>TP2 (3R)</td><td style="color:#22c55e">$${d.tp2.toFixed(2)}</td></tr>
                <tr><td>Shares</td><td><strong>${d.shares}</strong></td></tr>
                <tr><td>Position Size</td><td><strong>$${d.position_size.toFixed(2)}</strong></td></tr>
                <tr><td>Risk Amount</td><td style="color:#f97316">$${d.risk_amount.toFixed(2)}</td></tr>
                ${d.ann_vol !== null ? `<tr><td>Ann. Vol</td><td>${(d.ann_vol*100).toFixed(1)}%</td></tr>` : ''}
                <tr><td>Kelly (rough)</td><td>${(d.kelly*100).toFixed(1)}%</td></tr>
              </tbody>
            </table>`;
    } catch (e) {
        results.innerHTML = `<div style="color:var(--red);">Failed: ${e.message}</div>`;
    }
}

// ── Options Chain ─────────────────────────────────────────────────────────────
let _optionsSymbol = null;

async function openOptionsModal(symbol) {
    const sym = symbol || state.activeSymbol;
    if (!sym) { toast('Select a symbol first', 'warning'); return; }
    _optionsSymbol = sym;
    document.getElementById('options-symbol-label').textContent = sym;
    document.getElementById('options-modal').style.display = 'flex';
    await loadOptions();
}

function closeOptionsModal() {
    document.getElementById('options-modal').style.display = 'none';
}

async function loadOptions() {
    const expiry  = document.getElementById('options-expiry-select')?.value || '';
    const metaEl  = document.getElementById('options-meta');
    const callsTb = document.getElementById('options-calls-tbody');
    const putsTb  = document.getElementById('options-puts-tbody');
    if (!callsTb) return;
    callsTb.innerHTML = '<tr><td colspan="8"><span class="spinner"></span></td></tr>';
    putsTb.innerHTML  = callsTb.innerHTML;
    try {
        const url = `${API}/options/${_optionsSymbol}` + (expiry ? `?expiry=${expiry}` : '');
        const d   = await apiFetch(url);

        // Populate expiry select
        const sel = document.getElementById('options-expiry-select');
        if (sel && d.expirations.length) {
            sel.innerHTML = d.expirations.map(e => `<option value="${e}" ${e === d.expiry ? 'selected' : ''}>${e}</option>`).join('');
        }
        if (metaEl) {
            metaEl.textContent = `P/C Ratio: ${d.pc_ratio ?? '–'} · Max Pain: ${d.max_pain ? '$' + d.max_pain : '–'}`;
        }

        const row = r => `<tr>
            <td>${r.strike}</td><td>$${r.last.toFixed(2)}</td>
            <td>$${r.bid.toFixed(2)}</td><td>$${r.ask.toFixed(2)}</td>
            <td>${r.volume.toLocaleString()}</td><td>${r.oi.toLocaleString()}</td>
            <td>${(r.iv * 100).toFixed(1)}%</td>
            <td style="color:${r.itm ? '#22c55e' : 'var(--text-dim)'};">${r.itm ? '✓' : '–'}</td>
        </tr>`;

        callsTb.innerHTML = (d.calls || []).map(row).join('') || '<tr><td colspan="8" style="color:var(--text-muted);">No data</td></tr>';
        putsTb.innerHTML  = (d.puts  || []).map(row).join('') || '<tr><td colspan="8" style="color:var(--text-muted);">No data</td></tr>';
    } catch (e) {
        const msg = `<tr><td colspan="8" style="color:var(--red);">${e.message}</td></tr>`;
        callsTb.innerHTML = putsTb.innerHTML = msg;
    }
}
