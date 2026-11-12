// Small helpers shared by the map, the parcel finder, the score panel and the site summary.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function num(v, digits = 0) {
  if (v === null || v === undefined || v === "" || Number.isNaN(Number(v))) return "";
  return Number(v).toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// "2026-09-30" or "2026-09" -> "Sep 2026"; anything else is returned unchanged
export function monthYear(d) {
  const m = /^(\d{4})-(\d{2})/.exec(String(d ?? ""));
  return m ? `${MONTHS[Number(m[2]) - 1]} ${m[1]}` : String(d ?? "");
}

export const OWNER_TYPES = { C: "Company", I: "Individual", T: "Trust or estate", G: "Government", U: "Not listed" };

// ---- distance
export function miles(lat1, lon1, lat2, lon2) {
  const R = 3958.8, rad = Math.PI / 180;
  const dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// ---- links out (plain links, no API key)
export function googleMapsUrl(lat, lon) {
  return `https://www.google.com/maps/@?api=1&map_action=map&center=${lat},${lon}&zoom=15&basemap=satellite`;
}
export function googleEarthUrl(lat, lon) {
  return `https://earth.google.com/web/@${lat},${lon},0a,2500d,35y,0h,0t,0r`;
}
export function mapLinks(lat, lon) {
  return `<p class="links"><a href="${googleMapsUrl(lat, lon)}" target="_blank" rel="noopener">Open in Google Maps</a>
    <a href="${googleEarthUrl(lat, lon)}" target="_blank" rel="noopener">Open in Google Earth</a></p>`;
}

// ---- CSV
export function parseCsv(text) {
  // Handles quoted fields with commas and doubled quotes. First row is the header.
  const rows = [];
  let row = [], field = "", quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else quoted = false; }
      else field += c;
    } else if (c === '"') quoted = true;
    else if (c === ",") { row.push(field); field = ""; }
    else if (c === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (c !== "\r") field += c;
  }
  if (field !== "" || row.length) { row.push(field); rows.push(row); }
  const head = rows.shift() || [];
  return rows.filter((r) => r.length === head.length).map((r) => Object.fromEntries(head.map((h, i) => [h, r[i]])));
}

export function toCsv(rows, columns) {
  // columns: [[header, key or function], ...]
  const cell = (v) => {
    const s = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [columns.map((c) => cell(c[0])).join(",")];
  for (const r of rows) lines.push(columns.map((c) => cell(typeof c[1] === "function" ? c[1](r) : r[c[1]])).join(","));
  return lines.join("\r\n");
}

export function download(name, content, type) {
  const blob = content instanceof Blob ? content : new Blob([content], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

// ---- KML / KMZ. A KMZ is a zip file holding one doc.kml; this writes that zip without compression.
export function toKml(title, placemarks) {
  // placemarks: [{name, lat, lon, fields: [[label, value], ...]}]
  const body = placemarks.map((p) => {
    const rows = p.fields.filter((f) => f[1] !== "" && f[1] !== null && f[1] !== undefined)
      .map((f) => `<tr><td>${esc(f[0])}</td><td>${esc(f[1])}</td></tr>`).join("");
    return `<Placemark><name>${esc(p.name)}</name><description><![CDATA[<table>${rows}</table>]]></description>` +
      `<Point><coordinates>${p.lon},${p.lat},0</coordinates></Point></Placemark>`;
  }).join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>${esc(title)}</name>\n${body}\n</Document></kml>`;
}

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

export function toKmz(kmlText) {
  const data = new TextEncoder().encode(kmlText);
  const name = new TextEncoder().encode("doc.kml");
  const crc = crc32(data);
  const local = new DataView(new ArrayBuffer(30));
  local.setUint32(0, 0x04034b50, true); local.setUint16(4, 20, true); local.setUint16(8, 0, true);
  local.setUint32(14, crc, true); local.setUint32(18, data.length, true); local.setUint32(22, data.length, true);
  local.setUint16(26, name.length, true);
  const central = new DataView(new ArrayBuffer(46));
  central.setUint32(0, 0x02014b50, true); central.setUint16(4, 20, true); central.setUint16(6, 20, true);
  central.setUint32(16, crc, true); central.setUint32(20, data.length, true); central.setUint32(24, data.length, true);
  central.setUint16(28, name.length, true); central.setUint32(42, 0, true);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true); end.setUint16(8, 1, true); end.setUint16(10, 1, true);
  end.setUint32(12, 46 + name.length, true); end.setUint32(16, 30 + name.length + data.length, true);
  return new Blob([local, name, data, central, name, end], { type: "application/vnd.google-earth.kmz" });
}

// ---- small table builder
export function table(headers, rows, cls = "") {
  return `<table class="${cls}"><thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>` +
    `<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

export function facts(pairs) {
  // [[label, value], ...] -> definition list; rows with an empty value are skipped
  const rows = pairs.filter((p) => p[1] !== "" && p[1] !== null && p[1] !== undefined);
  return `<dl class="facts">${rows.map((p) => `<dt>${p[0]}</dt><dd>${p[1]}</dd>`).join("")}</dl>`;
}
