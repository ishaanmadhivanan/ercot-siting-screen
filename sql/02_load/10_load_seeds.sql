/*  10_load_seeds.sql
    Loads the two checked-in seed CSVs. These are small, stable, and versioned
    in git on purpose - they are reference data, not extracts.

    EDIT THE PATHS BELOW to wherever you cloned the repo.
    BULK INSERT paths are resolved by the SQL Server SERVICE account, not by you,
    so use a full local path and keep the repo somewhere readable (not OneDrive).
*/

USE ErcotSiting;
GO

DECLARE @repo NVARCHAR(400) = N'C:\projects\ercot-siting-screen';   -- <<< EDIT ME

TRUNCATE TABLE dim.county;
EXEC('BULK INSERT dim.county
      FROM ''' + @repo + '\data\seed\dim_county_tx.csv''
      WITH (FIRSTROW = 2, FIELDTERMINATOR = '','', ROWTERMINATOR = ''0x0a'', TABLOCK);');

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
