/**
 * Optional this-ticker news date markers on the daily price pane.
 *
 * Copy: "News dates on the daily pane" — headlines, not a rating.
 * Headlines from GET /api/news/<symbol>. Off by default. Merged into the
 * same setMarkers() array as EP / volume-climax in charts.js — Lightweight
 * Charts replaces the whole marker set, so this file never calls setMarkers
 * itself.
 *
 * Isolated so chart specialists can keep editing packs / legend / prefetch
 * without a rewrite here. charts.js only calls collectNewsPriceMarkers()
 * (sync merge) and applyNewsMarkersIfOn() (fetch when the pill is on).
 */

const NEWS_MARKERS_MAX = 12;
const NEWS_HEADLINE_COLOR = '#c4b5fd';
const NEWS_EARNINGS_COLOR = '#fb7185';

let newsMarkersOn = false;
let _newsMarkerCache = { symbol: '', articles: [] };
let _newsMarkerSeq = 0;

function newsMarkersIsOn() {
    return !!newsMarkersOn;
}

function getNewsMarkersOn() {
    return newsMarkersIsOn();
}

function setNewsMarkersOn(on, opts) {
    opts = opts || {};
    newsMarkersOn = !!on;
    _syncNewsMarkersPill();
    if (opts.apply !== false) {
        if (!newsMarkersOn) {
            if (typeof applyPriceMarkers === 'function') applyPriceMarkers('daily');
        } else {
            applyNewsMarkersIfOn();
        }
    }
    if (opts.persist && typeof persistOverlays === 'function') persistOverlays();
    return newsMarkersOn;
}

function _newsMarkersApi() {
    return (typeof API !== 'undefined' && API) ? API : '/api';
}

async function _newsMarkersGet(path) {
    if (typeof apiFetch === 'function') return apiFetch(path);
    const res = await fetch(path);
    if (!res.ok) {
        let msg = res.statusText;
        try {
            const body = await res.json();
            if (body && body.error) msg = body.error;
        } catch (_) {}
        throw new Error(msg || 'news-markers fetch failed');
    }
    return res.json();
}

function _fmtNyDate(d) {
    try {
        const parts = new Intl.DateTimeFormat('en-CA', {
            timeZone: 'America/New_York',
            year: 'numeric',
            month: '2-digit',
            day: '2-digit',
        }).formatToParts(d);
        const get = t => {
            const hit = parts.find(p => p.type === t);
            return hit ? hit.value : '';
        };
        const y = get('year');
        const m = get('month');
        const day = get('day');
        if (y && m && day) return `${y}-${m}-${day}`;
    } catch (_) { /* Intl / timezone missing */ }
    return d.toISOString().slice(0, 10);
}

function newsDateKey(publishTime) {
    if (publishTime == null || publishTime === '') return null;
    if (typeof publishTime === 'number' && Number.isFinite(publishTime)) {
        const ms = publishTime < 1e12 ? publishTime * 1000 : publishTime;
        const d = new Date(ms);
        return isNaN(d.getTime()) ? null : _fmtNyDate(d);
    }
    const raw = String(publishTime).trim();
    const parsed = new Date(raw);
    if (!isNaN(parsed.getTime())) return _fmtNyDate(parsed);
    const m = raw.match(/^(\d{4}-\d{2}-\d{2})/);
    return m ? m[1] : null;
}

function titleLooksLikeEarnings(title) {
    return /\b(earnings|results)\b/i.test(String(title || ''));
}

function buildNewsPriceMarkers(articles, rows, enabled) {
    if (!enabled) return [];
    const list = Array.isArray(articles) ? articles : [];
    const bars = Array.isArray(rows) ? rows : [];
    const barDates = Object.create(null);
    for (let i = 0; i < bars.length; i++) {
        const row = bars[i];
        const key = String(row && row.date != null ? row.date : '').slice(0, 10);
        if (key) barDates[key] = row.date;
    }
    const byDate = Object.create(null);
    for (let i = 0; i < list.length; i++) {
        const art = list[i] || {};
        const key = newsDateKey(art.publish_time);
        if (!key || barDates[key] == null) continue;
        const ts = String(art.publish_time || '');
        const earnings = titleLooksLikeEarnings(art.title);
        const prev = byDate[key];
        if (!prev || ts > prev.ts) {
            byDate[key] = { ts, earnings: earnings || !!(prev && prev.earnings) };
        } else if (earnings) {
            prev.earnings = true;
        }
    }
    const keys = Object.keys(byDate).sort((a, b) => {
        const tsCmp = String(byDate[b].ts).localeCompare(String(byDate[a].ts));
        return tsCmp !== 0 ? tsCmp : b.localeCompare(a);
    });
    const picked = keys.slice(0, NEWS_MARKERS_MAX);
    picked.sort();
    return picked.map(key => {
        const earnings = !!(byDate[key] && byDate[key].earnings);
        return {
            time: barDates[key],
            position: 'belowBar',
            color: earnings ? NEWS_EARNINGS_COLOR : NEWS_HEADLINE_COLOR,
            shape: 'circle',
            text: earnings ? 'E' : 'N',
            size: 1,
        };
    });
}

function collectNewsPriceMarkers(rows) {
    if (!newsMarkersOn) return [];
    const sym = _activeNewsSymbol();
    if (!sym || _newsMarkerCache.symbol !== sym) return [];
    return buildNewsPriceMarkers(_newsMarkerCache.articles, rows, true);
}

function _syncNewsMarkersPill() {
    const pill = document.getElementById('pill-news-markers');
    if (!pill) return;
    pill.classList.toggle('active-news-markers', newsMarkersOn);
    pill.setAttribute('aria-pressed', newsMarkersOn ? 'true' : 'false');
}

function _activeNewsSymbol() {
    return (typeof state !== 'undefined' && state.activeSymbol)
        ? String(state.activeSymbol).toUpperCase()
        : '';
}

async function applyNewsMarkersIfOn() {
    const seq = ++_newsMarkerSeq;
    _syncNewsMarkersPill();
    if (!newsMarkersOn) return;
    const sym = _activeNewsSymbol();
    if (!sym) {
        _newsMarkerCache = { symbol: '', articles: [] };
        if (typeof applyPriceMarkers === 'function') applyPriceMarkers('daily');
        return;
    }
    if (_newsMarkerCache.symbol === sym && typeof applyPriceMarkers === 'function') {
        applyPriceMarkers('daily');
    }
    try {
        const data = await _newsMarkersGet(`${_newsMarkersApi()}/news/${encodeURIComponent(sym)}`);
        if (seq !== _newsMarkerSeq) return;
        _newsMarkerCache = {
            symbol: sym,
            articles: (data && data.articles) ? data.articles : [],
        };
        if (typeof applyPriceMarkers === 'function') applyPriceMarkers('daily');
    } catch (_) {
        if (seq !== _newsMarkerSeq) return;
        if (_newsMarkerCache.symbol !== sym) {
            _newsMarkerCache = { symbol: '', articles: [] };
            if (typeof applyPriceMarkers === 'function') applyPriceMarkers('daily');
        }
    }
}

function toggleNewsMarkers() {
    return setNewsMarkersOn(!newsMarkersOn, { persist: true });
}

if (typeof document !== 'undefined' && document.addEventListener) {
    document.addEventListener('DOMContentLoaded', () => {
        const pill = document.getElementById('pill-news-markers');
        if (!pill) return;
        pill.addEventListener('click', () => toggleNewsMarkers());
        _syncNewsMarkersPill();
    });
}
