/*  18_load_land.sql  --  Phase 4 (land)
    Loads data/processed/county_land_attribute.csv (from scripts/load_parcels.py,
    TxGIO StratMap Land Parcels 2025) into fact.county_attribute.

    Run order for Phase 4:
      1. sql/01_schema/07_dim_metric.sql       (adds the land rows to the catalog)
      2. this file
      3. sql/03_views/20_vw_county_factor.sql  (adds the three land factors)
      4. sql/03_views/22_vw_county_factor_score.sql
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS stg.county_land_attribute;
GO

CREATE TABLE stg.county_land_attribute (
    county_fips    NVARCHAR(10),
    attribute_key  NVARCHAR(60),
    value_num      NVARCHAR(40),
    value_text     NVARCHAR(200)
);
GO

DECLARE @repo NVARCHAR(400) = N'D:\sql\ercot-siting-screen';   -- <<< EDIT IF YOUR PATH DIFFERS

EXEC('BULK INSERT stg.county_land_attribute
      FROM ''' + @repo + '\data\processed\county_land_attribute.csv''
      WITH (FIRSTROW = 2, FIELDTERMINATOR = '','', ROWTERMINATOR = ''0x0a'',
            FIELDQUOTE = ''"'', FORMAT = ''CSV'', TABLOCK);');
GO

DELETE FROM fact.county_attribute WHERE attribute_key LIKE 'land[_]%';

INSERT INTO fact.county_attribute (county_fips, attribute_key, value_num, value_text)
SELECT
    s.county_fips,
    s.attribute_key,
    TRY_CAST(TRY_CAST(NULLIF(s.value_num, '') AS FLOAT) AS DECIMAL(18,4)),
    NULLIF(s.value_text, '')
FROM stg.county_land_attribute s
WHERE s.attribute_key LIKE 'land[_]%';
GO

-- Check 1: rows per key. Expect 194 counties for most keys (Donley has no
-- parcel file); land_industrial_acres only ~62 (codes too sparse elsewhere).
SELECT attribute_key, COUNT(*) AS counties
FROM fact.county_attribute
WHERE attribute_key LIKE 'land[_]%'
GROUP BY attribute_key
ORDER BY attribute_key;

-- Check 2: every attribute key has a catalog row. Should return zero rows.
SELECT DISTINCT a.attribute_key AS attribute_not_in_catalog
FROM fact.county_attribute a
LEFT JOIN dim.metric m ON m.metric_key = a.attribute_key
WHERE m.metric_key IS NULL;
GO
