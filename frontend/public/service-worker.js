// Legacy cache name kept for compatibility with existing installations.
const CACHE = "frequency-shell-20261011-pixel";
const SHELL = [
  "/",
  "/site.html",
  "/static/site.css?v=7",
  "/static/generated/site.js?v=1",
  "/static/frequency-cover-whatsapp.png",
  "/app",
  "/monitor",
  "/offline.html",
  "/frequency.webmanifest",
  "/monitor.webmanifest",
  "/static/styles.css?v=heatmap-20261005",
  "/static/meta-pixel.js?v=20261011",
  "/static/i18n.js?v=oauth-20261010",
  "/static/app.js?v=backup-save-device-20261004-v7-oauth-20261010",
  "/static/monitor.css",
  "/static/monitor.js?v=20261010-camera-recovery",
  "/static/monitor-legacy.js?v=20261005",
  "/static/brand-mark.svg",
  "/static/brand-mark-light.svg"
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(request).then((cached) => cached || caches.match("/offline.html"))));
    return;
  }
  if (url.pathname.startsWith("/static/") || url.pathname.endsWith(".webmanifest")) {
    event.respondWith(caches.match(request).then((cached) => cached || fetch(request).then((response) => {
      const copy = response.clone();
      caches.open(CACHE).then((cache) => cache.put(request, copy));
      return response;
    })));
  }
});



