// Site summary: one printable page about a parcel. Built to grow into the fuller "fatal-flaw" check later:
// each section below is a function that returns HTML, so new checks are new sections.
import { $, esc, num, facts, table, miles, googleMapsUrl, googleEarthUrl, OWNER_TYPES } from "./util.js";

export function initSummary(ctx) {
  const { map, app } = ctx;

  async function mapPicture(r) {
    // Center the map on the parcel, wait for it to finish drawing, then copy the canvas.
    ctx.showLayer("parcels");
    await ctx.parcels.select(r.id, false);
    const idle = () => Promise.race([new Promise((ok) => map.once("idle", ok)), new Promise((ok) => setTimeout(ok, 7000))]);
    map.jumpTo({ center: [r.lon, r.lat], zoom: 11.5 });
    await idle();
    // Now that the parcel's tiles are loaded, frame the whole shape.
    const pieces = map.querySourceFeatures("parcels", { sourceLayer: "parcels", filter: ["==", ["get", "id"], r.id] });
    const pts = pieces.flatMap((f) => f.geometry.coordinates.flat(f.geometry.type === "Polygon" ? 1 : 2));
    if (pts.length) {
      const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
      map.fitBounds([[Math.min(...xs), Math.min(...ys)], [Math.max(...xs), Math.max(...ys)]], { padding: 90, maxZoom: 14.5, animate: false });
    } else map.jumpTo({ center: [r.lon, r.lat], zoom: 12.5 });
    // County shading would muddy the picture, so it is switched off while the picture is taken.
    const shade = map.getPaintProperty("counties-fill", "fill-opacity");
    map.setPaintProperty("counties-fill", "fill-opacity", 0);
    await idle();
    let picture = "";
    try { picture = map.getCanvas().toDataURL("image/jpeg", 0.85); } catch (e) { /* no picture */ }
    map.setPaintProperty("counties-fill", "fill-opacity", shade);
    return picture;
  }

  const sections = {
    parcel(r, c) {
      const cad = `https://www.google.com/search?q=${encodeURIComponent(`${c.name} County Appraisal District property search`)}`;
      return `<h2>The parcel</h2>` + facts([["Size", `${num(r.ac)} acres (from the mapped shape)`], ["County", `${esc(c.name)} County, Texas`],
        ["Owner type", esc(OWNER_TYPES[r.ot])], ["Owner", esc(r.on)], ["Owners on record", r.no > 1 ? num(r.no) : ""],
        ["Parcel ID", esc(r.pid)], ["Center point", `${r.lat}, ${r.lon}`]]) +
        `<p class="small">Owner of record: search parcel ID ${esc(r.pid)} at the <a href="${cad}">${esc(c.name)} County Appraisal District</a>.
         <a href="${googleMapsUrl(r.lat, r.lon)}">Google Maps</a>, <a href="${googleEarthUrl(r.lat, r.lon)}">Google Earth</a>.</p>`;
    },
    gas(r, c) {
      return `<h2>Gas supply</h2>` + facts([["Nearest gas line of 20 in or more", `${num(r.dp20, 1)} mi`], ["Nearest gas transmission line of any size", `${num(r.dpa, 1)} mi`]]) +
        (c.pipes?.length ? `<p class="small">Largest pipeline operators in the county: ${c.pipes.slice(0, 4).map((p) => `${esc(p[0])} (${num(p[1])} mi, up to ${num(p[2])} in)`).join("; ")}.</p>` : "") +
        `<p class="small">Distance to pipe says a connection is physically close. It says nothing about spare capacity, pressure or price.</p>`;
    },
    grid(r) {
      const subs = (ctx.points.substations || []).map((s) => ({ p: s.properties, d: miles(r.lat, r.lon, s.geometry.coordinates[1], s.geometry.coordinates[0]) }))
        .sort((a, b) => a.d - b.d).slice(0, 5);
      const plants = (ctx.points.plants || []).map((s) => ({ p: s.properties, d: miles(r.lat, r.lon, s.geometry.coordinates[1], s.geometry.coordinates[0]) }))
        .filter((x) => x.d <= 10).sort((a, b) => a.d - b.d).slice(0, 8);
      return `<h2>Grid connection</h2>` +
        facts([["Nearest 345 kV substation", `${num(r.ds345, 1)} mi`], ["Nearest substation of 138 kV or more", `${num(r.ds138, 1)} mi`], ["Nearest substation of 69 kV or more", `${num(r.ds69, 1)} mi`]]) +
        `<h3>Closest substations</h3>` + table(["Substation", "kV", "Miles from center", "Queue projects matched", "Queued MW"],
          subs.map((s) => [esc(s.p.name || "Not named"), esc(s.p.kvs || ""), num(s.d, 1), num(s.p.q_n), num(s.p.q_mw)]), "mini") +
        `<h3>Operating plants within 10 miles</h3>` +
        (plants.length ? table(["Plant", "Fuel", "MW", "Miles"], plants.map((s) => [esc(s.p.name), esc(s.p.fuel), num(s.p.mw), num(s.d, 1)]), "mini") : `<p class="small">None.</p>`) +
        `<p class="small">Queue figures count only projects whose connection point could be matched to a substation by name, so they are a floor. Whether a substation has room is decided by ERCOT and utility studies, not by this map.</p>`;
    },
    constraints(r, c) {
      const flood = r.fl < 0 ? "Unknown: FEMA has no countywide digital flood map here" : r.fl === 0 ? "None of the parcel" : `About ${num(r.fl)}% of the parcel`;
      return `<h2>Constraints checked</h2>` + facts([["In FEMA's 1% annual chance floodplain", flood],
        ["Nearest city or town", r.dpl === 0 ? "The parcel is inside or touching one" : `${num(r.dpl, 1)} mi`],
        ["Nearest public-use airport", `${num(r.dair, 1)} mi`], ["Nearest main road", `${num(r.drd, 1)} mi`]]) +
        `<p class="small">Not checked on this page: wetlands, protected species, slope and soils, existing easements, title, zoning, water supply.</p>`;
    },
    county(r, c) {
      const a = c.a || {};
      const ozone = a.ozone_classification || "Attainment";
      const q = Object.entries(c.queue || {}).sort((x, y) => y[1][1] - x[1][1]).map(([k, v]) => `${esc(k)} ${num(v[1])} MW (${num(v[0])})`).join(", ");
      return `<h2>${esc(c.name)} County</h2>` + facts([["Ozone rating (EPA)", esc(ozone)],
        ["NOx offsets", ozone === "Attainment" ? "None needed" : `${num(a.nox_offset_ratio, 2)} tons of credit per ton emitted`],
        ["NOx offset cost", a.nox_offset_cost_per_tpy ? `About $${num(a.nox_offset_cost_per_tpy)} per ton per year emitted` : (ozone === "Attainment" ? "" : "No priced credit trades in this area")],
        ["Active interconnection queue", q || "No active projects"], ["Population", num(c.pop)]]);
    },
    dates() {
      const m = app.meta;
      return `<h2>Data dates</h2><p class="small">Parcels: TxGIO 2025. Gas pipelines: Railroad Commission of Texas, ${esc(m.pipes)}. Substations and power lines: OpenStreetMap, ${esc(m.osm)}.
        Queue: ERCOT GIS Report, ${esc(m.queue)}. Plants: EIA-860, ${esc(m.eia)}. Floodplain: FEMA NFHL, ${esc(m.fema)}. Ozone: EPA Green Book, Aug 2026. NOx credits: TCEQ, Sep 2026.</p>
        <p class="small">This is a first-look screen made from public data. It cannot confirm grid capacity, gas supply, or that the land is for sale, and it does not replace title work, surveys, environmental studies or interconnection studies.</p>`;
    },
  };

  async function open(id) {
    const r = await ctx.parcels.getRow(id);
    if (!r) return;
    const c = app.counties[r.fips] || {};
    const picture = await mapPicture(r);
    $("#summaryBody").innerHTML = `
      <header><p class="kind">Site summary, ERCOT gas plant siting map</p>
      <h1>${num(r.ac)} acres in ${esc(c.name)} County, Texas</h1>
      <p class="small">Parcel ${esc(r.pid)}. Made ${new Date().toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" })}.</p></header>
      ${picture ? `<img src="${picture}" alt="Map of the parcel and nearby layers">` : ""}
      <div class="summary-cols">
        <section>${sections.parcel(r, c)}${sections.gas(r, c)}${sections.constraints(r, c)}</section>
        <section>${sections.grid(r, c)}${sections.county(r, c)}</section>
      </div>
      ${sections.dates()}`;
    $("#summary").hidden = false;
    document.body.classList.add("summary-open");
    $("#summary").scrollTop = 0;
  }

  function close() {
    $("#summary").hidden = true;
    document.body.classList.remove("summary-open");
  }
  $("#summaryClose").addEventListener("click", close);
  $("#summaryPrint").addEventListener("click", () => window.print());
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#summary").hidden) close(); });
  return { open, close };
}
