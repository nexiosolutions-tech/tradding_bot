// Zero-dependency static file server for dist/ — deliberately not using the `serve` npm
// package, which currently pulls in a high-severity DoS advisory (minimatch via
// serve-handler) with no fixed version available. This app has no client-side routes
// beyond "/", so it doesn't need SPA-fallback rewriting either — just plain file serving.
import { createServer } from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";

const DIST_DIR = join(import.meta.dirname, "dist");
const PORT = Number(process.env.PORT) || 3000;

const CONTENT_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

createServer((req, res) => {
  // Normalizing the URL path *before* joining it to DIST_DIR is what makes this safe:
  // normalize() collapses any ".." against the leading "/" (there's nothing above root
  // to escape to), so the fragment handed to join() can never point outside DIST_DIR.
  const requestPath = normalize(decodeURIComponent(req.url.split("?")[0]));
  let filePath = join(DIST_DIR, requestPath);
  if (!existsSync(filePath) || statSync(filePath).isDirectory()) {
    filePath = join(DIST_DIR, "index.html"); // single-page app, no client-side routes to fall back for
  }

  res.writeHead(200, { "Content-Type": CONTENT_TYPES[extname(filePath)] ?? "application/octet-stream" });
  createReadStream(filePath).pipe(res);
}).listen(PORT, () => {
  console.log(`Serving ${DIST_DIR} on port ${PORT}`);
});
