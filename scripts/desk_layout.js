/**
 * desk_layout.js — Hide/unhide + resize dashboard components
 *
 * View pills (extended) + drag splitters for sidebar / charts / scanner.
 * Prefs: whats-news-view, whats-news-layout
 */

const LAYOUT_KEY = 'whats-news-layout';

const LAYOUT_DEFAULTS = {
    sidebar_w: 240,
    daily_pct: 50,
    setup_h: 420,
    sidebar_collapsed: false,
};

function loadLayoutPrefs() {
    try {
        return { ...LAYOUT_DEFAULTS, ...JSON.parse(localStorage.getItem(LAYOUT_KEY) || '{}') };
    } catch {
        return { ...LAYOUT_DEFAULTS };
    }
}

function saveLayoutPrefs(prefs) {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(prefs));
}

function applyLayoutPrefs(prefs) {
    const p = prefs || loadLayoutPrefs();
    const root = document.documentElement;
    root.style.setProperty('--sidebar-w', `${Math.max(160, Math.min(480, p.sidebar_w || 240))}px`);
    root.style.setProperty('--daily-chart-pct', `${Math.max(25, Math.min(75, p.daily_pct || 50))}%`);
    root.style.setProperty('--setup-panel-h', `${Math.max(180, Math.min(800, p.setup_h || 420))}px`);

    const app = document.querySelector('.app');
    if (app) {
        app.classList.toggle('sidebar-collapsed', !!p.sidebar_collapsed);
    }
}

function updateLayoutPref(key, value) {
    const p = loadLayoutPrefs();
    p[key] = value;
    saveLayoutPrefs(p);
    applyLayoutPrefs(p);
}

/**
 * Horizontal or vertical drag splitter.
 * @param {HTMLElement} handle
 * @param {{ axis: 'x'|'y', onDrag: (delta, start) => void, onEnd?: () => void }} opts
 */
function bindSplitter(handle, opts) {
    if (!handle || handle.dataset.splitBound) return;
    handle.dataset.splitBound = '1';
    handle.classList.add('desk-splitter');
    handle.title = handle.title || 'Drag to resize';

    handle.addEventListener('mousedown', e => {
        if (e.button !== 0) return;
        e.preventDefault();
        const start = opts.axis === 'x' ? e.clientX : e.clientY;
        const startState = opts.getStart ? opts.getStart() : null;
        handle.classList.add('dragging');
        document.body.classList.add('is-resizing');

        const onMove = ev => {
            const cur = opts.axis === 'x' ? ev.clientX : ev.clientY;
            opts.onDrag(cur - start, startState, ev);
        };
        const onUp = () => {
            handle.classList.remove('dragging');
            document.body.classList.remove('is-resizing');
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            opts.onEnd?.();
            window.resizeAllCharts?.();
        };
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
    });
}

function setupLayoutSplitters() {
    applyLayoutPrefs();

    // Sidebar edge — create handle if missing
    let sideHandle = document.getElementById('sidebar-resize-handle');
    const sidebar = document.querySelector('.sidebar');
    if (sidebar && !sideHandle) {
        sideHandle = document.createElement('div');
        sideHandle.id = 'sidebar-resize-handle';
        sideHandle.className = 'desk-splitter desk-splitter-v sidebar-resize-handle';
        sideHandle.setAttribute('aria-hidden', 'true');
        sidebar.appendChild(sideHandle);
    }
    bindSplitter(sideHandle, {
        axis: 'x',
        getStart: () => loadLayoutPrefs().sidebar_w || 240,
        onDrag: (dx, startW) => {
            const app = document.querySelector('.app');
            if (app?.classList.contains('sidebar-collapsed')) return;
            const next = Math.max(160, Math.min(480, startW + dx));
            document.documentElement.style.setProperty('--sidebar-w', `${next}px`);
        },
        onEnd: () => {
            const w = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-w'), 10);
            if (!Number.isNaN(w)) updateLayoutPref('sidebar_w', w);
        },
    });

    // Daily / Weekly chart divider
    const chartDiv = document.getElementById('chart-panel-divider');
    if (chartDiv) {
        chartDiv.classList.add('desk-splitter', 'desk-splitter-v');
    }
    bindSplitter(chartDiv, {
        axis: 'x',
        getStart: () => loadLayoutPrefs().daily_pct || 50,
        onDrag: (dx, startPct) => {
            const wrap = document.querySelector('.charts-container');
            if (!wrap) return;
            const w = wrap.getBoundingClientRect().width || 1;
            const next = Math.max(25, Math.min(75, startPct + (dx / w) * 100));
            document.documentElement.style.setProperty('--daily-chart-pct', `${next}%`);
        },
        onEnd: () => {
            const raw = getComputedStyle(document.documentElement).getPropertyValue('--daily-chart-pct');
            const pct = parseFloat(raw);
            if (!Number.isNaN(pct)) updateLayoutPref('daily_pct', Math.round(pct));
        },
    });

    // Setups / heatmap divider doubles as height resize for setups panel
    const setupHandle = document.getElementById('setup-resize-handle');
    if (setupHandle) {
        setupHandle.classList.add('desk-splitter', 'desk-splitter-h');
    }
    bindSplitter(setupHandle, {
        axis: 'y',
        getStart: () => loadLayoutPrefs().setup_h || 420,
        onDrag: (dy, startH) => {
            const next = Math.max(180, Math.min(800, startH + dy));
            document.documentElement.style.setProperty('--setup-panel-h', `${next}px`);
        },
        onEnd: () => {
            const raw = getComputedStyle(document.documentElement).getPropertyValue('--setup-panel-h');
            const h = parseInt(raw, 10);
            if (!Number.isNaN(h)) updateLayoutPref('setup_h', h);
        },
    });
}

function persistSidebarCollapsed(collapsed) {
    updateLayoutPref('sidebar_collapsed', !!collapsed);
}

function initDeskLayout() {
    setupLayoutSplitters();
    document.getElementById('btn-layout-reset')?.addEventListener('click', () => {
        saveLayoutPrefs({ ...LAYOUT_DEFAULTS });
        applyLayoutPrefs();
        window.resizeAllCharts?.();
        toast?.('Layout sizes reset', 'success');
    });
    // Hook existing sidebar toggle to persist
    const btn = document.getElementById('btn-sidebar-toggle');
    if (btn && !btn.dataset.layoutHook) {
        btn.dataset.layoutHook = '1';
        btn.addEventListener('click', () => {
            setTimeout(() => {
                const collapsed = document.querySelector('.app')?.classList.contains('sidebar-collapsed');
                persistSidebarCollapsed(!!collapsed);
            }, 0);
        });
    }
}
