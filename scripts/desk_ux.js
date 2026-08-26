/**
 * desk_ux.js — View hide/show toggles + step-by-step desk guide
 */

const VIEW_KEY = 'whats-news-view';
const GUIDE_SEEN_KEY = 'whats-news-guide-seen';
const MODAL_FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
let _modalFocusPrev = null;

function overlayIsShown(el) {
    if (!el) return false;
    if (el.hidden) return false;
    if (el.style && el.style.display === 'none') return false;
    const cs = window.getComputedStyle(el);
    return cs.display !== 'none' && cs.visibility !== 'hidden';
}

function openModalRoot() {
    const ids = ['desk-palette', 'desk-guide-modal', 'badge-key-modal', 'smart-lists-modal', 'bulk-modal'];
    for (const id of ids) {
        const el = document.getElementById(id);
        if (overlayIsShown(el)) return el;
    }
    return null;
}

function modalFocusables(root) {
    const dialog = root.querySelector('[role="dialog"]') || root;
    return [...dialog.querySelectorAll(MODAL_FOCUSABLE)].filter(el => {
        if (el.disabled || el.getAttribute('aria-hidden') === 'true') return false;
        return el.offsetWidth > 0 || el.offsetHeight > 0 || el === document.activeElement;
    });
}

function armModalFocus(root) {
    if (!root) return;
    _modalFocusPrev = document.activeElement;
    requestAnimationFrame(() => {
        const list = modalFocusables(root);
        if (list.length) list[0].focus();
    });
}

function disarmModalFocus() {
    const prev = _modalFocusPrev;
    _modalFocusPrev = null;
    if (prev && document.contains(prev) && typeof prev.focus === 'function') {
        try { prev.focus(); } catch (_) { /* detached */ }
    }
}

document.addEventListener('keydown', e => {
    if (e.key !== 'Tab') return;
    const root = openModalRoot();
    if (!root) return;
    const list = modalFocusables(root);
    if (!list.length) return;
    const first = list[0];
    const last = list[list.length - 1];
    const active = document.activeElement;
    if (e.shiftKey) {
        if (active === first || !root.contains(active)) {
            e.preventDefault();
            last.focus();
        }
    } else if (active === last || !root.contains(active)) {
        e.preventDefault();
        first.focus();
    }
}, true);

const DESK_GUIDE_PAGES = [
    {
        title: '1 · Build the database (once)',
        body: `
          <p>Open the <strong>Data</strong> tab.</p>
          <ol>
            <li>Check S&amp;P / Nasdaq / Russell → <strong>Sync indices</strong></li>
            <li><strong>Archive history</strong> (hours — run once)</li>
            <li>Every day after close: <strong>Daily refresh</strong> (last few days only)</li>
          </ol>
          <p class="guide-tip">CLI equivalent: <code>python3 scripts/bulk_archive.py --sync-indices all</code> then <code>--archive</code>, later <code>--refresh</code>.</p>
        `,
        action: { label: 'Open Data', run: () => switchTab('data-manager') },
    },
    {
        title: '2 · Make a smart list',
        body: `
          <p>In the sidebar click <strong>Lists ▾</strong>.</p>
          <ol>
            <li>Pick a <strong>preset card</strong> (EP, Near high, Darvas…)</li>
            <li>Click <strong>Preview</strong> — matching tickers appear as chips</li>
            <li>Click <strong>Apply to watchlist →</strong></li>
          </ol>
          <p class="guide-tip">Click the green list pill on the sidebar to clear the filter anytime.</p>
        `,
        action: { label: 'Open Lists', run: () => typeof openSmartListsModal === 'function' && openSmartListsModal() },
    },
    {
        title: '3 · Scan named setups',
        body: `
          <p>Open the <strong>Scanner</strong> tab → <strong>Setups board</strong>.</p>
          <ol>
            <li>Pick a family or a <strong>badge</strong>: KQ · MM · SB4/SBW/SB9 · DB · ON · 2A/2B</li>
            <li>The <strong>M</strong> strip is book breadth of the cached universe — not a licensed Market Monitor</li>
            <li>Stage pills: S1 basing · S2 advancing · S3 topping · S4 declining</li>
            <li>Click a row → chart opens; weekly <strong>30W</strong> SMA shows for stage</li>
            <li><strong>Apply as list</strong> turns the active badge into a smart watchlist</li>
          </ol>
          <p class="guide-tip">After archiving prices, click <strong>Precompute</strong> once — Setups / Lists / desk tape then read the cache (fast).</p>
        `,
        action: { label: 'Open Scanner', run: () => switchTab('scanner') },
    },
    {
        title: '4 · Clean chart view',
        body: `
          <p>Use the <strong>Scan / Chart / Review</strong> workspace pills (keys <kbd>1</kbd> <kbd>2</kbd> <kbd>3</kbd>), or the <strong>View</strong> pills to hide chrome — Tape · Weekly · Vol · PM · Overlays · Sidebar · Header · Setups · Heatmap.</p>
          <ul>
            <li><strong>Focus</strong> (or press <kbd>f</kbd>) — chart only</li>
            <li>Drag the sidebar edge, chart divider, or setups handle to <strong>resize</strong></li>
            <li>Scanner: <kbd>j</kbd>/<kbd>k</kbd> walk rows, <kbd>Enter</kbd> opens the chart</li>
            <li><kbd>/</kbd> jumps to a ticker without adding it · <kbd>⌘K</kbd> opens commands</li>
            <li><strong>Positions</strong> (<kbd>Shift+J</kbd>) tracks open heat vs entry/stop</li>
            <li>Panes: turn on RSI / MACD / Trend only when needed</li>
            <li>Method types light a chart pack: Minervini SMA 50/150/200 · Stockbee EMA 9/20 · Qulla EMA 10/21/50 · Brandt risk box</li>
          </ul>
        `,
        action: { label: 'Open Charts', run: () => switchTab('charts') },
    },
    {
        title: '5 · Deep dive',
        body: `
          <p>On a shortlist name:</p>
          <ul>
            <li><strong>Adaptive Trend</strong> — regime lines</li>
            <li><strong>KNN</strong> — similar historical patterns</li>
            <li><strong>Statistics</strong> — distributions &amp; KAMA stats</li>
            <li><strong>Journal / Positions</strong> (<kbd>Shift+J</kbd>) — save the setup, track Last heat vs entry/stop</li>
          </ul>
          <p class="guide-tip">Daily loop: Refresh → Lists / Scanner → Chart → Journal.</p>
        `,
        action: null,
    },
];

let _guidePage = 0;

function loadViewPrefs() {
    try {
        return JSON.parse(localStorage.getItem(VIEW_KEY) || '{}');
    } catch {
        return {};
    }
}

function saveViewPrefs(prefs) {
    localStorage.setItem(VIEW_KEY, JSON.stringify(prefs));
}

function applyViewToggle(name, visible) {
    document.body.classList.toggle(`hide-${name}`, !visible);
    const pill = document.querySelector(`.view-pill[data-view="${name}"]`);
    if (pill) {
        pill.classList.toggle('active', visible);
        pill.setAttribute('aria-pressed', visible ? 'true' : 'false');
    }
    if (name === 'weekly' || name === 'volume' || name === 'sidebar' || name === 'header') {
        window.resizeAllCharts?.();
    }
    if (name === 'sidebar') {
        const app = document.querySelector('.app');
        // hide-sidebar fully removes it; don't fight collapse class
        if (!visible && app) app.classList.add('sidebar-collapsed');
    }
}

function setupViewToggles() {
    const prefs = loadViewPrefs();
    const defaults = {
        tape: true,
        weekly: true,
        volume: true,
        pm: true,
        overlays: true,
        sidebar: true,
        header: true,
        setups: true,
        heatmap: true,
    };
    Object.keys(defaults).forEach(name => {
        const on = prefs[name] !== undefined ? prefs[name] : defaults[name];
        applyViewToggle(name, on);
    });

    document.querySelectorAll('.view-pill[data-view]').forEach(btn => {
        btn.addEventListener('click', () => {
            const name = btn.dataset.view;
            const next = !btn.classList.contains('active');
            applyViewToggle(name, next);
            const p = loadViewPrefs();
            p[name] = next;
            saveViewPrefs(p);
        });
    });
    setupWorkspacePresets();
}

const WORKSPACE_PRESETS = {
    scan: {
        label: 'Scan',
        tab: 'scanner',
        views: {
            sidebar: true, header: false, tape: false, weekly: false, volume: false,
            pm: false, overlays: false, setups: true, heatmap: false,
        },
    },
    chart: {
        label: 'Chart',
        tab: 'charts',
        views: {
            sidebar: true, header: true, tape: true, weekly: true, volume: true,
            pm: true, overlays: true, setups: false, heatmap: false,
        },
    },
    review: {
        label: 'Review',
        tab: 'review',
        views: {
            sidebar: true, header: true, tape: true, weekly: true, volume: false,
            pm: true, overlays: true, setups: true, heatmap: false,
        },
    },
};

function applyWorkspace(id) {
    const ws = WORKSPACE_PRESETS[id];
    if (!ws) return;
    const prefs = loadViewPrefs();
    Object.entries(ws.views).forEach(([name, on]) => {
        applyViewToggle(name, on);
        prefs[name] = on;
    });
    saveViewPrefs(prefs);
    document.body.classList.remove('ws-scan', 'ws-chart', 'ws-review');
    document.body.classList.add(`ws-${id}`);
    document.querySelectorAll('.workspace-pill').forEach(btn => {
        const on = btn.dataset.workspace === id;
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    try { localStorage.setItem('whats-news-workspace', id); } catch { /* ignore */ }
    if (typeof switchTab === 'function' && ws.tab) switchTab(ws.tab);
    window.resizeAllCharts?.();
}

function setupWorkspacePresets() {
    document.querySelectorAll('.workspace-pill[data-workspace]').forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.dataset.workspace === 'mine') applyMyDesk();
            else applyWorkspace(btn.dataset.workspace);
        });
    });
    document.getElementById('btn-save-desk')?.addEventListener('click', saveMyDesk);
    syncMyDeskPill();
    let saved = null;
    try { saved = localStorage.getItem('whats-news-workspace'); } catch { saved = null; }
    if (saved && WORKSPACE_PRESETS[saved]) {
        document.body.classList.remove('ws-scan', 'ws-chart', 'ws-review');
        document.body.classList.add(`ws-${saved}`);
        document.querySelectorAll('.workspace-pill').forEach(btn => {
            const on = btn.dataset.workspace === saved;
            btn.classList.toggle('active', on);
            btn.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
    }
}

const MY_DESK_KEY = 'whats-news-my-desk';

function saveMyDesk() {
    let workspace = 'chart';
    try { workspace = localStorage.getItem('whats-news-workspace') || 'chart'; } catch { /* ignore */ }
    const layout = {
        workspace: WORKSPACE_PRESETS[workspace] ? workspace : 'chart',
        views: loadViewPrefs(),
        tab: (typeof state !== 'undefined' && state.activeTab) || null,
        saved_at: new Date().toISOString(),
    };
    try { localStorage.setItem(MY_DESK_KEY, JSON.stringify(layout)); } catch { /* ignore */ }
    syncMyDeskPill();
    toast?.('Saved My desk', 'success');
}

function applyMyDesk(opts = {}) {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(MY_DESK_KEY) || 'null'); } catch { raw = null; }
    if (!raw) {
        if (!opts.silent) toast?.('No saved desk — click Save desk first', 'warning');
        return false;
    }
    if (raw.workspace && WORKSPACE_PRESETS[raw.workspace]) applyWorkspace(raw.workspace);
    Object.entries(raw.views || {}).forEach(([name, on]) => applyViewToggle(name, !!on));
    if (raw.views) saveViewPrefs(raw.views);
    document.querySelectorAll('.workspace-pill').forEach(btn => {
        const on = btn.dataset.workspace === 'mine';
        btn.classList.toggle('active', on);
        btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    window.resizeAllCharts?.();
    return true;
}

function syncMyDeskPill() {
    const pill = document.getElementById('pill-my-desk');
    if (!pill) return;
    let has = false;
    try { has = !!localStorage.getItem(MY_DESK_KEY); } catch { has = false; }
    pill.hidden = !has;
}

function openDeskGuide(page = 0) {
    _guidePage = page;
    const modal = document.getElementById('desk-guide-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    renderDeskGuidePage();
    armModalFocus(modal);
}

function closeDeskGuide() {
    const modal = document.getElementById('desk-guide-modal');
    if (modal) modal.style.display = 'none';
    localStorage.setItem(GUIDE_SEEN_KEY, '1');
    disarmModalFocus();
}

function renderDeskGuidePage() {
    const page = DESK_GUIDE_PAGES[_guidePage];
    const body = document.getElementById('desk-guide-body');
    const prog = document.getElementById('desk-guide-progress');
    const prev = document.getElementById('btn-guide-prev');
    const next = document.getElementById('btn-guide-next');
    if (!page || !body) return;

    body.innerHTML = `<h3>${page.title}</h3>${page.body}`;
    if (page.action) {
        const wrap = document.createElement('div');
        wrap.className = 'desk-guide-action';
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn btn-primary btn-sm';
        b.textContent = page.action.label;
        b.addEventListener('click', () => {
            closeDeskGuide();
            page.action.run();
        });
        wrap.appendChild(b);
        body.appendChild(wrap);
    }

    if (prog) prog.textContent = `${_guidePage + 1} / ${DESK_GUIDE_PAGES.length}`;
    if (prev) prev.disabled = _guidePage === 0;
    if (next) {
        next.textContent = _guidePage >= DESK_GUIDE_PAGES.length - 1 ? 'Done' : 'Next →';
    }
}

function initDeskGuide() {
    document.getElementById('btn-desk-guide')?.addEventListener('click', () => openDeskGuide(0));
    document.getElementById('btn-open-full-guide')?.addEventListener('click', () => openDeskGuide(0));
    document.getElementById('btn-open-lists-from-guide')?.addEventListener('click', () => {
        if (typeof openSmartListsModal === 'function') openSmartListsModal();
    });

    document.querySelectorAll('.guide-step[data-guide]').forEach(btn => {
        btn.addEventListener('click', () => {
            const map = { data: 0, lists: 1, scanner: 2, chart: 3, deep: 4 };
            const idx = map[btn.dataset.guide];
            if (idx != null) openDeskGuide(idx);
        });
    });

    document.getElementById('btn-guide-prev')?.addEventListener('click', () => {
        if (_guidePage > 0) { _guidePage--; renderDeskGuidePage(); }
    });
    document.getElementById('btn-guide-next')?.addEventListener('click', () => {
        if (_guidePage >= DESK_GUIDE_PAGES.length - 1) closeDeskGuide();
        else { _guidePage++; renderDeskGuidePage(); }
    });

    document.addEventListener('keydown', e => {
        const tag = (e.target && e.target.tagName) || '';
        const typing = tag === 'INPUT' || tag === 'TEXTAREA' || e.target?.isContentEditable;
        if (typing) return;
        const wantGuide = e.key === '?' || (e.shiftKey && e.key === '/');
        if (wantGuide) {
            e.preventDefault();
            e.stopPropagation();
            openDeskGuide(0);
        }
    }, true);
}
