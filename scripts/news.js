/**
 * news.js — News & Sentiment tab
 * Fetches /api/news/<symbol> and renders headlines with sentiment tags.
 */

function _newsEsc(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
}

function _sentimentBadge(score) {
    if (score > 0)  return '<span class="news-tag news-bull">▲ Bullish</span>';
    if (score < 0)  return '<span class="news-tag news-bear">▼ Bearish</span>';
    return '<span class="news-tag news-neutral">● Neutral</span>';
}

async function initNews() {
    const area = document.getElementById('news-area');
    if (!area) return;
    const sym = state.activeSymbol;
    const titleEl = document.getElementById('news-symbol');
    const listEl  = document.getElementById('news-list');
    if (titleEl) titleEl.textContent = sym ? sym : '—';

    if (!sym) {
        if (listEl) listEl.innerHTML = '<div class="news-empty">Select a symbol from the sidebar to load news.</div>';
        return;
    }

    if (listEl) listEl.innerHTML = '<div class="news-empty"><span class="spinner"></span> Loading headlines…</div>';

    try {
        const articles = await apiFetch(`${API}/news/${encodeURIComponent(sym)}`);
        if (!Array.isArray(articles) || articles.length === 0) {
            if (listEl) listEl.innerHTML = '<div class="news-empty">No recent headlines found.</div>';
            return;
        }
        const rows = articles.map(a => `
            <a class="news-item" href="${_newsEsc(a.link || '#')}" target="_blank" rel="noopener noreferrer">
                <div class="news-item-head">
                    ${_sentimentBadge(a.sentiment ?? 0)}
                    <span class="news-source">${_newsEsc(a.source || '')}</span>
                    <span class="news-date">${_newsEsc(a.pub_date || '')}</span>
                </div>
                <div class="news-title">${_newsEsc(a.title || '')}</div>
                ${a.summary ? `<div class="news-summary">${_newsEsc(a.summary)}</div>` : ''}
            </a>
        `).join('');
        if (listEl) listEl.innerHTML = rows;
    } catch (e) {
        if (listEl) listEl.innerHTML = `<div class="news-empty">Failed to load news: ${_newsEsc(e.message || e)}</div>`;
    }
}
