"""
load_parcels.py  --  Phase 4 (land)

Turns TxGIO StratMap Land Parcels (2025 release, one zip per county, saved
in data/raw/parcels/parcels_<fips>.zip by download_parcels.ps1) into county
land metrics.

WHAT THE TEST COUNTIES SHOWED (Ward, Freestone, Young, Wharton)
1. Land-use codes cannot be relied on. The state property code
   (STAT_LAND_USE) is blank for every parcel in Wharton and two thirds of
   Young; Ward codes 433,000 acres of ranch land as C1 ("vacant lot").
   So the SCORED metrics use only parcel size and ownership, which every
   county reports. Code-based industrial acres are kept as context, and
   only where at least 80% of parcels carry a code.
2. One polygon can appear many times. Undivided-interest owners each get
   their own record on the same shape (one Ward polygon appears 134 times).
   Raw acreage overstated Ward by 3x. Shapes are de-duplicated by their exact
   geometry before any acreage is summed; owners are still counted from
   every record.
3. The supplied GIS_AREA field is unusable statewide: some counties compute
   it in Web Mercator, which inflates areas ~38% at Texas latitudes. Acres
   are recomputed here in Texas Centric Albers Equal Area (EPSG:3083).
   Check: de-duplicated parcel acres match Census land area within 2% in
   Freestone, Young and Wharton (Ward +10%, from overlapping tracts).

METRICS (per county)
  land_large_tract_share   share of parcel acres in parcels of 100+ acres
                           (room to site a plant on one ownership)
  land_owner_density       distinct owners per 1,000 acres of rural
                           parcels (5+ acres): fragmentation, i.e. how many
                           landowners a project must deal with
  land_parcels_500ac       count of parcels of 500+ acres
  land_industrial_acres    acres coded F2 (industrial real property) or J3
                           (electric utility) - brownfield context only,
                           left out where code coverage is under 80%
  land_code_coverage       share of parcels with a state land-use code
  land_parcel_coverage     de-duplicated parcel acres / Census land area
  land_parcel_vintage      data month from the TxGIO file name (YYYYMM)

Each county is cached in data/processed/parcels/<fips>.json, so re-runs only
process new zips. Output: data/processed/county_land_attribute.csv (tall),
loaded into fact.county_attribute by sql/02_load/18_load_land.sql.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Transformer

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "parcels"
CACHE = REPO / "data" / "processed" / "parcels"
OUT = REPO / "data" / "processed" / "county_land_attribute.csv"
DEMOG = REPO / "data" / "processed" / "dim_county_demog.csv"

SQM_PER_ACRE = 4046.8564224
INDUSTRIAL_CODES = ("F2", "J3")
MIN_CODE_COVERAGE = 0.80


def norm_owner(s: pd.Series) -> pd.Series:
    s = s.fillna("").astype(str).str.upper()
    s = s.str.replace(r"[^A-Z0-9 ]", " ", regex=True).str.replace(r"\s+", " ", regex=True).str.strip()
    return s


def process(zpath: Path, land_acres: float) -> dict:
    fips = re.search(r"(\d{5})", zpath.name).group(1)
    with zipfile.ZipFile(zpath) as z:
        shp = [n for n in z.namelist() if n.lower().endswith(".shp")][0]
    vintage = re.search(r"_(\d{6})\.shp$", shp)
    src = f"/vsizip/{zpath.as_posix()}/{shp}"

    meta, _, geom, fields = pyogrio.raw.read(src, columns=["OWNER_NAME", "STAT_LAND_"], encoding="latin1")
    df = pd.DataFrame({n: f for n, f in zip(meta["fields"], fields)})
    keep = np.array([g is not None for g in geom])
    df = df[keep].reset_index(drop=True)
    wkb = [g for g in geom if g is not None]
    df["gkey"] = [hashlib.md5(b).hexdigest() for b in wkb]

    # one row per distinct shape for acreage
    first = ~df["gkey"].duplicated()
    shapes = shapely.from_wkb([w for w, f in zip(wkb, first) if f])
    tr = Transformer.from_crs(meta["crs"], "EPSG:3083", always_xy=True)
    shapes = shapely.transform(shapes, lambda xy: np.column_stack(tr.transform(xy[:, 0], xy[:, 1])))
    acres = shapely.area(shapes) / SQM_PER_ACRE
    u = df[first].copy()
    u["acres"] = acres

    df["owner"] = norm_owner(df["OWNER_NAME"])
    df = df.merge(u[["gkey", "acres"]], on="gkey", how="left")
    code = df["STAT_LAND_"].fillna("").astype(str).str.upper().str.strip()
    df["code"] = code.str.extract(r"^([A-Z][0-9]?)")[0]       # 'E1,D2' -> 'E1'; ' ' -> NaN

    total = float(u["acres"].sum())
    rural = df[df["acres"] >= 5]
    rural_acres = float(rural.drop_duplicates("gkey")["acres"].sum())
    owners = rural.loc[rural["owner"] != "", "owner"].nunique()
    code_cov = float(df["code"].notna().mean())
    ind = df[df["code"].isin(INDUSTRIAL_CODES)].drop_duplicates("gkey")["acres"].sum()

    return {
        "county_fips": fips,
        "records": int(len(df)),
        "shapes": int(len(u)),
        "parcel_acres": round(total, 1),
        "land_large_tract_share": round(float(u.loc[u["acres"] >= 100, "acres"].sum()) / total, 4) if total else None,
        "land_owner_density": round(owners / rural_acres * 1000, 3) if rural_acres else None,
        "land_parcels_500ac": int((u["acres"] >= 500).sum()),
        "land_industrial_acres": round(float(ind), 1) if code_cov >= MIN_CODE_COVERAGE else None,
        "land_code_coverage": round(code_cov, 4),
        "land_parcel_coverage": round(total / land_acres, 4) if land_acres else None,
        "land_parcel_vintage": vintage.group(1) if vintage else None,
    }


def main() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    land = (pd.read_csv(DEMOG, dtype={"county_fips": str}).set_index("county_fips")["land_area_sqmi"] * 640)
    only = set(sys.argv[1:])           # optional: process just these FIPS
    budget = 150                        # seconds per run; re-run to continue
    t0 = time.time()
    for z in sorted(RAW.glob("parcels_*.zip")):
        fips = z.stem.split("_")[1]
        if only and fips not in only:
            continue
        out = CACHE / f"{fips}.json"
        if out.exists() and out.stat().st_mtime > z.stat().st_mtime:
            continue
        if time.time() - t0 > budget:
            print("Time budget used; re-run to continue.")
            break
        t = time.time()
        res = process(z, float(land.get(fips, np.nan)))
        out.write_text(json.dumps(res))
        print(f"{fips}: {res['shapes']:,} shapes, {res['parcel_acres']:,.0f} ac, "
              f"coverage {res['land_parcel_coverage']}, codes {res['land_code_coverage']:.0%} ({time.time()-t:.0f}s)")

    rows = [json.loads(p.read_text()) for p in sorted(CACHE.glob("*.json"))]
    if not rows:
        return
    wide = pd.DataFrame(rows)
    num = ["land_large_tract_share", "land_owner_density", "land_parcels_500ac", "land_industrial_acres",
           "land_code_coverage", "land_parcel_coverage"]
    tall = wide.melt(id_vars="county_fips", value_vars=num, var_name="attribute_key", value_name="value_num")
    tall = tall.dropna(subset=["value_num"])
    tall["value_text"] = ""
    vint = wide[["county_fips", "land_parcel_vintage"]].dropna().rename(columns={"land_parcel_vintage": "value_text"})
    vint["attribute_key"] = "land_parcel_vintage"
    vint["value_num"] = np.nan
    tall = pd.concat([tall, vint[tall.columns]], ignore_index=True).sort_values(["county_fips", "attribute_key"])
    tall.to_csv(OUT, index=False, lineterminator="\n")
    print(f"\n{len(wide)} counties summarised -> {OUT.relative_to(REPO)} ({len(tall)} rows)")


if __name__ == "__main__":
    main()
