/*  08_fact_county_attribute.sql  --  Phase 1 foundation

    The home for county data that is FILTERED ON rather than weighted:
    ozone nonattainment status, offset cost, share of land outside cities,
    and similar.

    Why a separate table: rpt.county_factor feeds the weighted score. A flag
    like "Serious ozone nonattainment" is not a number to average - it is a
    deal-breaker a user either applies or ignores. Keeping flags out of the
    scoring path stops them being accidentally weighted.

    Shape: tall, one row per county per attribute, same as the factor view.
      value_num  - for numeric attributes (e.g. offset cost in dollars)
      value_text - for categorical ones (e.g. 'Serious')
    Every attribute_key must have a row in dim.metric with metric_type
    'flag' or 'context', so it is documented like everything else.

    Empty for now. Phase 2 (air permitting) is the first to fill it.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS fact.county_attribute;
GO

CREATE TABLE fact.county_attribute (
    county_fips    CHAR(5)        NOT NULL,
    attribute_key  VARCHAR(50)    NOT NULL,
    value_num      DECIMAL(18,4)  NULL,
    value_text     NVARCHAR(100)  NULL,
    CONSTRAINT pk_county_attribute PRIMARY KEY (county_fips, attribute_key),
    CONSTRAINT fk_attr_county FOREIGN KEY (county_fips) REFERENCES dim.county (county_fips),
    CONSTRAINT ck_attr_has_value CHECK (value_num IS NOT NULL OR value_text IS NOT NULL)
);
GO

SELECT COUNT(*) AS attribute_rows FROM fact.county_attribute;   -- expect 0
GO
