"""
load_pipelines.py  --  Phase 3 (gas access) extract.

Source: Railroad Commission of Texas, Texas Pipeline Mapping System (TPMS),
public map service
    https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0
This is the same data as the RRC "Pipeline Layers by County" download
(fields OPER_NM, P5_NUM, SYS_NM, DIAMETER, COMMODITY1, INTERSTATE,
STATUS_CD, QUALITY_CD ...), served as a queryable table. RRC already
splits every line at county boundaries and stores each piece's length
(ALBERS_MILES, measured in an equal-area projection), so no map
processing is needed: we pull the attribute table and add up miles.

Code meanings (RRC "TPMS Attribute Definitions and Valid Codes"):
    COMMODITY1  NGT = natural gas, transmission   <- kept
                NGG / NFG = gas gathering (raw gas from wells, not
                pipeline quality) - kept separately as context only
    STATUS_CD   I = in service (includes maintained idle lines) <- kept
                B = abandoned
    INTERSTATE  Y = interstate (federally regulated, FERC)
                N = intrastate (Texas regulated)
    DIAMETER    outside diameter, inches

OUTPUTS
    data/raw/rrc_tpms_ngt.csv                 every in-service transmission segment (raw pull)
    data/processed/fact_pipeline_segment.csv  transmission miles summed by
        county, operator, system, diameter, interstate - loaded by
        sql/02_load/17_load_pipelines.sql
    data/processed/county_gas_attribute.csv   tall county attributes, loaded into
        fact.county_attribute:
          gas_gathering_miles - gathering pipe miles (summed on the RRC server,
                                since there are ~330,000 gathering segments)
          lng_terminal_count / lng_terminals - from data/seed/lng_terminals.csv

LIMITS (recorded in dim.metric)
    Miles of existing pipe, not spare capacity. Capacity, pressure and flow
    are not public for intrastate lines. A big line nearby says a plant CAN
    be connected; it does not say gas is available on it.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw" / "rrc_tpms_ngt.csv"
OUT_SEG = REPO / "data" / "processed" / "fact_pipeline_segment.csv"
OUT_ATTR = REPO / "data" / "processed" / "county_gas_attribute.csv"
LNG = REPO / "data" / "seed" / "lng_terminals.csv"

URL = "https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0/query"
FIELDS = ["OBJECTID", "COUNTY", "P5_NUM", "OPER_NM", "SYS_NM", "DIAMETER",
          "COMMODITY1", "INTERSTATE", "STATUS_CD", "QUALITY_CD", "ALBERS_MILES", "MODDATE"]
WHERE = "STATUS_CD = 'I' AND COMMODITY1 = 'NGT'"
WHERE_GATHERING = "STATUS_CD = 'I' AND COMMODITY1 IN ('NGG', 'NFG')"
PAGE = 1000   # the service's maxRecordCount


def fetch(params: dict) -> dict:
    q = urllib.parse.urlencode(params)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(f"{URL}?{q}", timeout=120) as r:
                d = json.load(r)
            if "error" in d:
                raise RuntimeError(d["error"])
            return d
        except Exception as e:  # network hiccup: wait and retry
            if attempt == 3:
                raise
            print(f"  retry after error: {e}")
            time.sleep(5 * (attempt + 1))
    raise AssertionError


def download() -> pd.DataFrame:
    total = fetch({"where": WHERE, "returnCountOnly": "true", "f": "json"})["count"]
    print(f"In-service transmission segments to download: {total:,}")
    rows, offset = [], 0
    while offset < total:
        d = fetch({"where": WHERE, "outFields": ",".join(FIELDS), "returnGeometry": "false",
                   "orderByFields": "OBJECTID", "resultOffset": offset,
                   "resultRecordCount": PAGE, "f": "json"})
        feats = [f["attributes"] for f in d["features"]]
        if not feats:
            break
        rows.extend(feats)
        offset += len(feats)
        if offset % 20000 < PAGE:
            print(f"  {offset:,} / {total:,}")
    df = pd.DataFrame(rows)
    if len(df) != total:
        raise SystemExit(f"Expected {total:,} rows, got {len(df):,}")
    df["download_date"] = date.today().isoformat()
    RAW.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(RAW, index=False, lineterminator="\n")
    return df


def main() -> None:
    if RAW.exists():
        print(f"Using saved pull {RAW.relative_to(REPO)} (delete it to re-download)")
        df = pd.read_csv(RAW, dtype={"COUNTY": str, "P5_NUM": str})
    else:
        df = download()

    df["county_fips"] = "48" + df["COUNTY"].astype(str).str.strip().str.zfill(3)
    df["miles"] = pd.to_numeric(df["ALBERS_MILES"], errors="coerce").fillna(0)
    df["diameter_in"] = pd.to_numeric(df["DIAMETER"], errors="coerce")
    for c in ["OPER_NM", "SYS_NM", "INTERSTATE", "P5_NUM"]:
        df[c] = df[c].fillna("").astype(str).str.strip()
    df["P5_NUM"] = df["P5_NUM"].str.lstrip("0")

    trans = df[df["COMMODITY1"] == "NGT"]
    seg = (trans.groupby(["county_fips", "P5_NUM", "OPER_NM", "SYS_NM", "diameter_in", "INTERSTATE"],
                         dropna=False, as_index=False)
                .agg(miles=("miles", "sum"), segments=("miles", "size")))
    seg = seg.rename(columns={"P5_NUM": "operator_p5", "OPER_NM": "operator_name",
                              "SYS_NM": "system_name", "INTERSTATE": "interstate"})
    seg["miles"] = seg["miles"].round(4)
    seg["download_date"] = df["download_date"].iloc[0]
    OUT_SEG.parent.mkdir(parents=True, exist_ok=True)
    seg.to_csv(OUT_SEG, index=False, lineterminator="\n")

    stats = json.dumps([{"statisticType": "sum", "onStatisticField": "ALBERS_MILES",
                         "outStatisticFieldName": "gathering_miles"}])
    g = fetch({"where": WHERE_GATHERING, "groupByFieldsForStatistics": "COUNTY",
               "outStatistics": stats, "f": "json"})
    gath = pd.DataFrame([f["attributes"] for f in g["features"]])
    gath.columns = [c.lower() for c in gath.columns]
    gath["county_fips"] = "48" + gath["county"].astype(str).str.strip().str.zfill(3)
    # 'FED' = federal offshore waters, not a county.
    gath = gath[gath["county_fips"].str.fullmatch(r"48\d{3}")]
    gath = (gath.groupby("county_fips", as_index=False)["gathering_miles"].sum().round(2))
    lng = pd.read_csv(LNG, dtype={"county_fips": str})
    lng_c = (lng.groupby("county_fips")
                .agg(n=("terminal", "size"),
                     names=("terminal", lambda t: "; ".join(
                         f"{x} ({s})" for x, s in zip(t, lng.loc[t.index, "status"]))))
                .reset_index())
    attr = pd.concat([
        pd.DataFrame({"county_fips": gath["county_fips"], "attribute_key": "gas_gathering_miles",
                      "value_num": gath["gathering_miles"], "value_text": ""}),
        pd.DataFrame({"county_fips": lng_c["county_fips"], "attribute_key": "lng_terminal_count",
                      "value_num": lng_c["n"], "value_text": ""}),
        pd.DataFrame({"county_fips": lng_c["county_fips"], "attribute_key": "lng_terminals",
                      "value_num": float("nan"), "value_text": lng_c["names"]}),
    ], ignore_index=True)
    attr.to_csv(OUT_ATTR, index=False, lineterminator="\n")

    # ---- summary ----
    print(f"\nDownload date: {seg['download_date'].iloc[0]}")
    print(f"Transmission: {trans['miles'].sum():,.0f} miles in {trans['county_fips'].nunique()} counties, "
          f"{trans['OPER_NM'].nunique()} operators; interstate "
          f"{trans.loc[trans['INTERSTATE'] == 'Y', 'miles'].sum():,.0f} miles")
    print(f"Gathering   : {gath['gathering_miles'].sum():,.0f} miles")
    print(f"Missing diameter: {trans['diameter_in'].isna().sum()} segments")
    print(f"Wrote {len(seg):,} rows to {OUT_SEG.relative_to(REPO)}")
    print(f"Wrote {len(attr):,} rows to {OUT_ATTR.relative_to(REPO)}")

    big = trans[trans["diameter_in"] >= 20]
    top = (trans.groupby("county_fips")
                .agg(miles=("miles", "sum"), operators=("OPER_NM", "nunique"))
                .join(big.groupby("county_fips")["miles"].sum().rename("miles_20in_plus"))
                .fillna(0).sort_values("miles_20in_plus", ascending=False).head(12))
    print("\nTop counties by 20-inch-plus transmission miles:")
    print(top.round(0).to_string())


if __name__ == "__main__":
    main()
