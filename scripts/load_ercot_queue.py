"""
load_ercot_queue.py  --  Stage 3 extract.

Reads the ERCOT monthly GIS Report and produces one row per interconnection
request, active or inactive, mapped to a county FIPS code.

FOUR SHEETS, TWO PURPOSES
  Project Details - Large Gen : active large projects (header row 30)
  Project Details - Small Gen : active small projects (header row 14)
  Inactive Projects           : cumulative withdrawals (header row 7)
  Cancellation Update         : ONE MONTH of cancellations - deliberately unused.
                                Using a single month as an attrition measure
                                would be noise, not signal. Inactive Projects
                                is the cumulative list and is what we want.

THINGS THE FILE WILL DO TO YOU IF YOU LET IT
  - Repowering projects report capacity as a NET CHANGE, so MW can be zero or
    negative. Left alone, a negative would reduce a county's congestion total.
    Floored at zero here.
  - Large Gen excludes projects that have not requested a Full Interconnection
    Study, per ERCOT confidentiality rules. The active queue is therefore a
    lower bound, not a census. Documented, not silently ignored.
  - POI Location is multi-line free text (substation names, bus numbers,
    occasionally raw coordinates). Unusable at county grain; not read.

Usage:
    python scripts/load_ercot_queue.py
"""

from __future__ import annotations

import glob
import re
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SEED_COUNTY = REPO / "data" / "seed" / "dim_county_tx.csv"
OUT_PATH = REPO / "data" / "processed" / "fact_queue_project.csv"

# sheet -> (header row index, column-3 name which differs between the two)
ACTIVE_SHEETS = {
    "Project Details - Large Gen": 30,
    "Project Details - Small Gen": 14,
}
INACTIVE_SHEET = "Inactive Projects"
INACTIVE_HEADER = 7


def normalise(name: str) -> str:
    """Must match the match_key logic in dim_county_tx.csv exactly."""
    n = str(name).lower().strip()
    n = re.sub(r"\s+county$", "", n)
    n = re.sub(r"[^a-z0-9]", "", n)
    return n


def first_county(raw: str) -> str:
    """Some projects straddle a county line and list several. Take the first."""
    return str(raw).split(",")[0].split("/")[0].strip()


def load_fips() -> dict[str, str]:
    df = pd.read_csv(SEED_COUNTY, dtype=str)
    return dict(zip(df["match_key"], df["county_fips"]))


def read_active(path: str) -> pd.DataFrame:
    frames = []
    for sheet, hdr in ACTIVE_SHEETS.items():
        df = pd.read_excel(path, sheet_name=sheet, header=hdr, usecols="A:K")
        df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
        # Column 3 is 'GIM Study Phase' (Large) or 'Model Ready Date' (Small).
        df = df.rename(columns={df.columns[2]: "phase_or_ready"})
        df = df[["INR", "Project Name", "phase_or_ready", "County",
                 "CDR Reporting Zone", "Projected COD", "Fuel",
                 "Technology", "Capacity (MW)"]]
        df["size_category"] = "Large" if "Large" in sheet else "Small"
        df["status"] = "Active"
        frames.append(df)
        print(f"  {sheet}: {len(df):,} rows")
    return pd.concat(frames, ignore_index=True)


def read_inactive(path: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=INACTIVE_SHEET, header=INACTIVE_HEADER,
                       usecols="A:G")
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    mw_col = next(c for c in df.columns if c.startswith("MW"))
    df = df.rename(columns={mw_col: "Capacity (MW)",
                            "Size Category": "size_category"})
    df["CDR Reporting Zone"] = None
    df["Projected COD"] = None
    df["Technology"] = None
    df["phase_or_ready"] = None
    df["status"] = "Inactive"
    df = df[["INR", "Project Name", "phase_or_ready", "County",
             "CDR Reporting Zone", "Projected COD", "Fuel",
             "Technology", "Capacity (MW)", "size_category", "status"]]
    print(f"  {INACTIVE_SHEET}: {len(df):,} rows")
    return df


def main() -> None:
    matches = glob.glob(str(REPO / "data" / "raw" / "*GIS_Report*"))
    if not matches:
        raise SystemExit("No GIS Report found in data/raw")
    path = matches[0]
    print(f"reading {Path(path).name}\n")

    df = pd.concat([read_active(path), read_inactive(path)], ignore_index=True)

    df = df[df["INR"].notna()]
    df = df[df["INR"].astype(str).str.match(r"^\d+INR", na=False)]

    df["capacity_mw"] = pd.to_numeric(df["Capacity (MW)"], errors="coerce")
    df["capacity_mw"] = df["capacity_mw"].fillna(0).clip(lower=0)

    df["match_key"] = df["County"].map(first_county).map(normalise)
    df["county_fips"] = df["match_key"].map(load_fips())

    unmatched = df[df["county_fips"].isna()]
    if not unmatched.empty:
        print("\nCOUNTY NAMES THAT DID NOT RESOLVE:")
        for raw, n in unmatched["County"].value_counts().items():
            print(f"  {raw!r:30} {n} projects  (normalised: {normalise(first_county(raw))!r})")
        print("\nNothing written. Add aliases to data/seed/dim_county_tx.csv or "
              "adjust normalise(), then rerun.")
        raise SystemExit(1)

    out = pd.DataFrame({
        "inr": df["INR"].astype(str).str.strip(),
        "county_fips": df["county_fips"],
        "status": df["status"],
        "size_category": df["size_category"],
        "fuel": df["Fuel"],
        "technology": df["Technology"],
        "cdr_zone": df["CDR Reporting Zone"],
        "capacity_mw": df["capacity_mw"].round(3),
    })
    out = out.drop_duplicates(subset=["inr", "status"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT_PATH, index=False, lineterminator="\n")

    active = out[out["status"] == "Active"]
    inactive = out[out["status"] == "Inactive"]
    print(f"\nWrote {len(out):,} rows to {OUT_PATH.relative_to(REPO)}")
    print(f"  active   : {len(active):,} projects, {active['capacity_mw'].sum():,.0f} MW")
    print(f"  inactive : {len(inactive):,} projects, {inactive['capacity_mw'].sum():,.0f} MW")
    print(f"  counties : {out['county_fips'].nunique()} of 254")


if __name__ == "__main__":
    main()