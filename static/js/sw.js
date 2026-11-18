// Cache only public application assets. API and HTML responses remain online.
const STATIC_CACHE = 'comicvault-static-v2';
const STATIC_ASSETS = [
    '/static/css/main.css',
    '/static/css/bottom_nav.css',
    '/static/js/main.js',
    '/static/js/bottom_nav.js',
    '/static/js/csrf.js',
    '/static/images/default-cover.svg'
];

self.addEventListener('install', event => {
    event.waitUntil(caches.open(STATIC_CACHE)
        .then(cache => cache.addAll(STATIC_ASSETS))
        .then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
    event.waitUntil(caches.keys().then(names => Promise.all(
        names.filter(name => name.startsWith('comicvault-') && name !== STATIC_CACHE)
            .map(name => caches.delete(name))
    )).then(() => self.clients.claim()));
});

self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);
    if (event.request.method !== 'GET' || url.origin !== self.location.origin ||
        !STATIC_ASSETS.includes(url.pathname) || url.search) {
        return;
    }
    event.respondWith(caches.open(STATIC_CACHE).then(async cache => {
        const cached = await cache.match(event.request);
        if (cached) return cached;
        const response = await fetch(event.request);
        if (response.ok && response.type === 'basic') {
            await cache.put(event.request, response.clone());
        }
        return response;
    }));
});
