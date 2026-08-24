/**
 * watchlist_filters.js — Smart list modal (saved filter rules → watchlist view)
 */

const SMART_LISTS_KEY = 'whats-news-smart-lists';
const ACTIVE_SMART_KEY = 'whats-news-active-smart-list';

let _filterCatalog = null;
let _smartLists = [];
let _editingId = null;

function loadSmartListsFromStorage() {
    try {
        _smartLists = JSON.parse(localStorage.getItem(SMART_LISTS_KEY) || '[]');
    } catch {
        _smartLists = [];
    }
}

function saveSmartListsToStorage() {
    localStorage.setItem(SMART_LISTS_KEY, JSON.stringify(_smartLists));
}

function getActiveSmartListId() {
    return localStorage.getItem(ACTIVE_SMART_KEY) || null;
}

function setActiveSmartListId(id) {
    if (id) localStorage.setItem(ACTIVE_SMART_KEY, id);
    else localStorage.removeItem(ACTIVE_SMART_KEY);
}

function openSmartListsModal() {
    loadSmartListsFromStorage();
    const el = document.getElementById('smart-lists-modal');
    if (!el) return;
    el.style.display = 'flex';
    if (!_filterCatalog) {
        apiFetch(`${API}/watchlist/filter-catalog`).then(cat => {
            _filterCatalog = cat;
            renderSmartListPresets();
            renderSmartListsNav();
            if (_editingId) selectSmartList(_editingId);
        }).catch(e => toast('Filter catalog failed: ' + e.message, 'error'));
    } else {
        renderSmartListsNav();
        if (_editingId) selectSmartList(_editingId);
    }
}

function closeSmartListsModal() {
    const el = document.getElementById('smart-lists-modal');
    if (el) el.style.display = 'none';
}

function renderSmartListsNav() {
    const nav = document.getElementById('smart-lists-nav');
    if (!nav) return;
    nav.innerHTML = '';
    _smartLists.forEach(list => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'smart-list-nav-item' + (list.id === _editingId ? ' active' : '');
        btn.textContent = list.name || 'Untitled';
        btn.addEventListener('click', () => selectSmartList(list.id));
        nav.appendChild(btn);
    });
}

function renderSmartListPresets() {
    const wrap = document.getElementById('smart-list-presets');
    if (!wrap || !_filterCatalog) return;
    wrap.innerHTML = '<span class="overlay-section-label">Presets</span>';
    (_filterCatalog.presets || []).forEach(p => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'ind-pill setup-pill';
        b.textContent = p.name;
        b.addEventListener('click', () => {
            _editingId = p.id;
            document.getElementById('smart-list-name').value = p.name;
            document.querySelector('input[name="smart-match"][value="' + (p.match || 'all') + '"]').checked = true;
            renderSmartListRules(p.rules || []);
            renderSmartListsNav();
        });
        wrap.appendChild(b);
    });
}

function newSmartList() {
    _editingId = 'list_' + Date.now();
    document.getElementById('smart-list-name').value = 'New list';
    document.getElementById('smart-list-scope').value = 'with_data';
    document.querySelector('input[name="smart-match"][value="all"]').checked = true;
    renderSmartListRules([]);
    renderSmartListsNav();
}

function selectSmartList(id) {
    const list = _smartLists.find(l => l.id === id);
    if (!list) return;
    _editingId = id;
    document.getElementById('smart-list-name').value = list.name || '';
    document.getElementById('smart-list-scope').value = list.scope || 'with_data';
    const match = list.match || 'all';
    document.querySelector(`input[name="smart-match"][value="${match}"]`).checked = true;
    renderSmartListRules(list.rules || []);
    renderSmartListsNav();
}

function fieldMeta(fieldId) {
    return (_filterCatalog?.fields || []).find(f => f.id === fieldId);
}

function renderSmartListRules(rules) {
    const wrap = document.getElementById('smart-list-rules');
    if (!wrap) return;
    wrap.innerHTML = '';
    const fields = _filterCatalog?.fields || [];
    (rules.length ? rules : [{ field: 'is_near_high', op: 'is_true' }]).forEach((rule, idx) => {
        const row = document.createElement('div');
        row.className = 'smart-rule-row';

        const fieldSel = document.createElement('select');
        fieldSel.className = 'dm-select smart-rule-field';
        fields.forEach(f => {
            const o = document.createElement('option');
            o.value = f.id;
            o.textContent = `${f.group}: ${f.label}`;
            if (f.id === rule.field) o.selected = true;
            fieldSel.appendChild(o);
        });

        const opSel = document.createElement('select');
        opSel.className = 'dm-select smart-rule-op';

        const valInput = document.createElement('input');
        valInput.type = 'text';
        valInput.className = 'dm-input smart-rule-value';
        valInput.placeholder = 'value';
        valInput.value = rule.value != null && rule.value !== '' ? String(rule.value) : '';

        function syncOps() {
            const meta = fieldMeta(fieldSel.value);
            opSel.innerHTML = '';
            (meta?.ops || ['eq']).forEach(op => {
                const o = document.createElement('option');
                o.value = op;
                o.textContent = op;
                if (op === rule.op) o.selected = true;
                opSel.appendChild(o);
            });
            if (meta?.values) {
                valInput.placeholder = meta.values.join('|');
            }
            if (meta?.type === 'bool' || ['is_true', 'is_false'].includes(opSel.value)) {
                valInput.style.display = 'none';
            } else {
                valInput.style.display = '';
            }
        }

        fieldSel.addEventListener('change', () => { rule.field = fieldSel.value; syncOps(); });
        syncOps();

        const del = document.createElement('button');
        del.type = 'button';
        del.className = 'btn btn-ghost btn-sm';
        del.textContent = '×';
        del.addEventListener('click', () => row.remove());

        row.appendChild(fieldSel);
        row.appendChild(opSel);
        row.appendChild(valInput);
        row.appendChild(del);
        wrap.appendChild(row);
    });
}

function collectRulesFromDom() {
    const rows = document.querySelectorAll('.smart-rule-row');
    const rules = [];
    rows.forEach(row => {
        const field = row.querySelector('.smart-rule-field')?.value;
        const op = row.querySelector('.smart-rule-op')?.value;
        const raw = row.querySelector('.smart-rule-value')?.value?.trim();
        let value = raw;
        if (op === 'between' && raw.includes(',')) {
            const parts = raw.split(',').map(s => parseFloat(s.trim()));
            value = parts;
        } else if (op === 'in' && raw.includes('|')) {
            value = raw.split('|').map(s => s.trim());
        } else if (['gt', 'gte', 'lt', 'lte', 'between'].includes(op) && raw) {
            const n = parseFloat(raw);
            if (!Number.isNaN(n)) value = n;
        }
        if (!field || !op) return;
        const rule = { field, op };
        if (value !== '' && value != null && !['is_true', 'is_false'].includes(op)) {
            rule.value = value;
        }
        rules.push(rule);
    });
    return rules;
}

function currentListPayload() {
    const match = document.querySelector('input[name="smart-match"]:checked')?.value || 'all';
    return {
        id: _editingId || 'list_' + Date.now(),
        name: document.getElementById('smart-list-name')?.value?.trim() || 'List',
        scope: document.getElementById('smart-list-scope')?.value || 'with_data',
        match,
        rules: collectRulesFromDom(),
    };
}

async function previewSmartList() {
    const payload = currentListPayload();
    const prev = document.getElementById('smart-list-preview');
    if (prev) prev.textContent = '…';
    try {
        const res = await apiFetch(`${API}/watchlist/apply-filter`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                rules: payload.rules,
                match: payload.match,
                scope: payload.scope,
                limit: 2000,
            }),
        });
        if (prev) prev.textContent = `${res.count} matches (scanned ${res.scanned})`;
    } catch (e) {
        if (prev) prev.textContent = 'Error';
        toast(e.message, 'error');
    }
}

function saveSmartList() {
    const payload = currentListPayload();
    const idx = _smartLists.findIndex(l => l.id === payload.id);
    if (idx >= 0) _smartLists[idx] = payload;
    else _smartLists.push(payload);
    _editingId = payload.id;
    saveSmartListsToStorage();
    renderSmartListsNav();
    toast('List saved', 'success');
}

async function applySmartList() {
    const payload = currentListPayload();
    saveSmartList();
    setActiveSmartListId(payload.id);
    closeSmartListsModal();
    if (typeof applySmartListToSidebar === 'function') {
        await applySmartListToSidebar(payload);
    }
}

function deleteSmartList() {
    if (!_editingId) return;
    _smartLists = _smartLists.filter(l => l.id !== _editingId);
    saveSmartListsToStorage();
    if (getActiveSmartListId() === _editingId) {
        setActiveSmartListId(null);
        if (typeof clearSmartListSidebar === 'function') clearSmartListSidebar();
    }
    _editingId = null;
    newSmartList();
    renderSmartListsNav();
}

function initSmartListsUi() {
    loadSmartListsFromStorage();
    document.getElementById('btn-smart-lists')?.addEventListener('click', openSmartListsModal);
    document.getElementById('btn-new-smart-list')?.addEventListener('click', newSmartList);
    document.getElementById('btn-add-rule')?.addEventListener('click', () => {
        const rules = collectRulesFromDom();
        rules.push({ field: 'change_pct', op: 'gt', value: 0 });
        renderSmartListRules(rules);
    });
    document.getElementById('btn-preview-smart-list')?.addEventListener('click', previewSmartList);
    document.getElementById('btn-save-smart-list')?.addEventListener('click', saveSmartList);
    document.getElementById('btn-apply-smart-list')?.addEventListener('click', applySmartList);
    document.getElementById('btn-delete-smart-list')?.addEventListener('click', deleteSmartList);

    const activeId = getActiveSmartListId();
    if (activeId) {
        const list = _smartLists.find(l => l.id === activeId);
        if (list && typeof applySmartListToSidebar === 'function') {
            applySmartListToSidebar(list).catch(() => {});
        }
    }
    renderSmartListPills();
}

function renderSmartListPills() {
    const wrap = document.getElementById('smart-list-pills');
    if (!wrap) return;
    wrap.innerHTML = '';
    const activeId = getActiveSmartListId();
    if (!activeId) return;
    const list = _smartLists.find(l => l.id === activeId);
    if (!list) return;

    const pill = document.createElement('button');
    pill.type = 'button';
    pill.className = 'smart-list-pill active';
    pill.textContent = list.name;
    pill.title = 'Clear list filter';
    pill.addEventListener('click', () => {
        setActiveSmartListId(null);
        if (typeof clearSmartListSidebar === 'function') clearSmartListSidebar();
        renderSmartListPills();
    });
    wrap.appendChild(pill);
}
