/*  07_dim_metric.sql  --  Phase 1 foundation

    The metric catalog. One row per layer in the model, documenting what it
    is, its unit, which direction is better, where it comes from, how current
    it is, and its main weakness. Every number shown in the report should
    trace back to a row here.

    metric_type:
      'score'   - numeric, can be weighted (lives in rpt.county_factor)
      'flag'    - used as a pass/fail filter, not weighted (e.g. ozone status)
      'context' - shown for information only (e.g. % outside city limits)

    better_direction:
      'higher' / 'lower' - fixed
      'preset'           - depends on the use case (see dim.score_weight)
      'none'             - descriptive text with no better or worse

    pillar (score metrics only): which of the five report pillars the factor
    belongs to (Gas supply, Grid connection, Site control, Air permit,
    Community). NULL keeps the factor in the catalog but out of the county
    score (rpt.county_factor_score skips it).

    zero_is_missing (score metrics only): 1 = a raw value of 0 means "nothing
    to measure here", so the county's score is left blank instead of 0 or 100.

    score_transform (score metrics only, used by rpt.county_factor_score):
      'linear' - raw value
      'log'    - LOG(1 + value), for right-skewed counts and MW where a few
                 counties dwarf the rest
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS dim.metric;
GO

CREATE TABLE dim.metric (
    metric_key        VARCHAR(50)    NOT NULL PRIMARY KEY,
    label             NVARCHAR(80)   NOT NULL,
    category          NVARCHAR(20)   NOT NULL,   -- grid, gas, air, land
    metric_type       VARCHAR(10)    NOT NULL,
    unit              NVARCHAR(40)   NOT NULL,
    better_direction  VARCHAR(10)    NOT NULL,
    source_name       NVARCHAR(120)  NOT NULL,
    source_url        NVARCHAR(300)  NULL,
    data_date         DATE           NULL,       -- as of when the underlying data is current
    caveat            NVARCHAR(400)  NULL,
    stage_added       SMALLINT       NOT NULL,
    score_transform   VARCHAR(10)    NOT NULL CONSTRAINT df_metric_transform DEFAULT 'linear',
    pillar            NVARCHAR(30)   NULL,       -- report pillar; NULL = not part of the county score
    zero_is_missing   BIT            NOT NULL CONSTRAINT df_metric_zero DEFAULT 0,
    CONSTRAINT ck_metric_transform CHECK (score_transform IN ('linear', 'log')),
    CONSTRAINT ck_metric_type CHECK (metric_type IN ('score', 'flag', 'context')),
    CONSTRAINT ck_metric_dir  CHECK (better_direction IN ('higher', 'lower', 'preset', 'none'))
);
GO

INSERT INTO dim.metric
    (metric_key, label, category, metric_type, unit, better_direction,
     source_name, source_url, data_date, caveat, stage_added)
VALUES
('installed_mw', 'Existing generation capacity', 'grid', 'score', 'MW', 'higher',
 'EIA Form 860 (2024)', 'https://www.eia.gov/electricity/data/eia860/', '2024-12-31',
 'Operating power plant capacity in the county. A rough sign that transmission lines are nearby; it says nothing about whether those lines have room for more.', 1),

('retiring_mw', 'Capacity retiring by 2030', 'grid', 'score', 'MW', 'higher',
 'EIA Form 860 (2024)', 'https://www.eia.gov/electricity/data/eia860/', '2024-12-31',
 'Not in the score. EIA lists planned ERCOT retirements through 2030 almost only in Bexar County, so this doesn''t separate counties. Plant age (Gas and coal 40+ years old) is used instead.', 1),

('pop_density', 'Population density', 'land', 'score', 'people per sq mi', 'lower',
 'US Census population estimates (2025) and Gazetteer land area (2024)', 'https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-total.html', '2025-07-01',
 'Fewer people means fewer neighbors near a plant and usually less local opposition. A rough measure only.', 2),

('capacity_factor', 'Realized capacity factor', 'grid', 'score', 'ratio 0-1', 'higher',
 'EIA Forms 923 and 860 (2024)', 'https://www.eia.gov/electricity/data/eia923/', '2024-12-31',
 'How hard all of the county''s power plants ran in 2024: actual output divided by the most they could produce. Capped at 1.0 because higher values are reporting errors. Blank for counties with no power plants.', 2),

('generation_trend', 'Generation trend 2020-2024', 'grid', 'score', 'log ratio', 'higher',
 'EIA Form 923 (2020-2024)', 'https://www.eia.gov/electricity/data/eia923/', '2024-12-31',
 'Change in the county''s power output from 2020 to 2024. A 10,000 MWh floor is added so counties with no generation don''t all tie for the top.', 2),

('queue_congestion', 'Active interconnection queue', 'grid', 'score', 'MW', 'lower',
 'ERCOT GIS Report', 'https://www.ercot.com/mp/data-products/data-product-details?id=PG7-200-ER', '2026-08-31',
 'MW of all projects waiting to connect to the grid in the county. Fewer is better: less competition for the same connection. Leaves out confidential projects ERCOT hasn''t published yet.', 3),

('queue_attrition', 'Queue attrition rate', 'grid', 'score', 'ratio 0-1', 'lower',
 'ERCOT GIS Report', 'https://www.ercot.com/mp/data-products/data-product-details?id=PG7-200-ER', '2026-08-31',
 'Not in the score. Share of past projects in the county that dropped out of the queue, pulled toward the statewide rate where there''s little history. Counties differ by only about 0.01, so scoring it would turn noise into big differences.', 3),

('aging_thermal_mw', 'Gas and coal 40+ years old', 'grid', 'score', 'MW', 'higher',
 'EIA Form 860 (2024)', 'https://www.eia.gov/electricity/data/eia860/', '2024-12-31',
 'Operating gas and coal units built in 1985 or earlier. Old plants are likely to retire or be rebuilt, and their sites already have grid and gas connections. Age is a guess, not an announced retirement.', 4),

('gas_queue_mw', 'Active gas queue', 'grid', 'score', 'MW', 'lower',
 'ERCOT GIS Report', 'https://www.ercot.com/mp/data-products/data-product-details?id=PG7-200-ER', '2026-08-31',
 'MW of gas projects waiting to connect in the county: the direct competition for a new gas plant. Fewer is better. Blank where there are none, since most counties have none. Leaves out confidential projects.', 4),

('gas_capacity_factor', 'Gas fleet capacity factor', 'grid', 'score', 'ratio 0-1', 'higher',
 'EIA Forms 923 and 860 (2024)', 'https://www.eia.gov/electricity/data/eia923/', '2024-12-31',
 'How hard the county''s existing gas plants ran in 2024. Busy plants suggest gas power is needed there. Blank for counties with no gas plants. Capped at 1.0.', 4),

('ozone_severity', 'Ozone nonattainment severity', 'air', 'score', 'rank 0-5', 'lower',
 'EPA Green Book', 'https://www3.epa.gov/airquality/greenbook/anayo_tx.html', '2026-08-31',
 'EPA ozone rating under the stricter of the 2008 and 2015 standards: 0 Attainment, 1 Marginal, 2 Moderate, 3 Serious, 4 Severe, 5 Extreme. A worse rating means a harder, more expensive air permit.', 5),

('ozone_classification', 'Ozone classification', 'air', 'flag', '', 'lower',
 'EPA Green Book', 'https://www3.epa.gov/airquality/greenbook/anayo_tx.html', '2026-08-31',
 'The county''s EPA ozone rating. Houston and Dallas-Fort Worth are Severe under the 2008 standard and Serious under 2015; permits follow the stricter one.', 5),

('ozone_standards_detail', 'Ozone standards breached', 'air', 'context', '', 'none',
 'EPA Green Book', 'https://www3.epa.gov/airquality/greenbook/anayo_tx.html', '2026-08-31',
 'Each ozone standard the county fails and its rating, for example "2008: Severe 15; 2015: Serious". Only for counties that fail one.', 5),

('nox_major_source_tpy', 'NOx major source threshold', 'air', 'flag', 'tons per year', 'higher',
 'Clean Air Act nonattainment permit rules', 'https://www.epa.gov/nsr/nonattainment-nsr-basic-information', NULL,
 'A plant emitting this much NOx or more needs a nonattainment permit and must buy offset credits. Only for counties that fail an ozone standard. Elsewhere, plants still need pollution controls but don''t buy offsets.', 5),

('nox_offset_ratio', 'NOx offset ratio', 'air', 'flag', 'tons of credit per ton emitted', 'lower',
 'Clean Air Act nonattainment permit rules', 'https://www.epa.gov/nsr/nonattainment-nsr-basic-information', NULL,
 'Tons of credits a plant must buy for each ton of NOx it will emit. 0 where no offsets are needed.', 5),

('nox_credit_trades', 'NOx credit trades (area)', 'air', 'context', 'trades', 'higher',
 'TCEQ Emission Credit Trade Report', 'https://www.tceq.texas.gov/assets/public/permitting/air/reports/banking/ectradereport.html', '2026-09-11',
 'Number of priced NOx credit trades in the county''s ozone area, Oct 2024 to Sep 2026. Credits must come from the same area, so few trades can mean credits are hard to find at any price.', 5),

('nox_credit_tons_traded', 'NOx credit tons traded (area)', 'air', 'context', 'tons per year', 'higher',
 'TCEQ Emission Credit Trade Report', 'https://www.tceq.texas.gov/assets/public/permitting/air/reports/banking/ectradereport.html', '2026-09-11',
 'Tons per year of NOx credits sold in the area, Oct 2024 to Sep 2026. Houston sold 87 in two years; one 100-ton-per-year plant at 1.3 to 1 would need 130.', 5),

('nox_credit_price_per_tpy', 'NOx credit price (area median)', 'air', 'context', 'USD per ton per year', 'lower',
 'TCEQ Emission Credit Trade Report', 'https://www.tceq.texas.gov/assets/public/permitting/air/reports/banking/ectradereport.html', '2026-09-11',
 'Median price paid for NOx credits in the area, a one-time purchase per ton per year. Blank where the area had no priced trades (San Antonio and El Paso).', 5),

('nox_offset_cost_per_tpy', 'NOx offset cost per ton emitted', 'air', 'flag', 'USD per ton per year', 'lower',
 'Calculated: offset ratio x area credit price', NULL, '2026-09-11',
 'Up-front credit cost for each ton per year of NOx the plant will emit; multiply by the plant''s own emissions. 0 where no offsets are needed; blank where the area had no priced trades.', 5),

('gas_pipe_miles', 'Gas transmission pipe', 'gas', 'score', 'miles', 'higher',
 'Railroad Commission of Texas pipeline map', 'https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0', '2026-09-30',
 'Miles of gas transmission pipe in the county. Shows a plant could connect, not that spare gas is available: capacity and pressure aren''t public for pipes inside Texas.', 6),

('gas_pipe_large_miles', 'Large gas pipe (20 in and up)', 'gas', 'score', 'miles', 'higher',
 'Railroad Commission of Texas pipeline map', 'https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0', '2026-09-30',
 'Miles of transmission pipe 20 inches or wider. Diameter stands in for capacity, which isn''t published. Large lines are the ones that can usually supply a power plant; small ones mostly serve towns and industry.', 6),

('gas_pipe_operators', 'Gas pipeline operators', 'gas', 'score', 'operators', 'higher',
 'Railroad Commission of Texas pipeline map', 'https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0', '2026-09-30',
 'Number of companies with at least 1 mile of transmission pipe in the county. More operators means more supply options and a better negotiating position.', 6),

('gas_pipe_interstate_miles', 'Interstate gas pipe', 'gas', 'score', 'miles', 'higher',
 'Railroad Commission of Texas pipeline map', 'https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0', '2026-09-30',
 'Miles of pipe that crosses state lines. These are federally regulated, with published rates and open access. Pipes inside Texas (about three quarters of the mileage) set terms privately.', 6),

('gas_gathering_miles', 'Gas gathering pipe', 'gas', 'score', 'miles', 'higher',
 'Railroad Commission of Texas pipeline map', 'https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0', '2026-09-30',
 'Miles of pipe that collects gas from wells. A sign of nearby production (Permian, Eagle Ford, Haynesville), where gas is usually cheapest. Gathering lines carry raw gas and can''t feed a plant directly.', 6),

('lng_terminal_count', 'LNG export terminals', 'gas', 'context', 'terminals', 'none',
 'Compiled by hand; Golden Pass status from EIA, April 2026', 'https://www.eia.gov/todayinenergy/detail.php?id=67564', '2026-09-30',
 'LNG export terminals operating or under construction. They compete for pipeline gas but also mean large supply lines are nearby. Status needs checking now and then.', 6),

('lng_terminals', 'LNG export terminals (names)', 'gas', 'context', '', 'none',
 'Compiled by hand', NULL, '2026-09-30',
 'Terminal names and status, for example "Golden Pass LNG (Operating)".', 6),

('land_large_tract_share', 'Land in large tracts (100+ ac)', 'land', 'score', 'share 0-1', 'higher',
 'TxGIO StratMap Land Parcels 2025 (county appraisal districts)', 'https://geographic.texas.gov/', '2025-05-01',
 'Share of parcel acres in parcels of 100 acres or more: room for a plant on land with one owner. Blank where the parcel data covers less than 80% or more than 125% of the county.', 7),

('land_owner_density', 'Landowners per 1,000 rural acres', 'land', 'score', 'owners per 1,000 acres', 'lower',
 'TxGIO StratMap Land Parcels 2025 (county appraisal districts)', 'https://geographic.texas.gov/', '2025-05-01',
 'Number of different owners of 5+ acre parcels per 1,000 acres of those parcels: how many landowners a project may have to deal with. The same owner spelled differently counts twice. Blank where parcel data is incomplete.', 7),

('land_parcels_500ac', 'Parcels of 500+ acres', 'land', 'score', 'parcels', 'higher',
 'TxGIO StratMap Land Parcels 2025 (county appraisal districts)', 'https://geographic.texas.gov/', '2025-05-01',
 'Number of single parcels of 500 acres or more: tracts big enough for a plant plus a buffer. Blank where parcel data is incomplete.', 7),

('land_industrial_acres', 'Industrial and utility land', 'land', 'context', 'acres', 'higher',
 'TxGIO StratMap Land Parcels 2025, state land-use codes F2 and J3', 'https://geographic.texas.gov/', '2025-05-01',
 'Acres coded as industrial (F2) or electric utility (J3) land. Only shown where at least 80% of parcels have a land-use code, about a third of counties.', 7),

('land_code_coverage', 'Parcels with a land-use code', 'land', 'context', 'share 0-1', 'none',
 'TxGIO StratMap Land Parcels 2025', 'https://geographic.texas.gov/', '2025-05-01',
 'Share of parcels that have a state land-use code. Many counties leave it blank (Wharton, Fort Bend and Travis are at 0%).', 7),

('land_parcel_coverage', 'Parcel coverage of county', 'land', 'context', 'ratio', 'none',
 'TxGIO StratMap Land Parcels 2025 and US Census', 'https://geographic.texas.gov/', '2025-05-01',
 'Parcel acres divided by the county''s Census land area. Close to 1.0 means the parcel data is complete. Harris is 0.40 (partial file); Frio (2.8) and Chambers (1.7) have overlapping parcels. Land scores are blank outside 0.8 to 1.25.', 7),

('land_parcel_vintage', 'Parcel data month', 'land', 'context', 'year and month', 'none',
 'TxGIO StratMap Land Parcels 2025', 'https://geographic.texas.gov/', NULL,
 'Month the county appraisal district''s data was collected.', 7);
GO

-- Transform used when each score metric is put on a 0-100 scale. Matches the
-- presets in dim.score_weight: log for skewed MW, miles and counts.
UPDATE dim.metric
SET score_transform = 'log'
WHERE metric_key IN ('installed_mw', 'retiring_mw', 'pop_density', 'queue_congestion',
                     'aging_thermal_mw', 'gas_queue_mw',
                     'gas_pipe_miles', 'gas_pipe_large_miles', 'gas_pipe_operators',
                     'gas_pipe_interstate_miles', 'gas_gathering_miles',
                     'land_owner_density', 'land_parcels_500ac');
GO


-- Phase 5: report pillars. Only score metrics get a pillar; NULL = not in the county score.
UPDATE dim.metric SET pillar = 'Gas supply'
WHERE metric_key IN ('gas_pipe_miles', 'gas_pipe_large_miles', 'gas_pipe_interstate_miles',
                     'gas_pipe_operators', 'gas_gathering_miles');

UPDATE dim.metric SET pillar = 'Grid connection'
WHERE metric_key IN ('installed_mw', 'capacity_factor', 'gas_capacity_factor', 'generation_trend',
                     'gas_queue_mw', 'queue_congestion');
-- queue_attrition and retiring_mw stay NULL on purpose (see their caveats).

UPDATE dim.metric SET pillar = 'Site control'
WHERE metric_key IN ('aging_thermal_mw', 'land_large_tract_share', 'land_owner_density', 'land_parcels_500ac');

UPDATE dim.metric SET pillar = 'Air permit'   WHERE metric_key = 'ozone_severity';
UPDATE dim.metric SET pillar = 'Community'    WHERE metric_key = 'pop_density';

-- A 0 here means "nothing to measure" (no queue, no plants), not a bad result.
UPDATE dim.metric SET zero_is_missing = 1
WHERE metric_key IN ('gas_queue_mw', 'gas_capacity_factor', 'capacity_factor');
GO

-- Check 1: every factor the model scores has a catalog row. Should return zero rows.
SELECT DISTINCT f.factor_key AS missing_from_catalog
FROM rpt.county_factor f
LEFT JOIN dim.metric m ON m.metric_key = f.factor_key
WHERE m.metric_key IS NULL;

-- Check 1b: every factor any preset weights has a catalog row. Should return zero rows.
SELECT DISTINCT w.factor_key AS weighted_but_undocumented
FROM dim.score_weight w
LEFT JOIN dim.metric m ON m.metric_key = w.factor_key
WHERE m.metric_key IS NULL;

-- Check 2: the catalog as a reader would see it.
SELECT metric_key, label, pillar, category, metric_type, unit, better_direction, score_transform, data_date
FROM dim.metric
ORDER BY pillar, stage_added, metric_key;

-- Check 3: every score metric is in a pillar except retiring_mw and queue_attrition. Expect exactly those two.
SELECT metric_key AS score_metric_without_pillar
FROM dim.metric
WHERE metric_type = 'score' AND pillar IS NULL;
GO
