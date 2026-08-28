/**
 * theme_leader_filter.js — click a Book drawer theme leader to filter the watchlist.
 * Wraps renderThemeLeaders after app.js. Stays on Review/Book; heatmap still opens the chart.
 * not a published rating.
 */

function themeLeaderGroupName(item) {
    if (!item || !item.querySelector) return '';
    return (item.querySelector('.theme-leader-name')?.textContent || '').trim();
}

function applyThemeLeaderFilter(group) {
    const name = group == null ? '' : String(group);
    const el = document.getElementById('watchlist-filter');
    if (el) el.value = name;
    if (typeof persistWatchlistFilter === 'function') persistWatchlistFilter();
    if (typeof renderSymbolList === 'function') renderSymbolList();
    if (typeof state !== 'undefined' && state && state.portfolioMeta && typeof renderPortfolioTape === 'function') {
        renderPortfolioTape(state.portfolioMeta);
    }
}

function onThemeLeadersActivate(ev) {
    if (!ev || !ev.target) return;
    if (ev.type === 'keydown' && ev.key !== 'Enter' && ev.key !== ' ') return;
    const root = document.getElementById('theme-leaders');
    const item = typeof ev.target.closest === 'function'
        ? ev.target.closest('.theme-leader-item')
        : null;
    if (!item || !root || (typeof root.contains === 'function' && !root.contains(item))) return;
    const group = themeLeaderGroupName(item);
    if (!group) return;
    if (ev.type === 'keydown' && typeof ev.preventDefault === 'function') ev.preventDefault();
    applyThemeLeaderFilter(group);
}

function enhanceThemeLeaderItems() {
    const root = document.getElementById('theme-leaders');
    if (!root || typeof root.querySelectorAll !== 'function') return;
    root.querySelectorAll('.theme-leader-item').forEach(item => {
        item.setAttribute('role', 'button');
        item.tabIndex = 0;
        const name = themeLeaderGroupName(item);
        if (name) {
            item.setAttribute('aria-label', 'Filter watchlist to ' + name);
            item.title = 'Filter list to this group — j/k and the tape follow it';
        }
    });
}

function bindThemeLeaderFilterUi() {
    const root = document.getElementById('theme-leaders');
    if (!root || root._themeLeaderFilterBound) return;
    root._themeLeaderFilterBound = true;
    root.addEventListener('click', onThemeLeadersActivate);
    root.addEventListener('keydown', onThemeLeadersActivate);
}

function wrapRenderThemeLeaders() {
    const g = typeof globalThis !== 'undefined' ? globalThis : window;
    if (typeof g.renderThemeLeaders !== 'function' || g.renderThemeLeaders._themeLeaderFilterWrapped) return;
    const orig = g.renderThemeLeaders;
    function renderThemeLeadersWithFilter() {
        orig.apply(this, arguments);
        enhanceThemeLeaderItems();
        bindThemeLeaderFilterUi();
    }
    renderThemeLeadersWithFilter._themeLeaderFilterWrapped = true;
    g.renderThemeLeaders = renderThemeLeadersWithFilter;
}

function bootThemeLeaderFilter() {
    wrapRenderThemeLeaders();
    bindThemeLeaderFilterUi();
    enhanceThemeLeaderItems();
}

if (typeof document !== 'undefined' && document.addEventListener) {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', bootThemeLeaderFilter);
    } else {
        bootThemeLeaderFilter();
    }
}
