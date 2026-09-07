/*  11_load_generators.sql
    Loads the output of scripts/load_eia860.py into the fact table.
    Run the Python script FIRST - it does the county-to-FIPS resolution and
    refuses to write a file if any county fails to match.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS stg.generator_capacity;
GO

CREATE TABLE stg.generator_capacity (
    data_vintage_year   NVARCHAR(20),
    plant_code          NVARCHAR(20),
    generator_id        NVARCHAR(20),
    plant_name          NVARCHAR(200),
    county_fips         NVARCHAR(10),
    technology          NVARCHAR(200),
    status_code         NVARCHAR(20),
    status_group        NVARCHAR(40),
    nameplate_mw        NVARCHAR(40),
    operating_year      NVARCHAR(20),
    planned_retire_year NVARCHAR(20),
    latitude            NVARCHAR(40),
    longitude           NVARCHAR(40),
    balancing_authority NVARCHAR(40)
);
GO

DECLARE @repo NVARCHAR(400) = N'D:\sql\ercot-siting-screen';

EXEC('BULK INSERT stg.generator_capacity
      FROM ''' + @repo + '\data\processed\fact_generator_capacity.csv''
      WITH (FIRSTROW = 2, FIELDTERMINATOR = '','', ROWTERMINATOR = ''0x0a'',
            FIELDQUOTE = ''"'', FORMAT = ''CSV'', TABLOCK);');
GO

TRUNCATE TABLE fact.generator_capacity;

INSERT INTO fact.generator_capacity (
    data_vintage_year, plant_code, generator_id, plant_name, county_fips,
    technology, status_code, status_group, nameplate_mw,
    operating_year, planned_retire_year, latitude, longitude, balancing_authority)
SELECT
    TRY_CAST(data_vintage_year   AS SMALLINT),
    TRY_CAST(TRY_CAST(plant_code AS DECIMAL(18,2)) AS INT),
    generator_id,
    plant_name,
    county_fips,
    NULLIF(technology, ''),
    NULLIF(status_code, ''),
    status_group,
    TRY_CAST(nameplate_mw        AS DECIMAL(12,2)),
    TRY_CAST(TRY_CAST(operating_year AS DECIMAL(18,2)) AS SMALLINT),
    TRY_CAST(TRY_CAST(planned_retire_year AS DECIMAL(18,2)) AS SMALLINT),
    TRY_CAST(latitude            AS DECIMAL(9,6)),
    TRY_CAST(longitude           AS DECIMAL(9,6)),
    NULLIF(balancing_authority, '')
FROM stg.generator_capacity
WHERE TRY_CAST(TRY_CAST(plant_code AS DECIMAL(18,2)) AS INT) IS NOT NULL;
GO

SELECT status_group, COUNT(*) AS generators, SUM(nameplate_mw) AS total_mw
FROM fact.generator_capacity
GROUP BY status_group
ORDER BY total_mw DESC;
GO
