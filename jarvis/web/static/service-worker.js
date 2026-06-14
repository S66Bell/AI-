// Mira PWA service worker: cache the app shell so it installs and opens
// instantly. API calls (/api/*) always go to the network — never cached.

const CACHE = "mira-shell-v5";
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

// ── Web Push: proactive briefings ──────────────────────────────────────
// The server pushes a JSON {title, body}; we surface it as a notification.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = {};
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "Mira", {
      body: data.body || "",
      icon: "/static/icon.svg",
      badge: "/static/icon.svg",
      data: { url: "/" },
    })
  );
});

// Tapping a notification focuses an open Mira tab, or opens one.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if ("focus" in client) return client.focus();
      }
      return clients.openWindow("/");
    })
  );
});
