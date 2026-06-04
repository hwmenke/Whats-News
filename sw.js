/**
 * sw.js — minimal app-shell service worker for the FinDash PWA.
 *
 * Caches the static shell so the dashboard opens instantly on a phone,
 * even before the network round-trip. API calls (anything under /api/)
 * always go to the network so prices stay fresh.
 */

const CACHE = 'findash-shell-v1';
const SHELL = [
    '/',
    '/index.html',
    '/styles/main.css',
    '/scripts/app.js',
    '/scripts/charts.js',
    '/scripts/scanner.js',
    '/scripts/trend_chart.js',
    '/scripts/data_manager.js',
    '/scripts/social_trends.js',
    '/manifest.webmanifest',
];

self.addEventListener('install', e => {
    self.skipWaiting();
    e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL).catch(() => null)));
});

self.addEventListener('activate', e => {
    e.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)));
        await self.clients.claim();
    })());
});

self.addEventListener('fetch', e => {
    const url = new URL(e.request.url);
    // Never cache API: always go to network so prices/trends are live.
    if (url.pathname.startsWith('/api/')) return;
    if (e.request.method !== 'GET') return;
    e.respondWith((async () => {
        const cached = await caches.match(e.request);
        if (cached) return cached;
        try {
            const fresh = await fetch(e.request);
            if (fresh && fresh.ok && url.origin === location.origin) {
                const copy = fresh.clone();
                caches.open(CACHE).then(c => c.put(e.request, copy));
            }
            return fresh;
        } catch {
            return cached || Response.error();
        }
    })());
});
