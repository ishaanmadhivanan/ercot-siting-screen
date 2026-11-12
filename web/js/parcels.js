// "Parcel finder" tab: filters, the sortable list, exports, and parcel selection.
import { $, $$, esc, num, parseCsv, toCsv, toKml, toKmz, download, googleMapsUrl, OWNER_TYPES } from "./util.js";
import { parcelHtml } from "./details.js";

const MAX_COUNTIES_IN_VIEW = 15;   // listing loads one small file per county
const MAX_ROWS_SHOWN = 200;

export function initParcels(ctx) {
  const { map, app } = ctx;
  const form = $("#parcelForm");
  const cache = new Map();          // fips -> Promise<rows>
  let boxes = null;                 // fips -> [w, s, e, n]
  let rows = [];                    // current matches
  let sort = { key: "ac", dir: -1 };
  let selected = "";

  // county choices: every county with a parcel file
  const withParcels = Object.keys(app.parcelIndex).filter((f) => app.parcelIndex[f] > 0 && app.counties[f])
    .sort((a, b) => app.counties[a].name.localeCompare(app.counties[b].name));
  $("#parcelArea").insertAdjacentHTML("beforeend", withParcels.map((f) => `<option value="${f}">${esc(app.counties[f].name)} County (${num(app.parcelIndex[f])})</option>`).join(""));

  fetch(ctx.dataUrl("counties.geojson")).then((r) => r.json()).then((g) => {
    boxes = {};
    for (const f of g.features) {
      const pts = f.geometry.type === "Polygon" ? f.geometry.coordinates.flat() : f.geometry.coordinates.flat(2);
      const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
      boxes[f.properties.fips] = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    }
    refresh();
  });

  function loadCounty(fips) {
    if (!cache.has(fips)) {
      cache.set(fips, fetch(ctx.dataUrl(`parcels/${fips}.csv`)).then((r) => r.ok ? r.text() : "").then((t) => parseCsv(t).map((r) => {
        for (const k of ["ac", "dp20", "dpa", "ds69", "ds138", "ds345", "drd", "dpl", "dair", "fl", "lat", "lon"]) r[k] = Number(r[k]);
        return r;
      })));
    }
    return cache.get(fips);
  }

  function read() {
    const d = new FormData(form);
    const n = (k) => d.get(k) === "" || d.get(k) === null ? null : Number(d.get(k));
    return { minAc: Math.max(100, n("minAc") || 100), maxPipe: n("maxPipe"), maxSub: n("maxSub"), subKv: d.get("subKv"),
      minPlace: n("minPlace"), flood: d.get("flood"), floodUnknown: d.get("floodUnknown") === "on",
      ot: d.getAll("ot"), area: d.get("area") };
  }

  function passes(r, f) {
    if (r.ac < f.minAc) return false;
    if (f.maxPipe !== null && !(r.dp20 <= f.maxPipe)) return false;
    if (f.maxSub !== null && !(r[`ds${f.subKv}`] <= f.maxSub)) return false;
    if (f.minPlace !== null && !(r.dpl >= f.minPlace)) return false;
    if (f.flood !== "any") {
      if (r.fl < 0) { if (!f.floodUnknown) return false; }
      else if (r.fl > Number(f.flood)) return false;
    }
    return f.ot.includes(r.ot);
  }

  function mapFilter(f) {
    const e = ["all", [">=", ["get", "ac"], f.minAc]];
    if (f.maxPipe !== null) e.push(["<=", ["get", "dp20"], f.maxPipe]);
    if (f.maxSub !== null) e.push(["<=", ["get", `ds${f.subKv}`], f.maxSub]);
    if (f.minPlace !== null) e.push([">=", ["get", "dpl"], f.minPlace]);
    if (f.flood !== "any") {
      const limit = ["<=", ["get", "fl"], Number(f.flood)];
      e.push(f.floodUnknown ? limit : ["all", [">=", ["get", "fl"], 0], limit]);
    }
    if (f.ot.length < 5) e.push(["in", ["get", "ot"], ["literal", f.ot]]);
    return e;
  }

  let ticket = 0;
  async function refresh() {
    const f = read();
    if (map.getLayer("parcels-fill")) {
      const expr = mapFilter(f);
      map.setFilter("parcels-fill", expr);
      map.setFilter("parcels-line", expr);
    }
    if ($("#tab-parcels").hidden || !boxes) return;
    const status = $("#parcelStatus"), wrap = $("#parcelTableWrap");
    const mine = ++ticket;
    let counties, bounds = null;
    if (f.area === "view") {
      const b = map.getBounds();
      bounds = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
      counties = withParcels.filter((c) => boxes[c] && boxes[c][0] < bounds[2] && boxes[c][2] > bounds[0] && boxes[c][1] < bounds[3] && boxes[c][3] > bounds[1]);
      if (counties.length > MAX_COUNTIES_IN_VIEW) {
        rows = [];
        status.innerHTML = `The map shows every matching parcel once you zoom in. To list them, zoom in further (the view covers ${counties.length} counties; the list handles up to ${MAX_COUNTIES_IN_VIEW}) or pick a county above.`;
        wrap.innerHTML = "";
        $("#parcelExport").hidden = true;
        return;
      }
    } else counties = [f.area];
    status.textContent = "Loading parcels...";
    const loaded = (await Promise.all(counties.map(loadCounty))).flat();
    if (mine !== ticket) return;      // a newer refresh has started
    rows = loaded.filter((r) => passes(r, f) && (!bounds || (r.lon >= bounds[0] && r.lon <= bounds[2] && r.lat >= bounds[1] && r.lat <= bounds[3])));
    draw(f);
  }

  function draw(f = read()) {
    const status = $("#parcelStatus"), wrap = $("#parcelTableWrap");
    const where = f.area === "view" ? "in the map view" : `in ${app.counties[f.area].name} County`;
    $("#parcelExport").hidden = !rows.length;
    if (!rows.length) {
      status.textContent = `No parcels match ${where}. Loosen a filter or move the map.`;
      wrap.innerHTML = "";
      return;
    }
    const subKey = `ds${f.subKv}`;
    rows.sort((a, b) => (a[sort.key] > b[sort.key] ? 1 : a[sort.key] < b[sort.key] ? -1 : 0) * sort.dir);
    status.textContent = `${num(rows.length)} parcels match ${where}.` + (rows.length > MAX_ROWS_SHOWN ? ` Showing the first ${MAX_ROWS_SHOWN}; the downloads include all of them.` : "");
    const cols = [["ac", "Acres"], ["dp20", "Gas line 20 in+ (mi)"], [subKey, `Substation ${f.subKv} kV+ (mi)`], ["fl", "Floodplain %"], ["ot", "Owner"]];
    const arrow = (k) => (sort.key === k ? (sort.dir > 0 ? " ▲" : " ▼") : "");
    wrap.innerHTML = `<table class="mini sortable"><thead><tr>${cols.map(([k, t]) => `<th><button data-sort="${k}">${t}${arrow(k)}</button></th>`).join("")}</tr></thead><tbody>` +
      rows.slice(0, MAX_ROWS_SHOWN).map((r) => `<tr data-id="${r.id}" class="${r.id === selected ? "sel" : ""}" tabindex="0">
        <td>${num(r.ac)}</td><td>${num(r.dp20, 1)}</td><td>${num(r[subKey], 1)}</td><td>${r.fl < 0 ? "n/a" : num(r.fl)}</td><td>${esc(OWNER_TYPES[r.ot])}</td></tr>`).join("") +
      `</tbody></table>`;
  }

  async function getRow(id) {
    const list = await loadCounty(id.split("-")[0]);
    return list.find((r) => r.id === id);
  }

  async function select(id, fromList) {
    selected = id || "";
    for (const lid of ["parcels-selected", "parcels-selected-ink"]) if (map.getLayer(lid)) map.setFilter(lid, ["==", ["get", "id"], selected]);
    $$("#parcelTableWrap tr.sel").forEach((tr) => tr.classList.remove("sel"));
    const tr = $(`#parcelTableWrap tr[data-id="${CSS.escape(selected)}"]`);
    if (tr) tr.classList.add("sel");
    if (fromList && id) {
      const r = await getRow(id);
      if (!r) return;
      map.flyTo({ center: [r.lon, r.lat], zoom: Math.max(map.getZoom(), 12.5) });
      ctx.showDetail(parcelHtml(r));
      if (window.matchMedia("(max-width: 760px)").matches) document.body.classList.add("panel-closed");
    }
  }

  // ---- exports
  const EXPORT_COLS = [
    ["parcel_id", "pid"], ["county", (r) => app.counties[r.fips]?.name], ["acres", "ac"],
    ["owner_type", (r) => OWNER_TYPES[r.ot]], ["owner_name_if_company_or_government", "on"],
    ["miles_to_gas_line_20in_plus", "dp20"], ["miles_to_any_gas_transmission_line", "dpa"],
    ["miles_to_substation_69kv_plus", "ds69"], ["miles_to_substation_138kv_plus", "ds138"], ["miles_to_substation_345kv", "ds345"],
    ["miles_to_main_road", "drd"], ["miles_to_city_or_town", "dpl"], ["miles_to_public_airport", "dair"],
    ["floodplain_pct_of_parcel", (r) => (r.fl < 0 ? "" : r.fl)], ["latitude", "lat"], ["longitude", "lon"],
    ["google_maps", (r) => googleMapsUrl(r.lat, r.lon)],
  ];
  const cell = (r, c) => (typeof c[1] === "function" ? c[1](r) : r[c[1]]);

  function exportRows(kind) {
    if (!rows.length) return;
    const stamp = new Date().toISOString().slice(0, 10);
    if (kind === "csv") download(`parcels_${stamp}.csv`, toCsv(rows, EXPORT_COLS), "text/csv");
    if (kind === "kmz") {
      const marks = rows.map((r) => ({ name: `${num(r.ac)} ac, ${app.counties[r.fips]?.name} Co.`, lat: r.lat, lon: r.lon,
        fields: EXPORT_COLS.slice(0, 14).map((c) => [c[0].replace(/_/g, " "), cell(r, c)]) }));
      download(`parcels_${stamp}.kmz`, toKmz(toKml("Parcels from the ERCOT siting map", marks)));
    }
    if (kind === "geojson") {
      const gj = { type: "FeatureCollection", features: rows.map((r) => ({ type: "Feature",
        geometry: { type: "Point", coordinates: [r.lon, r.lat] },
        properties: Object.fromEntries(EXPORT_COLS.slice(0, 14).map((c) => [c[0], cell(r, c)])) })) };
      download(`parcels_${stamp}.geojson`, JSON.stringify(gj), "application/geo+json");
    }
  }

  // ---- events
  let timer = null;
  const later = () => { clearTimeout(timer); timer = setTimeout(refresh, 250); };
  form.addEventListener("input", later);
  form.addEventListener("submit", (e) => e.preventDefault());
  $("#parcelReset").addEventListener("click", () => { form.reset(); refresh(); });
  map.on("moveend", () => { if (read().area === "view") later(); });
  document.addEventListener("tabchange", (e) => {
    if (e.detail === "parcels") { ctx.showLayer("parcels"); refresh(); }
  });
  document.addEventListener("layerchange", (e) => { if (e.detail.id === "parcels" && e.detail.on) refresh(); });
  $("#parcelArea").addEventListener("change", async () => {
    const f = read();
    if (f.area !== "view" && boxes?.[f.area]) {
      const b = boxes[f.area];
      map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 40 });
    }
  });
  $("#parcelTableWrap").addEventListener("click", (e) => {
    const s = e.target.closest("[data-sort]");
    if (s) { sort = { key: s.dataset.sort, dir: sort.key === s.dataset.sort ? -sort.dir : (s.dataset.sort === "ac" ? -1 : 1) }; draw(); return; }
    const tr = e.target.closest("tr[data-id]");
    if (tr) select(tr.dataset.id, true);
  });
  $("#parcelTableWrap").addEventListener("keydown", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); select(tr.dataset.id, true); }
  });
  $$("[data-export-parcels]").forEach((b) => b.addEventListener("click", () => exportRows(b.dataset.exportParcels)));

  return { select, getRow, refresh };
}
