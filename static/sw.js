// Service Worker — الميزان القانوني PWA
// يوفر: تخزين مؤقت للملفات الثابتة + صفحة offline
'use strict';

const CACHE_NAME    = 'mizan-legal-v1';
const OFFLINE_URL   = '/static/offline.html';

const STATIC_ASSETS = [
  '/',
  '/static/app.js',
  '/static/style.css',
  '/static/manifest.json',
  OFFLINE_URL,
];

// ── Install: pre-cache static assets ──
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(
        STATIC_ASSETS.filter(url => url !== OFFLINE_URL)   // offline.html optional
      ).catch(() => {
        // If some assets fail (e.g. offline.html not created yet), continue anyway
      });
    }).then(() => self.skipWaiting())
  );
});

// ── Activate: clean up old caches ──
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME)
          .map(k => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// ── Fetch: stale-while-revalidate for static, network-first for API ──
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // API requests — always go to network (no cache)
  if (url.pathname.startsWith('/api/')) {
    return;   // let browser handle normally
  }

  // Static assets — cache-first with network fallback
  if (url.pathname.startsWith('/static/') || url.pathname === '/') {
    event.respondWith(
      caches.match(event.request).then(cached => {
        const networkFetch = fetch(event.request).then(response => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return response;
        }).catch(() => null);

        return cached || networkFetch || offlineFallback(url.pathname);
      })
    );
  }
});

function offlineFallback(pathname) {
  if (pathname === '/' || pathname.endsWith('.html')) {
    return caches.match(OFFLINE_URL).then(r => r || new Response(
      '<html dir="rtl"><body style="font-family:sans-serif;text-align:center;padding:40px">' +
      '<h2>لا يوجد اتصال بالإنترنت</h2>' +
      '<p>يرجى التحقق من اتصالك والمحاولة مجدداً.</p>' +
      '</body></html>',
      { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    ));
  }
  return new Response('', { status: 503 });
}
