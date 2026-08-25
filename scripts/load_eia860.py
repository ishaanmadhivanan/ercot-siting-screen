"""
load_eia860.py  --  Stage 1 extract.

Reads a raw EIA-860 annual zip, pulls Schedule 2 (plants) and Schedule 3_1
(generators), filters to Texas, resolves every county name to a 5-digit FIPS
code, and writes a clean CSV for SQL Server to BULK INSERT.

The important part is resolve_fips(). It refuses to write output if any county
fails to match. That is deliberate: a silent 3% row loss is the single most
common way a project like this ends up quietly wrong.

Usage:
    python scripts/load_eia860.py data/raw/eia8602024.zip

Requires: pandas, openpyxl
"""

from __future__ import annotations

import csv
import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SEED_COUNTY = REPO / "data" / "seed" / "dim_county_tx.csv"
OUT_PATH = REPO / "data" / "processed" / "fact_generator_capacity.csv"

STATE = "TX"

# EIA-860 splits generators across sheets rather than flagging status in a column.
SHEET_STATUS_GROUP = {
    "Operable": "Operating",
    "Proposed": "Proposed",
    "Retired and Canceled": "Retired",
}

OUT_COLUMNS = [
    "data_vintage_year", "plant_code", "generator_id", "plant_name", "county_fips",
    "technology", "status_code", "status_group", "nameplate_mw",
    "operating_year", "planned_retire_year", "latitude", "longitude",
]


def normalise(name: str) -> str:
    """Must match the match_key logic used to build dim_county_tx.csv exactly."""
    n = str(name).lower().strip()
    n = re.sub(r"\s+county$", "", n)
    n = re.sub(r"[^a-z0-9]", "", n)
    return n


def load_fips_lookup() -> dict[str, str]:
    with open(SEED_COUNTY, newline="") as f:
        return {row["match_key"]: row["county_fips"] for row in csv.DictReader(f)}


def find_member(zf: zipfile.ZipFile, pattern: str) -> str:
    """EIA renames files slightly between vintages, so match on a pattern."""
    hits = [n for n in zf.namelist() if re.search(pattern, n, re.I) and n.endswith((".xlsx", ".xls"))]
    if not hits:
        raise SystemExit(f"No file in the zip matching /{pattern}/. Contents:\n  " + "\n  ".join(zf.namelist()))
    return sorted(hits, key=len)[0]


def read_sheet(zf: zipfile.ZipFile, member: str, sheet, probe: str) -> pd.DataFrame:
    """EIA prefixes each sheet with a title row or two, and the count varies.
    Find the real header by looking for the row containing `probe`."""
    with zf.open(member) as fh:
        preview = pd.read_excel(fh, sheet_name=sheet, header=None, nrows=8)
    header_row = None
    for i in range(len(preview)):
        if preview.iloc[i].astype(str).str.contains(probe, case=False, na=False).any():
            header_row = i
            break
    if header_row is None:
        raise SystemExit(f"Could not locate a header row containing '{probe}' in {member} / {sheet}")
    with zf.open(member) as fh:
        df = pd.read_excel(fh, sheet_name=sheet, header=header_row)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def pick(df: pd.DataFrame, *candidates: str) -> str:
    """Column names drift between vintages ('Plant Code' vs 'Plant ID')."""
    lowered = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lowered:
            return lowered[cand.lower()]
    raise SystemExit(f"None of {candidates} found. Available columns:\n  " + "\n  ".join(df.columns))


def main(zip_path: str) -> None:
    zp = Path(zip_path)
    if not zp.exists():
        raise SystemExit(f"Not found: {zp}")

    vintage = re.search(r"(20\d{2})", zp.name)
    vintage_year = int(vintage.group(1)) if vintage else 0
    if not vintage_year:
        raise SystemExit("Could not read a year out of the filename, e.g. eia8602024.zip")

    fips_lookup = load_fips_lookup()

    with zipfile.ZipFile(zp) as zf:
        plant_member = find_member(zf, r"^2_+.*plant")
        gen_member = find_member(zf, r"^3_1.*generator")

        plants = read_sheet(zf, plant_member, 0, "Plant Code")
        p_code = pick(plants, "Plant Code", "Plant Id", "Plant ID")
        p_name = pick(plants, "Plant Name")
        p_state = pick(plants, "State")
        p_county = pick(plants, "County")
        p_lat = pick(plants, "Latitude")
        p_lon = pick(plants, "Longitude")

        plants = plants[plants[p_state].astype(str).str.strip().str.upper() == STATE]
        plants = plants[[p_code, p_name, p_county, p_lat, p_lon]].rename(columns={
            p_code: "plant_code", p_name: "plant_name", p_county: "county_raw",
            p_lat: "latitude", p_lon: "longitude",
        })

        frames = []
        for sheet, status_group in SHEET_STATUS_GROUP.items():
            try:
                g = read_sheet(zf, gen_member, sheet, "Plant Code")
            except ValueError:
                print(f"  ! sheet '{sheet}' not present in this vintage, skipping")
                continue

            g_code = pick(g, "Plant Code", "Plant Id", "Plant ID")
            g_id = pick(g, "Generator ID", "Generator Id")
            g_mw = pick(g, "Nameplate Capacity (MW)", "Nameplate Capacity(MW)")

            out = pd.DataFrame({
                "plant_code": g[g_code],
                "generator_id": g[g_id],
                "nameplate_mw": g[g_mw],
                "status_group": status_group,
            })
            for target, cands in {
                "technology": ("Technology",),
                "status_code": ("Status",),
                "operating_year": ("Operating Year",),
                "planned_retire_year": ("Planned Retirement Year",),
            }.items():
                try:
                    out[target] = g[pick(g, *cands)]
                except SystemExit:
                    out[target] = None
            frames.append(out)

    gens = pd.concat(frames, ignore_index=True)
    gens = gens[pd.to_numeric(gens["plant_code"], errors="coerce").notna()]

    df = gens.merge(plants, on="plant_code", how="inner")

    # --- the check that matters ---------------------------------------------
    df["match_key"] = df["county_raw"].map(normalise)
    df["county_fips"] = df["match_key"].map(fips_lookup)

    unmatched = df[df["county_fips"].isna()]
    if not unmatched.empty:
        print("\nCOUNTY NAMES THAT DID NOT RESOLVE TO A FIPS CODE:\n")
        for raw, n in unmatched["county_raw"].value_counts().items():
            print(f"  {raw!r:30} {n} generators   (normalised: {normalise(raw)!r})")
        print(
            "\nNothing was written. Fix these before continuing - add the spelling "
            "to data/seed/dim_county_tx.csv as an alias row, or correct normalise().\n"
            "Do not 'just drop them'. That is how a screen ends up silently missing counties."
        )
        sys.exit(1)

    df["data_vintage_year"] = vintage_year
    df = df[OUT_COLUMNS]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False, lineterminator="\n")

    operating = df[df["status_group"] == "Operating"]["nameplate_mw"].sum()
    print(f"\nWrote {len(df):,} generator rows to {OUT_PATH.relative_to(REPO)}")
    print(f"  counties represented : {df['county_fips'].nunique()} of 254")
    print(f"  operating capacity   : {operating:,.0f} MW")
    print(f"  by status            : {df['status_group'].value_counts().to_dict()}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
