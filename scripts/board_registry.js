/**
 * Shared board column + measure registry (Market Moves + ENGINE).
 * GET /api/boards/registry — ordered columns, visibility, format, heat.
 * Customize prefs live in desk localStorage (boardColumns). Flutter path:
 * same JSON via GET /api/boards/registry; persist boardColumns on
 * whats-news-desk-prefs; apply in ScansPage slivers. Web first.
 */
/* global API, API_BASE, readDeskPrefs, writeDeskPrefs, loadMarketMoves, loadEngineBoard, loadEngineSigma, loadEngineMaps, renderEngineMaps */

(function () {
    const REGISTRY_URL = `${(typeof API !== 'undefined' && API) ? API : ((typeof API_BASE !== 'undefined' && API_BASE) ? API_BASE : '')}/api/boards/registry`;
    let _registry = null;
    let _registryPromise = null;
    let _activeBoard = 'market_moves';

    function _dig(obj, path) {
        if (obj == null || path == null) return undefined;
        if (!String(path).includes('.')) return obj[path];
        return String(path).split('.').reduce((cur, key) => (cur == null ? undefined : cur[key]), obj);
    }

    function _cssVar(name, fallback) {
        try {
            const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
            return v || fallback;
        } catch {
            return fallback;
        }
    }

    function heatStyle(value, measure) {
        if (value == null || Number.isNaN(Number(value))) return '';
        const heat = (measure && measure.heat) || 'none';
        if (heat === 'none' || heat === 'signed_text') return '';
        const n = Number(value);
        const scale = (measure && measure.heat_scale) || {};
        const green = _cssVar('--heat-green-rgb', '34, 197, 94');
        const red = _cssVar('--heat-red-rgb', '239, 68, 68');
        const floor = Number(_cssVar('--heat-floor', '0.06')) || 0.06;
        const span = Number(_cssVar('--heat-span', '0.32')) || 0.32;
        if (heat === 'z' || heat === 'signed') {
            const hi = Number(scale.hi != null ? scale.hi : 3);
            const a = Math.min(1, Math.abs(n) / (Math.abs(hi) || 3));
            const rgb = n >= 0 ? green : red;
            return `background: rgba(${rgb},${(floor + span * a).toFixed(2)})`;
        }
        if (heat === 'range') {
            const lo = Number(scale.lo != null ? scale.lo : 0);
            const hi = Number(scale.hi != null ? scale.hi : 1);
            const t = Math.max(0, Math.min(1, (n - lo) / (hi - lo || 1)));
            if (t >= 0.5) {
                const g = (t - 0.5) * 2;
                return `background: rgba(${green},${(floor + span * g).toFixed(2)})`;
            }
            const r = (0.5 - t) * 2;
            return `background: rgba(${red},${(floor + span * r).toFixed(2)})`;
        }
        return '';
    }

    function toneClass(value, measure) {
        if (value == null || Number.isNaN(Number(value))) return '';
        const heat = (measure && measure.heat) || '';
        if (heat === 'signed' || heat === 'z' || heat === 'range') {
            const n = Number(value);
            if (n > 0) return 'is-up mm-up';
            if (n < 0) return 'is-down mm-dn';
        }
        if (heat === 'signed_text') {
            const s = String(value);
            if (s.includes('Breakout') || s.includes('↑')) return 'is-up';
            if (s.includes('Breakdown') || s.includes('↓')) return 'is-down';
        }
        return '';
    }

    function cellValue(row, col) {
        const key = col.key || col.id;
        let raw = _dig(row, key);
        if (raw == null && col.fallback_key) raw = _dig(row, col.fallback_key);
        if (raw == null && col.id === 'tes') raw = _dig(row, 'tes_state');
        if (col.format === 'bar' && raw == null && col.fallback_key === 'stretch_pct' && row.stretch_pct != null) {
            raw = 50 + Number(row.stretch_pct);
        }
        return raw;
    }

    function formatValue(raw, col, row) {
        if (raw == null || (typeof raw === 'number' && Number.isNaN(raw))) return '—';
        const fmt = col.format || 'text';
        if (fmt === 'price') {
            const n = Number(raw);
            return n.toFixed(Math.abs(n) < 10 ? 3 : 2);
        }
        if (fmt === 'signed_1' || fmt === 'z_1') {
            const n = Number(raw);
            const sign = n > 0 ? '+' : '';
            const bullet = (fmt === 'z_1' && col.bullet_from && row && row[col.bullet_from])
                || (fmt === 'z_1' && col.heat === 'z' && Math.abs(n) >= ((col.heat_scale && col.heat_scale.extreme) || 99))
                ? '• ' : '';
            return `${bullet}${sign}${n.toFixed(1)}`;
        }
        if (fmt === 'signed_2') {
            const n = Number(raw);
            return `${n > 0 ? '+' : ''}${n.toFixed(2)}`;
        }
        if (fmt === 'int') return String(raw);
        if (fmt === 'bar') {
            const n = Math.max(0, Math.min(100, Number(raw)));
            return `<span class="engine-bar"><i style="width:${n}%"></i><em>${n.toFixed(0)}%</em></span>`;
        }
        if (fmt === 'gray') return `<span class="engine-gray">${_esc(raw)}</span>`;
        if (fmt === 'takeaway') return _esc(raw);
        return _esc(raw);
    }

    function _esc(s) {
        return String(s ?? '').replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    function cellHtml(row, col, extraClass) {
        const raw = cellValue(row, col);
        const opp = col.id === 'engine' && (row.engine_primary === 'OPPORTUNITY' || String(raw || '').includes('OPPORTUNITY'));
        const cls = [extraClass || '', toneClass(raw, col), col.id === 'name' ? 'mm-name' : '', col.id === 'symbol' ? 'macro-sym' : '', col.format === 'takeaway' ? 'engine-takeaway' : '', col.id === 'engine' ? 'engine-state' : '', opp ? 'engine-opp' : '', col.format === 'z_1' ? 'mm-z' : ''].filter(Boolean).join(' ');
        const take = col.format === 'takeaway' ? ((row.sentiment || '').includes('LONG') ? ' is-long' : (row.sentiment || '').includes('SHORT') ? ' is-short' : ' is-neutral') : '';
        const title = col.title ? ` title="${_esc(col.title)}"` : '';
        let body = formatValue(raw, col, row);
        if ((col.id === 'vs20' || String(col.measure || '').includes('sigma') || col.id.startsWith('sigma')) && raw != null && !Number.isNaN(Number(raw))) {
            body += `<span class="sigma-dot ${Number(raw) >= 0 ? 'is-up' : 'is-dn'}"></span>`;
        }
        return `<td class="${cls}${take}" style="${heatStyle(raw, col)}"${title}>${body}</td>`;
    }

    function headerHtml(cols) {
        return `<tr>${cols.map(c => `<th${c.title ? ` title="${_esc(c.title)}"` : ''}>${_esc(c.label)}</th>`).join('')}</tr>`;
    }

    function readLayout(boardId) {
        const prefs = typeof readDeskPrefs === 'function' ? readDeskPrefs() : {};
        const all = prefs.boardColumns || {};
        const layout = all[boardId] || {};
        return {
            order: Array.isArray(layout.order) ? layout.order.slice() : [],
            hidden: Array.isArray(layout.hidden) ? layout.hidden.slice() : [],
        };
    }

    function writeLayout(boardId, layout) {
        const prefs = typeof readDeskPrefs === 'function' ? readDeskPrefs() : {};
        const next = { ...(prefs.boardColumns || {}), [boardId]: layout };
        if (typeof writeDeskPrefs === 'function') writeDeskPrefs({ boardColumns: next });
    }

    function _resolveCol(c, registry) {
        const measures = ((registry || _registry || {}).measures) || {};
        const meas = measures[c.measure] || {};
        return {
            ...c,
            key: c.key || meas.key || c.id,
            fallback_key: c.fallback_key || meas.fallback_key,
            format: c.format || meas.format || 'text',
            heat: c.heat || meas.heat || 'none',
            heat_scale: c.heat_scale || meas.heat_scale,
            formula: c.formula || meas.formula,
            title: c.title || meas.formula,
            bullet_from: c.bullet_from || meas.bullet_from,
        };
    }

    function visibleColumns(boardId, registry) {
        const spec = ((registry || _registry || {}).boards || {})[boardId];
        if (!spec) return [];
        const cols = (spec.columns || []).map(c => _resolveCol({ ...c }, registry));
        const byId = Object.fromEntries(cols.map(c => [c.id, c]));
        const layout = readLayout(boardId);
        const order = layout.order.filter(id => byId[id]);
        const seen = new Set(order);
        cols.forEach(c => { if (!seen.has(c.id)) order.push(c.id); });
        const hidden = new Set(layout.hidden);
        return order.map(id => byId[id]).filter(c => {
            if (!c) return false;
            if (c.locked) return true;
            if (hidden.has(c.id)) return false;
            return c.visible !== false;
        });
    }

    function allColumns(boardId, registry) {
        const spec = ((registry || _registry || {}).boards || {})[boardId];
        if (!spec) return [];
        const cols = (spec.columns || []).map(c => _resolveCol({ ...c }, registry));
        const byId = Object.fromEntries(cols.map(c => [c.id, c]));
        const layout = readLayout(boardId);
        const order = layout.order.filter(id => byId[id]);
        const seen = new Set(order);
        cols.forEach(c => { if (!seen.has(c.id)) order.push(c.id); });
        const hidden = new Set(layout.hidden);
        return order.map(id => {
            const c = byId[id];
            return { ...c, shown: c.locked || (!hidden.has(c.id) && c.visible !== false) };
        });
    }

    async function loadRegistry(force) {
        if (_registry && !force) return _registry;
        if (_registryPromise && !force) return _registryPromise;
        _registryPromise = fetch(REGISTRY_URL).then(r => r.json()).then(data => {
            _registry = data;
            return data;
        }).catch(err => {
            _registryPromise = null;
            throw err;
        });
        return _registryPromise;
    }

    function currentRegistry() {
        return _registry;
    }

    function applyBoardRerender(boardId) {
        if (boardId === 'market_moves' && typeof loadMarketMoves === 'function') loadMarketMoves();
        if (boardId === 'engine_setup' && typeof loadEngineBoard === 'function') loadEngineBoard();
        if (boardId === 'engine_sigma' && typeof loadEngineSigma === 'function') loadEngineSigma();
        if (boardId === 'engine_maps') {
            if (window._engineMaps && typeof renderEngineMaps === 'function') {
                const on = document.querySelector('.engine-map-tabs .desk-ia-btn.on');
                renderEngineMaps(window._engineMaps, on ? on.dataset.map : 'coil');
            } else if (typeof loadEngineMaps === 'function') {
                loadEngineMaps();
            }
        }
        renderCustomizeList();
    }

    function toggleColumn(boardId, colId) {
        const spec = ((_registry || {}).boards || {})[boardId];
        const col = ((spec && spec.columns) || []).find(c => c.id === colId);
        if (!col || col.locked) return;
        const layout = readLayout(boardId);
        const hidden = new Set(layout.hidden);
        if (hidden.has(colId)) hidden.delete(colId);
        else hidden.add(colId);
        if (!layout.order.length) layout.order = allColumns(boardId).map(c => c.id);
        writeLayout(boardId, { order: layout.order, hidden: [...hidden] });
        applyBoardRerender(boardId);
    }

    function moveColumn(boardId, colId, dir) {
        const cols = allColumns(boardId);
        const order = cols.map(c => c.id);
        const i = order.indexOf(colId);
        const j = i + dir;
        if (i < 0 || j < 0 || j >= order.length) return;
        [order[i], order[j]] = [order[j], order[i]];
        const layout = readLayout(boardId);
        writeLayout(boardId, { order, hidden: layout.hidden });
        applyBoardRerender(boardId);
    }

    function resetBoard(boardId) {
        const prefs = typeof readDeskPrefs === 'function' ? readDeskPrefs() : {};
        const next = { ...(prefs.boardColumns || {}) };
        delete next[boardId];
        if (typeof writeDeskPrefs === 'function') writeDeskPrefs({ boardColumns: next });
        applyBoardRerender(boardId);
    }

    function renderCustomizeList() {
        const list = document.getElementById('board-customize-list');
        const title = document.getElementById('board-customize-title');
        if (!list || !_registry) return;
        const spec = (_registry.boards || {})[_activeBoard];
        if (title) title.textContent = `Customize — ${(spec && spec.label) || _activeBoard}`;
        const cols = allColumns(_activeBoard);
        list.innerHTML = cols.map((c, idx) => `
            <li data-col="${_esc(c.id)}" class="${c.locked ? 'is-locked' : ''}">
                <label>
                    <input type="checkbox" ${c.shown ? 'checked' : ''} ${c.locked ? 'disabled' : ''} data-toggle="${_esc(c.id)}" />
                    <span>${_esc(c.label)}</span>
                </label>
                <span class="board-customize-keys">${_esc(c.measure || '')} · ${_esc(c.format || '')}</span>
                <span class="board-customize-move">
                    <button type="button" data-up="${_esc(c.id)}" ${idx === 0 ? 'disabled' : ''} aria-label="Move up">↑</button>
                    <button type="button" data-down="${_esc(c.id)}" ${idx === cols.length - 1 ? 'disabled' : ''} aria-label="Move down">↓</button>
                </span>
            </li>`).join('');
        list.querySelectorAll('[data-toggle]').forEach(el => {
            el.addEventListener('change', () => toggleColumn(_activeBoard, el.getAttribute('data-toggle')));
        });
        list.querySelectorAll('[data-up]').forEach(el => {
            el.addEventListener('click', () => moveColumn(_activeBoard, el.getAttribute('data-up'), -1));
        });
        list.querySelectorAll('[data-down]').forEach(el => {
            el.addEventListener('click', () => moveColumn(_activeBoard, el.getAttribute('data-down'), 1));
        });
    }

    function openCustomize(boardId) {
        _activeBoard = boardId || _activeBoard;
        const el = document.getElementById('board-customize');
        if (el) {
            el.hidden = false;
            el.classList.add('is-open');
        }
        loadRegistry().then(() => renderCustomizeList());
    }

    function closeCustomize() {
        const el = document.getElementById('board-customize');
        if (el) {
            el.hidden = true;
            el.classList.remove('is-open');
        }
    }

    function bindCustomize() {
        document.getElementById('board-customize-close')?.addEventListener('click', closeCustomize);
        document.getElementById('board-customize-reset')?.addEventListener('click', () => resetBoard(_activeBoard));
        document.querySelectorAll('[data-customize-board]').forEach(btn => {
            btn.addEventListener('click', () => openCustomize(btn.getAttribute('data-customize-board')));
        });
        document.addEventListener('keydown', ev => {
            if (ev.key === 'Escape') closeCustomize();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bindCustomize);
    } else {
        bindCustomize();
    }

    loadRegistry().catch(() => { /* boards still render hardcoded fallbacks */ });

    window.BoardRegistry = {
        load: loadRegistry,
        current: currentRegistry,
        visibleColumns,
        allColumns,
        cellHtml,
        headerHtml,
        heatStyle,
        openCustomize,
        closeCustomize,
        readLayout,
    };
})();
