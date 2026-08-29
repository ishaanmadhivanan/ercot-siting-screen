/*  04_dim_score_weight.sql
    The weights are DATA, not code.

    Because the weights live in a table, the Power BI what-if sliders in Stage 4
    bind to this instead of requiring the scoring logic to be rewritten. Adding
    a factor = one INSERT here plus one UNION ALL block in rpt.county_factor.

    STAGE 1b ADDITION - the `transform` column.
    Min-max normalisation assumes a roughly even spread. Several of these
    factors are heavily right-skewed: a handful of large values and a long tail
    bunched near zero. Scaling those linearly hands almost every county a near
    identical score, which means the factor stops discriminating between
    counties and just adds a constant to everything.

    Declaring the transform per factor keeps that decision visible and
    documented rather than buried in the scoring view.
      'linear' - use the raw value (default; correct for bounded ratios)
      'log'    - use LOG(1 + value); compresses outliers, spreads the tail
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS dim.score_weight;
GO

CREATE TABLE dim.score_weight (
    weight_version  NVARCHAR(40) NOT NULL,
    factor_key      VARCHAR(50)  NOT NULL,
    weight          DECIMAL(6,4) NOT NULL,   -- weights within a version should sum to 1.0
    direction       SMALLINT     NOT NULL,   -- +1 = higher raw value is better, -1 = inverted
    transform       VARCHAR(10)  NOT NULL,   -- 'linear' or 'log'
    factor_label    NVARCHAR(80) NOT NULL,
    stage_added     SMALLINT     NOT NULL,
    CONSTRAINT pk_score_weight PRIMARY KEY (weight_version, factor_key),
    CONSTRAINT ck_transform CHECK (transform IN ('linear', 'log'))
);
GO

INSERT INTO dim.score_weight
    (weight_version, factor_key, weight, direction, transform, factor_label, stage_added)
VALUES
    ('generation', 'installed_mw', 0.4000,  1, 'log', 'Existing generation capacity', 1),
    ('generation', 'retiring_mw',  0.4000,  1, 'log', 'Capacity retiring by 2030',    1),
    ('generation', 'pop_density',  0.2000, -1, 'log', 'Population density',           2),
    ('datacenter', 'installed_mw', 0.5500,  1, 'log', 'Existing generation capacity', 1),
    ('datacenter', 'retiring_mw',  0.3500,  1, 'log', 'Capacity retiring by 2030',    1),
    ('datacenter', 'pop_density',  0.1000, -1, 'log', 'Population density',           2);GO

-- Sanity: weights in a version must sum to 1. Should return zero rows.
SELECT weight_version, SUM(weight) AS total_weight
FROM dim.score_weight
GROUP BY weight_version
HAVING ABS(SUM(weight) - 1.0) > 0.0001;
GO
