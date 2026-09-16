/*  21_vw_county_score.sql
    Applies the per-factor transform, min-max normalises each factor to 0-100
    across in-scope counties, applies direction, then applies the weights from
    dim.score_weight.

    This view needs no editing when a FACTOR is added - it reads whatever
    rpt.county_factor emits and whatever dim.score_weight contains.

    It has been edited twice, both times to change the METHOD rather than the
    factor list:
      Stage 1b - support for the per-factor `transform` column
      Stage 3  - scaled score and percentile (see the comment below)

    Power BI connects here and to rpt.county_factor_detail. It does not touch
    dim/fact directly.
*/

USE ErcotSiting;
GO

CREATE OR ALTER VIEW rpt.county_score AS
WITH transformed AS (
    -- LOG(1 + x) rather than LOG(x): raw values legitimately hit zero
    -- (a county with no generation), and LOG(0) is undefined.
    SELECT
        f.county_fips,
        f.factor_key,
        f.raw_value,
        w.weight,
        w.weight_version,
        w.direction,
        CASE WHEN w.transform = 'log' THEN LOG(1.0 + f.raw_value)
             ELSE f.raw_value END AS scaled_input
    FROM rpt.county_factor f
    JOIN dim.score_weight w ON w.factor_key = f.factor_key
),
bounds AS (
    SELECT
        t.*,
        MIN(t.scaled_input) OVER (PARTITION BY t.weight_version, t.factor_key) AS min_value,
        MAX(t.scaled_input) OVER (PARTITION BY t.weight_version, t.factor_key) AS max_value
    FROM transformed t
),
normalised AS (
    SELECT
        b.weight_version,
        b.county_fips,
        b.factor_key,
        b.weight,
        b.direction,
        -- Guard against a degenerate factor where every county is identical.
        CASE WHEN b.max_value = b.min_value THEN 50.0
             ELSE 100.0 * (b.scaled_input - b.min_value)
                  / NULLIF(b.max_value - b.min_value, 0)
        END AS scaled_value
    FROM bounds b
),
directed AS (
    SELECT
        n.weight_version,
        n.county_fips,
        n.weight,
        -- direction = -1 flips the scale, so "less is better" factors
        -- still score high when favourable.
        CASE WHEN n.direction = -1 THEN 100.0 - n.scaled_value
             ELSE n.scaled_value END AS factor_score
    FROM normalised n
),
composite AS (
    SELECT
        d.weight_version,
        d.county_fips,
        SUM(d.factor_score * d.weight) AS site_score,
        COUNT(*)                       AS factors_applied
    FROM directed d
    GROUP BY d.weight_version, d.county_fips
)
SELECT
    k.weight_version,
    k.county_fips,
    c.county_name,

    -- The interpretable number: a weighted average of factor scores that are
    -- each on a 0-100 scale. Comparable across weight versions.
    CAST(k.site_score AS DECIMAL(9,4)) AS site_score,

    /*  WHY A SCALED SCORE EXISTS
        Averaging k roughly independent variables shrinks the spread of the
        average by about sqrt(k). With seven factors, a county strong on three
        and weak on four lands near the middle - and nearly every county does.
        The top ten spanned only 57 to 49 before this was added, and the Power
        BI map rendered as a single flat colour.

        This is arithmetic, not redundancy. A correlation check across all seven
        factors found nothing above 0.51 (installed capacity vs population
        density, which is expected - people live where power is). The factors
        are not measuring the same thing; a weighted average simply cannot span
        0-100 the way its inputs do.

        So the composite is stretched back across its observed range. Rankings
        are untouched: this is a relabelling, not a re-scoring. Read it as
        "relative to other ERCOT counties", never as an absolute measure.
    */
    CAST(100.0 * (k.site_score - MIN(k.site_score) OVER (PARTITION BY k.weight_version))
         / NULLIF(MAX(k.site_score) OVER (PARTITION BY k.weight_version)
                  - MIN(k.site_score) OVER (PARTITION BY k.weight_version), 0)
         AS DECIMAL(9,4)) AS site_score_scaled,

    -- Uniform by construction, so immune to the compression above. This is the
    -- right field for map colour: a choropleth needs an evenly spread variable.
    CAST(100.0 * PERCENT_RANK() OVER (PARTITION BY k.weight_version
                                      ORDER BY k.site_score) AS DECIMAL(9,2)) AS county_percentile,

    RANK() OVER (PARTITION BY k.weight_version ORDER BY k.site_score DESC) AS county_rank,
    k.factors_applied
FROM composite k
JOIN dim.county c ON c.county_fips = k.county_fips;
GO


/*  Companion view: the per-factor breakdown behind each county's score.
    Binds to the Power BI drill-through page - it shows WHY a county ranked
    where it did, which is the difference between a dashboard and an analysis.
    Exposes the raw value, the transform applied, and the resulting factor
    score, so the effect of each step is inspectable rather than hidden.
*/
CREATE OR ALTER VIEW rpt.county_factor_detail AS
WITH transformed AS (
    SELECT
        f.county_fips,
        f.factor_key,
        f.raw_value,
        w.weight,
        w.weight_version,
        w.direction,
        w.transform,
        w.factor_label,
        w.stage_added,
        CASE WHEN w.transform = 'log' THEN LOG(1.0 + f.raw_value)
             ELSE f.raw_value END AS scaled_input
    FROM rpt.county_factor f
    JOIN dim.score_weight w ON w.factor_key = f.factor_key
),
bounds AS (
    SELECT
        t.*,
        MIN(t.scaled_input) OVER (PARTITION BY t.weight_version, t.factor_key) AS min_value,
        MAX(t.scaled_input) OVER (PARTITION BY t.weight_version, t.factor_key) AS max_value
    FROM transformed t
)
SELECT
    b.weight_version,
    b.county_fips,
    c.county_name,
    b.factor_key,
    b.factor_label,
    b.raw_value,
    b.transform,
    CAST(
        CASE WHEN b.direction = -1
             THEN 100.0 - (CASE WHEN b.max_value = b.min_value THEN 50.0
                                ELSE 100.0 * (b.scaled_input - b.min_value)
                                     / NULLIF(b.max_value - b.min_value, 0) END)
             ELSE          (CASE WHEN b.max_value = b.min_value THEN 50.0
                                ELSE 100.0 * (b.scaled_input - b.min_value)
                                     / NULLIF(b.max_value - b.min_value, 0) END)
        END AS DECIMAL(9,4)) AS factor_score,
    b.weight,
    -- What this factor actually contributed to the county's composite score.
    -- Sums to site_score across all factors for a county, so a reader can see
    -- exactly where a ranking came from.
    CAST(
        CASE WHEN b.direction = -1
             THEN 100.0 - (CASE WHEN b.max_value = b.min_value THEN 50.0
                                ELSE 100.0 * (b.scaled_input - b.min_value)
                                     / NULLIF(b.max_value - b.min_value, 0) END)
             ELSE          (CASE WHEN b.max_value = b.min_value THEN 50.0
                                ELSE 100.0 * (b.scaled_input - b.min_value)
                                     / NULLIF(b.max_value - b.min_value, 0) END)
        END * b.weight AS DECIMAL(9,4)) AS weighted_contribution,
    b.stage_added
FROM bounds b
JOIN dim.county c ON c.county_fips = b.county_fips;
GO


-- Smoke test: raw score stays compressed, scaled should span 0-100.
SELECT TOP 10 county_rank, county_name, site_score, site_score_scaled, county_percentile
FROM rpt.county_score
WHERE weight_version = 'generation'
ORDER BY county_rank;

SELECT
    weight_version,
    CAST(MIN(site_score) AS DECIMAL(9,2))        AS raw_min,
    CAST(MAX(site_score) AS DECIMAL(9,2))        AS raw_max,
    CAST(MIN(site_score_scaled) AS DECIMAL(9,2)) AS scaled_min,
    CAST(MAX(site_score_scaled) AS DECIMAL(9,2)) AS scaled_max,
    COUNT(*) AS counties
FROM rpt.county_score
GROUP BY weight_version;
GO
