// What the details card says when something on the map is clicked.
import { esc, num, facts, table, mapLinks, OWNER_TYPES } from "./util.js";

let ctx = null;
const points = { plants: null, substations: null };   // loaded once, used for county totals and the site summary

export function setDetailContext(c) {
  ctx = c;
  ctx.points = points;
  for (const name of Object.keys(points)) {
    fetch(ctx.dataUrl(`${name}.geojson`)).then((r) => r.json()).then((g) => { points[name] = g.features; });
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-action]");
    if (!b) return;
    const a = b.dataset.action;
    if (a === "summary") ctx.summary.open(b.dataset.id);
    if (a === "county") showCounty(b.dataset.fips);
    if (a === "zoom") ctx.map.flyTo({ center: [Number(b.dataset.lon), Number(b.dataset.lat)], zoom: Math.max(ctx.map.getZoom(), Number(b.dataset.z || 12)) });
  });
}

const MATCH_WORDS = { high: "name and voltage match", medium: "name match", low: "weak match", none: "not located" };
const FLOOD_ZONES = { A: "no base flood elevation set", AE: "base flood elevation set", AH: "shallow ponding", AO: "shallow sheet flow",
  VE: "coastal, with wave action", V: "coastal, with wave action", "A99": "protected by a levee under construction", AR: "levee being restored" };

export function countyName(fips) { return ctx.app.counties[fips]?.name || ""; }

function title(kind, name) { return `<p class="kind">${esc(kind)}</p><h2>${esc(name)}</h2>`; }

function countyLink(fips) {
  const n = countyName(fips);
  return n ? `<button class="linkish" data-action="county" data-fips="${fips}">${esc(n)} County</button>` : "";
}

export function showCounty(fips) { ctx.showDetail(countyHtml(fips)); }

function queueTable(list) {
  return table(["Project", "Fuel", "MW", "Online", "Match"],
    list.map((p) => [esc(p[1]), esc(p[2]), num(p[3]), esc(p[4]), esc(MATCH_WORDS[p[5]] || p[5])]), "mini");
}

// ---------------------------------------------------------------- county
export function countyHtml(fips) {
  const c = ctx.app.counties[fips];
  if (!c) return "";
  if (!c.ercot) {
    return title("County", `${c.name} County`) + `<p>This county is not on the ERCOT grid, so the county figures stop at the boundary. The map layers (pipelines, power lines, flood zones) still cover it.</p>`;
  }
  const a = c.a || {}, metrics = ctx.app.metrics;
  const q = c.queue || {};
  const qRows = Object.entries(q).sort((x, y) => y[1][1] - x[1][1]).map(([fuel, v]) => [esc(fuel), num(v[0]), num(v[1])]);
  const plants = (points.plants || []).filter((p) => p.properties.fips === fips);
  const byFuel = {};
  for (const p of plants) byFuel[p.properties.fuel] = (byFuel[p.properties.fuel] || 0) + p.properties.mw;
  const scored = metrics.filter((m) => m.category && c.f[m.metric_key] !== undefined);
  const order = ["Gas supply", "Grid connection", "Site control", "Air permit", "Community"];
  const cats = [...new Set(scored.map((m) => m.category))].sort((x, y) => order.indexOf(x) - order.indexOf(y));
  const value = (m) => {
    const v = c.f[m.metric_key];
    if (m.zero_is_missing && v === 0) return ["none", ""];        // nothing to measure, not a zero score
    return [num(v, Math.abs(v) < 10 ? 2 : 0), esc(m.unit)];
  };
  const factorRows = cats.flatMap((cat) => scored.filter((m) => m.category === cat).map((m) => [esc(cat), esc(m.label), ...value(m)]));
  const ozone = a.ozone_classification || "Attainment";
  const nonattain = ozone !== "Attainment";
  const air = [["Ozone rating (EPA)", esc(ozone) + (a.ozone_standards_detail ? ` <span class="muted">(${esc(a.ozone_standards_detail)})</span>` : "")]];
  if (nonattain) {
    air.push(["NOx offset ratio", a.nox_offset_ratio ? `${num(a.nox_offset_ratio, 2)} tons of credit per ton emitted` : ""],
      ["Major source threshold", a.nox_major_source_tpy ? `${num(a.nox_major_source_tpy)} tons of NOx per year` : ""],
      ["NOx credit price (area median)", a.nox_credit_price_per_tpy ? `$${num(a.nox_credit_price_per_tpy)} per ton per year` : "No priced trades in this area"],
      ["Offset cost per ton emitted", a.nox_offset_cost_per_tpy ? `$${num(a.nox_offset_cost_per_tpy)}` : ""],
      ["Credits traded, Oct 2024 to Sep 2026", a.nox_credit_tons_traded !== undefined ? `${num(a.nox_credit_tons_traded, 1)} tons per year in ${num(a.nox_credit_trades)} trades` : ""]);
  } else air.push(["NOx offsets", "None needed. A new plant still needs pollution controls."]);
  const nParcels = ctx.app.parcelIndex?.[fips];
  return title("County", `${c.name} County`) +
    facts([["Population", num(c.pop)], ["Land area", `${num(c.sqmi)} sq mi`],
      ["Parcels of 100+ acres", nParcels !== undefined ? num(nParcels) : "No parcel file"],
      ["FEMA flood map", c.flood_mapped ? "Countywide digital map" : "No countywide digital map"],
      ["LNG terminals", esc(a.lng_terminals || "")]]) +
    `<h3>Air permit</h3>` + facts(air) +
    `<h3>Interconnection queue in the county</h3>` +
    (qRows.length ? table(["Fuel", "Projects", "MW"], qRows, "mini") : `<p class="muted">No active projects.</p>`) +
    `<h3>Operating power plants</h3>` +
    (plants.length ? `<p>${num(plants.length)} ${plants.length === 1 ? "plant" : "plants"}: ${Object.entries(byFuel).sort((x, y) => y[1] - x[1]).map(([k, v]) => `${esc(k)} ${num(v)} MW`).join(", ")}.</p>` : `<p class="muted">None.</p>`) +
    `<h3>Gas pipeline operators</h3>` +
    (c.pipes?.length ? table(["Operator", "Miles", "Largest pipe (in)"], c.pipes.map((p) => [esc(p[0]), num(p[1], 1), num(p[2], 1)]), "mini") : `<p class="muted">No transmission pipe.</p>`) +
    `<h3>County factors</h3>` + table(["Category", "Factor", "Value", "Unit"], factorRows, "mini") +
    `<p class="muted">Sources and dates for every factor are on the <a href="about.html#catalog">About page</a>.</p>`;
}

// ---------------------------------------------------------------- parcel
export function parcelHtml(p) {
  const c = ctx.app.counties[p.fips] || {};
  const hasPoint = p.lat !== undefined && p.lat !== "";
  const flood = Number(p.fl) < 0 ? "FEMA has no countywide digital map here" : Number(p.fl) === 0 ? "None of the parcel" : `About ${num(p.fl)}% of the parcel`;
  const cadSearch = `https://www.google.com/search?q=${encodeURIComponent(`${c.name} County Appraisal District property search`)}`;
  return title("Parcel", `${num(p.ac)} acres in ${c.name || ""} County`) +
    facts([["Owner type", esc(OWNER_TYPES[p.ot] || "")], ["Owner", esc(p.on || "")], ["Parcel ID", esc(p.pid || "")]]) +
    `<p class="muted">For the owner of record, search parcel ID ${esc(p.pid || "")} at the <a href="${cadSearch}" target="_blank" rel="noopener">${esc(c.name || "")} County Appraisal District</a>.</p>` +
    `<h3>Distances from the parcel edge</h3>` +
    facts([["Gas line, 20 in or larger", `${num(p.dp20, 1)} mi`], ["Any gas transmission line", `${num(p.dpa, 1)} mi`],
      ["Substation, 345 kV", `${num(p.ds345, 1)} mi`], ["Substation, 138 kV and up", `${num(p.ds138, 1)} mi`],
      ["Substation, 69 kV and up", `${num(p.ds69, 1)} mi`], ["Main road", `${num(p.drd, 1)} mi`],
      ["City or town", Number(p.dpl) === 0 ? "Inside or touching one" : `${num(p.dpl, 1)} mi`], ["Public-use airport", `${num(p.dair, 1)} mi`]]) +
    `<h3>Constraints</h3>` + facts([["In the floodplain", flood], ["County ozone rating", esc(c.a?.ozone_classification || "Attainment")]]) +
    `<p class="btn-row"><button class="btn primary" data-action="summary" data-id="${esc(p.id)}">Site summary</button></p>` +
    (hasPoint ? mapLinks(p.lat, p.lon) : "") +
    `<p>${countyLink(p.fips)}</p>`;
}

// ---------------------------------------------------------------- everything else
export function describe(f, lngLat, short = false) {
  const p = f.properties, layer = f.layer.id;
  const at = f.geometry.type === "Point" ? { lat: f.geometry.coordinates[1], lon: f.geometry.coordinates[0] } : { lat: lngLat.lat, lon: lngLat.lng };
  const lat = at.lat.toFixed(5), lon = at.lon.toFixed(5);

  if (layer === "counties-fill") return short ? `${p.name} County` : countyHtml(p.fips);

  if (layer === "parcels-fill") {
    if (short) return `Parcel, ${num(p.ac)} acres`;
    return parcelHtml({ ...p, lat, lon });
  }

  if (layer === "plants-dot" || layer === "plants_proposed-dot") {
    const proposed = layer !== "plants-dot";
    if (short) return `${proposed ? "Proposed plant" : "Power plant"}: ${p.name}`;
    return title(proposed ? "Proposed power plant" : "Power plant", p.name) +
      facts([["Capacity", `${num(p.mw, 1)} MW`], ["Fuel", esc(p.mix)], ["Type", esc(p.tech)], ["Units", num(p.units)],
        [proposed ? "Planned online" : "Online since", p.first ? (p.first === p.last ? p.first : `${p.first} to ${p.last}`) : ""], ["EIA plant ID", p.id]]) +
      mapLinks(lat, lon) + `<p>${countyLink(p.fips)}</p>`;
  }

  if (layer === "substations-dot") {
    const name = p.name || "Substation (not named on the map)";
    if (short) return `Substation: ${name}`;
    const q = ctx.app.sub_queue[p.id] || { direct: [], tap: [] };
    let html = title("Substation", name) + facts([["Voltage", p.kvs ? `${esc(p.kvs)} kV` : "Not recorded"], ["Operator", esc(p.op)]]);
    html += `<h3>Queue projects connecting here</h3>`;
    html += q.direct.length
      ? `<p><strong>${num(p.q_n)} projects, ${num(p.q_mw)} MW.</strong> Gas: ${num(p.q_gas_n)} projects, ${num(p.q_gas_mw)} MW.</p>` + queueTable(q.direct)
      : `<p class="muted">None matched to this substation.</p>`;
    if (q.tap.length) html += `<h3>Projects tapping a line from here</h3><p>${num(p.tap_n)} projects, ${num(p.tap_mw)} MW.</p>` + queueTable(q.tap);
    html += `<p class="muted">Matched from ERCOT's connection-point text by station name. A project that could not be matched is counted in its county only, so treat this as a floor.</p>`;
    return html + mapLinks(lat, lon) + `<p>${countyLink(p.fips)}</p>`;
  }

  if (layer === "queue-dot") {
    if (short) return `Queue project: ${p.name}`;
    return title("Interconnection queue project", p.name) +
      facts([["Fuel", `${esc(p.fuel)} (${esc(p.tech)})`], ["Capacity", `${num(p.mw, 1)} MW`], ["Planned online", esc(p.cod)],
        ["Study status", esc(p.phase)], ["ERCOT ID", esc(p.inr)], ["County", esc(p.county)],
        ["Connection point (ERCOT's words)", esc(p.poi)], ["Where it is drawn", esc(p.how)]]) +
      (p.match === "none" ? "" : mapLinks(lat, lon)) + `<p>${countyLink(p.fips)}</p>`;
  }

  if (layer === "pipes-line" || layer === "gathering-line") {
    const gathering = layer === "gathering-line";
    const op = String(p.OPER_NM || "").replace(/\b\w+/g, (w) => w.length > 3 ? w[0] + w.slice(1).toLowerCase() : w);
    if (short) return `${gathering ? "Gathering line" : "Gas pipeline"}: ${op}`;
    return title(gathering ? "Gas gathering line" : "Gas transmission pipeline", op) +
      facts([["Diameter", p.DIAMETER ? `${num(p.DIAMETER, 2)} in` : "Not recorded"], ["System", esc(p.SYS_NM || "")],
        ["Regulation", gathering ? "" : p.INTERSTATE === "Y" ? "Interstate (FERC, published rates)" : "Inside Texas (Railroad Commission, terms set privately)"]]) +
      `<p class="muted">The map shows where pipe is, not whether it has spare capacity.</p>`;
  }

  if (layer === "lines-line") {
    if (short) return `Power line${p.kvs ? `, ${p.kvs} kV` : ""}`;
    return title("Power line", p.name || (p.kvs ? `${p.kvs} kV line` : "Power line")) +
      facts([["Voltage", p.kvs ? `${esc(p.kvs)} kV` : "Not recorded"], ["Operator", esc(p.op)], ["Circuits", esc(p.circuits)]]) +
      `<p class="muted">From OpenStreetMap, mapped by volunteers.</p>`;
  }

  if (layer === "flood-fill") {
    if (short) return `Flood zone ${p.FLD_ZONE}`;
    return title("FEMA flood zone", `Zone ${p.FLD_ZONE}`) +
      `<p>Inside the 1% annual chance floodplain${FLOOD_ZONES[p.FLD_ZONE] ? ` (${FLOOD_ZONES[p.FLD_ZONE]})` : ""}. Shapes are simplified; check FEMA's map before relying on an edge.</p>`;
  }

  if (layer === "places-fill") return short ? p.name : title(p.kind, p.name);

  if (layer === "airports-dot") {
    if (short) return `Airport: ${p.name}`;
    return title(`${p.use}-use airport`, p.name) + facts([["FAA ID", esc(p.id)], ["City", esc(p.city)]]) + mapLinks(lat, lon);
  }

  if (layer === "lng-dot") {
    if (short) return `LNG terminal: ${p.name}`;
    return title("LNG export terminal", p.name) + facts([["Status", esc(p.status)], ["County", esc(p.county)], ["Note", esc(p.note)], ["Location from", esc(p.loc)]]) + mapLinks(lat, lon);
  }
  return short ? "Feature" : "";
}
