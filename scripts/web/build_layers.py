"""
build_layers.py  --  website (Phase 7): every map layer except parcels

Turns the raw downloads (scripts/web/fetch_layers.py), the processed CSVs
from the earlier phases and the SQL export (sql/05_export/30_export_web.sql
saved as data/processed/web_export.csv) into the files the website loads
from web/data/.

    python scripts/web/build_layers.py            # all steps
    python scripts/web/build_layers.py core       # one step

Steps
    core     counties, county facts, plants, substations, queue matching,
             LNG terminals, airports  (small GeoJSON/JSON files)
    lines    power lines            -> lines.pmtiles
    pipes    gas transmission pipe  -> pipes.pmtiles
    gath     gas gathering pipe     -> gathering.pmtiles
    places   cities and towns       -> places.pmtiles
    flood    FEMA flood zones       -> flood.pmtiles
    ref      distance reference shapes for build_parcels.py (not published)

Small layers are plain GeoJSON. Big ones are PMTiles (vector tiles in one
file that a static site can read piece by piece).
"""
from __future__ import annotations

import datetime as dt
import difflib
import glob
import json
import pickle
import re
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import pyogrio
import shapely
from shapely import STRtree

from common import METERS_PER_MILE, OUT, PROC, RAW, RAWWEB, SEED, WORK, read_sql_export, tippecanoe, to_albers, write_json

GIS_REPORT = sorted(glob.glob(str(RAW / "*GIS_Report*.xlsx")))[-1]


# ----------------------------------------------------------------- shared loaders
def load_counties():
    """Texas county shapes (Census 1:500k) as (fips list, names, shapely polygons in lon/lat)."""
    src = f"/vsizip/{RAWWEB / 'cb_2023_us_county_500k.zip'}"
    meta, _, geom, fields = pyogrio.raw.read(src, columns=["GEOID", "NAME"])
    keep = np.array([str(g).startswith("48") for g in fields[0]])
    geoms, ids, nm = shapely.from_wkb(geom[keep]), fields[0][keep], fields[1][keep]
    order = np.argsort(ids)
    return list(ids[order]), list(nm[order]), geoms[order]


def county_of(points_lonlat, fips, polys):
    """County FIPS for each point (None if outside Texas)."""
    tree = STRtree(polys)
    pts = shapely.points(points_lonlat)
    idx_pt, idx_poly = tree.query(pts, predicate="within")
    out = [None] * len(pts)
    for i, j in zip(idx_pt, idx_poly):
        out[i] = fips[j]
    return out


def kv_list(tag: str | None) -> list[float]:
    """OpenStreetMap voltage tag ('345000;138000') -> [345.0, 138.0] in kV."""
    out = []
    for part in re.split(r"[;,/]", tag or ""):
        part = part.strip()
        if part.replace(".", "", 1).isdigit():
            v = float(part) / 1000
            if 1 <= v <= 800:
                out.append(v)
    return sorted(set(out), reverse=True)


# ----------------------------------------------------------------- queue parsing
FUEL_LABEL = {"GAS": "Gas", "SOL": "Solar", "WIN": "Wind", "OIL": "Other", "WAT": "Other", "HYD": "Other",
              "NUC": "Other", "OTH": "Other", "BIO": "Other", "COA": "Other", "GEO": "Other"}
STRIP_WORDS = (r"\b(SUBSTATION|SUB|SWITCHING STATION|SWITCH STATION|SWITCHING|SWITCHYARD|SWITCH|STATION|SW STA|SW|POI|POD|"
               r"LINE|EXISTING|NEW|PROPOSED|NAME|BUS|NO|NUMBER|PSSE|THE|FROM|CKT|CIRCUIT|CKTS|KV|"
               r"AEP|ONCOR|LCRA|TNMP|CNP|CENTERPOINT|STEC|BEPC|BRAZOS|ETT|WETT|LST|CPS|TMPA|SHARYLAND|RAYBURN|GSEC)\b")


def norm_name(s: str) -> str:
    s = str(s).upper()
    s = re.sub(r"\(.*?\)", " ", s)                       # (Bus# 43110), (PSSE#7100)
    s = re.sub(r"[#<>\"“”'’.,:;]", " ", s)
    s = re.sub(r"\b\d{2,3}\s*-?\s*KV\b", " ", s)         # 345kV, 138 KV, 345-kV
    s = re.sub(STRIP_WORDS, " ", s)
    s = re.sub(r"\b\d+\b", " ", s)                       # bus numbers
    s = re.sub(r"(?<=[A-Z])[_ ]?\d[A-Z]?\b", "", s)      # RILEY7A, CORSWEST1_8 -> RILEY, CORSWEST
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_poi(text: str) -> dict:
    """ERCOT 'POI Location' free text -> voltage, whether it taps a line, and 1-2 station names."""
    t = str(text).replace("\n", " ").strip()
    up = t.upper()
    kv = None
    m = re.search(r"(\d{2,3})\s*-?\s*KV", up) or re.search(r"\b(345|138|69|115|230)\b\s*$", up)
    if m and float(m.group(1)) in (69, 115, 138, 230, 345):
        kv = float(m.group(1))
    body = re.sub(r"^\s*(TO THE|TAP(PING)?( OF| ON)?|TAPS?)\b", " ", up)
    parts = re.split(r"\s+(?:-+|–|—|TO|AND|&)\s+|\s*/\s*", body)
    names = [n for n in (norm_name(p) for p in parts) if len(n) >= 3]
    is_tap = bool(re.search(r"\bTAP", up)) or (len(names) >= 2 and bool(re.search(r"\bLINE\b|\bCKT\b|-|–| TO ", up)))
    return {"kv": kv, "tap": is_tap and len(names) >= 2, "names": names[:2]}


def read_queue() -> pd.DataFrame:
    """Active projects from the ERCOT GIS report, large and small, with the connection point text."""
    fips = dict(zip(*[pd.read_csv(SEED / "dim_county_tx.csv", dtype=str)[c] for c in ("match_key", "county_fips")]))
    frames = []
    for sheet, hdr, size in (("Project Details - Large Gen", 30, "Large"), ("Project Details - Small Gen", 14, "Small")):
        df = pd.read_excel(GIS_REPORT, sheet_name=sheet, header=hdr, usecols="A:K")
        df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
        df = df[df["INR"].notna() & df["County"].notna()].copy()
        df["phase"] = df.iloc[:, 2].astype(str) if size == "Large" else ""
        df["size"] = size
        frames.append(df)
    q = pd.concat(frames, ignore_index=True)
    key = (q["County"].astype(str).str.split(r"[,/]").str[0].str.lower().str.replace(r"\s+county$", "", regex=True)
           .str.replace(r"[^a-z0-9]", "", regex=True))
    q["fips"] = key.map(fips)
    q["mw"] = pd.to_numeric(q["Capacity (MW)"], errors="coerce").fillna(0).clip(lower=0)   # repowers report net change
    tech = q["Technology"].astype(str).str.upper()
    q["fuel"] = np.where(tech.eq("BA"), "Battery", q["Fuel"].astype(str).str.upper().map(FUEL_LABEL).fillna("Other"))
    q["cod"] = pd.to_datetime(q["Projected COD"], errors="coerce").dt.strftime("%Y-%m")
    q["poi"] = q["POI Location"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    return q[q["fips"].notna()].reset_index(drop=True)


def match_queue(q: pd.DataFrame, subs: list[dict], centroids: dict) -> None:
    """Attach each queue project to OpenStreetMap substations where the names allow it.

    ERCOT gives no coordinates, only free text such as "7043 Hays 345kV" or
    "Tap 345kV 3109 Stryker to 3100 Martin Lake". Matching is by station name
    inside the project's county (then within 60 km of it), checked against voltage.

    match   meaning
    high    same name and the substation carries that voltage
    medium  same name, voltage unknown or different; or a close spelling with matching voltage
    low     no name match, but the county has exactly one substation at that voltage
    none    not located: shown at the county center, counted in the county only
    """
    by_county = defaultdict(list)
    for s in subs:
        s["norm"] = norm_name(s["name"]) if s["name"] else ""
        s["compact"] = s["norm"].replace(" ", "")
        by_county[s["fips"]].append(s)
    named = [s for s in subs if s["norm"]]

    def find(name: str, fips: str, kv: float | None):
        compact = name.replace(" ", "")
        cx, cy = centroids[fips]
        local = by_county.get(fips, [])
        near = [s for s in named if abs(s["lon"] - cx) < 0.9 and abs(s["lat"] - cy) < 0.7]   # roughly 60 km around
        for pool, pool_rank in ((local, 0), (near, 1)):
            best = None
            for s in pool:
                if not s["norm"]:
                    continue
                volt_ok = kv is not None and kv in s["kvs"]
                if s["norm"] == name or s["compact"] == compact:
                    score = 3 if volt_ok else 2
                elif len(compact) >= 5 and (s["compact"].startswith(compact) or compact.startswith(s["compact"])) and len(s["compact"]) >= 5:
                    score = 2 if volt_ok else 1
                elif len(compact) >= 6 and difflib.SequenceMatcher(None, s["compact"], compact).ratio() >= 0.88:
                    score = 2 if volt_ok else 1
                else:
                    continue
                if pool_rank == 1:
                    score -= 1                      # outside the stated county: one step less sure
                if score >= 1 and (best is None or score > best[0]):
                    best = (score, s)
            if best:
                return best[1], {3: "high", 2: "medium", 1: "low"}[best[0]]
        return None, "none"

    out_sub, out_sub2, out_conf, out_how, lat, lon = [], [], [], [], [], []
    for r in q.itertuples():
        p = parse_poi(r.poi)
        a = b = None
        conf, how = "none", "Connection point not located; shown at the county center"
        if p["names"]:
            a, conf = find(p["names"][0], r.fips, p["kv"])
        if p["tap"] and len(p["names"]) == 2:
            b, conf_b = find(p["names"][1], r.fips, p["kv"])
            rank = {"high": 3, "medium": 2, "low": 1, "none": 0}
            if a and b:
                conf = min(conf, conf_b, key=rank.get)
                how = f"Taps the line between {a['name']} and {b['name']}; shown at the midpoint"
            elif a or b:
                a = a or b
                b = None
                conf = "low"
                how = f"Taps a line from {a['name']}; the other end was not found, so it is shown at {a['name']}"
        elif a:
            how = f"Matched to {a['name']} by name" + (" and voltage" if conf == "high" else "")
        if not a and p["kv"]:
            same = [s for s in by_county.get(r.fips, []) if p["kv"] in s["kvs"]]
            if len(same) == 1:
                a, conf = same[0], "low"
                how = f"No name match; {a['name'] or 'this'} is the only {p['kv']:g} kV substation mapped in the county"
        if a and b:
            lat.append(round((a["lat"] + b["lat"]) / 2, 5)); lon.append(round((a["lon"] + b["lon"]) / 2, 5))
        elif a:
            lat.append(a["lat"]); lon.append(a["lon"])
        else:
            lat.append(round(centroids[r.fips][1], 5)); lon.append(round(centroids[r.fips][0], 5))
        out_sub.append(a["id"] if a else None); out_sub2.append(b["id"] if b else None)
        out_conf.append(conf if a else "none"); out_how.append(how)
        q.at[r.Index, "kv"] = p["kv"]
    q["sub"], q["sub2"], q["match"], q["how"], q["lat"], q["lon"] = out_sub, out_sub2, out_conf, out_how, lat, lon


# ----------------------------------------------------------------- core step
def core() -> None:
    rows = read_sql_export()
    fips, names, polys = load_counties()
    cent = {f: (p.representative_point().x, p.representative_point().y) for f, p in zip(fips, polys)}
    sqlc = {r["county_fips"]: r for r in rows if r["t"] == "county"}
    ercot = {f for f, r in sqlc.items() if r.get("in_ercot")}
    metrics = [{k: v for k, v in r.items() if k != "t"} for r in rows if r["t"] == "metric"]
    today = dt.date.today().isoformat()

    counties = {f: {"name": sqlc[f]["county_name"], "ercot": f in ercot, "pop": sqlc[f].get("population"),
                    "sqmi": sqlc[f].get("land_area_sqmi"), "f": {}, "s": {}, "a": {}} for f in fips}
    for r in rows:
        c = counties.get(r.get("county_fips"))
        if c is None:
            continue
        if r["t"] == "factor" and "raw_value" in r:
            c["f"][r["factor_key"]] = r["raw_value"]
            if "factor_score" in r:
                c["s"][r["factor_key"]] = round(r["factor_score"], 2)     # Power BI's score, for checking
        elif r["t"] == "attr":
            c["a"][r["attribute_key"]] = r["value_text"] if r.get("value_text") else r.get("value_num")

    # FEMA: which counties have a countywide digital flood map
    ids_path = RAWWEB / "fema_sfha" / "_dfirm_ids.json"
    dfirm = set(json.loads(ids_path.read_text())) if ids_path.exists() else set()
    for f, c in counties.items():
        c["flood_mapped"] = (f + "C") in dfirm

    # --- pipelines per county (top operators), from the county table built in Phase 3
    seg = pd.read_csv(PROC / "fact_pipeline_segment.csv", dtype={"county_fips": str})
    for f, g in seg.groupby("county_fips"):
        if f in counties:
            top = (g.groupby("operator_name").agg(mi=("miles", "sum"), dmax=("diameter_in", "max"))
                   .sort_values("mi", ascending=False).head(8))
            counties[f]["pipes"] = [[n.title(), round(r.mi, 1), r.dmax] for n, r in top.iterrows()]

    # --- power plants (operating, latest EIA-860), one point per plant
    gen = pd.read_csv(PROC / "fact_generator_capacity.csv", dtype={"county_fips": str})
    gen = gen[(gen.data_vintage_year == gen.data_vintage_year.max()) & gen.county_fips.isin(ercot)]
    fuel = dict(pd.read_csv(SEED / "dim_fuel.csv")[["technology", "fuel_category"]].values)
    gen["fuel"] = gen.technology.map(fuel).fillna("Other")
    gen.loc[gen.fuel.isin(["Biomass", "Geothermal", "Oil", "Hydro"]), "fuel"] = "Other"
    feats = []
    for status, key in (("Operating", "plants"), ("Proposed", "plants_proposed")):
        feats = []
        g0 = gen[(gen.status_group == status) & gen.latitude.notna()]
        for code, g in g0.groupby("plant_code"):
            by_fuel = g.groupby("fuel").nameplate_mw.sum().sort_values(ascending=False)
            feats.append({"type": "Feature",
                          "geometry": {"type": "Point", "coordinates": [round(float(g.longitude.iloc[0]), 5), round(float(g.latitude.iloc[0]), 5)]},
                          "properties": {"id": int(code), "name": g.plant_name.iloc[0], "fips": g.county_fips.iloc[0],
                                         "mw": round(float(g.nameplate_mw.sum()), 1), "fuel": by_fuel.index[0],
                                         "mix": "; ".join(f"{k} {v:,.0f} MW" for k, v in by_fuel.items()),
                                         "tech": "; ".join(sorted(set(g.technology))),
                                         "units": int(len(g)),
                                         "first": int(g.operating_year.min()) if g.operating_year.notna().any() else None,
                                         "last": int(g.operating_year.max()) if g.operating_year.notna().any() else None}})
        write_json(OUT / f"{key}.geojson", {"type": "FeatureCollection", "features": feats})
        print(f"  {key}: {len(feats)}")

    # --- substations (OpenStreetMap): 60 kV and up, or tagged as transmission
    subs = []
    raw = json.loads((RAWWEB / "osm_subs.json").read_text())["elements"]
    for e in raw:
        t = e.get("tags", {})
        kvs = kv_list(t.get("voltage"))
        top = kvs[0] if kvs else None
        if not ((top and top >= 60) or (top is None and t.get("substation") == "transmission")):
            continue
        c = e.get("center") or e
        subs.append({"id": e["type"][0] + str(e["id"]), "name": t.get("name", ""), "op": t.get("operator", ""),
                     "kv": top, "kvs": kvs, "kind": t.get("substation", ""), "lat": round(c["lat"], 5), "lon": round(c["lon"], 5)})
    for s, f in zip(subs, county_of([(s["lon"], s["lat"]) for s in subs], fips, polys)):
        s["fips"] = f
    subs = [s for s in subs if s["fips"]]

    # --- queue projects and matching
    q = read_queue()
    q = q[q.fips.isin(counties.keys())].reset_index(drop=True)
    match_queue(q, subs, cent)
    sub_q = defaultdict(lambda: {"direct": [], "tap": []})
    qfeats = []
    for r in q.itertuples():
        rec = [r.INR, str(r._2), r.fuel, round(r.mw, 1), r.cod if isinstance(r.cod, str) else "", r.match]
        if r.sub and not r.sub2:
            sub_q[r.sub]["direct" if "Taps" not in r.how else "tap"].append(rec)
        elif r.sub and r.sub2:
            sub_q[r.sub]["tap"].append(rec); sub_q[r.sub2]["tap"].append(rec)
        qfeats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
                       "properties": {"inr": r.INR, "name": str(r._2), "fuel": r.fuel, "tech": str(r.Technology), "mw": round(r.mw, 1),
                                      "cod": r.cod if isinstance(r.cod, str) else "", "phase": r.phase, "size": r.size,
                                      "fips": r.fips, "county": counties[r.fips]["name"], "poi": r.poi,
                                      "kv": None if pd.isna(r.kv) else r.kv, "match": r.match, "how": r.how,
                                      "sub": r.sub, "sub2": r.sub2}})
    write_json(OUT / "queue.geojson", {"type": "FeatureCollection", "features": qfeats})
    stats = q.groupby("match").agg(n=("mw", "size"), mw=("mw", "sum")).round(0).to_dict("index")
    print("  queue match:", stats)

    sfeats = []
    for s in subs:
        d = sub_q.get(s["id"], {"direct": [], "tap": []})
        mw = sum(p[3] for p in d["direct"]); gas = [p for p in d["direct"] if p[2] == "Gas"]
        sfeats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                       "properties": {"id": s["id"], "name": s["name"], "op": s["op"], "kv": s["kv"],
                                      "kvs": "/".join(f"{v:g}" for v in s["kvs"]), "kind": s["kind"], "fips": s["fips"],
                                      "q_n": len(d["direct"]), "q_mw": round(mw, 1), "q_gas_n": len(gas),
                                      "q_gas_mw": round(sum(p[3] for p in gas), 1), "tap_n": len(d["tap"]),
                                      "tap_mw": round(sum(p[3] for p in d["tap"]), 1)}})
    write_json(OUT / "substations.geojson", {"type": "FeatureCollection", "features": sfeats})
    print(f"  substations: {len(sfeats)}")

    # county queue totals (every active project counts in its county, matched or not)
    for f, g in q.groupby("fips"):
        by = g.groupby("fuel").agg(n=("mw", "size"), mw=("mw", "sum"))
        counties[f]["queue"] = {k: [int(v.n), round(float(v.mw), 1)] for k, v in by.iterrows()}

    # --- LNG terminals
    lng = pd.read_csv(SEED / "lng_terminals.csv", dtype=str).merge(pd.read_csv(SEED / "lng_terminal_locations.csv"), on="terminal")
    write_json(OUT / "lng.geojson", {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r.longitude, r.latitude]},
         "properties": {"name": r.terminal, "status": r.status, "county": r.county_name,
                        "note": "" if pd.isna(r.note) else r.note, "loc": r.location_source}} for r in lng.itertuples()]})

    # --- airports (FAA). Public-use airports matter most for tall stacks and airspace review.
    air = json.loads((RAWWEB / "airports_tx.geojson").read_text())["features"]
    afeats = []
    eff = ""
    for a in air:
        p = a["properties"]
        if p.get("SITE_TYPE_CODE") != "A" or p.get("ARPT_STATUS") != "O" or not a.get("geometry"):
            continue
        eff = max(eff, p.get("EFF_DATE") or "")
        afeats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(c, 5) for c in a["geometry"]["coordinates"][:2]]},
                       "properties": {"id": p["ARPT_ID"], "name": p["ARPT_NAME"].title(), "city": (p.get("CITY") or "").title(),
                                      "use": "Public" if p.get("FACILITY_USE_CODE") == "PU" else "Private"}})
    write_json(OUT / "airports.geojson", {"type": "FeatureCollection", "features": afeats})

    # --- county shapes (simplified a little) with a few properties for labels and popups
    simp = shapely.simplify(polys, 0.003, preserve_topology=True)
    cfeats = [{"type": "Feature", "id": int(f), "geometry": json.loads(shapely.to_geojson(shapely.set_precision(g, 0.0001))),
               "properties": {"fips": f, "name": counties[f]["name"], "ercot": counties[f]["ercot"],
                              "ozone": counties[f]["a"].get("ozone_classification", "")}}
              for f, g in zip(fips, simp)]
    write_json(OUT / "counties.geojson", {"type": "FeatureCollection", "features": cfeats})

    osm_date = json.loads((RAWWEB / "osm_subs.json").read_text())["osm3s"]["timestamp_osm_base"][:10]
    pipe_date = str(seg["download_date"].max()) if "download_date" in seg else ""
    m = re.search(r"GIS_Report_([A-Za-z]+)(\d{4})", GIS_REPORT)
    meta = {"built": today, "osm": osm_date, "pipes": pipe_date, "queue": f"{m.group(1)} {m.group(2)}" if m else "",
            "eia": int(gen.data_vintage_year.max()), "airports": eff.replace("/", "-"), "fema": today[:7],
            "queue_match": {k: {"n": int(v["n"]), "mw": float(v["mw"])} for k, v in stats.items()}}
    write_json(OUT / "app_data.json", {"meta": meta, "metrics": metrics, "counties": counties,
                                       "sub_queue": {k: v for k, v in sub_q.items()}})
    pickle.dump({"subs": subs, "cent": cent}, open(WORK / "core.pkl", "wb"))


# ----------------------------------------------------------------- tile steps
def lines() -> None:
    feats = []
    for f in sorted(glob.glob(str(RAWWEB / "osm_lines_*.json"))):
        for e in json.loads(open(f).read())["elements"]:
            t = e.get("tags", {})
            kvs = kv_list(t.get("voltage"))
            if (kvs and kvs[0] < 60) or len(e.get("geometry", [])) < 2:
                continue
            feats.append({"type": "Feature", "id": e["id"],
                          "geometry": {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in e["geometry"]]},
                          "properties": {"kv": kvs[0] if kvs else 0, "kvs": "/".join(f"{v:g}" for v in kvs),
                                         "op": t.get("operator", ""), "name": t.get("name", ""), "circuits": t.get("circuits", "")}})
    seen, uniq = set(), []
    for ft in feats:                       # lines that cross a download box come back twice
        if ft["id"] not in seen:
            seen.add(ft["id"]); uniq.append(ft)
    src = WORK / "lines.geojson"
    src.write_text(json.dumps({"type": "FeatureCollection", "features": uniq}))
    print(f"  power lines: {len(uniq)}")
    tippecanoe(OUT / "lines.pmtiles", ["-l", "lines", "-Z4", "-z11", "--drop-densest-as-needed", "--simplification=4", str(src)])


def pipes() -> None:
    pages = sorted(glob.glob(str(RAWWEB / "rrc_ngt" / "page_*.geojson")))
    tippecanoe(OUT / "pipes.pmtiles", ["-l", "pipes", "-Z4", "-z11", "--drop-densest-as-needed", "--simplification=4",
                                       "-y", "DIAMETER", "-y", "OPER_NM", "-y", "SYS_NM", "-y", "INTERSTATE", "-y", "COMMODITY1"] + pages)


def gath() -> None:
    pages = sorted(glob.glob(str(RAWWEB / "rrc_gath" / "page_*.geojson")))
    tippecanoe(OUT / "gathering.pmtiles", ["-l", "gathering", "-Z7", "-z11", "--drop-densest-as-needed", "--simplification=6",
                                           "-y", "DIAMETER", "-y", "OPER_NM"] + pages)


def places() -> None:
    src = f"/vsizip/{RAWWEB / 'cb_2023_48_place_500k.zip'}"
    meta, _, geom, fields = pyogrio.raw.read(src, columns=["NAME", "LSAD"])
    geoms = shapely.from_wkb(geom)
    feats = [{"type": "Feature", "geometry": json.loads(shapely.to_geojson(g)),
              "properties": {"name": n, "kind": "Census-designated place" if l == "57" else "City or town"}}
             for g, n, l in zip(geoms, fields[0], fields[1])]
    dst = WORK / "places.geojson"
    dst.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    tippecanoe(OUT / "places.pmtiles", ["-l", "places", "-Z5", "-z11", "--coalesce-densest-as-needed", "--simplification=4", str(dst)])


def flood() -> None:
    pages = sorted(glob.glob(str(RAWWEB / "fema_sfha" / "page_*.geojson")))
    tippecanoe(OUT / "flood.pmtiles", ["-l", "flood", "-Z7", "-z12", "--simplification=6", "--maximum-tile-bytes=350000",
                                       "--coalesce-smallest-as-needed", "--detect-shared-borders", "-y", "FLD_ZONE"] + pages)


# ----------------------------------------------------------------- reference shapes for parcel distances
def ref() -> None:
    """Everything build_parcels.py measures distance to, in metres (EPSG:3083)."""
    core_cache = pickle.load(open(WORK / "core.pkl", "rb"))
    out = {}

    def read_pages(folder):
        geoms, diam = [], []
        for f in sorted(glob.glob(str(RAWWEB / folder / "page_*.geojson"))):
            for ft in json.loads(open(f).read())["features"]:
                if ft.get("geometry"):
                    geoms.append(shapely.geometry.shape(ft["geometry"])); diam.append(ft["properties"].get("DIAMETER") or 0)
        return np.array(geoms, dtype=object), np.array(diam, dtype=float)

    g, d = read_pages("rrc_ngt")
    g = to_albers(g)
    out["pipe_any"] = g
    out["pipe_20"] = g[d >= 20]
    subs = core_cache["subs"]
    pts = to_albers(shapely.points([(s["lon"], s["lat"]) for s in subs]))
    kv = np.array([s["kv"] or 0 for s in subs])
    out["sub_69"], out["sub_138"], out["sub_345"] = pts[kv >= 60], pts[kv >= 130], pts[kv >= 340]
    roads = []
    for f in sorted(glob.glob(str(RAWWEB / "osm_roads_*.json"))):
        for e in json.loads(open(f).read())["elements"]:
            if len(e.get("geometry", [])) >= 2:
                roads.append(shapely.linestrings([[p["lon"], p["lat"]] for p in e["geometry"]]))
    out["road"] = to_albers(np.array(roads, dtype=object))
    meta, _, geom, _f = pyogrio.raw.read(f"/vsizip/{RAWWEB / 'cb_2023_48_place_500k.zip'}", columns=["NAME"])
    out["place"] = to_albers(shapely.from_wkb(geom))
    air = json.loads((OUT / "airports.geojson").read_text())["features"]
    out["airport"] = to_albers(shapely.points([a["geometry"]["coordinates"] for a in air if a["properties"]["use"] == "Public"]))
    fl = []
    for f in sorted(glob.glob(str(RAWWEB / "fema_sfha" / "page_*.geojson"))):
        for ft in json.loads(open(f).read())["features"]:
            if ft.get("geometry"):
                fl.append(shapely.geometry.shape(ft["geometry"]))
    fl = shapely.make_valid(to_albers(np.array(fl, dtype=object)))
    out["flood"] = fl
    pickle.dump(out, open(WORK / "ref.pkl", "wb"), protocol=4)
    print("  ref:", {k: len(v) for k, v in out.items()})


STEPS = {"core": core, "lines": lines, "pipes": pipes, "gath": gath, "places": places, "flood": flood, "ref": ref}

if __name__ == "__main__":
    for step in (sys.argv[1:] or list(STEPS)):
        print(step)
        STEPS[step]()
