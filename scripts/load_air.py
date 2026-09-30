"""
load_air.py  --  Phase 2 (air permitting) extract.

Builds county-level air permitting attributes from two saved pages:

  data/raw/epa_greenbook_tx.html
      EPA Green Book, "Texas Nonattainment/Maintenance Status for Each County
      by Year for All Criteria Pollutants"
      https://www3.epa.gov/airquality/greenbook/anayo_tx.html

  data/raw/tceq_erc_trade_report.html
      TCEQ Emission Credit (ERC) Trade Report
      https://www.tceq.texas.gov/assets/public/permitting/air/reports/banking/ectradereport.html

and one versioned rules table:

  data/seed/ozone_classification_rules.csv
      Clean Air Act thresholds by ozone classification: the NOx level that
      triggers nonattainment review, and the offset ratio.

OUTPUT: data/processed/county_air_attribute.csv, tall
(county_fips, attribute_key, value_num, value_text), loaded by
sql/02_load/16_load_air.sql into fact.county_attribute.

DECISIONS WORTH KNOWING
- Only ozone matters for a gas plant. Gas combustion emits NOx (which forms
  ozone) but very little SO2, so SO2 nonattainment is ignored here.
- A county can be nonattainment under more than one ozone standard. Houston
  and Dallas-Fort Worth are Serious under the 2015 standard but still Severe
  under the 2008 one. Permitting follows the stricter classification, so the
  effective classification is the most severe current one.
- Revoked standards (1-hour 1979, 8-hour 1997) are excluded.
- Credits are area-specific: a Houston-area plant must buy Houston-area
  credits. Price, trade count and tons traded are computed per area from
  NOx trades with a nonzero price, and assigned to that area's counties.
- No plant emissions figure is assumed. Offset cost is expressed per ton/year
  of NOx the plant would emit (ratio x price), so a user multiplies by their
  own plant's emissions.
"""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
RAW = REPO / "data" / "raw"
GREENBOOK = RAW / "epa_greenbook_tx.html"
TRADES = RAW / "tceq_erc_trade_report.html"
RULES = REPO / "data" / "seed" / "ozone_classification_rules.csv"
COUNTIES = REPO / "data" / "seed" / "dim_county_tx.csv"
OUT = REPO / "data" / "processed" / "county_air_attribute.csv"
OUT_MARKET = REPO / "data" / "processed" / "nox_credit_market_by_area.csv"

CURRENT_OZONE_STANDARDS = {"8-Hour Ozone (2008)", "8-Hour Ozone (2015)"}


def area_key(name: str) -> str:
    """'Houston-Galveston-Brazoria, TX' and 'HOUSTON-GALVESTON-BRAZORIA' -> same key."""
    n = str(name).upper()
    n = re.sub(r",\s*[A-Z]{2}(-[A-Z]{2})?\s*$", "", n)
    return re.sub(r"[^A-Z]", "", n)


def read_greenbook() -> tuple[pd.DataFrame, str]:
    html = GREENBOOK.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"current as of ([A-Za-z]+ \d{1,2}, \d{4})", html)
    data_date = m.group(1) if m else "unknown"

    df = pd.read_html(StringIO(html))[0].iloc[:, :9]
    df.columns = ["county", "naaqs", "area", "years", "redesig",
                  "classification", "whole_part", "pop2010", "fips"]
    df = df[df["county"] != "TEXAS"].copy()

    # A row is current if its list of nonattainment years (two-digit, e.g.
    # "18 19 ... 26") includes the Green Book's own data year, and it has no
    # redesignation date. (Taking the max two-digit year would pick 1999.)
    years = df["years"].astype(str).str.findall(r"\b(\d{2})\b")
    latest = f"{int(data_date[-4:]) % 100:02d}" if data_date != "unknown" else "26"
    df["current"] = years.apply(lambda ys: latest in ys) & \
                    ~df["redesig"].astype(str).str.contains(r"\d")

    oz = df[df["current"] & df["naaqs"].isin(CURRENT_OZONE_STANDARDS)].copy()
    oz["county_fips"] = oz["fips"].str.replace("/", "", regex=False).str.strip()
    # 'Severe 15' -> 'Severe' (the number is the attainment deadline in years)
    oz["class_base"] = oz["classification"].astype(str).str.extract(r"^([A-Za-z]+)")[0]
    oz["std_year"] = oz["naaqs"].str.extract(r"\((\d{4})\)")[0]
    return oz, data_date


def read_trades() -> tuple[pd.DataFrame, str]:
    html = TRADES.read_text(encoding="utf-8", errors="replace")
    df = pd.read_html(StringIO(html))[0]
    df.columns = [c.strip() for c in df.columns]
    df["received"] = pd.to_datetime(df["Received"], errors="coerce")
    df["price"] = pd.to_numeric(df["Price TPY"].astype(str).str.replace(r"[$,]", "", regex=True),
                                errors="coerce")
    df["tpy"] = pd.to_numeric(df["Final Amount Traded"], errors="coerce")
    nox = df[(df["Pollutant"].str.upper() == "NOX") & (df["price"] > 0)].copy()
    nox["area_key"] = nox["Area"].map(area_key)
    window = f"{df['received'].min():%Y-%m-%d} to {df['received'].max():%Y-%m-%d}"
    return nox, window


def main() -> None:
    rules = pd.read_csv(RULES).set_index("classification")
    counties = pd.read_csv(COUNTIES, dtype=str)
    oz, gb_date = read_greenbook()
    nox, window = read_trades()

    # Effective classification = most severe current ozone classification.
    oz["rank"] = oz["class_base"].map(rules["severity_rank"])
    if oz["rank"].isna().any():
        raise SystemExit(f"Unknown classification(s): {oz.loc[oz['rank'].isna(), 'classification'].unique()}")
    eff = (oz.sort_values("rank", ascending=False)
             .groupby("county_fips")
             .agg(classification=("class_base", "first"),
                  area_key=("area", lambda s: area_key(s.iloc[0])))
             .reset_index())
    # e.g. "2008: Severe 15; 2015: Serious" - one line per county listing each standard.
    detail = (oz.assign(pair=oz["std_year"].astype(str) + ": " + oz["classification"].astype(str))
                .sort_values("std_year")
                .groupby("county_fips")["pair"].agg("; ".join)
                .rename("standards_detail")
                .reset_index())
    eff = eff.merge(detail, on="county_fips")

    market = (nox.groupby("area_key")
                 .agg(area=("Area", "first"), trades=("price", "size"),
                      median_price=("price", "median"), tons_traded=("tpy", "sum"))
                 .reset_index())
    OUT_MARKET.parent.mkdir(parents=True, exist_ok=True)
    market.assign(window=window).to_csv(OUT_MARKET, index=False, lineterminator="\n")

    rows = []
    for fips in counties["county_fips"]:
        hit = eff[eff["county_fips"] == fips]
        if hit.empty:
            rows.append((fips, "ozone_classification", 0, "Attainment"))
            rows.append((fips, "nox_offset_ratio", 0, None))
            rows.append((fips, "nox_offset_cost_per_tpy", 0, None))
            continue
        h = hit.iloc[0]
        r = rules.loc[h["classification"]]
        rows.append((fips, "ozone_classification", int(r["severity_rank"]), h["classification"]))
        rows.append((fips, "ozone_standards_detail", None, h["standards_detail"]))
        rows.append((fips, "nox_major_source_tpy", float(r["nox_major_source_tpy"]), None))
        rows.append((fips, "nox_offset_ratio", float(r["nox_offset_ratio"]), None))
        m = market[market["area_key"] == h["area_key"]]
        trades = int(m["trades"].iloc[0]) if not m.empty else 0
        tons = float(m["tons_traded"].iloc[0]) if not m.empty else 0.0
        rows.append((fips, "nox_credit_trades", trades, None))
        rows.append((fips, "nox_credit_tons_traded", tons, None))
        if not m.empty:
            price = float(m["median_price"].iloc[0])
            rows.append((fips, "nox_credit_price_per_tpy", price, None))
            rows.append((fips, "nox_offset_cost_per_tpy", round(price * float(r["nox_offset_ratio"]), 2), None))
        # No trades in the area: price and cost are unknown and are left out,
        # so they show as missing rather than as zero.

    out = pd.DataFrame(rows, columns=["county_fips", "attribute_key", "value_num", "value_text"])
    out.to_csv(OUT, index=False, lineterminator="\n")

    na = eff.merge(counties[["county_fips", "county_name"]], on="county_fips")
    print(f"Green Book data date: {gb_date}")
    print(f"TCEQ trade window  : {window}")
    print(f"\nOzone nonattainment counties (effective classification): {len(na)}")
    for _, x in na.sort_values(["classification", "county_name"]).iterrows():
        print(f"  {x['county_name']:12} {x['classification']:9} ({x['standards_detail']})")
    print("\nNOx credit market by area:")
    print(market.to_string(index=False))
    print(f"\nWrote {len(out):,} rows to {OUT.relative_to(REPO)}")
    print(out["attribute_key"].value_counts().to_string())


if __name__ == "__main__":
    main()
