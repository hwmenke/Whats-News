/**
 * command_palette.js — Cmd+K command palette with fuzzy search.
 * Searches symbols, tabs, and actions.
 */

const CMD_TABS = [
    { label: 'Charts',        icon: '📈', action: () => switchTab('charts')       },
    { label: 'Statistics',    icon: '📊', action: () => switchTab('stats')        },
    { label: 'KNN Lookalike', icon: '🤖', action: () => switchTab('knn')         },
    { label: 'Backtest',      icon: '⚙️', action: () => switchTab('backtest')    },
    { label: 'Adaptive Trend',icon: '🎯', action: () => switchTab('trend')       },
    { label: 'Scanner',       icon: '📡', action: () => switchTab('scanner')     },
    { label: 'Data Manager',  icon: '🗄️', action: () => switchTab('data-manager')},
    { label: 'Portfolio',     icon: '💼', action: () => switchTab('portfolio')   },
    { label: 'News',          icon: '📰', action: () => switchTab('news')        },
    { label: 'Sector Heatmap',icon: '🗺️', action: () => switchTab('sector')     },
    { label: 'Compare Chart', icon: '⚖️', action: () => switchTab('compare')    },
    { label: 'Signals',       icon: '📶', action: () => switchTab('signals')     },
];

const CMD_ACTIONS = [
    { label: 'Refresh All',      icon: '⟳',  action: () => refreshAll()            },
    { label: 'Add Symbol',       icon: '+',   action: () => { closeCommandPalette(); document.getElementById('new-symbol-input')?.focus(); }},
    { label: 'Export Watchlist', icon: '⬇',  action: () => exportWatchlist()       },
    { label: 'Import Watchlist', icon: '⬆',  action: () => document.getElementById('import-file-input')?.click() },
    { label: 'View Alerts',      icon: '🔔',  action: () => openAlertsModal()       },
    { label: 'Risk Calculator',  icon: '📐',  action: () => openRiskModal()         },
    { label: 'Options Chain',    icon: '📋',  action: () => openOptionsModal()      },
    { label: 'Toggle Theme',     icon: '🌙',  action: () => toggleTheme()           },
    { label: 'Run Scanner',      icon: '📡',  action: () => { switchTab('scanner'); loadScannerData(); }},
    { label: 'Run Signals',      icon: '📶',  action: () => { switchTab('signals'); loadSignals(); } },
    { label: 'Run Backtest',     icon: '⚙️',  action: () => { if (state.activeSymbol) { switchTab('backtest'); loadBacktest(state.activeSymbol); } }},
];

let _cmdSelectedIdx = 0;
let _cmdItems       = [];

function openCommandPalette() {
    const overlay = document.getElementById('cmd-palette-overlay');
    const input   = document.getElementById('cmd-input');
    if (!overlay) return;
    overlay.style.display = 'flex';
    if (input) { input.value = ''; input.focus(); }
    _renderCmdResults('');
}

function closeCommandPalette() {
    const overlay = document.getElementById('cmd-palette-overlay');
    if (overlay) overlay.style.display = 'none';
}

function _fuzzyScore(query, label) {
    if (!query) return 1;
    const q = query.toLowerCase();
    const l = label.toLowerCase();
    if (l.startsWith(q)) return 3;
    if (l.includes(q))   return 2;
    // Character-by-character fuzzy
    let qi = 0;
    for (let i = 0; i < l.length && qi < q.length; i++) {
        if (l[i] === q[qi]) qi++;
    }
    return qi === q.length ? 1 : 0;
}

function _renderCmdResults(query) {
    const results = document.getElementById('cmd-results');
    if (!results) return;

    _cmdItems = [];

    // Symbols from watchlist
    const symbols = (typeof state !== 'undefined' ? state.symbols : []) || [];
    for (const sym of symbols) {
        const label = sym.symbol + (sym.name ? ` — ${sym.name}` : '');
        const score = _fuzzyScore(query, sym.symbol) || _fuzzyScore(query, sym.name || '');
        if (score > 0) {
            _cmdItems.push({
                score,
                type: 'symbol',
                icon: '📈',
                label,
                sub: sym.sector || '',
                action: () => { closeCommandPalette(); selectSymbol(sym.symbol); },
            });
        }
    }

    // Tabs
    for (const t of CMD_TABS) {
        const score = _fuzzyScore(query, t.label);
        if (score > 0) _cmdItems.push({ score: score - 0.5, type: 'tab', icon: t.icon, label: t.label, sub: 'Tab', action: () => { closeCommandPalette(); t.action(); } });
    }

    // Actions
    for (const a of CMD_ACTIONS) {
        const score = _fuzzyScore(query, a.label);
        if (score > 0) _cmdItems.push({ score: score - 1, type: 'action', icon: a.icon, label: a.label, sub: 'Action', action: () => { closeCommandPalette(); a.action(); } });
    }

    _cmdItems.sort((a, b) => b.score - a.score || a.label.localeCompare(b.label));
    _cmdItems = _cmdItems.slice(0, 12);
    _cmdSelectedIdx = 0;

    if (!_cmdItems.length) {
        results.innerHTML = '<div class="cmd-empty">No results</div>';
        return;
    }

    results.innerHTML = _cmdItems.map((item, i) => `
        <div class="cmd-item ${i === 0 ? 'cmd-item-selected' : ''}" data-idx="${i}" onclick="_cmdActivate(${i})">
          <span class="cmd-item-icon">${item.icon}</span>
          <span class="cmd-item-label">${item.label}</span>
          <span class="cmd-item-sub">${item.sub}</span>
        </div>
    `).join('');
}

function _cmdActivate(idx) {
    const item = _cmdItems[idx];
    if (item) item.action();
}

function _cmdMove(delta) {
    if (!_cmdItems.length) return;
    document.querySelectorAll('.cmd-item').forEach(el => el.classList.remove('cmd-item-selected'));
    _cmdSelectedIdx = (_cmdSelectedIdx + delta + _cmdItems.length) % _cmdItems.length;
    const el = document.querySelector(`.cmd-item[data-idx="${_cmdSelectedIdx}"]`);
    if (el) { el.classList.add('cmd-item-selected'); el.scrollIntoView({ block: 'nearest' }); }
}

// Wire up events
document.addEventListener('DOMContentLoaded', () => {
    // Cmd/Ctrl + K
    document.addEventListener('keydown', e => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
            e.preventDefault();
            const overlay = document.getElementById('cmd-palette-overlay');
            if (overlay && overlay.style.display !== 'none') closeCommandPalette();
            else openCommandPalette();
        }
    });

    const input = document.getElementById('cmd-input');
    if (input) {
        input.addEventListener('input', () => _renderCmdResults(input.value.trim()));
        input.addEventListener('keydown', e => {
            if (e.key === 'ArrowDown')  { e.preventDefault(); _cmdMove(1);  }
            if (e.key === 'ArrowUp')    { e.preventDefault(); _cmdMove(-1); }
            if (e.key === 'Enter')      { e.preventDefault(); _cmdActivate(_cmdSelectedIdx); }
            if (e.key === 'Escape')     { closeCommandPalette(); }
        });
    }
});
