const CACHE_NAME = "first-aid-copilot-approved-v2";
const EXCLUDED_PATHS = ["/v1/", "/shares/", "/share-sessions"];

self.addEventListener("install", (event) => {
  event.waitUntil(self.skipWaiting());
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((names) =>
        Promise.all(
          names
            .filter(
              (name) =>
                name.startsWith("first-aid-copilot-approved-") &&
                name !== CACHE_NAME,
            )
            .map((name) => caches.delete(name)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (event) => {
  if (event.data?.type === "activate.update") {
    event.waitUntil(self.skipWaiting());
    return;
  }
  if (event.data?.type !== "cache.approved" || !Array.isArray(event.data.assets)) {
    return;
  }

  const requests = event.data.assets
    .map(toApprovedRequest)
    .filter((request) => request !== undefined);
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(requests)));
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || !isApprovedUrl(new URL(request.url))) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.put("/index.html", copy)));
          }
          return response;
        })
        .catch(() => caches.match("/index.html", { ignoreVary: true })),
    );
    return;
  }

  event.respondWith(
    caches
      .match(request, { ignoreVary: true })
      .then((cached) => {
        if (cached) return cached;
        return undefined;
      })
      .then((response) => response ?? fetch(request)),
  );
});

function toApprovedRequest(value) {
  if (typeof value !== "string") return undefined;
  const url = new URL(value, self.location.origin);
  if (!isApprovedUrl(url)) return undefined;
  return new Request(url, { credentials: "same-origin", cache: "reload" });
}

function isApprovedUrl(url) {
  return (
    url.origin === self.location.origin &&
    url.search === "" &&
    !EXCLUDED_PATHS.some((path) => url.pathname.startsWith(path))
  );
}
