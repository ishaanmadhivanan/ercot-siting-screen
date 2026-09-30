/*  22_vw_county_factor_score.sql  --  Phase 3

    Every factor on its own 0-100 scale, for every ERCOT county, with NO
    weights applied. This is the view the Power BI rebuild (Phase 5) uses:
    the user picks which factors to keep and how much each matters, and the
    weighted sum is done in DAX.

    How each factor is scaled (settings come from dim.metric, not presets):
      1. transform   - score_transform: 'log' = LOG(1 + x), else raw
      2. min-max     - 0 = worst ERCOT county, 100 = best, on that factor alone
      3. direction   - better_direction 'lower' flips it, so 100 is always
                       the favourable end
    'preset' factors (queue_congestion) are left unflipped: 100 = most MW in
    the queue. Whether that is good depends on the use case, so the report
    decides.

    rpt.county_score (21) still works for the fixed presets; this view is
    independent of dim.score_weight, so factors without a preset weight
    (ozone_severity, the pipeline factors) are included.

    Grain: county_fips + factor_key.
*/

USE ErcotSiting;
GO

CREATE OR ALTER VIEW rpt.county_factor_score AS
WITH transformed AS (
    SELECT
        f.county_fips,
        f.factor_key,
        f.raw_value,
        m.label,
        m.category,
        m.unit,
        m.better_direction,
        m.score_transform,
        CASE WHEN m.score_transform = 'log' THEN LOG(1.0 + f.raw_value)
             ELSE f.raw_value END AS scaled_input
    FROM rpt.county_factor f
    JOIN dim.metric m ON m.metric_key = f.factor_key
    WHERE m.metric_type = 'score'
),
bounds AS (
    SELECT
        t.*,
        MIN(t.scaled_input) OVER (PARTITION BY t.factor_key) AS min_value,
        MAX(t.scaled_input) OVER (PARTITION BY t.factor_key) AS max_value
    FROM transformed t
),
normalised AS (
    SELECT
        b.*,
        CASE WHEN b.max_value = b.min_value THEN 50.0
             ELSE 100.0 * (b.scaled_input - b.min_value) / (b.max_value - b.min_value)
        END AS scaled_value
    FROM bounds b
)
SELECT
    n.county_fips,
    c.county_name,
    n.factor_key,
    n.label            AS factor_label,
    n.category,
    n.unit,
    n.raw_value,
    n.better_direction,
    n.score_transform,
    CAST(CASE WHEN n.better_direction = 'lower' THEN 100.0 - n.scaled_value
              ELSE n.scaled_value END AS DECIMAL(9,4)) AS factor_score
FROM normalised n
JOIN dim.county c ON c.county_fips = n.county_fips;
GO

-- Check 1: one row per ERCOT county per score factor, each spanning 0-100.
-- Expect 195 counties on every factor, min 0 and max 100 (retiring_mw may
-- look lopsided: only Bexar is nonzero).
SELECT factor_key, category, better_direction, score_transform,
       COUNT(*)                            AS counties,
       CAST(MIN(factor_score) AS DECIMAL(6,1)) AS min_score,
       CAST(AVG(factor_score) AS DECIMAL(6,1)) AS avg_score,
       CAST(MAX(factor_score) AS DECIMAL(6,1)) AS max_score
FROM rpt.county_factor_score
GROUP BY factor_key, category, better_direction, score_transform
ORDER BY category, factor_key;

-- Check 2: one county across every factor, as the report's drill-through will show it.
SELECT factor_label, raw_value, factor_score
FROM rpt.county_factor_score
WHERE county_name = 'Harris'
ORDER BY category, factor_label;
GO
