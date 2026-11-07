const CACHE_NAME = "fph-connect-shell-v1";
const APP_SHELL = [
    "/",
    "/offline",
    "/manifest.webmanifest",
    "/static/css/style.css",
    "/static/js/app.js",
    "/static/icons/icon.svg",
];

self.addEventListener("install", event => {
    event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(APP_SHELL)));
    self.skipWaiting();
});

self.addEventListener("activate", event => {
    event.waitUntil(
        caches.keys().then(keys => Promise.all(
            keys.filter(key => key.startsWith("fph-connect-shell-") && key !== CACHE_NAME)
                .map(key => caches.delete(key)),
        )),
    );
    self.clients.claim();
});

self.addEventListener("fetch", event => {
    const url = new URL(event.request.url);
    if (event.request.method !== "GET" || url.origin !== self.location.origin ||
        url.pathname.startsWith("/api/") || url.pathname === "/service-worker.js") {
        return;
    }

    if (event.request.mode === "navigate") {
        event.respondWith(fetch(event.request).catch(async () => {
            const cachedPage = await caches.match(event.request);
            return cachedPage || caches.match("/offline");
        }));
        return;
    }

    if (url.pathname.startsWith("/static/") || url.pathname === "/manifest.webmanifest") {
        event.respondWith(caches.match(event.request).then(cached =>
            cached || fetch(event.request).then(response => {
                if (response.ok) {
                    const copy = response.clone();
                    caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
                }
                return response;
            }),
        ));
    }
});
