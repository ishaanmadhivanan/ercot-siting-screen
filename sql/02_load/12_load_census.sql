/*  12_load_census.sql  --  Stage 1b
    Loads Census land area and population into the two placeholder columns that
    dim.county has carried since Stage 1.

    Note what is NOT here: any county name matching. Both Census files key on
    the same 5-digit FIPS code dim.county was built from, so this is a plain
    join on a code. That is the return on having built the FIPS spine first.

    Run scripts/load_census.py before this.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS stg.county_demog;
GO

CREATE TABLE stg.county_demog (
    county_fips    NVARCHAR(10),
    land_area_sqmi NVARCHAR(40),
    population     NVARCHAR(40)
);
GO

DECLARE @repo NVARCHAR(400) = N'D:\sql\ercot-siting-screen';   -- <<< EDIT IF YOUR PATH DIFFERS

EXEC('BULK INSERT stg.county_demog
      FROM ''' + @repo + '\data\processed\dim_county_demog.csv''
      WITH (FIRSTROW = 2, FIELDTERMINATOR = '','', ROWTERMINATOR = ''0x0a'',
            FIELDQUOTE = ''"'', FORMAT = ''CSV'', TABLOCK);');
GO

UPDATE c
SET c.land_area_sqmi = TRY_CAST(s.land_area_sqmi AS DECIMAL(12,2)),
    c.population     = TRY_CAST(TRY_CAST(s.population AS DECIMAL(18,2)) AS INT)
FROM dim.county c
JOIN stg.county_demog s ON s.county_fips = c.county_fips;
GO

-- Should return zero rows: every county must now have both values.
SELECT county_fips, county_name, land_area_sqmi, population
FROM dim.county
WHERE land_area_sqmi IS NULL OR population IS NULL;
GO

-- Sanity check: the five densest and five emptiest counties in Texas.
SELECT TOP 5 county_name, population, land_area_sqmi,
       CAST(population / NULLIF(land_area_sqmi, 0) AS DECIMAL(12,2)) AS density
FROM dim.county ORDER BY density DESC;

SELECT TOP 5 county_name, population, land_area_sqmi,
       CAST(population / NULLIF(land_area_sqmi, 0) AS DECIMAL(12,2)) AS density
FROM dim.county ORDER BY density ASC;
GO
