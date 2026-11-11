# ERCOT Gas Plant Siting Screen

Ranks all 195 counties on the ERCOT grid for building a new gas-fired power plant. Use the sliders to change how much each category matters and the map and top 10 table update. You can also go into the details for any county.

![Score map](docs/score_map.png)

## Install and open

1. Install [Power BI Desktop](https://www.microsoft.com/en-us/power-platform/products/power-bi/desktop). It's free and runs on Windows 10 or 11 (also in the Microsoft Store).
2. Download `ercot_siting_screen.pbix` from the [latest release](https://github.com/ishaanmadhivanan/ercot-siting-screen/releases/latest), under **Assets**.
3. Double-click the file to open it.
4. If Power BI asks to refresh or connect to a database, click **Cancel**. The data is already saved in the file.

No Windows? See [all four pages as a PDF](docs/ercot_siting_report.pdf) with default weights.

## How to use it

- **Score map:** move the five sliders (0–10) to set the weight for each category; 0 removes it. Untick any sub-component you don't want counted. Click a county on the map or in the table to see its category scores against the ERCOT average.
- **Explore one factor:** pick a single factor to map every county on it alone.
- **County detail:** pick a county in the box at the top left to see every number behind its score, background facts that aren't scored, and its pipelines and power plants.
- **Catalog:** every metric with its source, date and how it's scored.

## How the score works

Each factor is scored 0–100 against the other ERCOT counties (best county = 100). Factors are grouped into five categories: **Gas supply**, **Grid connection**, **Site control**, **Air permit** and **Community**. A category's score is the average of its ticked factors, and the overall score is the categories weighted by the sliders. Where a county has nothing to measure on a factor, it's left blank instead of scored 0. Full details in [docs/methodology.md](docs/methodology.md).

## Data

EIA 860 and 923 (2024), ERCOT GIS Report (Aug 2026), US Census (2025), EPA Green Book (Aug 2026), TCEQ emission credit trades (Sep 2026), Railroad Commission of Texas pipelines (Sep 2026), TxGIO land parcels (2025). All public.
