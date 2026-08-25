/*  01_dim_county.sql
    The spine of the whole model. Every fact table joins here on county_fips.

    WHY match_key EXISTS: source files disagree on county spelling.
    EIA writes "De Witt", Census writes "DeWitt", ERCOT writes something else.
    match_key is the normalised form (lowercase, no spaces, no punctuation,
    "county" suffix stripped) that all sources are mapped through.
    Never join on county_name. Ever.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS dim.county;
GO

CREATE TABLE dim.county (
    county_fips     CHAR(5)      NOT NULL PRIMARY KEY,   -- 5-digit state+county FIPS
    state_fips      CHAR(2)      NOT NULL,
    county_name     NVARCHAR(80) NOT NULL,
    match_key       VARCHAR(60)  NOT NULL,
    land_area_sqmi  DECIMAL(12,2) NULL,                  -- Stage 1b, Census Gazetteer
    population      INT           NULL,                  -- Stage 1b, Census
    CONSTRAINT uq_county_match_key UNIQUE (match_key)
);
GO

CREATE INDEX ix_county_match_key ON dim.county (match_key);
GO
