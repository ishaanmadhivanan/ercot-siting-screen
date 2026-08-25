/*  02_dim_fuel.sql
    Maps EIA-860's ~26 "Technology" strings down to a handful of fuel categories
    you can actually put on a chart legend.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS dim.fuel;
GO

CREATE TABLE dim.fuel (
    technology      NVARCHAR(120) NOT NULL PRIMARY KEY,  -- verbatim EIA-860 value
    fuel_category   NVARCHAR(40)  NOT NULL,
    is_renewable    BIT           NOT NULL,
    is_dispatchable BIT           NOT NULL
);
GO
