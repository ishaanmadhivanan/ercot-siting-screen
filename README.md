# ERCOT Gas Plant Siting Screen

A county-level screen for siting a new **gas-fired power plant in ERCOT**, built entirely from public data with **SQL Server, Python and Power BI**.

It scores all 195 ERCOT counties on the things a developer actually checks (gas supply, grid connection, site control, air permitting, community) and lets the user decide how much each one matters. There is no single "right" ranking: the weights are the user's, and the report shows exactly what each county's score is made of.

![Score map](docs/score_map.png)

---

## What it does

- **17 factors, each scored 0–100** across ERCOT counties, from 9 public sources.
- **Five pillars** matching a developer's siting checklist. Each pillar has a 0–10 weight slider. Components inside a pillar can be switched on or off.
- **Deal-breaker filters**: ozone attainment status, "must have a 20-inch+ gas pipeline".
- **County drill-through**: every factor's raw value and score, pipelines by operator and diameter, power plants, NOx offset costs, LNG terminals.
- **Catalog page**: every metric with its unit, direction, source, data date and caveat.

| Pillar | Components |
| --- | --- |
| Gas supply | Transmission pipe miles, 20-inch+ pipe miles, interstate pipe miles, number of pipeline operators, gathering pipe miles |
| Grid connection | Existing generation capacity, realised capacity factor, gas fleet capacity factor, generation trend 2020–2024, active gas queue, total interconnection queue |
| Site control | Gas and coal capacity 40+ years old (brownfield), land in 100+ acre tracts, landowners per 1,000 rural acres, parcels of 500+ acres |
| Air permit | Ozone nonattainment severity |
| Community | Population density |

---

## How it is built

```mermaid
flowchart LR
    A[Public sources<br/>EIA, ERCOT, EPA, TCEQ,<br/>RRC, TxGIO, Census] --> B[Python extract scripts<br/>scripts/load_*.py]
    B --> C[SQL Server<br/>star schema: dim / fact]
    C --> D[Tall factor view<br/>rpt.county_factor]
    D --> E[0-100 score per factor<br/>rpt.county_factor_score]
    E --> F[Power BI<br/>pillar weights in DAX]
```

- **Python** pulls and cleans each source (Excel files, HTML tables, ArcGIS map services, 194 county parcel files) into tidy CSVs.
- **SQL Server** holds a star schema. Every factor is one block in a single tall view, so adding a factor never changes the scoring code.
- **`dim.metric`** is the catalog: every factor's unit, direction, transform (linear or log), pillar, source and caveat lives in data, not code.
- **Power BI** reads named SQL views and does only the weighting, so the logic is testable in SQL.

---

## Data sources

| Source | What it gives | As of |
| --- | --- | --- |
| EIA Form 860 | Every generator: county, capacity, fuel, age, status | 2024 |
| EIA Form 923 | Monthly generation by plant and fuel, 2020–2024 | 2024 |
| ERCOT GIS Report | Interconnection queue: every proposed project, MW, fuel, status | Aug 2026 |
| US Census | County population and land area | 2025 |
| EPA Green Book | Ozone nonattainment status by county | Aug 2026 |
| TCEQ Emission Credit Trade Report | NOx credit prices and volumes by area | Sep 2026 |
| Railroad Commission of Texas (TPMS) | Every in-service gas pipeline segment: operator, diameter, miles | Sep 2026 |
| TxGIO StratMap Land Parcels | 11 million parcel records: size and owner, 194 counties | 2025 |
| EIA (LNG) | LNG export terminals | Apr 2026 |

---

## Findings worth knowing

- **Air permits are a supply problem, not just a price problem.** Houston and Dallas–Fort Worth are *Severe* ozone nonattainment, so a new plant must buy 1.3 tons of NOx credits per ton it emits. Houston's entire credit market traded 87 tons/year in two years; a single 100 ton/year plant would need 130.
- **Gas pipe is concentrated.** Of 48,700 miles of in-service gas transmission, the most 20-inch+ pipe sits in Harris, Pecos, Reeves, Brazoria and Wharton counties.
- **Planned retirements are almost invisible in public data.** Through 2030, EIA lists planned ERCOT retirements only in Bexar County, so plant age (40+ years) is used as the brownfield signal instead.

---

## Data quality problems caught

Each of these would have quietly produced wrong rankings:

| Problem | Fix |
| --- | --- |
| El Paso ranked #1, but it is not in ERCOT (one retired plant was coded ERCOT) | County is ERCOT only if most of its *operating* capacity is |
| Averaging many factors squeezed every county's score into a narrow band | Added a scaled score and percentile; then moved to per-factor 0–100 scores |
| 30 counties tied at the top of generation trend (zero-generation counties) | Smoothed log ratio |
| EPA's two-digit years read "99" as the latest year | Use the page's own data date |
| One parcel shape repeated up to 134 times (one record per co-owner) | De-duplicate shapes before summing acres |
| Some counties' parcel acreage computed in Web Mercator (~38% too large) | Recompute every parcel's area in an equal-area projection |
| Land-use codes blank or misapplied in two thirds of counties | Score land on parcel size and ownership only |
| Harris County's parcel file covers only 40% of the county | Land scores left blank where parcel coverage is outside 80–125% |

More in [docs/methodology.md](docs/methodology.md).

---

## Limitations

- **County grain.** This narrows 195 counties to a shortlist; it does not pick a site. Parcel-level screening is the planned next step.
- **Proxies.** Pipe diameter stands in for pipeline capacity (not public for intrastate lines). Installed capacity and the queue stand in for transmission headroom (substation-level data is not public).
- **Not yet covered:** water availability, heavy-haul access (rail, roads, bridge ratings), flood zones and wetlands, power prices, tax incentives.

---

## Rebuilding it

1. `pip install -r requirements.txt`
2. Download the raw sources into `data/raw/` (links in each script's header) and run the extract scripts in `scripts/` (`load_eia860.py`, `load_eia923.py`, `load_census.py`, `load_ercot_queue.py`, `load_air.py`, `load_pipelines.py`, `load_parcels.py`). Parcel files: `scripts/download_parcels.ps1 -ErcotOnly` (the TxGIO server blocks cloud IPs; run it from a home connection).
3. In SSMS against SQL Server Express, run the SQL files in number order: `sql/01_schema` (00–09), `sql/02_load` (10–18, edit the `@repo` path at the top), `sql/03_views` (20–23), then `sql/04_checks`.
4. Open `powerbi/ercot_siting_v2.pbip` in Power BI Desktop, set the `ServerName` / `DatabaseName` parameters if yours differ (default `localhost\SQLEXPRESS` / `ErcotSiting`), and Refresh.

The Power BI project is plain text (PBIP), generated by `scripts/build_powerbi_project.py`.

---

## Repository layout

```
data/seed/        small reference tables, versioned (counties, fuels, ozone rules, LNG terminals)
data/raw/         source downloads (gitignored)
data/processed/   script output (gitignored)
sql/01_schema/    tables
sql/02_load/      loads from data/processed
sql/03_views/     scoring views and the views Power BI reads
sql/04_checks/    data quality checks
scripts/          Python extract scripts and the Power BI project generator
powerbi/          Power BI project (PBIP)
docs/             methodology and screenshots
```

## Next

A web map that starts from this county shortlist and narrows to candidate parcels (100+ acres, near a 20-inch pipeline and a 345 kV substation, outside the floodplain), with presets for gas, wind and data centres.
