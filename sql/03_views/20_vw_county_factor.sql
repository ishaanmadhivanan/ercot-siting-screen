/*  20_vw_county_factor.sql
    Every scoring input, in TALL form: one row per county per factor.

    WHY TALL AND NOT WIDE: adding a factor is a single UNION ALL block plus one
    INSERT into dim.score_weight and one row in dim.metric. Nothing downstream
    changes - not the normalisation, not rpt.county_score, not the Power BI model.

    SCOPE FILTER (Stage 3): every block carries WHERE c.in_ercot = 1.
    Texas has 254 counties but only 195 are classified as ERCOT; the rest sit in
    SPP, MISO, SERC or WECC. Leaving them in would hand them a perfect zero on
    queue congestion and distort the min-max bounds for every factor.

    A factor that appears here but has no weight in a given weight_version is
    simply ignored by that version (the scoring view inner-joins on weights).
    That is how the gas-specific factors below coexist with the older presets.

    Grain: county_fips + factor_key.
*/

USE ErcotSiting;
GO

CREATE OR ALTER VIEW rpt.county_factor AS

-- Factor 1 (Stage 1): existing installed generation capacity, all fuels.
-- Proxy for transmission presence.
SELECT
    c.county_fips,
    'installed_mw' AS factor_key,
    CAST(ISNULL(SUM(CASE WHEN f.status_group = 'Operating'
                         THEN f.nameplate_mw END), 0) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN fact.generator_capacity f ON f.county_fips = c.county_fips
WHERE c.in_ercot = 1
GROUP BY c.county_fips

UNION ALL

-- Factor 2 (Stage 1): capacity with a planned retirement on or before 2030, all fuels.
SELECT
    c.county_fips,
    'retiring_mw' AS factor_key,
    CAST(ISNULL(SUM(CASE WHEN f.planned_retire_year IS NOT NULL
                          AND f.planned_retire_year <= 2030
                         THEN f.nameplate_mw END), 0) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN fact.generator_capacity f ON f.county_fips = c.county_fips
WHERE c.in_ercot = 1
GROUP BY c.county_fips

UNION ALL

-- Factor 3 (Stage 1b): population density, people per square mile.
SELECT
    c.county_fips,
    'pop_density' AS factor_key,
    CAST(ISNULL(c.population / NULLIF(c.land_area_sqmi, 0), 0) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
WHERE c.in_ercot = 1

UNION ALL

-- Factor 4 (Stage 2): realised capacity factor over 2024, all fuels.
-- actual MWh / (installed MW x hours). Capped at 1.0: values above are artefacts.
SELECT
    c.county_fips,
    'capacity_factor' AS factor_key,
    CAST(ISNULL(
        CASE WHEN cap.installed_mw > 0 AND gen.total_hours > 0
             THEN CASE WHEN gen.total_mwh / (cap.installed_mw * gen.total_hours) > 1.0
                       THEN 1.0
                       ELSE gen.total_mwh / (cap.installed_mw * gen.total_hours) END
        END, 0) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN (
    SELECT county_fips,
           SUM(CASE WHEN status_group = 'Operating' THEN nameplate_mw END) AS installed_mw
    FROM fact.generator_capacity
    GROUP BY county_fips
) cap ON cap.county_fips = c.county_fips
LEFT JOIN (
    SELECT g.county_fips,
           SUM(g.net_generation_mwh) AS total_mwh,
           (SELECT SUM(hours_in_month) FROM dim.month
            WHERE month_key BETWEEN 202401 AND 202412) AS total_hours
    FROM fact.generation_monthly g
    WHERE g.month_key BETWEEN 202401 AND 202412
    GROUP BY g.county_fips
) gen ON gen.county_fips = c.county_fips
WHERE c.in_ercot = 1

UNION ALL

-- Factor 5 (Stage 2): generation trend, 2020 vs 2024, smoothed log ratio.
-- LOG((new + 10,000) / (old + 10,000)); negatives floored at zero first.
SELECT
    c.county_fips,
    'generation_trend' AS factor_key,
    CAST(
        LOG(
            (CASE WHEN ISNULL(t.mwh_2024, 0) < 0 THEN 0 ELSE ISNULL(t.mwh_2024, 0) END + 10000.0)
            /
            (CASE WHEN ISNULL(t.mwh_2020, 0) < 0 THEN 0 ELSE ISNULL(t.mwh_2020, 0) END + 10000.0)
        ) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN (
    SELECT g.county_fips,
           SUM(CASE WHEN m.year = 2020 THEN g.net_generation_mwh END) AS mwh_2020,
           SUM(CASE WHEN m.year = 2024 THEN g.net_generation_mwh END) AS mwh_2024
    FROM fact.generation_monthly g
    JOIN dim.month m ON m.month_key = g.month_key
    WHERE m.year IN (2020, 2024)
    GROUP BY g.county_fips
) t ON t.county_fips = c.county_fips
WHERE c.in_ercot = 1

UNION ALL

-- Factor 6 (Stage 3): active interconnection queue, all fuels.
SELECT
    c.county_fips,
    'queue_congestion' AS factor_key,
    CAST(ISNULL(SUM(CASE WHEN q.status = 'Active' THEN q.capacity_mw END), 0)
         AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN fact.queue_project q ON q.county_fips = c.county_fips
WHERE c.in_ercot = 1
GROUP BY c.county_fips

UNION ALL

-- Factor 7 (Stage 3): queue attrition, shrunk toward the statewide rate (k = 500 MW).
SELECT
    c.county_fips,
    'queue_attrition' AS factor_key,
    CAST(
        (ISNULL(q.inactive_mw, 0) + 500.0 * sw.statewide_rate)
        / (ISNULL(q.total_mw, 0) + 500.0)
    AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN (
    SELECT county_fips,
           SUM(CASE WHEN status = 'Inactive' THEN capacity_mw ELSE 0 END) AS inactive_mw,
           SUM(capacity_mw)                                                AS total_mw
    FROM fact.queue_project
    GROUP BY county_fips
) q ON q.county_fips = c.county_fips
CROSS JOIN (
    SELECT SUM(CASE WHEN status = 'Inactive' THEN capacity_mw ELSE 0 END)
           / NULLIF(SUM(capacity_mw), 0) AS statewide_rate
    FROM fact.queue_project
) sw
WHERE c.in_ercot = 1

UNION ALL

-- Factor 8 (Phase 1, gas): gas and coal capacity built 1985 or earlier (40+ years old).
-- Brownfield signal for a gas developer. Old thermal units are the likeliest to
-- retire or be repowered, and their sites come with a grid connection, usually a
-- gas line, water rights and industrial land.
--
-- WHY AGE AND NOT ANNOUNCED RETIREMENTS: the first version of this factor used
-- EIA-860 planned retirement dates. Through 2030 those exist in ERCOT only for
-- CPS Energy's plants in Bexar (1,875 MW); every other county scored zero, so the
-- factor acted as a 25% bonus for one county. Owners rarely file retirement dates
-- years ahead. Age catches 28 counties and 23,600 MW instead.
SELECT
    c.county_fips,
    'aging_thermal_mw' AS factor_key,
    CAST(ISNULL(SUM(CASE WHEN f.status_group = 'Operating'
                          AND f.operating_year IS NOT NULL
                          AND f.operating_year <= 1985
                          AND d.fuel_category IN ('Gas', 'Coal')
                         THEN f.nameplate_mw END), 0) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN fact.generator_capacity f ON f.county_fips = c.county_fips
LEFT JOIN dim.fuel d ON d.technology = f.technology
WHERE c.in_ercot = 1
GROUP BY c.county_fips

UNION ALL

-- Factor 9 (Phase 1, gas): active GAS projects in the ERCOT queue.
-- The real competition for a new gas plant: other gas projects seeking the same
-- interconnection capacity. Solar and battery requests are a different market.
SELECT
    c.county_fips,
    'gas_queue_mw' AS factor_key,
    CAST(ISNULL(SUM(CASE WHEN q.status = 'Active' AND q.fuel = 'GAS'
                         THEN q.capacity_mw END), 0) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN fact.queue_project q ON q.county_fips = c.county_fips
WHERE c.in_ercot = 1
GROUP BY c.county_fips

UNION ALL

-- Factor 10 (Phase 1, gas): capacity factor of existing GAS plants only, 2024.
-- How hard the county's gas fleet actually runs. High values mean gas plants
-- there are dispatched often - evidence of good grid access and competitive fuel.
-- Uses EIA-923 fuel code NG against EIA-860 gas capacity. Counties with no gas
-- fleet score 0: there is no evidence either way, which the caveat records.
SELECT
    c.county_fips,
    'gas_capacity_factor' AS factor_key,
    CAST(ISNULL(
        CASE WHEN cap.gas_mw > 0 AND gen.total_hours > 0
             THEN CASE WHEN gen.gas_mwh / (cap.gas_mw * gen.total_hours) > 1.0
                       THEN 1.0
                       ELSE gen.gas_mwh / (cap.gas_mw * gen.total_hours) END
        END, 0) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN (
    SELECT f.county_fips,
           SUM(CASE WHEN f.status_group = 'Operating' AND d.fuel_category = 'Gas'
                    THEN f.nameplate_mw END) AS gas_mw
    FROM fact.generator_capacity f
    JOIN dim.fuel d ON d.technology = f.technology
    GROUP BY f.county_fips
) cap ON cap.county_fips = c.county_fips
LEFT JOIN (
    SELECT g.county_fips,
           SUM(g.net_generation_mwh) AS gas_mwh,
           (SELECT SUM(hours_in_month) FROM dim.month
            WHERE month_key BETWEEN 202401 AND 202412) AS total_hours
    FROM fact.generation_monthly g
    WHERE g.month_key BETWEEN 202401 AND 202412
      AND g.fuel_type = 'NG'
    GROUP BY g.county_fips
) gen ON gen.county_fips = c.county_fips
WHERE c.in_ercot = 1

UNION ALL

-- Factor 11 (Phase 2, air): ozone nonattainment severity, 0 (Attainment) to 5 (Extreme).
-- The one air number that can be weighted. It is read from fact.county_attribute,
-- which holds the full air detail (offset ratio, credit price, market depth) as
-- filters and context. Loaded by sql/02_load/16_load_air.sql.
-- A county missing from the attribute table is treated as Attainment (0).
SELECT
    c.county_fips,
    'ozone_severity' AS factor_key,
    CAST(ISNULL(a.value_num, 0) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN fact.county_attribute a
       ON a.county_fips = c.county_fips
      AND a.attribute_key = 'ozone_classification'
WHERE c.in_ercot = 1
;
GO

-- Spot check: top 10 counties on each new gas factor.
SELECT TOP 10 c.county_name, f.raw_value AS aging_thermal_mw
FROM rpt.county_factor f JOIN dim.county c ON c.county_fips = f.county_fips
WHERE f.factor_key = 'aging_thermal_mw' ORDER BY f.raw_value DESC;

SELECT TOP 10 c.county_name, f.raw_value AS gas_queue_mw
FROM rpt.county_factor f JOIN dim.county c ON c.county_fips = f.county_fips
WHERE f.factor_key = 'gas_queue_mw' ORDER BY f.raw_value DESC;

SELECT TOP 10 c.county_name, f.raw_value AS gas_capacity_factor
FROM rpt.county_factor f JOIN dim.county c ON c.county_fips = f.county_fips
WHERE f.factor_key = 'gas_capacity_factor' ORDER BY f.raw_value DESC;
GO

-- Spot check (Phase 2): ERCOT counties by ozone severity. Expect 178 at 0, 1 at 3 (Bexar), 16 at 4 (Houston and DFW).
-- Not counted: El Paso (Marginal, WECC) and Liberty and Montgomery (Severe, but mostly MISO).
SELECT f.raw_value AS ozone_severity, COUNT(*) AS counties
FROM rpt.county_factor f
WHERE f.factor_key = 'ozone_severity'
GROUP BY f.raw_value
ORDER BY f.raw_value;
GO
