// ════════════════════════════════════════════════════════════
// modules.js — module enable/disable (the "⚙ Modules" tab + nav gating)
// ════════════════════════════════════════════════════════════

let _moduleManifest = [];

// Hide nav buttons for disabled modules. Runs on every page load.
async function applyModuleNav() {
    try {
        _moduleManifest = await apiFetch(`${API}/modules`);
    } catch (e) {
        return; // registry unavailable — leave all tabs visible
    }
    _moduleManifest.forEach(m => {
        const btn = document.getElementById(`tab-${m.id}`);
        if (btn) btn.style.display = m.enabled ? '' : 'none';
    });
}

async function loadModules() {
    try {
        _moduleManifest = await apiFetch(`${API}/modules`);
    } catch (e) {
        document.getElementById('modules-body').innerHTML =
            `<p style="color:#e66;">${e.message}</p>`;
        return;
    }
    renderModules();
}

function renderModules() {
    const groups = {};
    _moduleManifest.forEach(m => { (groups[m.group] ||= []).push(m); });

    let html = '';
    for (const g of Object.keys(groups)) {
        html += `<div class="mod-group"><h3>${g}</h3><div class="mod-grid">`;
        html += groups[g].map(m => {
            const dep = m.requires && m.requires.length
                ? `<span class="mod-dep">needs ${m.requires.join(', ')}</span>` : '';
            const note = m.notes ? `<span class="mod-note">${m.notes}</span>` : '';
            return `<label class="mod-card ${m.enabled ? 'on' : 'off'}">
                <input type="checkbox" data-mid="${m.id}" ${m.enabled ? 'checked' : ''}
                       ${m.core ? 'disabled' : ''} onchange="this.closest('.mod-card').classList.toggle('on', this.checked); this.closest('.mod-card').classList.toggle('off', !this.checked);">
                <span class="mod-ic">${m.icon}</span>
                <span class="mod-name">${m.label}${m.core ? ' <em>(core)</em>' : ''}</span>
                ${dep}${note}
            </label>`;
        }).join('');
        html += `</div></div>`;
    }
    html += `<div class="mod-actions">
        <button class="btn btn-primary" onclick="saveModules()">Save &amp; Apply</button>
        <span id="mod-save-msg" style="color:var(--text-muted); margin-left:12px;"></span>
    </div>`;
    document.getElementById('modules-body').innerHTML = html;
}

async function saveModules() {
    const updates = {};
    document.querySelectorAll('#modules-body input[data-mid]').forEach(cb => {
        if (!cb.disabled) updates[cb.dataset.mid] = cb.checked;
    });
    try {
        _moduleManifest = await apiFetch(`${API}/modules`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ modules: updates }),
        });
        document.getElementById('mod-save-msg').textContent =
            'Saved — reloading to apply…';
        setTimeout(() => location.reload(), 700);
    } catch (e) {
        toast(e.message, 'error');
    }
}
