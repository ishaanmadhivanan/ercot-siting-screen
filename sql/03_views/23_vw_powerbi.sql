/*  23_vw_powerbi.sql  --  Phase 5
    One view per Power BI table. Power BI reads these by name instead of
    sending its own SQL, so Desktop never asks to approve native queries and
    the report's data logic stays in SQL with the rest of the model.
    Generated from the TABLES block of scripts/build_powerbi_project.py; edit
    both together.
*/

USE ErcotSiting;
GO

CREATE OR ALTER VIEW rpt.pbi_county AS
SELECT c.county_fips, c.county_name, c.county_name + ' County, Texas' AS map_label, c.population, c.land_area_sqmi, a.ozone_class, a.nox_offset_ratio, a.nox_offset_cost_per_tpy, a.nox_credit_trades, a.nox_credit_price_per_tpy, a.nox_credit_tons_traded, a.land_parcel_coverage, a.land_industrial_acres, a.lng_terminal_count, a.lng_terminals, ISNULL(pp.large_pipe_miles, 0) AS large_pipe_miles FROM dim.county c LEFT JOIN (SELECT county_fips, MAX(CASE WHEN attribute_key = 'ozone_classification' THEN value_text END) AS ozone_class, MAX(CASE WHEN attribute_key = 'nox_offset_ratio' THEN value_num END) AS nox_offset_ratio, MAX(CASE WHEN attribute_key = 'nox_offset_cost_per_tpy' THEN value_num END) AS nox_offset_cost_per_tpy, MAX(CASE WHEN attribute_key = 'nox_credit_trades' THEN value_num END) AS nox_credit_trades, MAX(CASE WHEN attribute_key = 'land_parcel_coverage' THEN value_num END) AS land_parcel_coverage, MAX(CASE WHEN attribute_key = 'land_industrial_acres' THEN value_num END) AS land_industrial_acres, MAX(CASE WHEN attribute_key = 'lng_terminal_count' THEN value_num END) AS lng_terminal_count, MAX(CASE WHEN attribute_key = 'lng_terminals' THEN value_text END) AS lng_terminals, MAX(CASE WHEN attribute_key = 'nox_credit_price_per_tpy' THEN value_num END) AS nox_credit_price_per_tpy, MAX(CASE WHEN attribute_key = 'nox_credit_tons_traded' THEN value_num END) AS nox_credit_tons_traded FROM fact.county_attribute GROUP BY county_fips) a ON a.county_fips = c.county_fips LEFT JOIN (SELECT county_fips, SUM(miles) AS large_pipe_miles FROM fact.pipeline_segment WHERE diameter_in >= 20 GROUP BY county_fips) pp ON pp.county_fips = c.county_fips WHERE c.in_ercot = 1;
GO

CREATE OR ALTER VIEW rpt.pbi_county_factor_score AS
SELECT county_fips, county_name, factor_key, factor_label, category, pillar, unit, raw_value, better_direction, score_transform, factor_score FROM rpt.county_factor_score;
GO

CREATE OR ALTER VIEW rpt.pbi_pipeline_segment AS
SELECT p.county_fips, p.operator_name, p.system_name, p.diameter_in, p.interstate, p.miles FROM fact.pipeline_segment p JOIN dim.county c ON c.county_fips = p.county_fips WHERE c.in_ercot = 1;
GO

CREATE OR ALTER VIEW rpt.pbi_plant AS
SELECT g.county_fips, g.plant_code, g.generator_id, g.plant_name, g.technology, g.nameplate_mw, g.operating_year, g.latitude, g.longitude FROM fact.generator_capacity g JOIN dim.county c ON c.county_fips = g.county_fips WHERE c.in_ercot = 1 AND g.status_group = 'Operating' AND g.data_vintage_year = (SELECT MAX(data_vintage_year) FROM fact.generator_capacity);
GO

CREATE OR ALTER VIEW rpt.pbi_metric AS
SELECT metric_key, label, category,
       -- "pillar" is the report's Category column.
       COALESCE(pillar, CASE WHEN metric_type = 'score' THEN 'Not in score' ELSE 'Background info' END) AS pillar,
       metric_type,
       CASE WHEN unit IN ('text', 'category') THEN '' ELSE unit END AS unit,
       CASE WHEN better_direction IN ('higher', 'lower') THEN better_direction ELSE '' END AS better_direction,
       source_name, data_date, caveat,
       -- Plain-English version of how rpt.county_factor_score turns the raw value into 0-100.
       CASE WHEN metric_type <> 'score' THEN 'Not scored. Shown in Background info on County detail.'
            WHEN pillar IS NULL THEN 'Not scored (see Notes). Shown in Background info on County detail.'
            ELSE CONCAT('Scored 0-100 against the other ERCOT counties: ',
                        CASE WHEN better_direction = 'lower' THEN 'lowest' ELSE 'highest' END,
                        ' value = 100, ',
                        CASE WHEN better_direction = 'lower' THEN 'highest' ELSE 'lowest' END,
                        ' = 0.',
                        CASE WHEN score_transform = 'log' THEN ' Uses a log scale so a few very large counties don''t flatten the rest.' ELSE '' END,
                        CASE WHEN zero_is_missing = 1 THEN ' Blank where the value is 0 (nothing to measure).' ELSE '' END)
       END AS how_scored
FROM dim.metric;
GO

-- Everything about a county that is not in the score, one row per fact, for
-- the Background info table on County detail.
CREATE OR ALTER VIEW rpt.pbi_county_background AS
SELECT a.county_fips, m.label AS fact,
       COALESCE(a.value_text, FORMAT(a.value_num, '#,0.##')) AS value,
       CASE WHEN m.unit IN ('text', 'category') THEN '' ELSE m.unit END AS unit
FROM fact.county_attribute a
JOIN dim.metric m ON m.metric_key = a.attribute_key
JOIN dim.county c ON c.county_fips = a.county_fips
WHERE c.in_ercot = 1 AND m.metric_type IN ('flag', 'context')
UNION ALL
SELECT f.county_fips, m.label, FORMAT(f.raw_value, '#,0.##'), m.unit
FROM rpt.county_factor f
JOIN dim.metric m ON m.metric_key = f.factor_key
JOIN dim.county c ON c.county_fips = f.county_fips
WHERE c.in_ercot = 1 AND m.metric_type = 'score' AND m.pillar IS NULL;
GO

-- Check: row counts (expect County 195, factor scores ~3,500, metric 40+).
SELECT 'pbi_county' AS view_name, COUNT(*) AS row_count FROM rpt.pbi_county UNION ALL
SELECT 'pbi_county_factor_score', COUNT(*) FROM rpt.pbi_county_factor_score UNION ALL
SELECT 'pbi_pipeline_segment', COUNT(*) FROM rpt.pbi_pipeline_segment UNION ALL
SELECT 'pbi_plant', COUNT(*) FROM rpt.pbi_plant UNION ALL
SELECT 'pbi_metric', COUNT(*) FROM rpt.pbi_metric UNION ALL
SELECT 'pbi_county_background', COUNT(*) FROM rpt.pbi_county_background;

-- Check: gas fleet factor is now blank (not 0) where a county has no gas plants.
SELECT COUNT(*) AS counties, SUM(CASE WHEN factor_score IS NULL THEN 1 ELSE 0 END) AS blank
FROM rpt.county_factor_score WHERE factor_key = 'gas_capacity_factor'
GO
