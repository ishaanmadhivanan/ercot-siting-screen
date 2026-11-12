// Tiny static server with HTTP Range support (PMTiles needs it). For local testing only.
const http = require("http"), fs = require("fs"), path = require("path");
const root = path.resolve(process.argv[2] || "web"), port = Number(process.argv[3] || 8765);
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".json": "application/json", ".geojson": "application/json", ".csv": "text/csv", ".pmtiles": "application/octet-stream", ".png": "image/png" };
http.createServer((req, res) => {
  let p = decodeURIComponent(req.url.split("?")[0]);
  if (p.endsWith("/")) p += "index.html";
  const file = path.join(root, p);
  if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); return res.end("not found"); }
  const size = fs.statSync(file).size, type = types[path.extname(file)] || "application/octet-stream";
  const m = /bytes=(\d+)-(\d*)/.exec(req.headers.range || "");
  if (m) {
    const start = Number(m[1]), end = m[2] ? Math.min(Number(m[2]), size - 1) : size - 1;
    res.writeHead(206, { "Content-Type": type, "Content-Range": `bytes ${start}-${end}/${size}`, "Content-Length": end - start + 1, "Accept-Ranges": "bytes" });
    fs.createReadStream(file, { start, end }).pipe(res);
  } else {
    res.writeHead(200, { "Content-Type": type, "Content-Length": size, "Accept-Ranges": "bytes" });
    fs.createReadStream(file).pipe(res);
  }
}).listen(port, () => console.log("serving", root, "on", port));
