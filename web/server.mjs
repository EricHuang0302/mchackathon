import { createReadStream, statSync } from "node:fs";
import { createServer, request as upstreamRequest } from "node:http";
import { connect } from "node:net";
import { extname, join, normalize } from "node:path";

const port = Number(process.env.PORT ?? 8080);
const root = process.env.STATIC_ROOT ?? "/srv/web/dist";
const upstream = new URL(process.env.API_UPSTREAM ?? "http://api:8080");
const apiPath = (path) => path === "/healthz" || path.startsWith("/v1/");
const contentTypes = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon" };

const proxy = (req, res) => {
  const forwarded = upstreamRequest({ hostname: upstream.hostname, port: upstream.port, path: req.url, method: req.method, headers: { ...req.headers, host: upstream.host } }, (response) => {
    res.writeHead(response.statusCode ?? 502, response.headers); response.pipe(res);
  });
  forwarded.on("error", () => { res.writeHead(502, { "content-type": "application/json" }); res.end(JSON.stringify({ error: { code: "unavailable", message: "API unavailable" } })); });
  req.pipe(forwarded);
};

const server = createServer((req, res) => {
  const pathname = new URL(req.url ?? "/", "http://localhost").pathname;
  if (apiPath(pathname)) return proxy(req, res);
  let requested = normalize(decodeURIComponent(pathname)).replace(/^(\.\.(\/|\\|$))+/, "");
  let file = join(root, requested === "/" ? "index.html" : requested);
  try { if (!statSync(file).isFile()) file = join(root, "index.html"); } catch { file = join(root, "index.html"); }
  res.writeHead(200, { "content-type": contentTypes[extname(file)] ?? "application/octet-stream", "cache-control": extname(file) === ".html" ? "no-cache" : "public, max-age=31536000, immutable" });
  createReadStream(file).pipe(res);
});

server.on("upgrade", (req, socket, head) => {
  const pathname = new URL(req.url ?? "/", "http://localhost").pathname;
  if (!apiPath(pathname)) return socket.destroy();
  const target = connect(Number(upstream.port || 80), upstream.hostname, () => {
    const headers = Object.entries(req.headers).filter(([name]) => name.toLowerCase() !== "host").map(([name, value]) => `${name}: ${Array.isArray(value) ? value.join(", ") : value}`).join("\r\n");
    target.write(`${req.method} ${req.url} HTTP/${req.httpVersion}\r\nHost: ${upstream.host}\r\n${headers}\r\n\r\n`);
    if (head.length) target.write(head);
    socket.pipe(target).pipe(socket);
  });
  target.on("error", () => socket.destroy());
});

server.listen(port, "0.0.0.0", () => console.log(`web listening on ${port}`));
