// NEXUS Service Worker — cache seguro (não cacheia API nem HTML)
// Versão muda a cada deploy para forçar refresh do SW no browser
const CACHE_VERSION = 'nexus-v20250501';
const STATIC_ASSETS = [
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/manifest.json'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_VERSION).then(cache => {
      // Só cacheia assets estáticos — nunca HTML nem API
      return Promise.allSettled(STATIC_ASSETS.map(url =>
        cache.add(url).catch(() => {}) // falha silenciosa por asset individual
      ));
    })
  );
  self.skipWaiting(); // ativa imediatamente sem esperar janelas fecharem
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys
        .filter(k => k !== CACHE_VERSION)
        .map(k => {
          console.log('[SW] Removendo cache antiga:', k);
          return caches.delete(k);
        })
      )
    )
  );
  self.clients.claim(); // toma controlo imediato de todas as abas
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);

  // ── REGRA 1: Nunca interceptar chamadas de API ──────────────────────────
  // Se o SW serve uma resposta em cache de /api/*, o frontend recebe HTML
  // em vez de JSON e aparece "Resposta inválida (500)"
  if (url.pathname.startsWith('/api/')) return;

  // ── REGRA 2: Só interceptar GET ────────────────────────────────────────
  if (e.request.method !== 'GET') return;

  // ── REGRA 3: Nunca cachear HTML (index.html e raiz) ─────────────────────
  // O HTML tem sempre a versão mais recente do frontend após deploy
  if (url.pathname === '/' ||
      url.pathname === '' ||
      url.pathname.endsWith('.html') ||
      url.pathname.endsWith('sw.js')) {
    return; // deixa o browser ir sempre à rede
  }

  // ── REGRA 4: Cache-first para assets estáticos (ícones, manifest) ──────
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(resp => {
        if (resp && resp.ok && resp.status === 200) {
          const clone = resp.clone();
          caches.open(CACHE_VERSION).then(cache => cache.put(e.request, clone));
        }
        return resp;
      }).catch(() => cached); // offline: serve cache se existir
    })
  );
});

// ── Push notifications ──────────────────────────────────────────────────────
self.addEventListener('push', e => {
  const data = e.data ? e.data.json() : {};
  e.waitUntil(
    self.registration.showNotification(data.title || 'NEXUS', {
      body: data.body || 'Nova mensagem da tua IA pessoal',
      icon: '/static/icon-192.png',
      badge: '/static/icon-192.png',
      vibrate: [200, 100, 200],
      data: { url: data.url || '/' }
    })
  );
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(clients.openWindow(e.notification.data.url));
});
