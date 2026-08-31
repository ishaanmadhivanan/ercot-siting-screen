/*  13_load_generation.sql  --  Stage 2
    Loads the output of scripts/load_eia923.py.
    Run that script first; it does the wide-to-long reshape and the county join.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS stg.generation_monthly;
GO

CREATE TABLE stg.generation_monthly (
    plant_code         NVARCHAR(20),
    county_fips        NVARCHAR(10),
    year               NVARCHAR(10),
    month              NVARCHAR(10),
    prime_mover        NVARCHAR(20),
    fuel_type          NVARCHAR(20),
    net_generation_mwh NVARCHAR(40)
);
GO

DECLARE @repo NVARCHAR(400) = N'D:\sql\ercot-siting-screen';   -- <<< EDIT IF YOUR PATH DIFFERS

EXEC('BULK INSERT stg.generation_monthly
      FROM ''' + @repo + '\data\processed\fact_generation_monthly.csv''
      WITH (FIRSTROW = 2, FIELDTERMINATOR = '','', ROWTERMINATOR = ''0x0a'',
            FIELDQUOTE = ''"'', FORMAT = ''CSV'', TABLOCK);');
GO

TRUNCATE TABLE fact.generation_monthly;

INSERT INTO fact.generation_monthly
    (plant_code, county_fips, month_key, prime_mover, fuel_type, net_generation_mwh)
SELECT
    TRY_CAST(TRY_CAST(s.plant_code AS DECIMAL(18,2)) AS INT),
    s.county_fips,
    TRY_CAST(s.year AS INT) * 100 + TRY_CAST(s.month AS INT),
    NULLIF(s.prime_mover, ''),
    NULLIF(s.fuel_type, ''),
    TRY_CAST(s.net_generation_mwh AS DECIMAL(18,3))
FROM stg.generation_monthly s
WHERE TRY_CAST(TRY_CAST(s.plant_code AS DECIMAL(18,2)) AS INT) IS NOT NULL
  AND TRY_CAST(s.year AS INT) IS NOT NULL;
GO

-- Summary: generation by year. Texas runs roughly 450-520 TWh/yr, so each
-- year should land near 500,000,000 MWh. Anything far off means a parse problem.
SELECT m.year,
       COUNT(*)                              AS fact_rows,
       CAST(SUM(g.net_generation_mwh) AS DECIMAL(18,0)) AS total_mwh
FROM fact.generation_monthly g
JOIN dim.month m ON m.month_key = g.month_key
GROUP BY m.year
ORDER BY m.year;
GO
