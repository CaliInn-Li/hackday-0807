import http from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, join, normalize, resolve, sep } from "node:path";

const host = process.env.NAQI_GATEWAY_HOST ?? "0.0.0.0";
const port = Number(process.env.NAQI_GATEWAY_PORT ?? "18000");
const apiHost = process.env.NAQI_GATEWAY_API_HOST ?? "127.0.0.1";
const apiPort = Number(process.env.NAQI_GATEWAY_API_PORT ?? "18080");
const staticRoot = resolve(process.env.NAQI_GATEWAY_STATIC_ROOT ?? "../frontend/dist");

const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".glb": "model/gltf-binary",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".map": "application/json; charset=utf-8",
  ".mp4": "video/mp4",
  ".npz": "application/octet-stream",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
};

function proxyApi(request, response) {
  const upstreamPath = request.url.slice(4) || "/";
  const upstream = http.request(
    {
      host: apiHost,
      port: apiPort,
      method: request.method,
      path: upstreamPath,
      headers: { ...request.headers, host: `${apiHost}:${apiPort}` },
    },
    (upstreamResponse) => {
      response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
      upstreamResponse.pipe(response);
    },
  );
  upstream.on("error", (error) => {
    if (!response.headersSent) {
      response.writeHead(502, { "content-type": "application/json; charset=utf-8" });
    }
    response.end(JSON.stringify({ detail: "API upstream unavailable", error: error.code }));
  });
  request.pipe(upstream);
}

function serveStatic(request, response) {
  if (request.method !== "GET" && request.method !== "HEAD") {
    response.writeHead(405, { allow: "GET, HEAD" });
    response.end();
    return;
  }

  const pathname = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
  const relativePath = normalize(pathname).replace(/^[/\\]+/, "");
  let candidate = resolve(join(staticRoot, relativePath || "index.html"));
  if (!candidate.startsWith(`${staticRoot}${sep}`) && candidate !== staticRoot) {
    response.writeHead(403);
    response.end("Forbidden");
    return;
  }
  if (!existsSync(candidate) || !statSync(candidate).isFile()) {
    candidate = join(staticRoot, "index.html");
  }
  if (!existsSync(candidate)) {
    response.writeHead(503);
    response.end("Frontend build is missing");
    return;
  }

  response.writeHead(200, {
    "content-type": mimeTypes[extname(candidate).toLowerCase()] ?? "application/octet-stream",
    "x-content-type-options": "nosniff",
  });
  if (request.method === "HEAD") {
    response.end();
    return;
  }
  createReadStream(candidate).pipe(response);
}

const server = http.createServer((request, response) => {
  if (request.url === "/api" || request.url.startsWith("/api/")) {
    proxyApi(request, response);
  } else {
    serveStatic(request, response);
  }
});

server.requestTimeout = 0;
server.headersTimeout = 65_000;
server.listen(port, host, () => {
  console.log(`NAQI gateway listening on http://${host}:${port}`);
  console.log(`Static root: ${staticRoot}`);
  console.log(`API upstream: http://${apiHost}:${apiPort}`);
});
