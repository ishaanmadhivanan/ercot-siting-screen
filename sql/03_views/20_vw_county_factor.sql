/*  20_vw_county_factor.sql
    Every scoring input, in TALL form: one row per county per factor.

    WHY TALL AND NOT WIDE: adding a factor is a single UNION ALL block plus one
    INSERT into dim.score_weight. Nothing downstream changes - not the
    normalisation, not rpt.county_score, not the Power BI model.

    Grain: county_fips + factor_key.
    Every county appears for every factor, even at zero. LEFT JOIN from
    dim.county is deliberate - a county with no generators must score 0, not
    vanish from the map.
*/

USE ErcotSiting;
GO

CREATE OR ALTER VIEW rpt.county_factor AS

-- Factor 1 (Stage 1): existing installed generation capacity.
-- Proxy for transmission presence. Where generation already sits, there is
-- already interconnection infrastructure and a studied point of connection.
SELECT
    c.county_fips,
    'installed_mw' AS factor_key,
    CAST(ISNULL(SUM(CASE WHEN f.status_group = 'Operating'
                         THEN f.nameplate_mw END), 0) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN fact.generator_capacity f ON f.county_fips = c.county_fips
GROUP BY c.county_fips

UNION ALL

-- Factor 2 (Stage 1): capacity with a planned retirement on or before 2030.
-- The non-obvious signal. A retiring plant frees up interconnection rights and
-- an existing point of connection - often the fastest path to a large grid
-- connection anywhere in the state.
SELECT
    c.county_fips,
    'retiring_mw' AS factor_key,
    CAST(ISNULL(SUM(CASE WHEN f.planned_retire_year IS NOT NULL
                          AND f.planned_retire_year <= 2030
                         THEN f.nameplate_mw END), 0) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN fact.generator_capacity f ON f.county_fips = c.county_fips
GROUP BY c.county_fips

UNION ALL

-- Factor 3 (Stage 1b): population density, people per square mile.
-- Land friction proxy. Inverted in dim.score_weight (direction = -1), so an
-- empty county scores well. Weak proxy: it ignores parcel fragmentation and
-- existing land use, which are often what actually blocks a site.
SELECT
    c.county_fips,
    'pop_density' AS factor_key,
    CAST(ISNULL(c.population / NULLIF(c.land_area_sqmi, 0), 0) AS DECIMAL(18,4)) AS raw_value
FROM dim.county c

UNION ALL

-- Factor 4 (Stage 2): realised capacity factor over the most recent 12 months.
--   actual MWh generated / (installed MW x hours in those months)
-- This is why dim.month exists. Hours per month is not constant, and using a
-- flat 730 would inflate February's contribution by about 4% and understate
-- the 31-day months. Over a year those errors do not cancel evenly.
--
-- Interpretation: how hard the plants in this county actually run. High values
-- indicate good wind/solar resource or baseload plant. It is a resource
-- quality proxy, not a measure of grid headroom.
--
-- Capped at 1.0. Values above that are real in the data but always artefacts:
-- generation reported against a plant whose capacity is recorded under a
-- different plant code, or a generator that came online mid-period.
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
           -- SUM(DISTINCT ...) would be wrong here; hours must be counted once
           -- per month, not once per plant-month, so the months are collapsed first.
           (SELECT SUM(hours_in_month) FROM dim.month
            WHERE month_key BETWEEN 202401 AND 202412) AS total_hours
    FROM fact.generation_monthly g
    WHERE g.month_key BETWEEN 202401 AND 202412
    GROUP BY g.county_fips
) gen ON gen.county_fips = c.county_fips

UNION ALL

-- Factor 5 (Stage 2): generation trend, 2020 vs 2024.
--
-- THREE FORMULAS WERE CONSIDERED. The first two fail on this data:
--
--   percent change (new - old) / old
--       Divides by zero for the ~30 counties with no generation in 2020, and a
--       county going from 10 MWh to 1,000 MWh posts 9,900% growth, which would
--       dominate the min-max normalisation on its own.
--
--   symmetric rate (new - old) / (new + old)
--       Bounded to [-1, +1] and handles zeros, but every county starting from
--       zero lands on exactly 1.0 regardless of how much it added. 30 of 254
--       counties tied at the ceiling - the factor could not discriminate among
--       precisely the counties it should be most informative about. It also
--       broke its own bound where a county reported negative net generation
--       (batteries and idle plants consume more than they produce), which
--       shrinks the denominator faster than the numerator.
--
--   smoothed log ratio  LOG((new + k) / (old + k))     <- used here
--       k = 10,000 MWh, roughly 1 MW running continuously for a year. Growth
--       from a near-zero base is damped rather than infinite, magnitude still
--       separates counties, and zeros are handled without a special case.
--
-- Negative annual generation is floored at zero first: a county that was a net
-- consumer of electricity in a year has no meaningful growth rate, and letting
-- the negative through corrupts the ratio.
--
-- NOTE the transform for this factor in dim.score_weight is 'linear', not
-- 'log' - the log is already applied here, inside the factor.
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

-- STAGE 3: queue congestion, queue withdrawal rate (needs fact.queue_project)
;
GO

-- Spot check: the trend factor should now spread, not pile up at a ceiling.
SELECT TOP 10 c.county_name, f.raw_value
FROM rpt.county_factor f
JOIN dim.county c ON c.county_fips = f.county_fips
WHERE f.factor_key = 'generation_trend'
ORDER BY f.raw_value DESC;

SELECT COUNT(*) AS counties_sharing_the_max_value
FROM rpt.county_factor
WHERE factor_key = 'generation_trend'
  AND raw_value = (SELECT MAX(raw_value) FROM rpt.county_factor
                   WHERE factor_key = 'generation_trend');
GO
