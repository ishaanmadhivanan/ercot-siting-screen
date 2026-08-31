/*  05_fact_generation_monthly.sql  --  Stage 2

    Adds the time dimension and the monthly generation fact.

    WHY dim.month EXISTS
    You could compute hours-in-month inline every time it is needed. A date
    dimension is better for two reasons: the hours calculation is written once
    and cannot drift between queries, and leap years stop being a special case
    anyone has to remember. Capacity factor is generation divided by
    (capacity x hours), so getting February wrong quietly inflates every
    capacity factor in the state by about 7% in leap years.

    GRAIN
    dim.month              : one row per calendar month
    fact.generation_monthly: one row per plant / prime mover / fuel / month
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS fact.generation_monthly;
DROP TABLE IF EXISTS dim.month;
GO

CREATE TABLE dim.month (
    month_key       INT         NOT NULL PRIMARY KEY,   -- yyyymm, e.g. 202401
    year            SMALLINT    NOT NULL,
    month_number    TINYINT     NOT NULL,
    month_start     DATE        NOT NULL,
    days_in_month   TINYINT     NOT NULL,
    hours_in_month  SMALLINT    NOT NULL,
    CONSTRAINT uq_month_year_num UNIQUE (year, month_number)
);
GO

-- Populate 2015-2035 so later 923 vintages drop in without a schema change.
WITH months AS (
    SELECT CAST('2015-01-01' AS DATE) AS d
    UNION ALL
    SELECT DATEADD(MONTH, 1, d) FROM months WHERE d < '2035-12-01'
)
INSERT INTO dim.month (month_key, year, month_number, month_start,
                       days_in_month, hours_in_month)
SELECT
    YEAR(d) * 100 + MONTH(d),
    YEAR(d),
    MONTH(d),
    d,
    DAY(EOMONTH(d)),
    DAY(EOMONTH(d)) * 24
FROM months
OPTION (MAXRECURSION 500);
GO

CREATE TABLE fact.generation_monthly (
    generation_sk       BIGINT IDENTITY(1,1) PRIMARY KEY,
    plant_code          INT           NOT NULL,
    county_fips         CHAR(5)       NOT NULL,
    month_key           INT           NOT NULL,
    prime_mover         NVARCHAR(10)  NULL,
    fuel_type           NVARCHAR(10)  NULL,
    net_generation_mwh  DECIMAL(18,3) NULL,
    CONSTRAINT fk_gen_month_county FOREIGN KEY (county_fips) REFERENCES dim.county (county_fips),
    CONSTRAINT fk_gen_month_month  FOREIGN KEY (month_key)   REFERENCES dim.month (month_key)
);
GO

CREATE INDEX ix_genmon_county ON fact.generation_monthly (county_fips);
CREATE INDEX ix_genmon_month  ON fact.generation_monthly (month_key);
CREATE INDEX ix_genmon_cm     ON fact.generation_monthly (county_fips, month_key)
    INCLUDE (net_generation_mwh);
GO

SELECT COUNT(*) AS months_created, MIN(month_start) AS first_month, MAX(month_start) AS last_month
FROM dim.month;
GO
