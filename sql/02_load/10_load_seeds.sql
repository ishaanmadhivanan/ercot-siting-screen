/*  10_load_seeds.sql
    Loads the two checked-in seed CSVs. These are small, stable, and versioned
    in git on purpose - they are reference data, not extracts.

    EDIT THE PATHS BELOW to wherever you cloned the repo.
    BULK INSERT paths are resolved by the SQL Server SERVICE account, not by you,
    so use a full local path and keep the repo somewhere readable (not OneDrive).
*/

USE ErcotSiting;
GO

DECLARE @repo NVARCHAR(400) = N'D:\sql\ercot-siting-screen';   -- <<< EDIT ME

DROP TABLE IF EXISTS stg.county_seed;
CREATE TABLE stg.county_seed (
    county_fips CHAR(5),
    state_fips  CHAR(2),
    county_name NVARCHAR(80),
    match_key   VARCHAR(60)
);

EXEC('BULK INSERT stg.county_seed
      FROM ''' + @repo + '\data\seed\dim_county_tx.csv''
      WITH (FIRSTROW = 2, FIELDTERMINATOR = '','', ROWTERMINATOR = ''0x0a'', TABLOCK);');

DELETE FROM dim.county;
INSERT INTO dim.county (county_fips, state_fips, county_name, match_key)
SELECT county_fips, state_fips, county_name, match_key
FROM stg.county_seed;
TRUNCATE TABLE dim.fuel;
EXEC('BULK INSERT dim.fuel
      FROM ''' + @repo + '\data\seed\dim_fuel.csv''
      WITH (FIRSTROW = 2, FIELDTERMINATOR = '','', ROWTERMINATOR = ''0x0a'', TABLOCK);');
GO

SELECT 'dim.county' AS table_name, COUNT(*) AS row_count FROM dim.county
UNION ALL
SELECT 'dim.fuel',  COUNT(*) FROM dim.fuel;
-- Expect 254 counties and 26 technologies.
GO
