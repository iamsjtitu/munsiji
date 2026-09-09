/* Munsiji service worker — network-first (never serves stale code), cache fallback for offline. */
const CACHE = "munsiji-shell-v1";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  const isNavigation = req.mode === "navigate";
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res && res.ok && res.type === "basic") {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(isNavigation ? "/index.html" : req, copy));
        }
        return res;
      })
      .catch(async () => {
        const cached = await caches.match(isNavigation ? "/index.html" : req);
        return cached || new Response("Offline — internet check karo", { status: 503, headers: { "Content-Type": "text/plain; charset=utf-8" } });
      }),
  );
});
