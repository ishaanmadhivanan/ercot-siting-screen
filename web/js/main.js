// Map set-up, the layer panel, base map switch and click handling.
import { $, $$, esc, monthYear } from "./util.js";
import { LAYERS, GROUPS, PIPE_STYLES } from "./layers.js";
import { describe, setDetailContext } from "./details.js";
import { initParcels } from "./parcels.js";
import { initScore } from "./score.js";
import { initCountyColor } from "./countycolor.js";
import { initSummary } from "./summary.js";
import { exportPoints } from "./export.js";

const dataUrl = (name) => new URL(`../data/${name}`, import.meta.url).href;
const STREET_STYLE = "https://tiles.openfreemap.org/styles/positron";
const AERIAL_TILES = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}";
const NAIP_CATALOG = "https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/query";

const state = { on: new Set(), added: new Set(), app: null, map: null };

// ---------------------------------------------------------------- start-up
async function start() {
  // On a phone the panel would cover the map, so it starts closed.
  if (window.matchMedia("(max-width: 760px)").matches) {
    document.body.classList.add("panel-closed");
    $("#panelToggle").setAttribute("aria-expanded", "false");
  }
  const protocol = new pmtiles.Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);

  const [app, parcelIndex, style] = await Promise.all([
    fetch(dataUrl("app_data.json")).then((r) => r.json()),
    fetch(dataUrl("parcel_index.json")).then((r) => r.json()).catch(() => ({})),
    fetch(STREET_STYLE).then((r) => r.json()).catch(() => null),
  ]);
  app.parcelIndex = parcelIndex;
  state.app = app;

  const map = new maplibregl.Map({
    container: "map",
    style: style || fallbackStyle(),
    bounds: [[-106.7, 25.8], [-93.4, 36.6]],
    fitBoundsOptions: { padding: 20 },
    maxZoom: 17, minZoom: 4.5,
    preserveDrawingBuffer: true,      // lets the site summary include a picture of the map
    attributionControl: { compact: true },
  });
  state.map = map;
  window.sitingMap = map;             // handy for debugging in the browser console
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
  map.addControl(new maplibregl.ScaleControl({ unit: "imperial" }), "bottom-right");

  map.on("load", () => {
    addAerial(map);
    buildPanel();
    for (const def of LAYERS) if (def.on) toggleLayer(def.id, true);
    addCountyLabels(map);
    const ctx = { map, app, state, showLayer: (id) => toggleLayer(id, true, true), showDetail, closeDetail, dataUrl };
    setDetailContext(ctx);
    ctx.countyColor = initCountyColor(ctx);
    ctx.summary = initSummary(ctx);
    ctx.parcels = initParcels(ctx);
    ctx.score = initScore(ctx);
    state.ctx = ctx;
    map.on("click", (e) => onMapClick(e));
    map.on("zoomend", updateZoomHint);
    updateZoomHint();
    document.body.classList.add("ready");
  });
  map.on("mousemove", (e) => {
    const ids = clickableLayerIds();
    map.getCanvas().style.cursor = ids.length && map.queryRenderedFeatures(e.point, { layers: ids }).length ? "pointer" : "";
  });
}

function fallbackStyle() {
  // Used only if the street map service cannot be reached: the data layers still work on a plain background.
  return { version: 8, glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf", sources: {},
    layers: [{ id: "background", type: "background", paint: { "background-color": "#eef1f3" } }] };
}

// ---------------------------------------------------------------- base map
function addAerial(map) {
  map.addSource("aerial", { type: "raster", tiles: [AERIAL_TILES], tileSize: 256, maxzoom: 16,
    attribution: "Aerial photos: USDA NAIP via USGS The National Map" });
  // Put the photo under the street map's labels so place names stay readable.
  const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol");
  map.addLayer({ id: "aerial", type: "raster", source: "aerial", layout: { visibility: "none" } }, firstLabel ? firstLabel.id : undefined);
  state.firstOverlayAnchor = firstLabel ? firstLabel.id : undefined;

  $$("#basemap button").forEach((b) => b.addEventListener("click", () => {
    const aerial = b.dataset.base === "aerial";
    map.setLayoutProperty("aerial", "visibility", aerial ? "visible" : "none");
    $$("#basemap button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    document.body.classList.toggle("aerial", aerial);
    const note = $("#aerialNote");
    note.hidden = !aerial;
    if (aerial) showAerialYear(note);
  }));
}

async function showAerialYear(note) {
  // The National Map's NAIP catalog says which year its Texas photos are from.
  note.textContent = "USDA NAIP aerial photos (USGS The National Map)";
  try {
    if (!state.naipYear) {
      const q = new URLSearchParams({ where: "State='TX'", returnDistinctValues: "true", outFields: "Year", returnGeometry: "false", f: "json" });
      const r = await fetch(`${NAIP_CATALOG}?${q}`).then((x) => x.json());
      const years = (r.features || []).map((f) => f.attributes.Year).filter(Boolean);
      if (years.length) state.naipYear = Math.max(...years);
    }
    if (state.naipYear) note.textContent = `USDA NAIP aerial photos, flown ${state.naipYear} (USGS The National Map)`;
  } catch (e) { /* keep the plain note */ }
}

// ---------------------------------------------------------------- layers
function layerDef(id) { return LAYERS.find((l) => l.id === id); }

function ensureAdded(def) {
  const map = state.map;
  if (state.added.has(def.id)) return;
  const sourceId = typeof def.source === "string" ? def.source : def.id;
  if (typeof def.source === "string") ensureAdded(layerDef(def.source));
  else if (!map.getSource(sourceId)) map.addSource(sourceId, def.source);
  // Keep the drawing order of LAYERS no matter which order layers are switched on:
  // insert each new layer under the first already-added layer that comes later in the list.
  const later = LAYERS.slice(LAYERS.indexOf(def) + 1).flatMap((d) => d.layers.map((l) => l.id)).find((lid) => map.getLayer(lid));
  for (const spec of def.layers) {
    const full = { ...spec, source: sourceId };
    if (def.sourceLayer) full["source-layer"] = def.sourceLayer;
    map.addLayer(full, later);
  }
  state.added.add(def.id);
}

async function addCountyLabels(map) {
  // One label point per county, at the middle of its outline.
  const g = await fetch(dataUrl("counties.geojson")).then((r) => r.json());
  const features = g.features.map((f) => {
    const rings = f.geometry.type === "Polygon" ? [f.geometry.coordinates[0]] : f.geometry.coordinates.map((p) => p[0]);
    const ring = rings.sort((a, b) => b.length - a.length)[0];
    const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
    return { type: "Feature", properties: { name: f.properties.name },
      geometry: { type: "Point", coordinates: [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2] } };
  });
  map.addSource("county-labels", { type: "geojson", data: { type: "FeatureCollection", features } });
  map.addLayer({ id: "counties-label", type: "symbol", source: "county-labels", minzoom: 6.5,
    layout: { "text-field": ["get", "name"], "text-font": ["Noto Sans Regular"], "text-size": 11, "text-letter-spacing": 0.04 },
    paint: { "text-color": "#3d4852", "text-halo-color": "rgba(255,255,255,0.85)", "text-halo-width": 1.4 } });
}

function toggleLayer(id, on, fromCode = false) {
  const def = layerDef(id);
  const map = state.map;
  if (on) {
    ensureAdded(def);
    state.on.add(id);
  } else state.on.delete(id);
  for (const spec of def.layers) if (map.getLayer(spec.id)) map.setLayoutProperty(spec.id, "visibility", on ? "visible" : "none");
  if (map.getLayer("counties-label")) map.moveLayer("counties-label");
  const row = $(`.layer[data-id="${id}"]`);
  if (row) {
    row.classList.toggle("on", on);
    const box = $("input[type=checkbox]", row);
    if (box && fromCode) box.checked = on;
  }
  updateZoomHint();
  document.dispatchEvent(new CustomEvent("layerchange", { detail: { id, on } }));
}

function clickableLayerIds() {
  const map = state.map;
  // top-most first: reverse of drawing order
  return [...LAYERS].reverse().filter((d) => state.on.has(d.id)).flatMap((d) => d.click || []).filter((lid) => map.getLayer(lid));
}

function updateZoomHint() {
  const z = state.map.getZoom();
  const waiting = LAYERS.filter((d) => state.on.has(d.id) && d.minzoomNote && z < d.minzoomNote).map((d) => d.label);
  const hint = $("#zoomHint");
  hint.hidden = !waiting.length;
  hint.textContent = waiting.length ? `Zoom in to see: ${waiting.join(", ")}` : "";
}

// ---------------------------------------------------------------- layer panel
function swatch([kind, color, size, label]) {
  let svg;
  if (kind === "line") svg = `<line x1="1" y1="8" x2="27" y2="8" stroke="${color}" stroke-width="${size}" stroke-linecap="round"/>`;
  else if (kind === "dot") svg = `<circle cx="14" cy="8" r="${Math.min(size, 7)}" fill="${color}" stroke="#fff" stroke-width="1"/>`;
  else if (kind === "ring") svg = `<circle cx="14" cy="8" r="${Math.min(size, 6)}" fill="#fff" stroke="${color}" stroke-width="2"/>`;
  else if (kind === "faint") svg = `<circle cx="14" cy="8" r="${Math.min(size, 6)}" fill="${color}" fill-opacity="0.3" stroke="#17212b" stroke-width="0.6"/>`;
  else svg = `<rect x="3" y="2" width="22" height="12" fill="${color}" fill-opacity="${size}" stroke="${color}" stroke-width="1"/>`;
  return `<li><svg width="28" height="16" aria-hidden="true">${svg}</svg><span>${esc(label)}</span></li>`;
}

function buildPanel() {
  const meta = state.app.meta;
  const list = $("#layerList");
  list.innerHTML = GROUPS.map((g) => {
    const rows = LAYERS.filter((d) => d.group === g).map((d) => {
      const option = d.option ? `<label class="layer-option">${esc(d.option.label)}
          <select data-option="${d.id}">${d.option.choices.map(([v, t]) => `<option value="${v}">${esc(t)}</option>`).join("")}</select></label>` : "";
      const extra = d.id === "counties" ? `<label class="layer-option">Color counties by <select id="countyColorBy"></select></label><div id="countyLegend"></div>` : "";
      return `<div class="layer${d.on ? " on" : ""}" data-id="${d.id}">
        <label class="layer-head"><input type="checkbox" ${d.on ? "checked" : ""} ${d.locked ? "disabled" : ""}> <span>${esc(d.label)}</span></label>
        <div class="layer-body">
          <ul class="legend" data-legend="${d.id}">${d.legend.map(swatch).join("")}</ul>
          ${option}${extra}
          <p class="source">${esc(d.src)} <span class="asof">${d.date(meta) === "live" ? "Live data." : `Data as of ${esc(monthYear(d.date(meta)))}.`}</span></p>
        </div>
      </div>`;
    }).join("");
    return `<section class="group"><h2>${g}</h2>${rows}</section>`;
  }).join("");

  list.addEventListener("change", (e) => {
    const row = e.target.closest(".layer");
    if (e.target.matches(".layer-head input")) toggleLayer(row.dataset.id, e.target.checked);
    if (e.target.matches("[data-option=pipes]")) {
      const s = PIPE_STYLES[e.target.value];
      state.map.setPaintProperty("pipes-line", "line-color", s.color);
      $("[data-legend=pipes]").innerHTML = s.legend.map(swatch).join("");
    }
  });

  // tabs
  $$(".tabs [role=tab]").forEach((tab) => tab.addEventListener("click", () => selectTab(tab.dataset.tab)));
  // panel open / close (matters on phones, where the panel covers the map)
  $("#panelToggle").addEventListener("click", () => {
    const open = document.body.classList.toggle("panel-closed") === false;
    $("#panelToggle").setAttribute("aria-expanded", String(open));
    setTimeout(() => state.map.resize(), 250);
  });
  $$("[data-export-points]").forEach((b) => b.addEventListener("click", () => exportPoints(state, b.dataset.exportPoints)));
  $("#detailClose").addEventListener("click", closeDetail);
}

export function selectTab(name) {
  $$(".tabs [role=tab]").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.tab === name)));
  $$(".tab-body").forEach((s) => { s.hidden = s.id !== `tab-${name}`; });
  document.dispatchEvent(new CustomEvent("tabchange", { detail: name }));
}

// ---------------------------------------------------------------- clicks and the details card
function onMapClick(e) {
  const map = state.map;
  const ids = clickableLayerIds();
  if (!ids.length) return;
  // Points and lines get a few pixels of slack; areas (counties, parcels, flood zones) must be under the pointer itself.
  const pad = 5;
  const box = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
  const isArea = (lid) => map.getLayer(lid).type === "fill";
  const found = [
    ...map.queryRenderedFeatures(box, { layers: ids.filter((l) => !isArea(l)) }),
    ...map.queryRenderedFeatures(e.point, { layers: ids.filter(isArea) }),
  ];
  found.sort((a, b) => ids.indexOf(a.layer.id) - ids.indexOf(b.layer.id));
  const seen = new Set();
  const hits = found.filter((f) => {
    const key = describe(f, e.lngLat, true);      // one entry per named thing, however many pieces it is drawn in
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 8);
  if (!hits.length) { closeDetail(); return; }
  showHits(hits, e.lngLat, 0);
}

function showHits(hits, lngLat, index) {
  const html = describe(hits[index], lngLat);
  const others = hits.length > 1 ? `<div class="also"><p>Also at this spot</p><ul>${hits.map((h, i) => i === index ? "" :
    `<li><button class="linkish" data-hit="${i}">${esc(describe(h, lngLat, true))}</button></li>`).join("")}</ul></div>` : "";
  showDetail(html + others);
  $$("[data-hit]", $("#detailBody")).forEach((b) => b.addEventListener("click", () => showHits(hits, lngLat, Number(b.dataset.hit))));
  const f = hits[index];
  if (f.layer.id === "parcels-fill") state.ctx.parcels.select(f.properties.id, false);
}

function showDetail(html) {
  $("#detailBody").innerHTML = html;
  $("#detail").hidden = false;
  $("#detail").scrollTop = 0;
  document.body.classList.add("detail-open");
}

function closeDetail() {
  $("#detail").hidden = true;
  document.body.classList.remove("detail-open");
}

start();
