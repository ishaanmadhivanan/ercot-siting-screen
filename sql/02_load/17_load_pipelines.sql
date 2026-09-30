/*  17_load_pipelines.sql  --  Phase 3 (gas access)
    Loads the outputs of scripts/load_pipelines.py:
      data/processed/fact_pipeline_segment.csv -> fact.pipeline_segment
      data/processed/county_gas_attribute.csv  -> fact.county_attribute
                                                  (gathering miles, LNG terminals)

    Run order for Phase 3:
      1. sql/01_schema/07_dim_metric.sql          (catalog rows + score_transform column)
      2. sql/01_schema/09_fact_pipeline_segment.sql
      3. this file
      4. sql/03_views/20_vw_county_factor.sql     (adds the pipeline factors)
      5. sql/03_views/22_vw_county_factor_score.sql (new: 0-100 score per factor)
*/

USE ErcotSiting;
GO

-- ---------- 1. Pipeline segments ----------
DROP TABLE IF EXISTS stg.pipeline_segment;
GO

CREATE TABLE stg.pipeline_segment (
    county_fips    NVARCHAR(10),
    operator_p5    NVARCHAR(20),
    operator_name  NVARCHAR(200),
    system_name    NVARCHAR(200),
    diameter_in    NVARCHAR(40),
    interstate     NVARCHAR(10),
    miles          NVARCHAR(40),
    segments       NVARCHAR(40),
    download_date  NVARCHAR(40)
);
GO

DROP TABLE IF EXISTS stg.county_gas_attribute;
GO

CREATE TABLE stg.county_gas_attribute (
    county_fips    NVARCHAR(10),
    attribute_key  NVARCHAR(60),
    value_num      NVARCHAR(40),
    value_text     NVARCHAR(400)
);
GO

DECLARE @repo NVARCHAR(400) = N'D:\sql\ercot-siting-screen';   -- <<< EDIT IF YOUR PATH DIFFERS

EXEC('BULK INSERT stg.pipeline_segment
      FROM ''' + @repo + '\data\processed\fact_pipeline_segment.csv''
      WITH (FIRSTROW = 2, FIELDTERMINATOR = '','', ROWTERMINATOR = ''0x0a'',
            FIELDQUOTE = ''"'', FORMAT = ''CSV'', CODEPAGE = ''65001'', TABLOCK);');

EXEC('BULK INSERT stg.county_gas_attribute
      FROM ''' + @repo + '\data\processed\county_gas_attribute.csv''
      WITH (FIRSTROW = 2, FIELDTERMINATOR = '','', ROWTERMINATOR = ''0x0a'',
            FIELDQUOTE = ''"'', FORMAT = ''CSV'', CODEPAGE = ''65001'', TABLOCK);');
GO

DELETE FROM fact.pipeline_segment;

INSERT INTO fact.pipeline_segment
    (county_fips, operator_p5, operator_name, system_name, diameter_in,
     interstate, miles, segments, download_date)
SELECT
    s.county_fips,
    s.operator_p5,
    s.operator_name,
    ISNULL(s.system_name, ''),
    TRY_CAST(s.diameter_in AS DECIMAL(6,2)),
    s.interstate,
    TRY_CAST(TRY_CAST(s.miles AS FLOAT) AS DECIMAL(12,4)),
    TRY_CAST(s.segments AS INT),
    TRY_CAST(s.download_date AS DATE)
FROM stg.pipeline_segment s
WHERE s.county_fips IS NOT NULL AND s.county_fips <> '';
GO

-- ---------- 2. Gas attributes: replace the gas keys only ----------
DELETE FROM fact.county_attribute
WHERE attribute_key IN ('gas_gathering_miles', 'lng_terminal_count', 'lng_terminals');

INSERT INTO fact.county_attribute (county_fips, attribute_key, value_num, value_text)
SELECT
    s.county_fips,
    s.attribute_key,
    TRY_CAST(TRY_CAST(NULLIF(s.value_num, '') AS FLOAT) AS DECIMAL(18,4)),
    NULLIF(s.value_text, '')
FROM stg.county_gas_attribute s
WHERE s.attribute_key IN ('gas_gathering_miles', 'lng_terminal_count', 'lng_terminals');
GO

-- Check 1: expect 8,381 rows, about 48,700 miles, 243 counties; interstate about 11,900 miles.
SELECT COUNT(*)                              AS rows_loaded,
       CAST(SUM(miles) AS DECIMAL(12,0))     AS total_miles,
       COUNT(DISTINCT county_fips)           AS counties,
       COUNT(DISTINCT operator_p5)           AS operators,
       CAST(SUM(CASE WHEN interstate = 'Y' THEN miles END) AS DECIMAL(12,0)) AS interstate_miles
FROM fact.pipeline_segment;

-- Check 2: gas attributes. Expect gas_gathering_miles 207, lng_terminal_count 4, lng_terminals 4.
SELECT attribute_key, COUNT(*) AS counties
FROM fact.county_attribute
WHERE attribute_key IN ('gas_gathering_miles', 'lng_terminal_count', 'lng_terminals')
GROUP BY attribute_key;

-- Check 3: every attribute key has a catalog row. Should return zero rows.
SELECT DISTINCT a.attribute_key AS attribute_not_in_catalog
FROM fact.county_attribute a
LEFT JOIN dim.metric m ON m.metric_key = a.attribute_key
WHERE m.metric_key IS NULL;
GO
