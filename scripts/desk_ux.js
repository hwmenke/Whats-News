/**
 * desk_ux.js — View hide/show toggles + step-by-step desk guide
 */

const VIEW_KEY = 'whats-news-view';
const GUIDE_SEEN_KEY = 'whats-news-guide-seen';

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
            <li>Pick a family: <strong>Qullamaggie</strong> · <strong>Darvas</strong> · <strong>Brandt</strong> · <strong>Stage</strong></li>
            <li>Stage pills: S1 basing · S2 advancing · S3 topping · S4 declining</li>
            <li>Click a row → chart opens; weekly <strong>30W</strong> SMA shows for stage</li>
            <li><strong>+ Desk</strong> promotes a name to your trading list</li>
          </ol>
          <p class="guide-tip">Stage labels use weekly SMA(30) — Weinstein / Jacobs-style book rules, not discretionary calls.</p>
        `,
        action: { label: 'Open Scanner', run: () => switchTab('scanner') },
    },
    {
        title: '4 · Clean chart view',
        body: `
          <p>Use the <strong>View</strong> pills (Tape · Weekly · Vol · PM · Overlays) to hide chrome.</p>
          <ul>
            <li><strong>Focus</strong> (or press <kbd>f</kbd>) — chart only</li>
            <li>Panes: turn on RSI / MACD / Trend only when needed</li>
            <li>Overlays: BB · EP · Box stay on for breakout work</li>
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
            <li><strong>Journal</strong> (<kbd>Shift+J</kbd>) — save the setup</li>
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
    if (pill) pill.classList.toggle('active', visible);
    if (name === 'weekly' || name === 'volume') {
        window.resizeAllCharts?.();
    }
}

function setupViewToggles() {
    const prefs = loadViewPrefs();
    const defaults = { tape: true, weekly: true, volume: true, pm: true, overlays: true };
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
}

function openDeskGuide(page = 0) {
    _guidePage = page;
    const modal = document.getElementById('desk-guide-modal');
    if (!modal) return;
    modal.style.display = 'flex';
    renderDeskGuidePage();
}

function closeDeskGuide() {
    const modal = document.getElementById('desk-guide-modal');
    if (modal) modal.style.display = 'none';
    localStorage.setItem(GUIDE_SEEN_KEY, '1');
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
        if (e.key === '?' && !(e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA')) {
            e.preventDefault();
            openDeskGuide(0);
        }
    });
}
