/*  21_vw_county_score.sql
    Applies the per-factor transform, min-max normalises to 0-100 within Texas,
    applies direction, then applies the weights from dim.score_weight.

    This view still needs no editing when a FACTOR is added - it reads whatever
    rpt.county_factor emits and whatever dim.score_weight contains.

    It was edited once, in Stage 1b, to support the `transform` column. That is
    a change to the METHOD, not to the factor list, and it is the kind of change
    that should require touching the scoring logic.

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
        -- Guard against a degenerate factor where every county is identical.
        CASE WHEN b.max_value = b.min_value THEN 50.0
             ELSE 100.0 * (b.scaled_input - b.min_value)
                  / NULLIF(b.max_value - b.min_value, 0)
        END AS scaled_value,
        b.direction
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
    Binds to the Power BI drill-through page in Stage 4 - it shows WHY a county
    ranked where it did, which is the difference between a dashboard and an
    analysis. Exposes both the raw value and the transformed score so the
    effect of the transform is inspectable rather than hidden.
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
    b.stage_added
FROM bounds b
JOIN dim.county c ON c.county_fips = b.county_fips;
GO


-- Smoke test: top 15 counties, and the spread of scores.
SELECT TOP 15 county_rank, county_name, site_score, factors_applied
FROM rpt.county_score
WHERE weight_version = 'baseline'
ORDER BY county_rank;

SELECT
    CAST(MIN(site_score) AS DECIMAL(9,2)) AS min_score,
    CAST(AVG(site_score) AS DECIMAL(9,2)) AS avg_score,
    CAST(MAX(site_score) AS DECIMAL(9,2)) AS max_score
FROM rpt.county_score WHERE weight_version = 'baseline';
GO
