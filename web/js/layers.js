// Every map layer in one place: how it is drawn, its legend, and where the data comes from.
// To add a layer: add an entry here. The panel, legend and click handling are built from this list.

const data = (name) => new URL(`../data/${name}`, import.meta.url).href;
const pm = (name) => `pmtiles://${data(name + ".pmtiles")}`;
const FONT = ["Noto Sans Regular"];

// Fuel colors: five classes checked for color-blind separation. The popup always names the fuel too.
export const FUEL_COLORS = { Gas: "#e34948", Wind: "#2a78d6", Solar: "#eda100", Storage: "#1baf7a", Battery: "#1baf7a", Other: "#008300" };
const fuelColor = (prop) => ["match", ["get", prop],
  "Gas", FUEL_COLORS.Gas, "Wind", FUEL_COLORS.Wind, "Solar", FUEL_COLORS.Solar,
  "Storage", FUEL_COLORS.Storage, "Battery", FUEL_COLORS.Battery, FUEL_COLORS.Other];

// Power: one hue, darker and thicker with voltage.
const KV_COLOR = ["step", ["get", "kv"], "#a9a9b4", 60, "#b3a8ee", 130, "#8a7de0", 200, "#5a48cf", 340, "#33208f"];
const KV_WIDTH = ["step", ["get", "kv"], 0.8, 60, 0.9, 130, 1.3, 200, 1.8, 340, 2.6];

// Gas pipe: one hue, darker and thicker with diameter.
export const PIPE_STYLES = {
  diameter: {
    color: ["step", ["to-number", ["get", "DIAMETER"], 0], "#f2b77c", 12, "#e07b2c", 20, "#a8380a"],
    legend: [["line", "#a8380a", 4, "20 in and larger"], ["line", "#e07b2c", 2.5, "12 to under 20 in"], ["line", "#f2b77c", 1.5, "Under 12 in"]],
  },
  interstate: {
    color: ["match", ["get", "INTERSTATE"], "Y", "#a8380a", "#f0a860"],
    legend: [["line", "#a8380a", 3, "Interstate (federal rates, open access)"], ["line", "#f0a860", 3, "Inside Texas only (terms set privately)"]],
  },
};
const PIPE_WIDTH = ["interpolate", ["linear"], ["zoom"],
  5, ["step", ["to-number", ["get", "DIAMETER"], 0], 0.4, 12, 0.7, 20, 1.3],
  11, ["step", ["to-number", ["get", "DIAMETER"], 0], 1.2, 12, 2.2, 20, 4]];

export const OZONE_COLORS = { Marginal: "#f1c9da", Moderate: "#e29abb", Serious: "#cc5f93", Severe: "#a8235e", Extreme: "#6d0f3a" };

export const GROUPS = ["Grid", "Gas", "Air", "Land", "Constraints", "Counties"];

export const LAYERS = [
  // ------------------------------------------------------------------ Counties (drawn first, under everything)
  {
    id: "counties", group: "Counties", label: "County boundaries", on: true, locked: true,
    source: { type: "geojson", data: data("counties.geojson"), promoteId: "fips" },
    layers: [
      { id: "counties-fill", type: "fill", paint: { "fill-color": "rgba(0,0,0,0)", "fill-opacity": ["interpolate", ["linear"], ["zoom"], 6, 0.72, 10, 0.3] } },
      { id: "counties-outside", type: "fill", filter: ["!", ["get", "ercot"]], paint: { "fill-color": "#3d4852", "fill-opacity": 0.16 } },
      { id: "counties-line", type: "line", paint: { "line-color": "#5b6773", "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.4, 10, 1.2] } },
    ],
    click: ["counties-fill"],
    legend: [["fill", "#3d4852", 0.25, "Outside ERCOT (no data)"]],
    src: "US Census Bureau county boundaries, 2023. ERCOT membership from EIA-860 balancing authority.",
    date: () => "2023",
  },
  {
    id: "ozone", group: "Air", label: "Ozone nonattainment counties", on: false,
    source: "counties",
    layers: [{ id: "ozone-fill", type: "fill", filter: ["!", ["in", ["get", "ozone"], ["literal", ["", "Attainment"]]]],
      paint: { "fill-opacity": ["interpolate", ["linear"], ["zoom"], 6, 0.5, 10, 0.2], "fill-color": ["match", ["get", "ozone"], ...Object.entries(OZONE_COLORS).flat(), "rgba(0,0,0,0)"] } }],
    click: [],
    legend: Object.entries(OZONE_COLORS).filter(([k]) => k !== "Extreme").map(([k, c]) => ["fill", c, 0.75, k]),
    src: "EPA Green Book. A worse rating means a harder, more expensive air permit; click a county for its NOx offset ratio and credit price (TCEQ).",
    date: (m) => "Aug 2026",
  },
  // ------------------------------------------------------------------ Constraints
  {
    id: "places", group: "Constraints", label: "Cities and towns", on: false,
    source: { type: "vector", url: pm("places") }, sourceLayer: "places",
    layers: [{ id: "places-fill", type: "fill", paint: { "fill-color": "#6b5b7b", "fill-opacity": 0.22, "fill-outline-color": "#6b5b7b" } }],
    click: ["places-fill"],
    legend: [["fill", "#6b5b7b", 0.35, "City, town or census-designated place"]],
    src: "US Census Bureau place boundaries, 2023. Each parcel also carries its distance to the nearest one.",
    date: () => "2023",
  },
  {
    id: "flood", group: "Constraints", label: "Floodplain (FEMA)", on: false,
    source: { type: "vector", url: pm("flood") }, sourceLayer: "flood", minzoomNote: 7,
    layers: [{ id: "flood-fill", type: "fill", minzoom: 7, paint: { "fill-color": "#2a78d6", "fill-opacity": 0.32 } }],
    click: ["flood-fill"],
    legend: [["fill", "#2a78d6", 0.4, "1% annual chance flood zone (the 100-year floodplain)"]],
    src: "FEMA National Flood Hazard Layer, simplified to about 20 m. About 60 ERCOT counties have no countywide digital flood map: blank there means unmapped, not dry.",
    date: (m) => m.fema,
  },
  {
    id: "wetlands", group: "Constraints", label: "Wetlands (live from USFWS)", on: false,
    source: { type: "raster", tileSize: 512, minzoom: 10,
      tiles: ["https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/export?bbox={bbox-epsg-3857}&bboxSR=3857&imageSR=3857&size=512,512&format=png32&transparent=true&layers=show:0&f=image"],
      attribution: "Wetlands: US Fish and Wildlife Service" },
    layers: [{ id: "wetlands-raster", type: "raster", minzoom: 10.5, paint: { "raster-opacity": 0.7 } }],
    click: [], minzoomNote: 10.5,
    legend: [["fill", "#5aa469", 0.7, "Wetland types, in the National Wetlands Inventory colors"]],
    src: "US Fish and Wildlife Service, National Wetlands Inventory. Drawn live from their server when you zoom in close; not part of the parcel filters.",
    date: () => "live",
  },
  // ------------------------------------------------------------------ Land
  {
    id: "parcels", group: "Land", label: "Parcels of 100 acres or more", on: false,
    source: { type: "vector", url: pm("parcels"), promoteId: "id" }, sourceLayer: "parcels", minzoomNote: 8,
    layers: [
      { id: "parcels-fill", type: "fill", minzoom: 8, paint: { "fill-color": "#1f7a3a", "fill-opacity": ["interpolate", ["linear"], ["zoom"], 8, 0.3, 12, 0.14] } },
      { id: "parcels-line", type: "line", minzoom: 9.5, paint: { "line-color": "#14542a", "line-width": ["interpolate", ["linear"], ["zoom"], 9.5, 0.3, 13, 1.2] } },
      { id: "parcels-selected", type: "line", minzoom: 8, filter: ["==", ["get", "id"], ""], paint: { "line-color": "#ffd23f", "line-width": 4 } },
      { id: "parcels-selected-ink", type: "line", minzoom: 8, filter: ["==", ["get", "id"], ""], paint: { "line-color": "#17212b", "line-width": 1.2 } },
    ],
    click: ["parcels-fill"],
    legend: [["fill", "#1f7a3a", 0.35, "Parcel matching the Parcel finder filters"]],
    src: "TxGIO StratMap Land Parcels (county appraisal districts). Acres recomputed from the shapes. Harris County's file is incomplete.",
    date: () => "2025",
  },
  // ------------------------------------------------------------------ Gas
  {
    id: "gathering", group: "Gas", label: "Gas gathering lines", on: false,
    source: { type: "vector", url: pm("gathering") }, sourceLayer: "gathering", minzoomNote: 7,
    layers: [{ id: "gathering-line", type: "line", minzoom: 7, paint: { "line-color": "#b89466", "line-width": ["interpolate", ["linear"], ["zoom"], 7, 0.3, 12, 1] } }],
    click: ["gathering-line"],
    legend: [["line", "#b89466", 1.2, "Gathering line (raw gas from wells)"]],
    src: "Railroad Commission of Texas pipeline map. A sign of nearby production; gathering lines cannot feed a plant directly.",
    date: (m) => m.pipes,
  },
  {
    id: "pipes", group: "Gas", label: "Gas transmission pipelines", on: true,
    source: { type: "vector", url: pm("pipes") }, sourceLayer: "pipes",
    layers: [{ id: "pipes-line", type: "line", layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": PIPE_STYLES.diameter.color, "line-width": PIPE_WIDTH } }],
    click: ["pipes-line"],
    legend: PIPE_STYLES.diameter.legend,
    option: { label: "Color by", choices: [["diameter", "Diameter"], ["interstate", "Interstate or not"]] },
    src: "Railroad Commission of Texas pipeline map, in-service gas transmission lines. Diameter stands in for capacity, which is not public.",
    date: (m) => m.pipes,
  },
  {
    id: "lng", group: "Gas", label: "LNG export terminals", on: true,
    source: { type: "geojson", data: data("lng.geojson") },
    layers: [
      { id: "lng-dot", type: "circle", paint: { "circle-radius": 7, "circle-color": "#a8380a", "circle-stroke-color": "#fff", "circle-stroke-width": 2 } },
      { id: "lng-label", type: "symbol", layout: { "text-field": ["get", "name"], "text-font": FONT, "text-size": 11, "text-offset": [0, 1.3], "text-anchor": "top" },
        paint: { "text-color": "#6e2406", "text-halo-color": "#fff", "text-halo-width": 1.5 } },
    ],
    click: ["lng-dot"],
    legend: [["dot", "#a8380a", 7, "Operating or under construction"]],
    src: "Compiled by hand; locations from OpenStreetMap. They compete for pipeline gas but also mean large supply lines are nearby.",
    date: (m) => m.pipes,
  },
  // ------------------------------------------------------------------ Grid
  {
    id: "lines", group: "Grid", label: "Power lines", on: true,
    source: { type: "vector", url: pm("lines") }, sourceLayer: "lines",
    layers: [{ id: "lines-line", type: "line",
      filter: ["any", [">=", ["zoom"], 8], [">=", ["get", "kv"], 200]],
      paint: { "line-color": KV_COLOR, "line-width": ["interpolate", ["linear"], ["zoom"], 5, ["*", KV_WIDTH, 0.6], 11, ["*", KV_WIDTH, 1.6]] } }],
    click: ["lines-line"],
    legend: [["line", "#33208f", 3.5, "345 kV"], ["line", "#5a48cf", 2.6, "230 kV"], ["line", "#8a7de0", 2, "138 kV"], ["line", "#b3a8ee", 1.5, "69 to 115 kV"], ["line", "#a9a9b4", 1.2, "Voltage not recorded"]],
    src: "OpenStreetMap contributors. Mapped by volunteers from aerial photos: good coverage, but not an official utility map. Lines under 200 kV appear as you zoom in.",
    date: (m) => m.osm,
  },
  {
    id: "substations", group: "Grid", label: "Substations", on: true,
    source: { type: "geojson", data: data("substations.geojson"), promoteId: "id" },
    layers: [{ id: "substations-dot", type: "circle",
      filter: ["any", [">=", ["zoom"], 8], [">=", ["coalesce", ["get", "kv"], 0], 340]],
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, ["step", ["coalesce", ["get", "kv"], 0], 1.5, 130, 2, 340, 3], 11, ["step", ["coalesce", ["get", "kv"], 0], 4, 130, 5.5, 340, 8]],
        "circle-color": ["step", ["coalesce", ["get", "kv"], 0], "#a9a9b4", 60, "#b3a8ee", 130, "#8a7de0", 200, "#5a48cf", 340, "#33208f"],
        "circle-stroke-color": ["case", [">", ["get", "q_n"], 0], "#17212b", "#ffffff"],
        "circle-stroke-width": ["case", [">", ["get", "q_n"], 0], 2, 1] } }],
    click: ["substations-dot"],
    legend: [["dot", "#33208f", 8, "345 kV"], ["dot", "#8a7de0", 6, "138 to 230 kV"], ["dot", "#b3a8ee", 5, "69 to 115 kV"], ["ring", "#17212b", 6, "Dark ring: queue projects matched here"]],
    src: "OpenStreetMap contributors, substations of 69 kV and up. Queue projects are matched to them by name (see About). Lower voltages appear as you zoom in.",
    date: (m) => m.osm,
  },
  {
    id: "plants_proposed", group: "Grid", label: "Proposed power plants (EIA)", on: false,
    source: { type: "geojson", data: data("plants_proposed.geojson") },
    layers: [{ id: "plants_proposed-dot", type: "circle", paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, ["max", 2.5, ["*", 0.22, ["sqrt", ["get", "mw"]]]], 11, ["max", 5, ["*", 0.6, ["sqrt", ["get", "mw"]]]]],
      "circle-color": "rgba(255,255,255,0.55)", "circle-stroke-color": fuelColor("fuel"), "circle-stroke-width": 2 } }],
    click: ["plants_proposed-dot"],
    legend: [["ring", "#e34948", 6, "Gas"], ["ring", "#2a78d6", 6, "Wind"], ["ring", "#eda100", 6, "Solar"], ["ring", "#1baf7a", 6, "Storage"], ["ring", "#008300", 6, "Other"]],
    src: "EIA Form 860, units reported as planned. Circle size grows with MW.",
    date: (m) => String(m.eia),
  },
  {
    id: "plants", group: "Grid", label: "Operating power plants", on: true,
    source: { type: "geojson", data: data("plants.geojson") },
    layers: [{ id: "plants-dot", type: "circle", paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, ["max", 1.8, ["*", 0.17, ["sqrt", ["get", "mw"]]]], 11, ["max", 4, ["*", 0.6, ["sqrt", ["get", "mw"]]]]],
      "circle-color": fuelColor("fuel"), "circle-opacity": 0.85, "circle-stroke-color": "#ffffff", "circle-stroke-width": 1 } }],
    click: ["plants-dot"],
    legend: [["dot", "#e34948", 7, "Gas"], ["dot", "#2a78d6", 7, "Wind"], ["dot", "#eda100", 7, "Solar"], ["dot", "#1baf7a", 7, "Storage"], ["dot", "#008300", 7, "Coal, nuclear and other"]],
    src: "EIA Form 860, operating units in ERCOT counties. Circle size grows with MW; color is the plant's largest fuel.",
    date: (m) => String(m.eia),
  },
  {
    id: "queue", group: "Grid", label: "Interconnection queue projects", on: false,
    source: { type: "geojson", data: data("queue.geojson") },
    layers: [{ id: "queue-dot", type: "circle", paint: {
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 5, ["max", 2.5, ["*", 0.2, ["sqrt", ["get", "mw"]]]], 11, ["max", 5, ["*", 0.55, ["sqrt", ["get", "mw"]]]]],
      "circle-color": fuelColor("fuel"),
      "circle-opacity": ["match", ["get", "match"], "none", 0.25, 0.7],
      "circle-stroke-color": "#17212b", "circle-stroke-width": ["match", ["get", "match"], "none", 0.6, 1.5] } }],
    click: ["queue-dot"],
    legend: [["dot", "#e34948", 7, "Gas"], ["dot", "#eda100", 7, "Solar"], ["dot", "#2a78d6", 7, "Wind"], ["dot", "#1baf7a", 7, "Battery"], ["dot", "#008300", 7, "Other"],
      ["faint", "#8a94a0", 7, "Faint: connection point not located, shown at the county center"]],
    src: "ERCOT GIS Report, active projects. ERCOT gives the connection point as text, not coordinates; each project is placed at the substation its text names where that could be matched.",
    date: (m) => m.queue,
  },
  {
    id: "airports", group: "Constraints", label: "Airports", on: false,
    source: { type: "geojson", data: data("airports.geojson") },
    layers: [{ id: "airports-dot", type: "circle", filter: ["any", [">=", ["zoom"], 8], ["==", ["get", "use"], "Public"]],
      paint: { "circle-radius": ["match", ["get", "use"], "Public", 5, 3.5], "circle-color": ["match", ["get", "use"], "Public", "#17212b", "#ffffff"],
        "circle-stroke-color": "#17212b", "circle-stroke-width": 1.5 } }],
    click: ["airports-dot"],
    legend: [["dot", "#17212b", 6, "Public-use airport"], ["ring", "#17212b", 5, "Private airstrip (zoom in)"]],
    src: "FAA airport data from the US DOT National Transportation Atlas. Tall stacks near an airport need FAA review.",
    date: (m) => m.airports,
  },
];
