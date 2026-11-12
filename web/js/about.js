// Fills the About page's tables from the same lists the map uses, so the two cannot drift apart.
import { $, esc, num, monthYear } from "./util.js";
import { LAYERS, GROUPS } from "./layers.js";

const MATCH = [
  ["high", "Name and voltage", "Same station name, and the substation carries that voltage"],
  ["medium", "Name", "Same name but the voltage is unknown or different, or a close spelling with matching voltage"],
  ["low", "Weak", "Only one end of a tapped line was found, a loose spelling match, or the only substation at that voltage in the county"],
  ["none", "Not located", "No match. Shown at the county center and counted in the county only"],
];
const ORDER = ["Gas supply", "Grid connection", "Site control", "Air permit", "Community"];

const [data, index] = await Promise.all([
  fetch(new URL("../data/app_data.json", import.meta.url)).then((r) => r.json()),
  fetch(new URL("../data/parcel_index.json", import.meta.url)).then((r) => r.json()),
]);
const meta = data.meta;

$("#layerTable tbody").innerHTML = GROUPS.flatMap((g) => LAYERS.filter((l) => l.group === g)).map((l) => {
  const d = l.date(meta);
  return `<tr><td><b>${esc(l.label)}</b><br><span class="muted">${esc(l.group)}</span></td><td>${esc(l.src)}</td><td>${d === "live" ? "Live" : esc(monthYear(d))}</td></tr>`;
}).join("");

$("#matchTable tbody").innerHTML = MATCH.map(([k, label, text]) => {
  const m = meta.queue_match[k] || { n: 0, mw: 0 };
  return `<tr><td><b>${label}</b></td><td>${text}</td><td>${num(m.n)}</td><td>${num(m.mw)}</td></tr>`;
}).join("");

const rank = (m) => (m.category ? ORDER.indexOf(m.category) : 9);
const metrics = [...data.metrics].sort((a, b) => rank(a) - rank(b) || a.label.localeCompare(b.label));
$("#metricTable tbody").innerHTML = metrics.map((m) => {
  const cat = m.category || (m.metric_type === "score" ? "Not in the score" : "Background");
  const better = ["higher", "lower"].includes(m.better_direction) && m.category ? m.better_direction + (m.score_transform === "log" ? ", log scale" : "") : "";
  const src = m.source_url ? `<a href="${esc(m.source_url)}">${esc(m.source_name)}</a>` : esc(m.source_name);
  return `<tr><td><b>${esc(m.label)}</b></td><td>${esc(cat)}</td><td>${esc(m.unit)}</td><td>${esc(better)}</td><td>${src}</td><td>${esc(monthYear(m.data_date))}</td><td>${esc(m.notes)}</td></tr>`;
}).join("");

const total = Object.values(index).reduce((s, v) => s + v, 0);
$("#parcelCount").textContent = `${num(total)} parcels in ${num(Object.keys(index).length)} counties`;
$("#built").textContent = new Date(`${meta.built}T12:00:00`).toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
