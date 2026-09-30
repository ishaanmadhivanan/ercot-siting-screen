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
    CONSTRAINT ck_metric_type CHECK (metric_type IN ('score', 'flag', 'context')),
    CONSTRAINT ck_metric_dir  CHECK (better_direction IN ('higher', 'lower', 'preset'))
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
 'How hard existing gas plants run. Counties with no gas fleet score 0 (no evidence either way). Capped at 1.0.', 4);
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
SELECT metric_key, label, category, metric_type, unit, better_direction, data_date
FROM dim.metric
ORDER BY stage_added, metric_key;
GO
