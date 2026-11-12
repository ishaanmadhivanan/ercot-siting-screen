/*  30_export_web.sql  --  website (Phase 7)

    Everything the website needs from the database, as ONE result set with
    one column. Each row is a small JSON object; the "t" field says which
    table it came from:

        county   every Texas county: name, in ERCOT or not, population, land area
        factor   raw value per ERCOT county per factor (rpt.county_factor),
                 plus the 0-100 score Power BI uses, kept so the website's own
                 scoring can be checked against it
        attr     background facts per county (fact.county_attribute):
                 ozone class, NOx offsets and credits, LNG, parcel data checks
        metric   the catalog (dim.metric): label, unit, direction, log scale,
                 blank-when-zero rule, category, source, date, notes

    HOW TO USE
      1. Open this file in SSMS and press F5.
      2. Right-click the results grid > Save Results As...
      3. Save as  data\processed\web_export.csv  in the repo folder.
      4. Run  python scripts/web/build_layers.py

    One JSON object per row keeps the file safe to save as CSV: there is only
    one column, so commas and quotes inside notes cannot shift columns.
*/

USE ErcotSiting;
GO

SELECT (SELECT 'county' AS t, c.county_fips, c.county_name, c.in_ercot, c.population, c.land_area_sqmi
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER) AS line
FROM dim.county c

UNION ALL
SELECT (SELECT 'factor' AS t, f.county_fips, f.factor_key, f.raw_value, s.factor_score
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER)
FROM rpt.county_factor f
LEFT JOIN rpt.county_factor_score s
       ON s.county_fips = f.county_fips AND s.factor_key = f.factor_key

UNION ALL
SELECT (SELECT 'attr' AS t, a.county_fips, a.attribute_key, a.value_num, a.value_text
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER)
FROM fact.county_attribute a
JOIN dim.county c ON c.county_fips = a.county_fips
WHERE c.in_ercot = 1

UNION ALL
SELECT (SELECT 'metric' AS t, m.metric_key, m.label, m.category AS topic, m.metric_type, m.unit,
               m.better_direction, m.score_transform, m.zero_is_missing, m.pillar AS category,
               m.source_name, m.source_url, m.data_date, m.caveat AS notes
        FOR JSON PATH, WITHOUT_ARRAY_WRAPPER)
FROM dim.metric m;
GO
