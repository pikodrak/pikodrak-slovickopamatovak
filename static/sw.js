const CACHE_NAME = 'sp-v2';
const SHELL_URLS = [
    '/static/style.css',
    '/static/icon.svg',
    '/static/manifest.json',
    '/static/offline.js',
];

// Install: cache shell assets
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_URLS))
    );
    self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
        )
    );
    self.clients.claim();
});

// Fetch strategy:
// - Static assets: cache-first
// - API calls (/api/, /ai/, /practice/log): network-only (queued offline)
// - HTML pages: network-first, fallback to cache, then offline page
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // Skip non-GET for caching (POST results handled by offline queue in app JS)
    if (event.request.method !== 'GET') return;

    // Static assets: cache-first
    if (url.pathname.startsWith('/static/')) {
        event.respondWith(
            caches.match(event.request).then(cached =>
                cached || fetch(event.request).then(resp => {
                    const clone = resp.clone();
                    caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
                    return resp;
                })
            )
        );
        return;
    }

    // HTML pages: network-first, cache fallback
    if (event.request.headers.get('Accept')?.includes('text/html')) {
        event.respondWith(
            fetch(event.request)
                .then(resp => {
                    const clone = resp.clone();
                    caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
                    return resp;
                })
                .catch(() =>
                    caches.match(event.request).then(cached =>
                        cached || caches.match('/dashboard') || new Response(
                            '<html><body style="font-family:sans-serif;text-align:center;padding:60px 20px;">' +
                            '<h1 style="color:#e65100;">Offline</h1>' +
                            '<p>Tato stránka není dostupná offline.</p>' +
                            '<p><a href="/dashboard">Zkusit znovu</a></p></body></html>',
                            {headers: {'Content-Type': 'text/html; charset=utf-8'}}
                        )
                    )
                )
        );
        return;
    }
});
