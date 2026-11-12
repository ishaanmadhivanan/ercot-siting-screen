// "Download what's on the map": point layers that are switched on, inside the current view.
import { toCsv, toKml, toKmz, download } from "./util.js";

const POINT_LAYERS = { plants: "Operating power plant", plants_proposed: "Proposed power plant", substations: "Substation",
  queue: "Queue project", airports: "Airport", lng: "LNG terminal" };
const cache = {};

export async function exportPoints(state, kind) {
  const b = state.map.getBounds();
  const rows = [];
  for (const [id, label] of Object.entries(POINT_LAYERS)) {
    if (!state.on.has(id)) continue;
    cache[id] ||= await fetch(state.ctx.dataUrl(`${id}.geojson`)).then((r) => r.json());
    for (const f of cache[id].features) {
      const [lon, lat] = f.geometry.coordinates;
      if (lon < b.getWest() || lon > b.getEast() || lat < b.getSouth() || lat > b.getNorth()) continue;
      rows.push({ layer: label, ...f.properties, latitude: lat, longitude: lon });
    }
  }
  if (!rows.length) { alert("No points from the switched-on layers are inside the map view. Switch on plants, substations, queue projects, airports or LNG, or zoom out."); return; }
  const keys = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  const stamp = new Date().toISOString().slice(0, 10);
  if (kind === "csv") download(`map_points_${stamp}.csv`, toCsv(rows, keys.map((k) => [k, k])), "text/csv");
  if (kind === "kmz") {
    const marks = rows.map((r) => ({ name: `${r.layer}: ${r.name || r.id || ""}`, lat: r.latitude, lon: r.longitude,
      fields: keys.filter((k) => !["latitude", "longitude"].includes(k)).map((k) => [k, r[k]]) }));
    download(`map_points_${stamp}.kmz`, toKmz(toKml("Points from the ERCOT siting map", marks)));
  }
  if (kind === "geojson") {
    download(`map_points_${stamp}.geojson`, JSON.stringify({ type: "FeatureCollection", features: rows.map((r) => {
      const { latitude, longitude, ...props } = r;
      return { type: "Feature", geometry: { type: "Point", coordinates: [longitude, latitude] }, properties: props };
    }) }), "application/geo+json");
  }
}
