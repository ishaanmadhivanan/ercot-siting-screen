/*  03_fact_generator_capacity.sql
    Grain: one row per generator (plant_code + generator_id) per EIA-860 vintage.
    Sourced from EIA-860 Schedule 3_1, joined to Schedule 2 for county/lat/lon.

    NOTE ON GRAIN: this is the ONLY table stored below county level. It exists at
    generator grain because that is how EIA publishes it and because Power BI's
    map page wants lat/lon. All scoring aggregates to county in the rpt views.
    Do not add county-level measures here.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS fact.generator_capacity;
GO

CREATE TABLE fact.generator_capacity (
    generator_sk        INT IDENTITY(1,1) PRIMARY KEY,
    data_vintage_year   SMALLINT      NOT NULL,   -- which EIA-860 release this came from
    plant_code          INT           NOT NULL,
    generator_id        NVARCHAR(20)  NOT NULL,
    plant_name          NVARCHAR(120) NULL,
    county_fips         CHAR(5)       NOT NULL,
    technology          NVARCHAR(120) NULL,
    status_code         NVARCHAR(10)  NULL,       -- OP, SB, RE, etc.
    status_group        NVARCHAR(20)  NULL,       -- Operating / Proposed / Retired
    nameplate_mw        DECIMAL(12,2) NULL,
    operating_year      SMALLINT      NULL,
    planned_retire_year SMALLINT      NULL,
    latitude            DECIMAL(9,6)  NULL,
    longitude           DECIMAL(9,6)  NULL,
    CONSTRAINT fk_gen_county FOREIGN KEY (county_fips) REFERENCES dim.county (county_fips)
);
GO

CREATE INDEX ix_gen_county   ON fact.generator_capacity (county_fips);
CREATE INDEX ix_gen_status   ON fact.generator_capacity (status_group);
CREATE INDEX ix_gen_retire   ON fact.generator_capacity (planned_retire_year);
GO
