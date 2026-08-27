# ERCOT Siting Screen

A county-level screening model for siting large electrical loads and new generation in Texas, built entirely from public data. SQL Server for the modelling, Power BI for the interface.

The question it answers: **if you had to connect several hundred megawatts of new load or generation somewhere in ERCOT, which of Texas's 254 counties should be on the shortlist — and how much does that shortlist depend on what you decide to care about?**

The second half of that question is the interesting one. Screening models tend to present a single ranking as though the weighting behind it were settled. This one exposes the weights and lets you move them.

---

## What this is not

The factors here are public-data proxies. They stand in for things a real siting screen would measure directly, and the substitutions are not free:

| What matters | What this uses | Where the proxy is weak |
|---|---|---|
| Transmission headroom at a specific point of interconnection | Existing installed capacity in the county | Says nothing about whether the nearby line is already congested |
| Deliverability | Retiring capacity through 2030 | Retirement announcements slip, and rights are not automatically transferable |
| Land cost and assembly risk | Population density (Stage 1b) | Ignores parcel fragmentation, which is often the binding constraint |
| Soil, floodplain, land ownership | *Not modelled* | No usable public source at county grain |

County grain is itself a compromise. Real siting happens at parcel grain. A county-level screen narrows a search from 254 candidates to a dozen; it does not choose a site.

Stated plainly because a screening model whose limits are undocumented is worse than no model.

---

## Data sources

- **EIA Form 860** — generator-level inventory: plant, county, coordinates, nameplate capacity, technology, status, planned retirement year. The backbone.
- **EIA Form 923** *(Stage 2)* — monthly generation and fuel consumption. The volume that makes this a database rather than a spreadsheet.
- **ERCOT GIS Report** *(Stage 3)* — the monthly generator interconnection queue: proposed projects by county, capacity, fuel, and study status. Requires free registration on the ERCOT Public Portal.
- **US Census** *(Stage 1b)* — county population, land area, and TIGER boundaries.

---

## Build stages

The commit history follows these. Each stage is independently complete.

- **Stage 1 — foundation.** EIA-860 loaded, star schema, two factors, static weights, ranked county map.
- **Stage 1b — land friction.** Census population and land area; density added as a third, inverted factor.
- **Stage 2 — volume.** EIA-923 monthly generation. Adds a date dimension and roughly a million fact rows. New factors: realised capacity factor by county, generation trend.
- **Stage 3 — the interesting layer.** ERCOT interconnection queue. Adds queue congestion (how much proposed capacity is already competing locally) and queue attrition by county.
- **Stage 4 — interface and writeup.** What-if parameters wired to the weights table, per-county drill-through, sensitivity analysis, `docs/methodology.md`.

---

## Running it

```bash
# 1. Environment
pip install -r requirements.txt

# 2. Fetch EIA-860 (annual zip) into data/raw/
#    https://www.eia.gov/electricity/data/eia860/

# 3. Extract, resolve counties to FIPS, write a clean CSV.
#    Refuses to write if any county fails to match.
python scripts/load_eia860.py data/raw/eia8602024.zip
```

Then in SSMS, against a local SQL Server Express instance, in order:

```
sql/01_schema/00_create_database.sql
sql/01_schema/01_dim_county.sql
sql/01_schema/02_dim_fuel.sql
sql/01_schema/03_fact_generator_capacity.sql
sql/01_schema/04_dim_score_weight.sql
sql/02_load/10_load_seeds.sql          <- edit the @repo path first
sql/02_load/11_load_generators.sql     <- edit the @repo path first
sql/03_views/20_vw_county_factor.sql
sql/03_views/21_vw_county_score.sql
sql/04_checks/90_check_fips_coverage.sql
```

Every query in the checks file should return zero rows.

---

## Repository layout

```
data/seed/        reference data, versioned (county FIPS, fuel categories)
data/raw/         source downloads, gitignored
data/processed/   script output, gitignored
sql/01_schema/    DDL
sql/02_load/      staging loads
sql/03_views/     the rpt layer Power BI connects to
sql/04_checks/    data quality assertions - run after every load
scripts/          Python extractors
powerbi/          .pbix and exported screenshots
docs/             methodology writeup
```
