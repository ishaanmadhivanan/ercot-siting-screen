/*  21_vw_county_score.sql
    Min-max normalises every factor to 0-100 within Texas, applies direction,
    then applies the weights from dim.score_weight.

    This view NEVER needs editing when a factor is added. It reads whatever
    rpt.county_factor emits and whatever dim.score_weight contains. That is the
    entire point of the tall design.

    Power BI connects here and to rpt.county_factor_detail. It does not touch
    dim/fact directly.
*/

USE ErcotSiting;
GO

CREATE OR ALTER VIEW rpt.county_score AS
WITH bounds AS (
    -- Window functions give us the min/max per factor without a self-join.
    SELECT
        county_fips,
        factor_key,
        raw_value,
        MIN(raw_value) OVER (PARTITION BY factor_key) AS min_value,
        MAX(raw_value) OVER (PARTITION BY factor_key) AS max_value
    FROM rpt.county_factor
),
normalised AS (
    SELECT
        b.county_fips,
        b.factor_key,
        b.raw_value,
        -- Guard against a degenerate factor where every county is identical.
        CASE WHEN b.max_value = b.min_value THEN 50.0
             ELSE 100.0 * (b.raw_value - b.min_value) / NULLIF(b.max_value - b.min_value, 0)
        END AS scaled_value
    FROM bounds b
),
directed AS (
    SELECT
        n.county_fips,
        n.factor_key,
        n.raw_value,
        -- direction = -1 flips the scale, so "less is better" factors
        -- (population density, land cost) still score high when favourable.
        CASE WHEN w.direction = -1 THEN 100.0 - n.scaled_value
             ELSE n.scaled_value END AS factor_score,
        w.weight,
        w.weight_version,
        w.factor_label
    FROM normalised n
    JOIN dim.score_weight w ON w.factor_key = n.factor_key
)
SELECT
    d.weight_version,
    d.county_fips,
    c.county_name,
    CAST(SUM(d.factor_score * d.weight) AS DECIMAL(9,4)) AS site_score,
    RANK() OVER (PARTITION BY d.weight_version
                 ORDER BY SUM(d.factor_score * d.weight) DESC) AS county_rank,
    COUNT(*) AS factors_applied
FROM directed d
JOIN dim.county c ON c.county_fips = d.county_fips
GROUP BY d.weight_version, d.county_fips, c.county_name;
GO


/*  Companion view: the per-factor breakdown behind each county's score.
    This is what the Power BI drill-through page binds to in Stage 4 - it lets
    a reader see WHY a county ranked where it did, which is the difference
    between a dashboard and an analysis.
*/
CREATE OR ALTER VIEW rpt.county_factor_detail AS
WITH bounds AS (
    SELECT
        county_fips, factor_key, raw_value,
        MIN(raw_value) OVER (PARTITION BY factor_key) AS min_value,
        MAX(raw_value) OVER (PARTITION BY factor_key) AS max_value
    FROM rpt.county_factor
)
SELECT
    w.weight_version,
    b.county_fips,
    c.county_name,
    b.factor_key,
    w.factor_label,
    b.raw_value,
    CASE WHEN w.direction = -1
         THEN 100.0 - (CASE WHEN b.max_value = b.min_value THEN 50.0
                            ELSE 100.0 * (b.raw_value - b.min_value)
                                 / NULLIF(b.max_value - b.min_value, 0) END)
         ELSE      (CASE WHEN b.max_value = b.min_value THEN 50.0
                            ELSE 100.0 * (b.raw_value - b.min_value)
                                 / NULLIF(b.max_value - b.min_value, 0) END)
    END AS factor_score,
    w.weight,
    w.stage_added
FROM bounds b
JOIN dim.score_weight w ON w.factor_key = b.factor_key
JOIN dim.county c       ON c.county_fips = b.county_fips;
GO


-- Smoke test: top 15 counties under the baseline weighting.
SELECT TOP 15 county_rank, county_name, site_score
FROM rpt.county_score
WHERE weight_version = 'baseline'
ORDER BY county_rank;
GO
