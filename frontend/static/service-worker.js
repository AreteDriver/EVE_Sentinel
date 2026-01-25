// EVE Sentinel Service Worker
// Provides offline support and caching for the PWA

const CACHE_NAME = 'eve-sentinel-v1';
const OFFLINE_URL = '/offline.html';

// Assets to cache on install
const PRECACHE_ASSETS = [
  '/',
  '/static/css/sentinel.css',
  '/static/manifest.json',
  '/offline.html',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.2/font/bootstrap-icons.min.css',
  'https://unpkg.com/htmx.org@1.9.10',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js'
];

// Install event - cache core assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[ServiceWorker] Pre-caching assets');
        return cache.addAll(PRECACHE_ASSETS);
      })
      .then(() => self.skipWaiting())
  );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== CACHE_NAME)
          .map((name) => {
            console.log('[ServiceWorker] Removing old cache:', name);
            return caches.delete(name);
          })
      );
    }).then(() => self.clients.claim())
  );
});

// Fetch event - network first, fallback to cache
self.addEventListener('fetch', (event) => {
  // Skip non-GET requests
  if (event.request.method !== 'GET') {
    return;
  }

  // Skip API requests (don't cache dynamic data)
  if (event.request.url.includes('/api/')) {
    event.respondWith(
      fetch(event.request).catch(() => {
        return new Response(
          JSON.stringify({ error: 'Offline - API unavailable' }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
          }
        );
      })
    );
    return;
  }

  // For navigation requests, try network first
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          // Cache successful responses
          if (response.ok) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(event.request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          // Try cache, then offline page
          return caches.match(event.request)
            .then((cached) => cached || caches.match(OFFLINE_URL));
        })
    );
    return;
  }

  // For other requests, try cache first, then network
  event.respondWith(
    caches.match(event.request)
      .then((cached) => {
        if (cached) {
          // Return cached version and update in background
          event.waitUntil(
            fetch(event.request)
              .then((response) => {
                if (response.ok) {
                  caches.open(CACHE_NAME).then((cache) => {
                    cache.put(event.request, response);
                  });
                }
              })
              .catch(() => {})
          );
          return cached;
        }

        // Not in cache, fetch from network
        return fetch(event.request)
          .then((response) => {
            if (response.ok) {
              const responseClone = response.clone();
              caches.open(CACHE_NAME).then((cache) => {
                cache.put(event.request, responseClone);
              });
            }
            return response;
          });
      })
  );
});

// Background sync for offline analysis requests
self.addEventListener('sync', (event) => {
  if (event.tag === 'sync-analysis') {
    event.waitUntil(syncPendingAnalysis());
  }
});

async function syncPendingAnalysis() {
  // Get pending analysis requests from IndexedDB
  const pending = await getPendingRequests();

  for (const request of pending) {
    try {
      await fetch('/api/v1/analyze/' + request.characterId, {
        method: 'GET'
      });
      await removePendingRequest(request.id);
    } catch (error) {
      console.log('[ServiceWorker] Sync failed, will retry:', error);
    }
  }
}

// Placeholder functions for IndexedDB operations
async function getPendingRequests() {
  return [];
}

async function removePendingRequest(id) {
  return;
}

// Push notification support
self.addEventListener('push', (event) => {
  if (!event.data) return;

  const data = event.data.json();
  const options = {
    body: data.body || 'New recruitment alert',
    icon: '/static/icons/icon-192x192.png',
    badge: '/static/icons/icon-96x96.png',
    tag: data.tag || 'eve-sentinel-notification',
    data: data.url || '/',
    actions: [
      { action: 'view', title: 'View Report' },
      { action: 'dismiss', title: 'Dismiss' }
    ]
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'EVE Sentinel', options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  if (event.action === 'dismiss') return;

  event.waitUntil(
    clients.openWindow(event.notification.data || '/')
  );
});
