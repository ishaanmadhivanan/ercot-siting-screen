// "County score" tab: an optional score the user builds from the county factors.
import { $, $$, esc, num, table } from "./util.js";
import { showCounty } from "./details.js";

// 0-100 score for one factor across the ERCOT counties (same rules as the SQL view rpt.county_factor_score).
export function factorScores(app, metric, direction) {
  const key = metric.metric_key, log = metric.score_transform === "log";
  const t = {};
  for (const [fips, c] of Object.entries(app.counties)) {
    if (!c.ercot) continue;
    const raw = c.f[key];
    if (raw === undefined || raw === null) continue;
    if (metric.zero_is_missing && raw === 0) continue;       // nothing to measure: leave blank
    t[fips] = log ? Math.log(1 + raw) : raw;
  }
  const vals = Object.values(t);
  const min = Math.min(...vals), max = Math.max(...vals);
  const out = {};
  for (const [fips, v] of Object.entries(t)) {
    const s = max === min ? 50 : (100 * (v - min)) / (max - min);
    out[fips] = (direction || metric.better_direction) === "lower" ? 100 - s : s;
  }
  return out;
}

export function initScore(ctx) {
  const { app, map } = ctx;
  const factors = app.metrics.filter((m) => m.category);
  const order = ["Gas supply", "Grid connection", "Site control", "Air permit", "Community"];
  const cats = [...new Set(factors.map((m) => m.category))].sort((a, b) => order.indexOf(a) - order.indexOf(b));
  const box = $("#scoreFactors");

  box.innerHTML = cats.map((cat) => `
    <fieldset class="score-cat" data-cat="${esc(cat)}">
      <legend>${esc(cat)}</legend>
      <label class="slider cat-weight">Weight of this category <input type="range" min="0" max="10" value="5" data-catw> <output>5</output></label>
      ${factors.filter((m) => m.category === cat).map((m) => `
        <div class="score-factor" data-key="${m.metric_key}">
          <label class="check"><input type="checkbox" data-pick> ${esc(m.label)}</label>
          <div class="score-controls">
            <label class="slider">Weight <input type="range" min="0" max="10" value="5" data-w> <output>5</output></label>
            <select data-dir aria-label="Which direction is better for ${esc(m.label)}">
              <option value="higher" ${m.better_direction === "higher" ? "selected" : ""}>Higher is better</option>
              <option value="lower" ${m.better_direction === "lower" ? "selected" : ""}>Lower is better</option>
            </select>
          </div>
          <p class="hint">${esc(m.notes || "")}</p>
        </div>`).join("")}
    </fieldset>`).join("");

  function compute() {
    const picked = $$(".score-factor", box).filter((el) => $("[data-pick]", el).checked);
    $$(".score-factor", box).forEach((el) => el.classList.toggle("picked", $("[data-pick]", el).checked));
    if (!picked.length) {
      $("#scoreResult").innerHTML = "";
      ctx.countyColor.setScores(null);
      return null;
    }
    const perCat = {};
    for (const el of picked) {
      const m = factors.find((x) => x.metric_key === el.dataset.key);
      const w = Number($("[data-w]", el).value);
      if (w > 0) (perCat[m.category] ||= []).push({ w, s: factorScores(app, m, $("[data-dir]", el).value) });
    }
    const scores = {};
    for (const [fips, c] of Object.entries(app.counties)) {
      if (!c.ercot) continue;
      let top = 0, bottom = 0;
      for (const [cat, list] of Object.entries(perCat)) {
        const W = Number($(`[data-cat="${CSS.escape(cat)}"] [data-catw]`, box).value);
        let a = 0, b = 0;
        for (const f of list) if (f.s[fips] !== undefined) { a += f.w * f.s[fips]; b += f.w; }
        if (b > 0 && W > 0) { top += W * (a / b); bottom += W; }
      }
      if (bottom > 0) scores[fips] = top / bottom;
    }
    ctx.countyColor.setScores(scores);
    const ranked = Object.entries(scores).sort((a, b) => b[1] - a[1]);
    $("#scoreResult").innerHTML = `<h3>Highest-scoring counties</h3>` +
      table(["", "County", "Score"], ranked.slice(0, 15).map(([fips, s], i) =>
        [i + 1, `<button class="linkish" data-score-county="${fips}">${esc(app.counties[fips].name)}</button>`, num(s)]), "mini") +
      `<p class="hint">${num(ranked.length)} counties scored. The map is colored by this score; change that under Layers, Counties.</p>`;
    return scores;
  }

  box.addEventListener("input", (e) => {
    if (e.target.type === "range") e.target.nextElementSibling.textContent = e.target.value;
    compute();
  });
  $("#scoreResult").addEventListener("click", (e) => {
    const b = e.target.closest("[data-score-county]");
    if (!b) return;
    showCounty(b.dataset.scoreCounty);
    const f = map.querySourceFeatures("counties", { filter: ["==", ["get", "fips"], b.dataset.scoreCounty] })[0];
    if (f) {
      const pts = f.geometry.type === "Polygon" ? f.geometry.coordinates[0] : f.geometry.coordinates.flat(2);
      const lons = pts.map((p) => p[0]), lats = pts.map((p) => p[1]);
      map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], { padding: 80, maxZoom: 9 });
    }
  });
  $("#scorePreset").addEventListener("click", () => {
    // Every factor ticked, equal weights: the same set-up as the Power BI report's defaults.
    $$("[data-pick]", box).forEach((x) => { x.checked = true; });
    $$("input[type=range]", box).forEach((x) => { x.value = 5; x.nextElementSibling.textContent = "5"; });
    $$(".score-factor", box).forEach((el) => {
      $("[data-dir]", el).value = factors.find((m) => m.metric_key === el.dataset.key).better_direction;
    });
    compute();
  });
  $("#scoreClear").addEventListener("click", () => {
    $$("[data-pick]", box).forEach((x) => { x.checked = false; });
    compute();
  });
  return { compute };
}
