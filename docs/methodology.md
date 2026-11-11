# Methodology

How the ERCOT gas plant siting screen turns public data into county scores, and where each number is weak. Every caveat here also lives in `dim.metric.caveat`, which feeds the report's Catalog page.

## 1. Scope: which counties

Texas has 254 counties but only some are on the ERCOT grid. A county is **in ERCOT** if more than half of its *operating* generating capacity reports balancing authority ERCO (EIA-860). Counties with no operating plants fall back to the ERCOT interconnection queue: any queued project counts as ERCOT. Result: **195 counties**.

Why majority capacity and not "any ERCOT plant": the first version used presence, and El Paso (WECC) ranked #1 because one retired plant was coded ERCO.

## 2. Factors

Every factor is one block in the tall view `rpt.county_factor` (one row per county per factor). Adding a factor means one SQL block plus one row in `dim.metric`; nothing downstream changes.

| Category | Factor | Unit | Better | Transform | Source |
| --- | --- | --- | --- | --- | --- |
| Gas supply | Gas transmission pipe | miles | higher | log | RRC TPMS, in-service NGT lines |
| Gas supply | Large gas pipe (20 in+) | miles | higher | log | RRC TPMS |
| Gas supply | Interstate gas pipe | miles | higher | log | RRC TPMS |
| Gas supply | Gas pipeline operators | operators with 1+ mile | higher | log | RRC TPMS |
| Gas supply | Gas gathering pipe | miles | higher | log | RRC TPMS (NGG/NFG lines) |
| Grid connection | Existing generation capacity | MW | higher | log | EIA-860 |
| Grid connection | Realized capacity factor | ratio | higher | linear | EIA-923 / EIA-860 |
| Grid connection | Gas fleet capacity factor | ratio | higher | linear | EIA-923 (NG) / EIA-860 |
| Grid connection | Generation trend 2020–2024 | smoothed log ratio | higher | linear | EIA-923 |
| Grid connection | Active gas queue | MW | lower | log | ERCOT GIS Report |
| Grid connection | Active interconnection queue | MW | lower | log | ERCOT GIS Report |
| Site control | Gas and coal 40+ years old | MW | higher | log | EIA-860 |
| Site control | Land in large tracts (100+ ac) | share | higher | linear | TxGIO parcels |
| Site control | Landowners per 1,000 rural acres | owners | lower | log | TxGIO parcels |
| Site control | Parcels of 500+ acres | count | higher | log | TxGIO parcels |
| Air permit | Ozone nonattainment severity | rank 0–5 | lower | linear | EPA Green Book |
| Community | Population density | people / sq mi | lower | log | Census |

Kept in the catalog but **out of the score**: capacity retiring by 2030 (nonzero only in Bexar), queue attrition rate (too noisy).

## 3. Scoring

For each factor, across the 195 ERCOT counties (`rpt.county_factor_score`):

1. **Transform.** Skewed counts and MW use `LOG(1 + x)`, so a few very large counties don't flatten everyone else to near zero. Ratios stay linear.
2. **Min–max to 0–100.** Worst county 0, best 100, on that factor alone.
3. **Direction.** "Lower is better" factors are flipped, so 100 is always favourable.
4. **Missing stays missing.** A county with no data on a factor gets a blank, not a 0 or a 100 (for example, counties with no gas queue are blank rather than "perfect", and counties with no power plants or no gas plants are blank on the two capacity-factor factors rather than scored 0). There is nothing to measure, so the factor is simply skipped and the category averages the rest.

In Power BI:

- **Category score** = average of the county's switched-on components that have a value.
- **Overall score** = category scores weighted by the user's 0–10 category sliders, over the categories the county has data for.
- **Data coverage** = share of the user's weight that had data for that county. Below 100% means a whole category was missing and the score rests on the rest.

Scores are relative to other ERCOT counties, not absolute measures of suitability.

## 4. Source-specific methods

**Air.** EPA Green Book, current 8-hour ozone standards only (2008 and 2015); revoked standards excluded. A county's class is the strictest current one. Houston and Dallas–Fort Worth are Severe under 2008 (Serious under 2015), so permitting follows Severe: 25 tpy major-source threshold, 1.3:1 NOx offsets. Thresholds and ratios are in `data/seed/ozone_classification_rules.csv`. Credit prices: TCEQ trade report, priced NOx trades only, median by nonattainment area; areas with no priced trades are left blank. Offset cost is per ton/year of NOx the plant emits, so no plant size is assumed.

**Gas.** RRC's pipeline map service, in-service (`STATUS_CD = I`) natural gas transmission (`NGT`). RRC already splits lines at county boundaries and stores each piece's length, so miles are summed directly. Gathering lines (`NGG`, `NFG`) are summed on the server and used only as a sign of nearby production.

**Land.** TxGIO StratMap parcels (2025), 194 ERCOT counties (Donley has no file).
- Identical shapes are counted once: undivided-interest owners each get their own record on the same polygon.
- Acres are recomputed in Texas Centric Albers Equal Area (EPSG:3083). The supplied `GIS_AREA` is Web Mercator in some counties and about 38% too large at Texas latitudes.
- State land-use codes are blank or misapplied in about two thirds of counties, so the scores use only parcel size and owner names. Industrial acres are shown as context only where 80%+ of parcels carry a code (62 counties).
- Quality gate: land scores are blank where de-duplicated parcel acres fall outside 80–125% of the county's Census land area (11 counties, including Harris at 40% and Frio at 280%).

**Grid.** Capacity factor = 2024 generation / (operating MW × hours), capped at 1.0. Generation trend = `LOG((MWh 2024 + 10,000) / (MWh 2020 + 10,000))`; the floor stops zero-generation counties tying at the top. Brownfield signal = operating gas and coal units built 1985 or earlier, because announced retirements barely exist in EIA-860.

## 5. What the proxies cannot tell you

| What matters | What this uses | Weakness |
| --- | --- | --- |
| Spare pipeline capacity | Pipe miles and diameter | Capacity, pressure and flow are not public for intrastate lines |
| Transmission headroom at a substation | County generation and queue MW | Says nothing about congestion on a specific line |
| Land cost and assembly | Parcel size, owner count, density | No prices, mineral rights, easements or zoning |
| Air permit timeline | Ozone class and credit market | No modelling of the permit process itself |

Not yet covered: water availability, heavy-haul access (rail, roads, bridge weight ratings), flood zones and wetlands, power prices, tax incentives (JETI). A county screen narrows the search; site selection happens at parcel level.
