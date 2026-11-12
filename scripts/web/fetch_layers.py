"""
fetch_layers.py  --  website (Phase 7) raw downloads

Downloads the public map data the website needs into data/raw/web/.
Everything here is free and needs no account or key.

    python scripts/web/fetch_layers.py            # run every step that is not done yet
    python scripts/web/fetch_layers.py rrc_gath   # run one step

Each step skips work that is already on disk, so the script can simply be
run again after a dropped connection until it prints "all steps done". To
download something again, delete it from data/raw/web/ first.

Steps and sources
    counties   US Census cartographic county boundaries (2023, 1:500k)
    places     US Census cartographic place boundaries for Texas (2023)
    osm_subs   OpenStreetMap power substations in Texas (Overpass API)
    osm_lines  OpenStreetMap power lines in Texas
    osm_roads  OpenStreetMap motorways, trunk and primary roads (distance only)
    osm_lng    OpenStreetMap features named "LNG" (to place the LNG terminals)
    rrc_ngt    Railroad Commission of Texas gas transmission lines, with shapes
    rrc_gath   Railroad Commission of Texas gas gathering lines, with shapes
    airports   FAA aviation facilities (US DOT / BTS National Transportation Atlas)
    fema       FEMA National Flood Hazard Layer: 1%-annual-chance flood zones
               (Special Flood Hazard Areas) for Texas, simplified to about 20 m
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw" / "web"
RAW.mkdir(parents=True, exist_ok=True)
UA = "ercot-siting-screen/1.0 (github.com/ishaanmadhivanan/ercot-siting-screen)"
BUDGET = int(os.environ.get("FETCH_BUDGET", 100000))   # optional time limit in seconds, for shells that cut long jobs off
T0 = time.time()
TX_AREA = 3600114690  # OpenStreetMap relation 114690 (Texas) as an Overpass area
OVERPASS = "https://overpass-api.de/api/interpreter"
RRC = "https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0/query"


def out_of_time() -> bool:
    return time.time() - T0 > BUDGET


def get(url: str, data: bytes | None = None, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    for attempt in range(3):            # public servers drop the odd connection
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception:
            if attempt == 2:
                raise
            time.sleep(4)


def download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    print("downloading", url)
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(get(url))
    tmp.replace(dest)


def counties() -> bool:
    download("https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_county_500k.zip", RAW / "cb_2023_us_county_500k.zip")
    return True


def places() -> bool:
    download("https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_48_place_500k.zip", RAW / "cb_2023_48_place_500k.zip")
    return True


# Texas split into boxes (south, west, north, east) so no single Overpass answer is huge.
BOXES = [(s, w, s + 2.75, w + 3.35) for s in (25.7, 28.45, 31.2, 33.95) for w in (-106.8, -103.45, -100.1, -96.75)]


def overpass(name: str, selector: str, out: str, boxed: bool) -> bool:
    boxes = BOXES if boxed else [None]
    for i, box in enumerate(boxes):
        dest = RAW / (f"{name}_{i:02d}.json" if boxed else f"{name}.json")
        if dest.exists():
            continue
        if out_of_time():
            return False
        bbox = f"({box[0]},{box[1]},{box[2]},{box[3]})" if box else ""
        q = f"[out:json][timeout:85];area({TX_AREA})->.tx;{selector}{bbox}(area.tx);out {out};"
        for attempt in range(3):
            try:
                body = get(OVERPASS, urllib.parse.urlencode({"data": q}).encode(), timeout=90)
                json.loads(body)
                break
            except Exception as e:      # busy server: wait and retry
                print("  overpass retry:", str(e)[:80])
                time.sleep(8)
        else:
            return False
        dest.write_bytes(body)
        print(f"{dest.name}: {len(body) / 1e6:.1f} MB")
        time.sleep(2)
    return True


def osm_subs() -> bool:
    return overpass("osm_subs", 'nwr["power"="substation"]', "center tags", False)


def osm_lines() -> bool:
    return overpass("osm_lines", 'way["power"="line"]', "geom tags", True)


def osm_roads() -> bool:
    return overpass("osm_roads", 'way["highway"~"^(motorway|trunk|primary)$"]', "skel geom", True)


def osm_lng() -> bool:
    return overpass("osm_lng", 'nwr["name"~"LNG"]', "center tags", False)


def rrc(name: str, where: str) -> bool:
    """Page through the RRC pipeline layer by OBJECTID, 1,000 lines at a time.
    Shapes come back in longitude/latitude, lightly simplified (about 5 m)."""
    d = RAW / name
    d.mkdir(exist_ok=True)
    state = d / "_state.json"
    st = json.loads(state.read_text()) if state.exists() else {"last": 0, "page": 0, "done": False}
    fields = "OBJECTID,COUNTY,P5_NUM,OPER_NM,SYS_NM,DIAMETER,COMMODITY1,INTERSTATE,ALBERS_MILES"
    while not st["done"]:
        if out_of_time():
            return False
        params = {"where": f"({where}) AND OBJECTID > {st['last']}", "outFields": fields, "orderByFields": "OBJECTID",
                  "resultRecordCount": 1000, "outSR": 4326, "geometryPrecision": 5, "maxAllowableOffset": 0.00005,
                  "f": "geojson"}
        body = get(RRC + "?" + urllib.parse.urlencode(params), timeout=90)
        feats = json.loads(body).get("features", [])
        if not feats:
            st["done"] = True
        else:
            (d / f"page_{st['page']:04d}.geojson").write_bytes(body)
            st["last"] = max(f["properties"]["OBJECTID"] for f in feats)
            st["page"] += 1
        state.write_text(json.dumps(st))
    print(f"{name}: {st['page']} pages")
    return True


def rrc_ngt() -> bool:
    return rrc("rrc_ngt", "COMMODITY1='NGT' AND STATUS_CD='I'")


def rrc_gath() -> bool:
    return rrc("rrc_gath", "COMMODITY1 IN ('NGG','NFG') AND STATUS_CD='I'")


FEMA = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"


def fema() -> bool:
    """Flood zones where SFHA_TF = 'T' (the regulatory 100-year floodplain).
    Also saves the list of DFIRM study IDs, which shows which counties FEMA
    has mapped digitally at all (an unmapped county is not a dry county)."""
    d = RAW / "fema_sfha"
    d.mkdir(exist_ok=True)
    ids = d / "_dfirm_ids.json"
    if not ids.exists():
        q = {"where": "DFIRM_ID LIKE '48%'", "returnDistinctValues": "true", "outFields": "DFIRM_ID",
             "returnGeometry": "false", "f": "json"}
        got = json.loads(get(FEMA + "?" + urllib.parse.urlencode(q)))
        ids.write_text(json.dumps(sorted(f["attributes"]["DFIRM_ID"] for f in got["features"])))
    state = d / "_state.json"
    st = json.loads(state.read_text()) if state.exists() else {"last": 0, "page": 0, "done": False}
    while not st["done"]:
        if out_of_time():
            return False
        q = {"where": f"DFIRM_ID LIKE '48%' AND SFHA_TF='T' AND OBJECTID > {st['last']}",
             "outFields": "OBJECTID,DFIRM_ID,FLD_ZONE,ZONE_SUBTY", "orderByFields": "OBJECTID",
             "resultRecordCount": 250, "outSR": 4326, "geometryPrecision": 5, "maxAllowableOffset": 0.0002,
             "f": "geojson"}
        body = get(FEMA + "?" + urllib.parse.urlencode(q))
        feats = json.loads(body).get("features", [])
        if not feats:
            st["done"] = True
        else:
            (d / f"page_{st['page']:04d}.geojson").write_bytes(body)
            st["last"] = max(f["properties"]["OBJECTID"] for f in feats)
            st["page"] += 1
        state.write_text(json.dumps(st))
    print(f"fema: {st['page']} pages")
    return True


def airports() -> bool:
    dest = RAW / "airports_tx.geojson"
    if dest.exists():
        return True
    base = "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_Aviation_Facilities/FeatureServer/0/query"
    feats, offset = [], 0
    while True:
        params = {"where": "STATE_CODE='TX'", "outFields": "*", "outSR": 4326, "f": "geojson",
                  "resultOffset": offset, "resultRecordCount": 1000, "orderByFields": "OBJECTID"}
        page = json.loads(get(base + "?" + urllib.parse.urlencode(params)))
        got = page.get("features", [])
        feats += got
        if len(got) < 1000:
            break
        offset += 1000
    dest.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print("airports:", len(feats))
    return True


STEPS = {"counties": counties, "places": places, "osm_subs": osm_subs, "osm_lng": osm_lng, "airports": airports,
         "osm_lines": osm_lines, "osm_roads": osm_roads, "rrc_ngt": rrc_ngt, "rrc_gath": rrc_gath, "fema": fema}

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    todo = args or list(STEPS)
    all_done = True
    for step in todo:
        try:
            ok = STEPS[step]()
        except Exception as e:
            ok = False
            print(f"{step}: failed ({e})")
        print(f"{step}: {'done' if ok else 'not finished, run again'}")
        all_done &= ok
        if out_of_time():
            all_done = all_done and step == todo[-1]
            break
    print("all steps done" if all_done else "run again to continue")
