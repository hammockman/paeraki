// Paeraki Vessel Monitor Service Worker - Cache Invalidation & Self-Unregister
// This worker clears all legacy caches and unregisters itself to prevent stale asset serving.

self.addEventListener('install', (event) => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(keys.map((key) => {
        console.log('[PWA SW] Purging cache:', key);
        return caches.delete(key);
      }));
    }).then(() => {
      console.log('[PWA SW] All legacy caches cleared. Unregistering service worker.');
      return self.registration.unregister();
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Always fetch directly from network; never serve stale cached assets
  event.respondWith(fetch(event.request));
});
