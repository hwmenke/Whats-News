/**
 * settings_app.js — App settings panel
 * Controls routine component visibility/order and provides CSV export shortcuts.
 */

function initSettings() {
    const area = document.getElementById('settings-area');
    if (!area) return;
    _renderSettingsArea(area);
}

function _renderSettingsArea(area) {
    const rs = _loadRoutineSettings();

    const ordered = rs.order
        .map(id => ROUTINE_COMPONENTS.find(c => c.id === id))
        .filter(Boolean);
    ROUTINE_COMPONENTS.forEach(c => {
        if (!ordered.find(o => o.id === c.id)) ordered.push(c);
    });

    const rows = ordered.map((comp, i) => {
        const on = rs.enabled.has(comp.id);
        return `
            <div class="sc-row" data-id="${comp.id}">
                <label class="sc-toggle" title="${on ? 'Enabled — click to disable' : 'Disabled — click to enable'}">
                    <input type="checkbox" ${on ? 'checked' : ''}
                        onchange="_settingsToggleComponent('${comp.id}', this.checked)">
                    <span class="sc-slider"></span>
                </label>
                <span class="sc-icon">${comp.icon}</span>
                <div class="sc-info">
                    <div class="sc-name">${comp.name}</div>
                    <div class="sc-desc">${comp.desc}</div>
                </div>
                <div class="sc-order-btns">
                    <button class="btn btn-icon btn-ghost" title="Move up"
                        onclick="_settingsMoveComponent('${comp.id}', -1)">↑</button>
                    <button class="btn btn-icon btn-ghost" title="Move down"
                        onclick="_settingsMoveComponent('${comp.id}', +1)">↓</button>
                </div>
            </div>`;
    }).join('');

    area.innerHTML = `
        <div class="sc-container">
            <h2 class="feat-title" style="margin:0 0 24px;">Settings</h2>

            ${_renderAppearanceSection()}
            ${_renderTabVisibilitySection()}
            ${_renderEconDataSection()}

            <section class="sc-section">
                <div class="sc-section-title">Morning Routine Components</div>
                <div class="sc-section-desc">Toggle components on/off and set the order they run.</div>
                <div class="sc-comp-list">${rows}</div>
            </section>

            <section class="sc-section">
                <div class="sc-section-title">Quick CSV Export</div>
                <div class="sc-section-desc">Download the current table from any view as a CSV file.</div>
                <div class="sc-export-btns">
                    <button class="btn btn-ghost"
                        onclick="exportTableToCSV('scanner-table','scanner.csv')">⬇ Scanner</button>
                    <button class="btn btn-ghost"
                        onclick="exportTableToCSV('mom-tbl','momentum.csv')">⬇ Momentum</button>
                    <button class="btn btn-ghost"
                        onclick="exportTableToCSV('journal-table','journal.csv')">⬇ Journal</button>
                </div>
            </section>
            <section class="sc-section">
                <div class="sc-section-title">Database Backup</div>
                <div class="sc-section-desc">Download a copy of the SQLite database (finance.db) for safekeeping.</div>
                <div class="sc-export-btns">
                    <a class="btn btn-ghost" href="/api/backup" download>⬇ Download finance.db</a>
                </div>
            </section>
        </div>`;

    _loadEconSettingsStatus();
}

// ── Appearance ────────────────────────────────────────────────────────────────

const _ACCENTS = [
    ['amber',  '#f0a32f', 'Amber (terminal)'],
    ['blue',   '#3b82f6', 'Blue'],
    ['green',  '#22c55e', 'Green'],
    ['purple', '#a855f7', 'Purple'],
    ['cyan',   '#06b6d4', 'Cyan'],
];

function _renderAppearanceSection() {
    const p = loadUiPrefs();
    const accent  = p.accent  || 'amber';
    const density = p.density || 'comfortable';
    const scale   = p.scale   || 100;

    const swatches = _ACCENTS.map(([id, color, label]) => `
        <button class="sc-swatch ${accent === id ? 'sc-swatch-on' : ''}"
                style="--swatch:${color}" title="${label}"
                onclick="_setUiPref('accent','${id}')"></button>`).join('');

    const densityBtns = [['comfortable', 'Comfortable'], ['compact', 'Compact']].map(([id, label]) =>
        `<button class="cal-chip ${density === id ? 'cal-chip-on' : ''}"
                 onclick="_setUiPref('density','${id}')">${label}</button>`).join('');

    const scaleBtns = [90, 100, 110].map(s =>
        `<button class="cal-chip ${scale === s ? 'cal-chip-on' : ''}"
                 onclick="_setUiPref('scale',${s})">${s}%</button>`).join('');

    return `
        <section class="sc-section">
            <div class="sc-section-title">Appearance</div>
            <div class="sc-section-desc">Accent color, information density, and UI scale. Saved per browser.</div>
            <div class="sc-appearance-grid">
                <div class="sc-app-row"><span class="sc-app-label">Accent</span><div class="sc-swatches">${swatches}</div></div>
                <div class="sc-app-row"><span class="sc-app-label">Density</span><div>${densityBtns}</div></div>
                <div class="sc-app-row"><span class="sc-app-label">UI Scale</span><div>${scaleBtns}</div></div>
            </div>
        </section>`;
}

function _setUiPref(key, value) {
    const p = loadUiPrefs();
    p[key] = value;
    saveUiPrefs(p);
    const area = document.getElementById('settings-area');
    if (area) _renderSettingsArea(area);
}

// ── Tab visibility ────────────────────────────────────────────────────────────

function _renderTabVisibilitySection() {
    const p      = loadUiPrefs();
    const hidden = new Set(p.hiddenTabs || []);
    const tabs   = [];
    document.querySelectorAll('.tab-btn').forEach(btn => {
        const id = (btn.id || '').replace(/^tab-/, '');
        if (!id || id === 'charts' || id === 'settings') return;
        const label = (btn.title || btn.textContent || id).split('(')[0].trim();
        tabs.push([id, label]);
    });
    if (!tabs.length) return '';

    const boxes = tabs.map(([id, label]) => `
        <label class="sc-tab-check ${hidden.has(id) ? 'sc-tab-off' : ''}">
            <input type="checkbox" ${hidden.has(id) ? '' : 'checked'}
                   onchange="_toggleTabVisible('${id}', this.checked)">
            <span>${label}</span>
        </label>`).join('');

    return `
        <section class="sc-section">
            <div class="sc-section-title">Visible Tabs</div>
            <div class="sc-section-desc">Hide tabs you don't use — they stay reachable via Ctrl+K. Charts and Settings are always visible.</div>
            <div class="sc-tab-grid">${boxes}</div>
        </section>`;
}

function _toggleTabVisible(id, visible) {
    const p      = loadUiPrefs();
    const hidden = new Set(p.hiddenTabs || []);
    if (visible) hidden.delete(id); else hidden.add(id);
    p.hiddenTabs = [...hidden];
    saveUiPrefs(p);
}

// ── Economic data (FRED) ──────────────────────────────────────────────────────

function _renderEconDataSection() {
    return `
        <section class="sc-section">
            <div class="sc-section-title">Economic Data — FRED</div>
            <div class="sc-section-desc">
                The calendar ships with a built-in macro schedule (FOMC exact, CPI/NFP/GDP… estimated).
                Add a free <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank" rel="noopener">FRED API key</a>
                to replace the estimates with actual published release dates.
            </div>
            <div class="sc-fred-row">
                <input id="sc-fred-key" class="alp-input" type="password" placeholder="FRED API key"
                       autocomplete="off" spellcheck="false" style="max-width:320px;">
                <button class="btn btn-primary btn-sm" onclick="_saveFredKey()">Save</button>
                <span id="sc-fred-status" class="sc-fred-status"></span>
            </div>
        </section>`;
}

async function _loadEconSettingsStatus() {
    const el = document.getElementById('sc-fred-status');
    if (!el) return;
    try {
        const s = await apiFetch(`${API}/settings`);
        el.textContent = s.fred_api_key_set ? '✓ key configured' : 'no key — using estimated dates';
        el.className   = `sc-fred-status ${s.fred_api_key_set ? 'sc-fred-ok' : ''}`;
    } catch (_) {
        el.textContent = '';
    }
}

async function _saveFredKey() {
    const input = document.getElementById('sc-fred-key');
    if (!input) return;
    try {
        await apiFetch(`${API}/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ fred_api_key: input.value.trim() }),
        });
        toast(input.value.trim() ? 'FRED key saved — calendar will use exact release dates' : 'FRED key cleared', 'success');
        input.value = '';
        _loadEconSettingsStatus();
    } catch (e) {
        toast(`Could not save key: ${e.message}`, 'error');
    }
}

function _exportJournal() {
    // Journal table has no id — find it by its body's parent
    const tbody = document.getElementById('journal-body');
    if (!tbody) { toast('Open the Journal tab first, then export', 'warning'); return; }
    exportTableToCSV(tbody.closest('table'), 'journal.csv');
}

function _settingsToggleComponent(id, enabled) {
    const rs = _loadRoutineSettings();
    if (enabled) rs.enabled.add(id); else rs.enabled.delete(id);
    saveRoutineSettings(rs);
    _routineSettings = rs;
    toast(`${ROUTINE_COMPONENTS.find(c => c.id === id)?.name || id} ${enabled ? 'enabled' : 'disabled'}`, 'info', 1500);
}

function _settingsMoveComponent(id, delta) {
    const rs  = _loadRoutineSettings();
    const idx = rs.order.indexOf(id);
    if (idx < 0) return;
    const nxt = Math.max(0, Math.min(rs.order.length - 1, idx + delta));
    if (nxt === idx) return;
    rs.order.splice(idx, 1);
    rs.order.splice(nxt, 0, id);
    saveRoutineSettings(rs);
    _routineSettings = rs;
    // Re-render settings in-place
    const area = document.getElementById('settings-area');
    if (area) _renderSettingsArea(area);
}
