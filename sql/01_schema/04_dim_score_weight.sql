/*  04_dim_score_weight.sql
    The weights are DATA, not code.

    Note the primary key: (weight_version, factor_key). Weight, direction AND
    transform are all per-version. Two use cases can therefore share a factor
    and disagree about how much it matters, which direction is favourable, and
    how it should be scaled - with no schema change and no edit to the scoring
    view, which already partitions by weight_version.

    THE `transform` COLUMN (Stage 1b)
    Min-max normalisation assumes a roughly even spread. Several factors here
    are heavily right-skewed: a few large values, a long tail bunched near zero.
    Scaling those linearly hands almost every county a near identical score, so
    the factor stops discriminating and just adds a constant to everything.
      'linear' - raw value (correct for bounded ratios)
      'log'    - LOG(1 + value); compresses outliers, spreads the tail

    THE TWO WEIGHT VERSIONS
    'generation' - siting a new power plant. Land hungry, must be where the
                   resource is, tolerant of remoteness.
    'datacenter' - siting a large load. Needs a strong grid node, occupies a
                   fraction of the land, far less tolerant of remoteness.

    With only three factors these two rankings are similar. The real separation
    arrives with the Stage 2 and 3 factors - see the table at the bottom.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS dim.score_weight;
GO

CREATE TABLE dim.score_weight (
    weight_version  NVARCHAR(40) NOT NULL,
    factor_key      VARCHAR(50)  NOT NULL,
    weight          DECIMAL(6,4) NOT NULL,   -- weights within a version sum to 1.0
    direction       SMALLINT     NOT NULL,   -- +1 = higher is better, -1 = inverted
    transform       VARCHAR(10)  NOT NULL,   -- 'linear' or 'log'
    factor_label    NVARCHAR(80) NOT NULL,
    stage_added     SMALLINT     NOT NULL,
    CONSTRAINT pk_score_weight PRIMARY KEY (weight_version, factor_key),
    CONSTRAINT ck_transform CHECK (transform IN ('linear', 'log')),
    CONSTRAINT ck_direction CHECK (direction IN (1, -1))
);
GO

INSERT INTO dim.score_weight
    (weight_version, factor_key, weight, direction, transform, factor_label, stage_added)
VALUES
    -- ---------- GENERATION: siting a new power plant ----------
    -- Land hungry, resource driven, tolerant of remoteness.
    ('generation', 'installed_mw',     0.1500,  1, 'log',    'Existing generation capacity', 1),
    ('generation', 'retiring_mw',      0.2000,  1, 'log',    'Capacity retiring by 2030',    1),
    ('generation', 'pop_density',      0.1000, -1, 'log',    'Population density',           2),
    ('generation', 'capacity_factor',  0.1500,  1, 'linear', 'Realised capacity factor',     2),
    ('generation', 'generation_trend', 0.1000,  1, 'linear', 'Generation trend 2020-2024',   2),
    ('generation', 'queue_congestion', 0.2000, -1, 'log',    'Active queue capacity',        3),
    ('generation', 'queue_attrition',  0.1000, -1, 'linear', 'Queue attrition rate',         3),

    -- ---------- DATACENTER: siting a large load ----------
    -- Small footprint, so land friction barely matters. Needs a grid node that
    -- can already move hundreds of MW, and needs it without queueing behind
    -- 20 GW of solar. Congestion carries the heaviest single weight here.
    ('datacenter', 'installed_mw',     0.2000,  1, 'log',    'Existing generation capacity', 1),
    ('datacenter', 'retiring_mw',      0.2000,  1, 'log',    'Capacity retiring by 2030',    1),
    ('datacenter', 'pop_density',      0.0500, -1, 'log',    'Population density',           2),
    ('datacenter', 'capacity_factor',  0.1000,  1, 'linear', 'Realised capacity factor',     2),
    ('datacenter', 'generation_trend', 0.1000,  1, 'linear', 'Generation trend 2020-2024',   2),
    ('datacenter', 'queue_congestion', 0.2500, -1, 'log',    'Active queue capacity',        3),
    ('datacenter', 'queue_attrition',  0.1000, -1, 'linear', 'Queue attrition rate',         3);
GO

-- Sanity: weights within each version must sum to 1. Should return zero rows.
SELECT weight_version, SUM(weight) AS total_weight
FROM dim.score_weight
GROUP BY weight_version
HAVING ABS(SUM(weight) - 1.0) > 0.0001;
GO

/*  PLANNED FACTORS - where the two versions actually diverge
    ------------------------------------------------------------------------
    factor              stage  generation      datacenter
    ------------------------------------------------------------------------
    capacity_factor       2    high (+)        low
    generation_trend      2    medium (+)      low
    queue_congestion      3    high (-)        high (-)
    queue_attrition       3    medium (-)      medium (-)
    metro_proximity       -    low             HIGH (+)  fibre, staff, latency
    water_availability    -    low             HIGH (+)  cooling
    farm_size             -    HIGH (+)        low       parcel assembly
    ------------------------------------------------------------------------
    Until metro_proximity exists, the datacenter ranking inherits generation's
    bias toward empty West Texas counties. Documented, not hidden.
*/
