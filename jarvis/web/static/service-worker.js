// Mira PWA service worker: cache the app shell so it installs and opens
// instantly. API calls (/api/*) always go to the network — never cached.

const CACHE = "mira-shell-v2";
const SHELL = [
  "/",
  "/static/styles.css",
  "/static/app.js",
  "/static/icon.svg",
  "/manifest.webmanifest",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Never intercept API traffic — it must be live and may stream.
  if (url.pathname.startsWith("/api/") || event.request.method !== "GET") {
    return;
  }
  // App shell: cache-first, falling back to (and refreshing from) the network.
  event.respondWith(
    caches.match(event.request).then((cached) => {
      const network = fetch(event.request)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(event.request, copy));
          }
          return res;
        })
        .catch(() => cached);
      return cached || network;
    })
  );
});
