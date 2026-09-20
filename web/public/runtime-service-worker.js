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
        .catch(async () => {
          const cached = await caches.match("/index.html", { ignoreVary: true });
          return cached ?? offlineNavigationResponse();
        }),
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

function offlineNavigationResponse() {
  return new Response(
    `<!doctype html>
<html lang="zh-Hant">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>目前離線</title>
  </head>
  <body>
    <main>
      <h1>目前無法載入此頁</h1>
      <p>裝置已離線，且這個頁面尚未儲存在裝置上。恢復網路後請重新整理。</p>
    </main>
  </body>
</html>`,
    {
      status: 503,
      statusText: "Service Unavailable",
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "no-store",
      },
    },
  );
}
