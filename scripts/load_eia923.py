"""
load_eia923.py  --  Stage 2 extract.

Reads every EIA-923 annual zip in data/raw and produces one row per
plant / prime mover / fuel / month.

THE RESHAPE
EIA publishes generation WIDE: twelve columns, "Netgen January" through
"Netgen December", one row per plant-fuel-prime mover combination per year.
That shape is unusable for time series work - you cannot GROUP BY a column
name. This script melts those twelve columns into a month column and a value
column, which multiplies the row count by twelve and turns the month into
data instead of structure.

THE COUNTY JOIN
EIA-923 reports Plant State but not county. County comes from EIA-860, which
Stage 1 already loaded, so this script reads the processed EIA-860 output to
build a plant_code -> county_fips map. That means load_eia860.py must run first.

Some 923 plants will not appear in the 860 vintage on disk - plants retired
before that year, or new plants not yet in the annual inventory. Those are
reported with their generation volume so the coverage loss is visible, and the
script aborts if the unmatched share is large enough to distort county totals.

Usage:
    python scripts/load_eia923.py

Requires: pandas, openpyxl
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw"
EIA860_OUT = REPO / "data" / "processed" / "fact_generator_capacity.csv"
OUT_PATH = REPO / "data" / "processed" / "fact_generation_monthly.csv"

STATE = "TX"

# Abort if more than this share of Texas generation cannot be mapped to a county.
MAX_UNMATCHED_SHARE = 0.02

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
MONTH_NUM = {m: i + 1 for i, m in enumerate(MONTHS)}


def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    """923 headers carry embedded newlines and inconsistent spacing."""
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    return df


def pick(df: pd.DataFrame, *candidates: str) -> str:
    lowered = {c.lower(): c for c in df.columns}
    for cand in candidates:
        if cand.lower() in lowered:
            return lowered[cand.lower()]
    raise SystemExit(f"None of {candidates} found. Columns were:\n  "
                     + "\n  ".join(df.columns))


def read_generation_sheet(zf: zipfile.ZipFile, member: str) -> pd.DataFrame:
    """Page 1 holds generation and fuel. Header row position varies by year."""
    with zf.open(member) as fh:
        xls = pd.ExcelFile(fh)
        sheet = next((s for s in xls.sheet_names if "page 1" in s.lower()), None)
        if sheet is None:
            raise SystemExit(f"No 'Page 1' sheet in {member}. Sheets: {xls.sheet_names}")

    with zf.open(member) as fh:
        preview = pd.read_excel(fh, sheet_name=sheet, header=None, nrows=12)
    header_row = None
    for i in range(len(preview)):
        row = preview.iloc[i].astype(str)
        if row.str.contains("Plant Id", case=False, na=False).any():
            header_row = i
            break
    if header_row is None:
        raise SystemExit(f"Could not find a header row in {member} / {sheet}")

    with zf.open(member) as fh:
        df = pd.read_excel(fh, sheet_name=sheet, header=header_row)
    return clean_columns(df)


def load_one_year(zip_path: Path) -> pd.DataFrame:
    year = int(re.search(r"(20\d{2})", zip_path.name).group(1))
    print(f"  {zip_path.name} ...", end=" ", flush=True)

    with zipfile.ZipFile(zip_path) as zf:
        members = [n for n in zf.namelist()
                   if n.lower().endswith((".xlsx", ".xls"))
                   and re.search(r"schedules?_2", n, re.I)]
        if not members:
            members = [n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls"))]
        if not members:
            raise SystemExit(f"No spreadsheet inside {zip_path.name}")
        df = read_generation_sheet(zf, sorted(members, key=len)[0])

    c_plant = pick(df, "Plant Id", "Plant ID", "Plant Code")
    c_state = pick(df, "Plant State", "State")
    c_mover = pick(df, "Reported Prime Mover", "Prime Mover")
    c_fuel = pick(df, "Reported Fuel Type Code", "Reported Fuel Type")

    df = df[df[c_state].astype(str).str.strip().str.upper() == STATE]

    # Month columns are "Netgen January" etc, but spacing and case drift.
    netgen_cols = {}
    for col in df.columns:
        m = re.match(r"netgen\s*[\._]?\s*(" + "|".join(MONTHS) + r")$", col, re.I)
        if m:
            netgen_cols[col] = m.group(1).capitalize()
    if len(netgen_cols) != 12:
        found = sorted(netgen_cols.values())
        raise SystemExit(f"Expected 12 Netgen month columns in {zip_path.name}, "
                         f"found {len(netgen_cols)}: {found}")

    keep = [c_plant, c_mover, c_fuel] + list(netgen_cols)
    df = df[keep].rename(columns={
        c_plant: "plant_code", c_mover: "prime_mover", c_fuel: "fuel_type"})

    # --- the reshape: 12 columns become 12 rows ---
    long = df.melt(id_vars=["plant_code", "prime_mover", "fuel_type"],
                   value_vars=list(netgen_cols),
                   var_name="month_col", value_name="net_generation_mwh")
    long["month"] = long["month_col"].map(lambda c: MONTH_NUM[netgen_cols[c]])
    long["year"] = year
    long = long.drop(columns=["month_col"])

    # 923 uses "." for withheld or not-applicable values.
    long["net_generation_mwh"] = pd.to_numeric(long["net_generation_mwh"], errors="coerce")
    long = long[long["net_generation_mwh"].notna()]
    long["plant_code"] = pd.to_numeric(long["plant_code"], errors="coerce")
    long = long[long["plant_code"].notna()]
    long["plant_code"] = long["plant_code"].astype(int)

    print(f"{len(long):,} rows")
    return long


def main() -> None:
    if not EIA860_OUT.exists():
        raise SystemExit(f"{EIA860_OUT} not found. Run scripts/load_eia860.py first - "
                         "923 has no county field and needs 860 for the mapping.")

    gen860 = pd.read_csv(EIA860_OUT, dtype={"county_fips": str})
    plant_county = (gen860[["plant_code", "county_fips"]]
                    .drop_duplicates("plant_code")
                    .set_index("plant_code")["county_fips"])
    print(f"plant -> county map: {len(plant_county):,} plants from EIA-860\n")

    zips = sorted(p for p in RAW.iterdir()
                  if p.suffix.lower() == ".zip" and re.search(r"923", p.name))
    if not zips:
        raise SystemExit("No EIA-923 zips found in data/raw (expected names like f923_2024.zip)")

    print("reading:")
    frames = [load_one_year(p) for p in zips]
    df = pd.concat(frames, ignore_index=True)

    df["county_fips"] = df["plant_code"].map(plant_county)

    # --- coverage check ---
    unmatched = df[df["county_fips"].isna()]
    total_mwh = df["net_generation_mwh"].sum()
    lost_mwh = unmatched["net_generation_mwh"].sum()
    share = (lost_mwh / total_mwh) if total_mwh else 0.0

    if not unmatched.empty:
        print(f"\n{unmatched['plant_code'].nunique()} plants in 923 are absent from the "
              f"860 vintage on disk ({lost_mwh:,.0f} MWh, {share:.2%} of total).")
        print("Largest by generation:")
        top = (unmatched.groupby("plant_code")["net_generation_mwh"]
               .sum().sort_values(ascending=False).head(10))
        for pc, mwh in top.items():
            print(f"  plant {pc}: {mwh:,.0f} MWh")

    if share > MAX_UNMATCHED_SHARE:
        raise SystemExit(
            f"\nUnmatched share {share:.2%} exceeds the {MAX_UNMATCHED_SHARE:.0%} limit. "
            "County totals would be materially wrong. Nothing written.\n"
            "Most likely fix: download the EIA-860 vintage that matches your 923 years."
        )

    df = df[df["county_fips"].notna()]
    df = df[["plant_code", "county_fips", "year", "month",
             "prime_mover", "fuel_type", "net_generation_mwh"]]
    df = df.sort_values(["year", "month", "plant_code"])

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_PATH, index=False, lineterminator="\n")

    print(f"\nWrote {len(df):,} rows to {OUT_PATH.relative_to(REPO)}")
    print(f"  years    : {df['year'].min()} to {df['year'].max()}")
    print(f"  counties : {df['county_fips'].nunique()}")
    print(f"  plants   : {df['plant_code'].nunique():,}")
    print(f"  total    : {df['net_generation_mwh'].sum():,.0f} MWh")


if __name__ == "__main__":
    main()