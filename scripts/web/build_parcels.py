"""
build_parcels.py  --  website (Phase 7): candidate parcels

Finds every land parcel of 100 acres or more in the TxGIO county files
(data/raw/parcels/parcels_<fips>.zip) and measures what a first look at a
site needs:

    acres            recomputed in an equal-area projection (the supplied
                     area fields are unreliable, see scripts/load_parcels.py)
    owner type       Government / Company / Trust or estate / Individual /
                     Not listed, read from the owner name
    distances (mi)   to the nearest gas transmission line of 20 in or more,
                     any gas transmission line, a substation at 69+, 138+ and
                     345 kV, a main road, a city or town boundary, and a
                     public-use airport. Measured from the parcel edge.
    floodplain       share of the parcel inside FEMA's 1%-annual-chance flood
                     zone; blank where FEMA has no countywide digital map

PRIVACY. Names of individuals, trusts and estates are never written out,
and no mailing or site addresses are read at all. An owner name is kept
only when it is a government body or clearly a registered business
(LLC, LP, Inc, Ltd ...).

    python scripts/web/build_parcels.py           # process counties not done yet
    python scripts/web/build_parcels.py tiles     # then build parcels.pmtiles + per-county CSV files
    python scripts/web/build_parcels.py 48001     # redo one county

Needs data/processed/web/ref.pkl from build_layers.py (step "ref").
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import pickle
import re
import sys
import time
import zipfile

import numpy as np
import pyogrio
import shapely
from pyproj import CRS, Transformer
from shapely import STRtree

from common import METERS_PER_MILE, OUT, RAW, SQM_PER_ACRE, WORK, tippecanoe, to_albers, write_json

SRC = RAW / "parcels"
CACHE = WORK / "parcels"
CACHE.mkdir(parents=True, exist_ok=True)
MIN_ACRES = 100
BUDGET = int(os.environ.get("PARCEL_BUDGET", 100000))   # optional time limit in seconds
MIN_DEG2 = 3.0e-5                # 100 acres is at least 3.6e-5 square degrees anywhere in Texas

STRONG = re.compile(r"\b(LLC|L L C|LC|LP|L P|LLP|LLLP|LTD|LIMITED|INC|INCORPORATED|CORP|CORPORATION|COMPANY|PARTNERSHIP|"
                    r"PARTNERS|HOLDINGS|BANK|COOP|COOPERATIVE|ASSOCIATION|ASSN|FOUNDATION|CHURCH|PLC|FLP)\b")
WEAK = re.compile(r"\b(RANCH|RANCHES|FARM|FARMS|PROPERTIES|INVESTMENTS|CATTLE|MINERALS|ENERGY|OIL|ENTERPRISES|VENTURES|"
                  r"CEMETERY|CLUB|DAIRY|TIMBER|LAND CO|CATTLE CO|RESOURCES|DEVELOPMENT|REALTY|MINISTRIES)\b")
GOV = re.compile(r"\b(STATE OF TEXAS|STATE OF TX|UNITED STATES|U S GOVERNMENT|COUNTY OF|CITY OF|TOWN OF|VILLAGE OF|ISD|I S D|"
                 r"INDEPENDENT SCHOOL|SCHOOL DIST|SCHOOL DISTRICT|UNIVERSITY|COLLEGE DIST|RIVER AUTHORITY|WATER DISTRICT|WATER DIST|"
                 r"MUD|UTILITY DISTRICT|NAVIGATION DIST|NAVIGATION DISTRICT|PORT OF|DRAINAGE DIST|HOSPITAL DIST|APPRAISAL DIST|"
                 r"GENERAL LAND OFFICE|PERMANENT SCHOOL FUND|PARKS AND WILDLIFE|PARKS WILDLIFE|TXDOT|DEPT OF|DEPARTMENT OF|"
                 r"CORPS OF ENGINEERS|BUREAU OF|NATIONAL PARK|NATIONAL FOREST|HOUSING AUTHORITY|WATER AUTHORITY|MUNICIPAL|"
                 r"VETERANS LAND BOARD|TEXAS A M|WATER SUPPLY|WATER CONTROL)\b|\bCOUNTY$|^USA$|^U S A$|^STATE OF\b")
TRUST = re.compile(r"\b(TRUST|TRUSTEE|TRUSTEES|TR|TRS|ESTATE|EST|HEIRS|REVOCABLE|LIVING|LIFE ESTATE|ET AL|ETAL)\b")
TYPE_RANK = {"G": 4, "C": 3, "T": 2, "I": 1, "U": 0}


def classify(name: str) -> tuple[str, bool]:
    """Owner name -> (type code, True if the name may be published)."""
    n = re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", str(name or "").upper())).strip()
    if not n or n in ("UNKNOWN", "NONE", "NULL", "NAN"):
        return "U", False
    strong = bool(STRONG.search(n))
    if GOV.search(n) and (not strong or re.search(r"\b(CITY|COUNTY|STATE|TOWN) OF\b", n)):
        return "G", True
    if strong:
        return "C", True
    if TRUST.search(n):
        return "T", False
    if WEAK.search(n):
        return "C", False
    return "I", False


def nearest_miles(tree: STRtree, geoms) -> np.ndarray:
    idx, dist = tree.query_nearest(geoms, return_distance=True, all_matches=False)
    out = np.full(len(geoms), np.nan)
    out[idx[0]] = dist
    return np.round(out / METERS_PER_MILE, 1)


def process(zpath, ref, trees, flood_mapped: bool) -> list[dict]:
    fips = re.search(r"(\d{5})", zpath.name).group(1)
    with zipfile.ZipFile(zpath) as z:
        gdb = sorted({n.split(".gdb/")[0] + ".gdb" for n in z.namelist() if ".gdb/" in n})[0]
    src = f"/vsizip/{zpath.as_posix()}/{gdb}"
    crs = CRS.from_user_input(pyogrio.read_info(src)["crs"])
    # Read only shapes that could reach 100 acres. Shape_Area is in the file's own units:
    # square degrees for longitude/latitude files, square metres or feet for projected ones
    # (Web Mercator overstates area, so the same cut-off is still safe there).
    if crs.is_geographic:
        cut = MIN_DEG2
    else:
        cut = 0.9 * MIN_ACRES * SQM_PER_ACRE / crs.axis_info[0].unit_conversion_factor ** 2
    # Shape_Area must be in the column list for the filter to apply.
    meta, _, geom, fields = pyogrio.raw.read(src, columns=["Prop_ID", "GEO_ID", "OWNER_NAME", "Shape_Area"],
                                             where=f"Shape_Area > {cut}")
    f = dict(zip(meta["fields"], fields))
    keep = np.array([g is not None for g in geom], dtype=bool)
    wkb = geom[keep]
    owners, prop, geo = f["OWNER_NAME"][keep], f["Prop_ID"][keep], f["GEO_ID"][keep]
    if len(wkb) == 0:
        return []

    # one shape can repeat once per co-owner: keep it once, remember every owner
    keys = np.array([hashlib.md5(b).hexdigest() for b in wkb])
    _, first, inverse = np.unique(keys, return_index=True, return_inverse=True)
    shapes_ll = shapely.from_wkb(wkb[first])
    if crs.to_epsg() != 4326:
        tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        shapes_ll = shapely.transform(shapes_ll, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))
    shapes_ll = shapely.make_valid(shapes_ll)
    shapes = to_albers(shapes_ll)
    acres = shapely.area(shapes) / SQM_PER_ACRE
    big = np.where(acres >= MIN_ACRES)[0]
    if len(big) == 0:
        return []
    by_shape: dict[int, list[int]] = {}
    for rec, s in enumerate(inverse):
        by_shape.setdefault(int(s), []).append(rec)

    g = shapes[big]
    d = {k: nearest_miles(trees[k], g) for k in ("pipe_20", "pipe_any", "sub_69", "sub_138", "sub_345", "road", "place", "airport")}
    flood = np.full(len(big), -1.0)
    if flood_mapped:
        flood[:] = 0
        ip, iflood = trees["flood"].query(g, predicate="intersects")
        if len(ip):
            with np.errstate(all="ignore"):
                part = shapely.area(shapely.intersection(g[ip], ref["flood"][iflood]))
            tot = np.zeros(len(big))
            np.add.at(tot, ip, np.nan_to_num(part))
            flood = np.clip(tot / shapely.area(g), 0, 1) * 100
    # about 12 m simplification, coordinates rounded to 5 decimals (about 1 m)
    simp = shapely.transform(shapely.simplify(shapes_ll[big], 0.00012, preserve_topology=True), lambda xy: np.round(xy, 5))
    pts = shapely.point_on_surface(shapes_ll[big])

    feats = []
    for n, s in enumerate(big):
        recs = by_shape[int(s)]
        names = sorted({str(owners[r]).strip() for r in recs if owners[r] is not None and str(owners[r]).strip()})
        typed = [classify(x) + (x,) for x in names] or [("U", False, "")]
        code, publish, nm = max(typed, key=lambda t: TYPE_RANK[t[0]])
        pid = str(prop[recs[0]] or "").strip()
        pid = re.sub(r"\.0+$", "", pid)
        props = {"id": f"{fips}-{n}", "fips": fips, "ac": int(round(acres[s])), "ot": code,
                 "on": re.sub(r"\s+", " ", nm).title() if publish else "", "no": len(names),
                 "pid": pid, "gid": str(geo[recs[0]] or "").strip(),
                 "dp20": d["pipe_20"][n], "dpa": d["pipe_any"][n], "ds69": d["sub_69"][n], "ds138": d["sub_138"][n],
                 "ds345": d["sub_345"][n], "drd": d["road"][n], "dpl": d["place"][n], "dair": d["airport"][n],
                 "fl": int(round(flood[n])), "lat": round(pts[n].y, 5), "lon": round(pts[n].x, 5)}
        if simp[n].is_empty:
            continue
        feats.append({"type": "Feature", "properties": props, "geometry": json.loads(shapely.to_geojson(simp[n]))})
    return feats


CSV_COLS = ["id", "fips", "ac", "ot", "on", "no", "pid", "gid", "dp20", "dpa", "ds69", "ds138", "ds345", "drd", "dpl", "dair", "fl", "lat", "lon"]


def tiles() -> None:
    """All cached counties -> parcels.pmtiles, one CSV per county for the finder list, and an index."""
    files = sorted(CACHE.glob("*.geojsonl"))
    (OUT / "parcels").mkdir(exist_ok=True)
    index = {}
    for fl in files:
        fips = fl.stem
        rows = [json.loads(ln)["properties"] for ln in fl.read_text().splitlines() if ln]
        index[fips] = len(rows)
        with open(OUT / "parcels" / f"{fips}.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(CSV_COLS)
            for r in rows:
                w.writerow([r[c] for c in CSV_COLS])
    write_json(OUT / "parcel_index.json", index)
    print(f"  {sum(index.values()):,} parcels in {len(index)} counties")
    nonempty = [str(f) for f in files if f.stat().st_size > 0]
    tippecanoe(OUT / "parcels.pmtiles", ["-l", "parcels", "-Z7", "-z11", "-P", "--drop-smallest-as-needed", "--simplification=3",
                                         "--maximum-tile-bytes=450000", "--no-tiny-polygon-reduction",
                                         "-x", "lat", "-x", "lon", "-x", "gid", "-x", "no"] + nonempty)


def main() -> None:
    args = sys.argv[1:]
    if args == ["tiles"]:
        return tiles()
    t0 = time.time()
    ref = pickle.load(open(WORK / "ref.pkl", "rb"))
    trees = {k: STRtree(v) for k, v in ref.items()}
    counties = json.loads((OUT / "app_data.json").read_text())["counties"]
    todo = [z for z in sorted(SRC.glob("parcels_*.zip"))
            if (not args and not (CACHE / f"{z.stem.split('_')[1]}.geojsonl").exists()) or z.stem.split("_")[1] in args]
    print(f"{len(todo)} counties to do (ref loaded in {time.time() - t0:.0f}s)")
    for z in todo:
        if time.time() - t0 > BUDGET:
            print("time budget used; run again to continue")
            return
        fips = z.stem.split("_")[1]
        t = time.time()
        feats = process(z, ref, trees, counties.get(fips, {}).get("flood_mapped", False))
        (CACHE / f"{fips}.geojsonl").write_text("\n".join(json.dumps(f, separators=(",", ":")) for f in feats))
        print(f"{fips}: {len(feats):,} parcels of {MIN_ACRES}+ acres ({time.time() - t:.0f}s)")
    print("all counties done; now run: python scripts/web/build_parcels.py tiles")


if __name__ == "__main__":
    main()
