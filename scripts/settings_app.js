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
