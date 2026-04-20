const CACHE_NAME = 'sp-v8';
const SHELL_URLS = [
    '/static/style.css',
    '/static/icon.svg',
    '/static/manifest.json',
    '/static/offline.js',
    '/offline',
];

// Install: cache shell + offline page
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

self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // Skip non-GET
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

    // API/data calls: network-only
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ai/') || url.pathname.startsWith('/practice/')) {
        return;
    }

    // HTML pages: network-first, cache fallback, offline page
    if (event.request.headers.get('Accept')?.includes('text/html')) {
        event.respondWith(
            fetch(event.request)
                .then(resp => {
                    // Cache successful HTML responses
                    if (resp.status === 200) {
                        const clone = resp.clone();
                        caches.open(CACHE_NAME).then(c => c.put(event.request, clone));
                    }
                    return resp;
                })
                .catch(() =>
                    // Offline: try cache first, then offline page
                    caches.match(event.request)
                        .then(cached => cached || caches.match('/offline'))
                )
        );
        return;
    }
});
