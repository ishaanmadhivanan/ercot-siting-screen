// "Color counties by": shades the ERCOT counties by any county number, in five steps from light to dark.
import { $, esc, num } from "./util.js";

const RAMP = ["#cde2fb", "#9ec5f4", "#5598e7", "#256abf", "#0d366b"];   // one hue, light = low, dark = high

export function initCountyColor(ctx) {
  const { map, app } = ctx;
  const select = $("#countyColorBy");
  const legend = $("#countyLegend");
  let scores = null;      // fips -> score, set by the score panel

  const options = [["", "Nothing"], ["score", "My county score"], ["queue", "Queue, all fuels (MW)"], ["queue_gas", "Queue, gas only (MW)"],
    ["parcels", "Parcels of 100+ acres (count)"],
    ...app.metrics.filter((m) => m.category).map((m) => [`f:${m.metric_key}`, `${m.label} (${m.unit})`])];
  select.innerHTML = options.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");

  function valueOf(key, fips, c) {
    if (key === "score") return scores ? scores[fips] : undefined;
    if (key === "queue") return Object.values(c.queue || {}).reduce((s, v) => s + v[1], 0);
    if (key === "queue_gas") return c.queue?.Gas?.[1] || 0;
    if (key === "parcels") return app.parcelIndex?.[fips];
    return c.f[key.slice(2)];
  }

  function apply() {
    const key = select.value;
    if (!key || (key === "score" && !scores)) {
      map.setPaintProperty("counties-fill", "fill-color", "rgba(0,0,0,0)");
      legend.innerHTML = key === "score" ? `<p class="hint">Tick some factors on the County score tab first.</p>` : "";
      return;
    }
    const vals = [];
    for (const [fips, c] of Object.entries(app.counties)) {
      if (!c.ercot) continue;
      const v = valueOf(key, fips, c);
      if (v !== undefined && v !== null && !Number.isNaN(v)) vals.push([fips, Number(v)]);
    }
    if (!vals.length) { map.setPaintProperty("counties-fill", "fill-color", "rgba(0,0,0,0)"); legend.innerHTML = ""; return; }
    // five classes with about the same number of counties in each
    const sorted = vals.map((v) => v[1]).sort((a, b) => a - b);
    const breaks = [...new Set([0.2, 0.4, 0.6, 0.8].map((q) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))]))];
    const classOf = (v) => breaks.filter((b) => v >= b).length;
    const groups = RAMP.map(() => []);
    for (const [fips, v] of vals) groups[Math.round(classOf(v) * (RAMP.length - 1) / Math.max(1, breaks.length))].push(fips);
    const expr = ["match", ["get", "fips"]];
    groups.forEach((g, i) => { if (g.length) expr.push(g, RAMP[i]); });
    expr.push("rgba(0,0,0,0)");
    map.setPaintProperty("counties-fill", "fill-color", expr);

    const digits = sorted[sorted.length - 1] < 10 ? 2 : 0;
    const edges = [sorted[0], ...breaks, sorted[sorted.length - 1]];
    const items = [];
    for (let i = 0; i < edges.length - 1; i++) {
      const color = RAMP[Math.round(i * (RAMP.length - 1) / Math.max(1, breaks.length))];
      items.push(`<li><span class="chip" style="background:${color}"></span>${num(edges[i], digits)} to ${num(edges[i + 1], digits)}</li>`);
    }
    legend.innerHTML = `<ul class="legend ramp">${items.join("")}<li><span class="chip none"></span>No value</li></ul>`;
  }

  select.addEventListener("change", apply);
  return {
    setScores(s) { scores = s; if (select.value === "score" || (s && !select.value)) { select.value = "score"; } apply(); },
    refresh: apply,
  };
}
