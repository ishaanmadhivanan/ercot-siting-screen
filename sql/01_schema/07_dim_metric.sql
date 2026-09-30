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
 'Proxy for transmission presence. Says nothing about whether nearby lines are congested.', 1),

('retiring_mw', 'Capacity retiring by 2030', 'grid', 'score', 'MW', 'higher',
 'EIA Form 860 (2024)', 'https://www.eia.gov/electricity/data/eia860/', '2024-12-31',
 'Through 2030, EIA-860 lists planned ERCOT retirements almost only in Bexar, so this barely discriminates between counties. Superseded by aging_thermal_mw in the gas preset.', 1),

('pop_density', 'Population density', 'land', 'score', 'people per sq mi', 'lower',
 'US Census population estimates (2025) and Gazetteer land area (2024)',
 'https://www.census.gov/data/tables/time-series/demo/popest/2020s-counties-total.html', '2025-07-01',
 'Weak land proxy. Ignores parcel structure and land use; to be superseded by parcel metrics.', 2),

('capacity_factor', 'Realised capacity factor', 'grid', 'score', 'ratio 0-1', 'higher',
 'EIA Form 923 (2024) with EIA-860 capacity', 'https://www.eia.gov/electricity/data/eia923/', '2024-12-31',
 'All fuels combined; capped at 1.0 because values above that are reporting artefacts.', 2),

('generation_trend', 'Generation trend 2020-2024', 'grid', 'score', 'smoothed log ratio', 'higher',
 'EIA Form 923 (2020-2024)', 'https://www.eia.gov/electricity/data/eia923/', '2024-12-31',
 'Smoothed with a 10,000 MWh floor so zero-generation counties do not tie at a ceiling.', 2),

('queue_congestion', 'Active interconnection queue', 'grid', 'score', 'MW', 'preset',
 'ERCOT GIS Report (August 2026)', 'https://www.ercot.com/mp/data-products/data-product-details?id=PG7-200-ER', '2026-08-31',
 'Negative for generation (competition), positive for datacenter (supply arriving). Excludes confidential projects not yet in full study.', 3),

('queue_attrition', 'Queue attrition rate', 'grid', 'score', 'ratio 0-1', 'lower',
 'ERCOT GIS Report (August 2026)', 'https://www.ercot.com/mp/data-products/data-product-details?id=PG7-200-ER', '2026-08-31',
 'Shrunk toward the statewide rate for counties with little history. Cumulative withdrawals vs current queue, not a true failure rate.', 3),

-- ---------- Phase 1 of the gas pivot: gas-specific versions of existing factors ----------
('aging_thermal_mw', 'Gas and coal 40+ years old', 'grid', 'score', 'MW', 'higher',
 'EIA Form 860 (2024)', 'https://www.eia.gov/electricity/data/eia860/', '2024-12-31',
 'Operating gas and coal units built 1985 or earlier. Age proxies for retirement or repowering candidates; it is not an announced retirement.', 4),

('gas_queue_mw', 'Active gas queue', 'grid', 'score', 'MW', 'lower',
 'ERCOT GIS Report (August 2026)', 'https://www.ercot.com/mp/data-products/data-product-details?id=PG7-200-ER', '2026-08-31',
 'Gas projects only - the direct competition for a new gas plant. Excludes confidential projects not yet in full study.', 4),

('gas_capacity_factor', 'Gas fleet capacity factor', 'grid', 'score', 'ratio 0-1', 'higher',
 'EIA Form 923 (2024, fuel code NG) with EIA-860 gas capacity', 'https://www.eia.gov/electricity/data/eia923/', '2024-12-31',
 'How hard existing gas plants run. Counties with no gas fleet score 0 (no evidence either way). Capped at 1.0.', 4),

-- ---------- Phase 2: air permitting (ozone nonattainment and NOx offsets) ----------
-- The score: one number per county that can be weighted like any other factor.
('ozone_severity', 'Ozone nonattainment severity', 'air', 'score', 'rank 0-5', 'lower',
 'EPA Green Book (current as of August 31, 2026)', 'https://www3.epa.gov/airquality/greenbook/anayo_tx.html', '2026-08-31',
 '0 Attainment, 1 Marginal, 2 Moderate, 3 Serious, 4 Severe, 5 Extreme. Strictest current ozone standard (2008 or 2015). Whole-county designations only in Texas today.', 5),

-- The attributes: filters and context, stored in fact.county_attribute, never weighted.
('ozone_classification', 'Ozone classification', 'air', 'flag', 'category', 'lower',
 'EPA Green Book (current as of August 31, 2026)', 'https://www3.epa.gov/airquality/greenbook/anayo_tx.html', '2026-08-31',
 'value_text holds the class name, value_num the severity rank. Houston and Dallas-Fort Worth are Severe under 2008 and Serious under 2015; permitting follows the stricter one.', 5),

('ozone_standards_detail', 'Ozone standards breached', 'air', 'context', 'text', 'none',
 'EPA Green Book (current as of August 31, 2026)', 'https://www3.epa.gov/airquality/greenbook/anayo_tx.html', '2026-08-31',
 'Each current ozone standard the county violates and its class, e.g. "2008: Severe 15; 2015: Serious". Nonattainment counties only.', 5),

('nox_major_source_tpy', 'NOx major source threshold', 'air', 'flag', 'tons per year', 'higher',
 'Clean Air Act Title I, Part D (versioned in data/seed/ozone_classification_rules.csv)', 'https://www.epa.gov/nsr/nonattainment-nsr-basic-information', NULL,
 'A plant emitting at or above this much NOx needs nonattainment review and must buy offsets. Nonattainment counties only. Attainment counties go through PSD review instead: pollution controls, but no offsets to buy.', 5),

('nox_offset_ratio', 'NOx offset ratio', 'air', 'flag', 'tons of credit per ton emitted', 'lower',
 'Clean Air Act Title I, Part D (versioned in data/seed/ozone_classification_rules.csv)', 'https://www.epa.gov/nsr/nonattainment-nsr-basic-information', NULL,
 'Tons of emission credit a major source must buy per ton of NOx it will emit. 0 in attainment counties (no offsets required).', 5),

('nox_credit_trades', 'NOx credit trades (area)', 'air', 'context', 'trades', 'higher',
 'TCEQ Emission Credit Trade Report', 'https://www.tceq.texas.gov/assets/public/permitting/air/reports/banking/ectradereport.html', '2026-09-11',
 'Priced NOx credit trades in the county''s nonattainment area, Oct 2024 to Sep 2026. Credits must come from the same area. A thin market means credits may not be available at any price.', 5),

('nox_credit_tons_traded', 'NOx credit tons traded (area)', 'air', 'context', 'tons per year', 'higher',
 'TCEQ Emission Credit Trade Report', 'https://www.tceq.texas.gov/assets/public/permitting/air/reports/banking/ectradereport.html', '2026-09-11',
 'Total credit volume in priced NOx trades, Oct 2024 to Sep 2026. Houston traded 87 tpy in two years; a single 100 tpy plant at 1.3:1 would need 130.', 5),

('nox_credit_price_per_tpy', 'NOx credit price (area median)', 'air', 'context', 'USD per tpy', 'lower',
 'TCEQ Emission Credit Trade Report', 'https://www.tceq.texas.gov/assets/public/permitting/air/reports/banking/ectradereport.html', '2026-09-11',
 'Median price of priced NOx trades in the area, one-time purchase per ton/year of credit. Missing (not zero) where the area had no priced trades: San Antonio and El Paso.', 5),

('nox_offset_cost_per_tpy', 'NOx offset cost per tpy emitted', 'air', 'flag', 'USD per tpy', 'lower',
 'Derived: offset ratio x area median credit price', NULL, '2026-09-11',
 'Up-front credit cost per ton/year of NOx the plant will emit; multiply by your own plant''s emissions. 0 in attainment counties; missing where the area has no priced trades.', 5),

-- ---------- Phase 3: gas access (RRC pipeline map, LNG terminals) ----------
('gas_pipe_miles', 'Gas transmission pipe', 'gas', 'score', 'miles', 'higher',
 'Railroad Commission of Texas pipeline map (TPMS), in-service NGT lines', 'https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0', '2026-09-30',
 'Miles of existing pipe, not spare capacity: capacity, pressure and flow are not public for intrastate lines. Says a plant could connect, not that gas is available.', 6),

('gas_pipe_large_miles', 'Large gas pipe (20 in and up)', 'gas', 'score', 'miles', 'higher',
 'Railroad Commission of Texas pipeline map (TPMS), in-service NGT lines', 'https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0', '2026-09-30',
 'Diameter stands in for capacity, which is not published. Large trunk lines are the ones typically able to supply a utility-scale plant; small lines mostly serve towns and industry.', 6),

('gas_pipe_operators', 'Gas pipeline operators', 'gas', 'score', 'operators', 'higher',
 'Railroad Commission of Texas pipeline map (TPMS), in-service NGT lines', 'https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0', '2026-09-30',
 'Distinct operators (RRC P-5 number) with at least 1 mile of transmission pipe in the county. More operators means more supply options and negotiating leverage.', 6),

('gas_pipe_interstate_miles', 'Interstate gas pipe', 'gas', 'score', 'miles', 'higher',
 'Railroad Commission of Texas pipeline map (TPMS), in-service NGT lines flagged interstate', 'https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0', '2026-09-30',
 'Interstate lines are FERC regulated with published, open-access tariffs. Intrastate lines (about three quarters of Texas mileage) negotiate service privately.', 6),

('gas_gathering_miles', 'Gas gathering pipe', 'gas', 'score', 'miles', 'higher',
 'Railroad Commission of Texas pipeline map (TPMS), in-service NGG and NFG lines', 'https://gis.rrc.texas.gov/server/rest/services/rrc_public/tpms/MapServer/0', '2026-09-30',
 'Proxy for nearby gas production (Permian, Eagle Ford, Haynesville), where gas tends to be cheapest. Gathering lines carry raw well gas and cannot feed a plant directly. Stored in fact.county_attribute.', 6),

('lng_terminal_count', 'LNG export terminals', 'gas', 'context', 'terminals', 'none',
 'Hand-built list (data/seed/lng_terminals.csv); Golden Pass status from EIA, April 2026', 'https://www.eia.gov/todayinenergy/detail.php?id=67564', '2026-09-30',
 'Operating or under construction. Competing demand for pipeline gas; also a sign of large-diameter supply lines nearby. Status needs periodic review.', 6),

('lng_terminals', 'LNG export terminals (names)', 'gas', 'context', 'text', 'none',
 'Hand-built list (data/seed/lng_terminals.csv)', NULL, '2026-09-30',
 'Terminal names with status, e.g. "Golden Pass LNG (Operating); Port Arthur LNG (Under construction)".', 6);
GO

-- Transform used when each score metric is put on a 0-100 scale. Matches the
-- presets in dim.score_weight: log for skewed MW, miles and counts.
UPDATE dim.metric
SET score_transform = 'log'
WHERE metric_key IN ('installed_mw', 'retiring_mw', 'pop_density', 'queue_congestion',
                     'aging_thermal_mw', 'gas_queue_mw',
                     'gas_pipe_miles', 'gas_pipe_large_miles', 'gas_pipe_operators',
                     'gas_pipe_interstate_miles', 'gas_gathering_miles');
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
SELECT metric_key, label, category, metric_type, unit, better_direction, score_transform, data_date
FROM dim.metric
ORDER BY stage_added, metric_key;
GO
