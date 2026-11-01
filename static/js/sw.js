// ComicVault Service Worker
const CACHE_NAME = 'comicvault-v1';
const STATIC_CACHE = 'comicvault-static-v1';

// Assets to cache
const STATIC_ASSETS = [
    '/',
    '/static/css/main.css',
    '/static/js/main.js',
    '/static/js/bottom_nav.js',
    '/static/images/logo.png',
    '/static/images/default-cover.jpg'
];

// Install event
self.addEventListener('install', event => {
    console.log('Service Worker: Installing...');
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then(cache => {
                console.log('Service Worker: Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate event
self.addEventListener('activate', event => {
    console.log('Service Worker: Activating...');
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cache => {
                    if (cache !== STATIC_CACHE && cache !== CACHE_NAME) {
                        console.log('Service Worker: Clearing old cache');
                        return caches.delete(cache);
                    }
                })
            );
        })
    );
    return self.clients.claim();
});

// Fetch event
self.addEventListener('fetch', event => {
    // Skip non-GET requests
    if (event.request.method !== 'GET') {
        return;
    }

    event.respondWith(
        caches.match(event.request)
            .then(response => {
                // Return cached version or fetch from network
                return response || fetch(event.request)
                    .then(fetchResponse => {
                        // Don't cache non-successful responses
                        if (!fetchResponse || fetchResponse.status !== 200 || fetchResponse.type !== 'basic') {
                            return fetchResponse;
                        }

                        // Clone response for caching
                        const responseToCache = fetchResponse.clone();
                        
                        // Cache API responses
                        if (event.request.url.includes('/api/')) {
                            caches.open(CACHE_NAME)
                                .then(cache => {
                                    cache.put(event.request, responseToCache);
                                });
                        }
                        
                        return fetchResponse;
                    });
            })
            .catch(() => {
                // Offline fallback for API requests
                if (event.request.url.includes('/api/')) {
                    return new Response(
                        JSON.stringify({ error: 'Offline - Service Unavailable' }),
                        { 
                            status: 503,
                            headers: { 'Content-Type': 'application/json' }
                        }
                    );
                }
                
                // Return offline page for navigation requests
                if (event.request.mode === 'navigate') {
                    return caches.match('/');
                }
            })
    );
});

// Background sync for offline actions
self.addEventListener('sync', event => {
    if (event.tag === 'background-sync') {
        console.log('Service Worker: Background sync triggered');
        event.waitUntil(doBackgroundSync());
    }
});

async function doBackgroundSync() {
    // Sync queued actions when back online
    const actions = await getQueuedActions();
    
    for (const action of actions) {
        try {
            await fetch(action.url, {
                method: action.method,
                headers: action.headers,
                body: action.body
            });
            
            // Remove synced action from queue
            await removeQueuedAction(action.id);
        } catch (error) {
            console.error('Failed to sync action:', error);
        }
    }
}

// IndexedDB helpers for offline queue
async function getQueuedActions() {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open('ComicVaultOffline', 1);
        
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
            const db = request.result;
            const transaction = db.transaction(['actions'], 'readonly');
            const store = transaction.objectStore('actions');
            const getAll = store.getAll();
            
            getAll.onsuccess = () => resolve(getAll.result);
            getAll.onerror = () => reject(getAll.error);
        };
        
        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains('actions')) {
                db.createObjectStore('actions', { keyPath: 'id', autoIncrement: true });
            }
        };
    });
}

async function removeQueuedAction(id) {
    return new Promise((resolve, reject) => {
        const request = indexedDB.open('ComicVaultOffline', 1);
        
        request.onerror = () => reject(request.error);
        request.onsuccess = () => {
            const db = request.result;
            const transaction = db.transaction(['actions'], 'readwrite');
            const store = transaction.objectStore('actions');
            const deleteRequest = store.delete(id);
            
            deleteRequest.onsuccess = () => resolve();
            deleteRequest.onerror = () => reject(deleteRequest.error);
        };
    });
}

// Push notifications
self.addEventListener('push', event => {
    const options = {
        body: event.data.text(),
        icon: '/static/images/logo.png',
        badge: '/static/images/badge.png',
        vibrate: [100, 50, 100],
        data: {
            dateOfArrival: Date.now(),
            primaryKey: '1'
        },
        actions: [
            {
                action: 'explore',
                title: 'Explore',
                icon: '/static/images/checkmark.png'
            },
            {
                action: 'close',
                title: 'Close',
                icon: '/static/images/xmark.png'
            }
        ]
    };

    event.waitUntil(
        self.registration.showNotification('ComicVault', options)
    );
});

// Notification click
self.addEventListener('notificationclick', event => {
    event.notification.close();
    
    if (event.action === 'explore') {
        event.waitUntil(
            clients.openWindow('/')
        );
    }
});