/*  04_dim_score_weight.sql
    The weights are DATA, not code.

    This is the single most important design decision in the repo. Because the
    weights live in a table, the Power BI what-if sliders in Stage 4 bind to
    this instead of requiring the scoring logic to be rewritten. Adding a new
    factor = one INSERT here plus one UNION ALL block in rpt.county_factor.

    weight_version lets you keep several named scenarios side by side and show
    how the ranking reshuffles - that is the sensitivity analysis in docs/.
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
    factor_label    NVARCHAR(80) NOT NULL,
    stage_added     SMALLINT     NOT NULL,
    CONSTRAINT pk_score_weight PRIMARY KEY (weight_version, factor_key)
);
GO

INSERT INTO dim.score_weight (weight_version, factor_key, weight, direction, factor_label, stage_added)
VALUES
    ('baseline', 'installed_mw',  0.4000,  1, 'Existing generation capacity', 1),
    ('baseline', 'retiring_mw',   0.4000,  1, 'Capacity retiring by 2030',    1),
    -- direction -1: a LOW population density is favourable, because land is
    -- cheaper to assemble and there are fewer neighbours to object.
    ('baseline', 'pop_density',   0.2000, -1, 'Population density',           2);
GO

-- Sanity: weights in a version must sum to 1. Should return zero rows.
SELECT weight_version, SUM(weight) AS total_weight
FROM dim.score_weight
GROUP BY weight_version
HAVING ABS(SUM(weight) - 1.0) > 0.0001;
GO
