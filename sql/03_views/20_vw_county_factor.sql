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

UNION ALL

-- Factor 6 (Stage 3): active interconnection queue capacity in the county.
--
-- DIRECTION IS NEGATIVE, AND THAT IS THE THESIS OF THIS MODEL.
-- A crowded queue is genuinely ambiguous evidence. It marks a county that many
-- developers have independently judged attractive, which argues for treating it
-- as a positive. But that judgement is already public and already priced in -
-- it is old news. A new entrant arriving into 20 GW of competing requests
-- inherits longer studies, contested interconnection capacity, and a weaker
-- negotiating position on land.
--
-- The other six factors already capture whether a county is attractive. This
-- one carries the cost of everyone else having noticed first. The model earns
-- its keep by surfacing counties with strong fundamentals and a thin queue.
SELECT
    c.county_fips,
    'queue_congestion' AS factor_key,
    CAST(ISNULL(SUM(CASE WHEN q.status = 'Active' THEN q.capacity_mw END), 0)
         AS DECIMAL(18,4)) AS raw_value
FROM dim.county c
LEFT JOIN fact.queue_project q ON q.county_fips = c.county_fips
GROUP BY c.county_fips

UNION ALL

-- Factor 7 (Stage 3): queue attrition, shrunk toward the statewide rate.
--
-- The naive rate is  inactive_mw / (active_mw + inactive_mw).
-- It fails the same way the first generation_trend attempt did: only 85 of 254
-- counties have any inactive projects at all, so 169 counties would post a
-- perfect 0% attrition. That is not a clean track record, it is the absence of
-- a track record, and it would hand a top score to any county with two active
-- projects and no history.
--
-- This applies shrinkage instead. Each county's rate is blended toward the
-- statewide rate (~7.7%) in inverse proportion to its volume:
--
--     (inactive_mw + k * statewide_rate) / (total_mw + k)
--
-- k = 500 MW acts as a pseudo-observation. A county with 20 GW of queue barely
-- moves; a county with 50 MW sits almost exactly on the statewide rate until it
-- accumulates enough history to argue otherwise. Standard empirical-Bayes
-- treatment for small-sample rates.
--
-- CAVEAT: Inactive Projects is a cumulative list while Active is a current
-- snapshot, so this is not a true historical failure rate. It is the ratio of
-- accumulated withdrawals to present activity, which is a proxy for the same
-- thing and should be read as one.
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

;
GO

-- Spot check: the counties with strong fundamentals but a thin queue are the
-- ones this model exists to find. Compare congestion against installed capacity.
SELECT TOP 15
    c.county_name,
    CAST(MAX(CASE WHEN f.factor_key = 'installed_mw'     THEN f.raw_value END) AS DECIMAL(12,0)) AS installed_mw,
    CAST(MAX(CASE WHEN f.factor_key = 'queue_congestion' THEN f.raw_value END) AS DECIMAL(12,0)) AS queue_mw,
    CAST(MAX(CASE WHEN f.factor_key = 'queue_attrition'  THEN f.raw_value END) AS DECIMAL(6,4))  AS attrition
FROM rpt.county_factor f
JOIN dim.county c ON c.county_fips = f.county_fips
GROUP BY c.county_name
HAVING MAX(CASE WHEN f.factor_key = 'installed_mw' THEN f.raw_value END) > 500
ORDER BY MAX(CASE WHEN f.factor_key = 'queue_congestion' THEN f.raw_value END) ASC;
GO
