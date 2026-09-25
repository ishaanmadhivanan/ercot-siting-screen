/*  04_dim_score_weight.sql
    The weights are DATA, not code.

    Note the primary key: (weight_version, factor_key). Weight, direction AND
    transform are all per-version. Two use cases can therefore share a factor
    and disagree about how much it matters, WHICH DIRECTION IS FAVOURABLE, and
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
    'generation' - siting a new power plant. Land hungry, resource driven,
                   tolerant of remoteness.
    'datacenter' - siting a large load. Small footprint, needs a grid node that
                   can already move hundreds of MW.
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
    -- Land hungry: a 200 MW solar farm needs roughly 1,500 acres, so land
    -- friction matters and remoteness is a feature rather than a cost.
    -- Resource quality drives project economics, hence real weight on
    -- realised capacity factor.
    ('generation', 'installed_mw',     0.1500,  1, 'log',    'Existing generation capacity', 1),
    ('generation', 'retiring_mw',      0.2000,  1, 'log',    'Capacity retiring by 2030',    1),
    ('generation', 'pop_density',      0.1000, -1, 'log',    'Population density',           2),
    ('generation', 'capacity_factor',  0.1500,  1, 'linear', 'Realised capacity factor',     2),
    ('generation', 'generation_trend', 0.1000,  1, 'linear', 'Generation trend 2020-2024',   2),

    /*  QUEUE CONGESTION IS NEGATIVE FOR GENERATION.

        A crowded queue is ambiguous evidence. It marks a county that many
        developers have independently judged attractive - but that judgement is
        already public and already priced in. A new entrant arriving into 20 GW
        of competing requests inherits longer studies, contested interconnection
        capacity, and a weaker negotiating position on land.

        The other six factors already capture whether a county is attractive.
        This one carries the cost of everyone else having noticed first. The
        model earns its keep by surfacing counties with strong fundamentals and
        a thin queue.
    */
    ('generation', 'queue_congestion', 0.2000, -1, 'log',    'Active queue capacity',        3),
    ('generation', 'queue_attrition',  0.1000, -1, 'linear', 'Queue attrition rate',         3),

    -- ---------- DATACENTER: siting a large load ----------
    -- A hyperscale campus occupies tens of acres, not thousands, so land
    -- friction is nearly irrelevant. What matters is a grid node that can
    -- already move hundreds of MW. Capacity factor is downweighted: how hard
    -- the local plants run says little about whether the grid can serve a
    -- new load.
    ('datacenter', 'installed_mw',     0.2000,  1, 'log',    'Existing generation capacity', 1),
    ('datacenter', 'retiring_mw',      0.2000,  1, 'log',    'Capacity retiring by 2030',    1),
    ('datacenter', 'pop_density',      0.0500, -1, 'log',    'Population density',           2),
    ('datacenter', 'capacity_factor',  0.1000,  1, 'linear', 'Realised capacity factor',     2),
    ('datacenter', 'generation_trend', 0.1000,  1, 'linear', 'Generation trend 2020-2024',   2),

    /*  QUEUE CONGESTION IS POSITIVE FOR DATACENTER.
        SAME FACTOR, OPPOSITE SIGN. THIS IS THE ONE THAT REVERSES.

        In ERCOT, generation and large load interconnect through SEPARATE
        processes. A data center is a load; the queue measured here is
        generation. So a crowded generation queue is not competition for a data
        center at all - it is evidence that supply is arriving at that node,
        and that the local transmission system is being studied and reinforced
        for it.

        This is the case that justifies the dual-version design existing. Every
        other factor merely gets reweighted between the two use cases; this one
        genuinely flips, which is why the two rankings now diverge rather than
        just reorder.

        WHAT THIS FACTOR IS NOT: the real competition measure for a data centre
        is ERCOT's LARGE LOAD queue, tracked separately and not published in the
        GIS Report. Until that is sourced, this model has no measure of
        load-side competition at all. Stated, not hidden.
    */
    ('datacenter', 'queue_congestion', 0.2500,  1, 'log',    'Active queue capacity',        3),
    ('datacenter', 'queue_attrition',  0.1000, -1, 'linear', 'Queue attrition rate',         3);
GO

-- Sanity: weights within each version must sum to 1. Should return zero rows.
SELECT weight_version, SUM(weight) AS total_weight
FROM dim.score_weight
GROUP BY weight_version
HAVING ABS(SUM(weight) - 1.0) > 0.0001;
GO

/*  The weights table as a READER should see it: each factor's share out of 100,
    which way is favourable, and which build stage introduced it.

    This is the query behind the "what is this model weighing?" question. Power
    BI binds a table visual straight to dim.score_weight so the weighting is
    visible in the report rather than buried in SQL.
*/
SELECT
    weight_version,
    factor_label,
    CAST(weight * 100 AS DECIMAL(5,1)) AS weight_out_of_100,
    CASE WHEN direction = 1 THEN 'higher is better'
         ELSE 'lower is better' END    AS direction,
    transform,
    stage_added
FROM dim.score_weight
ORDER BY weight_version, weight DESC;
GO
