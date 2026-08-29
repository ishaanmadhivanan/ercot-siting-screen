"""
load_census.py  --  Stage 1b extract.

Combines two Census sources into one county-level file:
  1. Gazetteer counties file  -> land area in square miles
  2. Population Estimates     -> resident population

Both are keyed on the same 5-digit FIPS code that dim.county already uses, so
no name matching is needed here. That is the payoff of having built the FIPS
spine in Stage 1 - the second source joins on a code, not a spelling.

Usage:
    python scripts/load_census.py

Reads whatever it finds in data/raw/, writes data/processed/dim_county_demog.csv
"""

from __future__ import annotations

import re
import sys
import zipfile
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw"
OUT_PATH = REPO / "data" / "processed" / "dim_county_demog.csv"

TX_STATE_FIPS = "48"
COUNTY_SUMMARY_LEVEL = "050"   # 050 = county rows; 040 = state totals, which we drop


def find_one(pattern: str, suffixes: tuple[str, ...]) -> Path:
    """Locate a file in data/raw by pattern so exact filenames can drift."""
    hits = [p for p in RAW.iterdir()
            if p.suffix.lower() in suffixes and re.search(pattern, p.name, re.I)]
    if not hits:
        listing = "\n  ".join(sorted(p.name for p in RAW.iterdir()))
        raise SystemExit(f"No file in data/raw matching /{pattern}/.\nFound:\n  {listing}")
    return sorted(hits, key=lambda p: len(p.name))[0]


def load_land_area() -> pd.DataFrame:
    """Gazetteer file: tab-delimited, one row per US county."""
    zp = find_one(r"gaz.*count", (".zip",))
    with zipfile.ZipFile(zp) as zf:
        member = next(n for n in zf.namelist() if n.lower().endswith(".txt"))
        with zf.open(member) as fh:
            df = pd.read_csv(fh, sep="\t", dtype=str, encoding="latin-1")

    # Census pads these headers with trailing spaces often enough to matter.
    df.columns = [c.strip().upper() for c in df.columns]

    if "GEOID" not in df.columns or "ALAND_SQMI" not in df.columns:
        raise SystemExit(f"Unexpected gazetteer columns:\n  " + "\n  ".join(df.columns))

    df = df[["GEOID", "ALAND_SQMI"]].rename(columns={
        "GEOID": "county_fips", "ALAND_SQMI": "land_area_sqmi"})
    df["county_fips"] = df["county_fips"].str.strip().str.zfill(5)
    df["land_area_sqmi"] = pd.to_numeric(df["land_area_sqmi"], errors="coerce")
    return df


def load_population() -> pd.DataFrame:
    """Population Estimates: national CSV, includes state rows we must drop."""
    fp = find_one(r"co-est.*alldata", (".csv",))
    # latin-1 because some county names carry accents (Dona Ana, NM).
    df = pd.read_csv(fp, dtype=str, encoding="latin-1")
    df.columns = [c.strip().upper() for c in df.columns]

    # Take the newest POPESTIMATE column present, whatever vintage this is.
    pop_cols = sorted(c for c in df.columns if re.fullmatch(r"POPESTIMATE\d{4}", c))
    if not pop_cols:
        raise SystemExit("No POPESTIMATE column found in the population file.")
    newest = pop_cols[-1]
    print(f"  using {newest} for population")

    df = df[df["SUMLEV"].str.strip() == COUNTY_SUMMARY_LEVEL]
    df["county_fips"] = (df["STATE"].str.strip().str.zfill(2)
                         + df["COUNTY"].str.strip().str.zfill(3))
    df["population"] = pd.to_numeric(df[newest], errors="coerce")
    return df[["county_fips", "population"]]


def main() -> None:
    land = load_land_area()
    pop = load_population()

    df = land.merge(pop, on="county_fips", how="inner")
    df = df[df["county_fips"].str.startswith(TX_STATE_FIPS)]

    # Same principle as the EIA loader: fail loudly rather than load a partial set.
    if len(df) != 254:
        raise SystemExit(
            f"Expected 254 Texas counties, got {len(df)}. "
            "Check that both source files cover the same vintage before continuing."
        )
    missing = df[df["land_area_sqmi"].isna() | df["population"].isna()]
    if not missing.empty:
        print(missing.to_string(index=False))
        raise SystemExit("Counties above are missing land area or population. Nothing written.")

    df = df.sort_values("county_fips")[["county_fips", "land_area_sqmi", "population"]]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False, lineterminator="\n")

    density = df["population"] / df["land_area_sqmi"]
    print(f"\nWrote {len(df)} counties to {OUT_PATH.relative_to(REPO)}")
    print(f"  population range : {df['population'].min():,.0f} to {df['population'].max():,.0f}")
    print(f"  density range    : {density.min():.2f} to {density.max():,.0f} people/sq mi")


if __name__ == "__main__":
    main()
