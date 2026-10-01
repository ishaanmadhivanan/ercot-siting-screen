"""
ercot_counties.py  --  writes data/seed/ercot_counties.csv

The same rule as sql/02_load/15_classify_ercot.sql, applied to the processed
CSVs so Python steps (and download_parcels.ps1 -ErcotOnly) can use the ERCOT
county list without a database connection:
  1. majority of OPERATING nameplate MW reports balancing authority ERCO, or
  2. no operating generation at all, but at least one ERCOT queue request.
"""
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
g = pd.read_csv(REPO / "data/processed/fact_generator_capacity.csv", dtype={"county_fips": str})
q = pd.read_csv(REPO / "data/processed/fact_queue_project.csv", dtype={"county_fips": str})
c = pd.read_csv(REPO / "data/seed/dim_county_tx.csv", dtype=str)

op = g[g["status_group"] == "Operating"]
mw = op.groupby("county_fips").agg(total=("nameplate_mw", "sum"))
mw["erco"] = op[op["balancing_authority"] == "ERCO"].groupby("county_fips")["nameplate_mw"].sum()
mw = mw.fillna(0)
by_capacity = set(mw.index[(mw["total"] > 0) & (mw["erco"] / mw["total"] > 0.5)])
by_queue = set(q["county_fips"]) - set(op["county_fips"])
ercot = c[c["county_fips"].isin(by_capacity | by_queue)][["county_fips", "county_name"]]
ercot.to_csv(REPO / "data/seed/ercot_counties.csv", index=False, lineterminator="\n")
print(f"{len(ercot)} ERCOT counties written")
