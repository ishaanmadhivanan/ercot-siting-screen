/*  20_vw_county_factor.sql
    Every scoring input, in TALL form: one row per county per factor.

    WHY TALL AND NOT WIDE: adding a factor in Stage 2 or 3 becomes a single
    UNION ALL block plus one INSERT into dim.score_weight. Nothing downstream
    changes - not the normalisation, not the scoring view, not the Power BI
    model. This is what makes the weekend version scale into the three-week
    version without a rewrite.

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

-- STAGE 1b: population density (needs Census load into dim.county)
-- STAGE 2:  county capacity factor, generation trend (needs fact.generation_monthly)
-- STAGE 3:  queue congestion, queue withdrawal rate (needs fact.queue_project)
;
GO
