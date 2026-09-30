/*  16_load_air.sql  --  Phase 2 (air permitting)
    Loads the output of scripts/load_air.py into fact.county_attribute.

    Run order for Phase 2:
      1. sql/01_schema/07_dim_metric.sql      (adds the air rows to the catalog)
      2. this file
      3. sql/03_views/20_vw_county_factor.sql (adds the ozone_severity factor)

    Only the air keys are replaced. Later phases (gas, land) write their own
    keys to the same table, and re-running this file leaves those alone.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS stg.county_attribute;
GO

CREATE TABLE stg.county_attribute (
    county_fips    NVARCHAR(10),
    attribute_key  NVARCHAR(60),
    value_num      NVARCHAR(40),
    value_text     NVARCHAR(200)
);
GO

DECLARE @repo NVARCHAR(400) = N'D:\sql\ercot-siting-screen';   -- <<< EDIT IF YOUR PATH DIFFERS

EXEC('BULK INSERT stg.county_attribute
      FROM ''' + @repo + '\data\processed\county_air_attribute.csv''
      WITH (FIRSTROW = 2, FIELDTERMINATOR = '','', ROWTERMINATOR = ''0x0a'',
            FIELDQUOTE = ''"'', FORMAT = ''CSV'', TABLOCK);');
GO

-- Replace the air keys only.
DELETE FROM fact.county_attribute
WHERE attribute_key IN (SELECT DISTINCT attribute_key FROM stg.county_attribute);

INSERT INTO fact.county_attribute (county_fips, attribute_key, value_num, value_text)
SELECT
    s.county_fips,
    s.attribute_key,
    TRY_CAST(TRY_CAST(NULLIF(s.value_num, '') AS FLOAT) AS DECIMAL(18,4)),
    NULLIF(s.value_text, '')
FROM stg.county_attribute s
WHERE s.county_fips IS NOT NULL AND s.county_fips <> '';
GO

-- Check 1: expect 858 rows across 8 keys.
SELECT attribute_key, COUNT(*) AS counties
FROM fact.county_attribute
GROUP BY attribute_key
ORDER BY counties DESC, attribute_key;

-- Check 2: every attribute has a catalog row. Should return zero rows.
SELECT DISTINCT a.attribute_key AS attribute_not_in_catalog
FROM fact.county_attribute a
LEFT JOIN dim.metric m ON m.metric_key = a.attribute_key
WHERE m.metric_key IS NULL;

-- Check 3: the nonattainment counties inside ERCOT, one row each.
-- Expect 17: Bexar (Serious) plus 16 Severe in Houston and Dallas-Fort Worth.
-- Liberty and Montgomery are Severe too but sit mostly in MISO, so in_ercot = 0.
SELECT
    c.county_name,
    cls.value_text                                        AS classification,
    det.value_text                                        AS standards,
    CAST(thr.value_num AS INT)                            AS major_source_tpy,
    ratio.value_num                                       AS offset_ratio,
    CAST(price.value_num AS INT)                          AS credit_price_per_tpy,
    CAST(cost.value_num AS INT)                           AS offset_cost_per_tpy,
    CAST(trd.value_num AS INT)                            AS area_trades,
    tons.value_num                                        AS area_tons_traded
FROM dim.county c
JOIN fact.county_attribute cls   ON cls.county_fips = c.county_fips   AND cls.attribute_key = 'ozone_classification'
LEFT JOIN fact.county_attribute det   ON det.county_fips = c.county_fips   AND det.attribute_key = 'ozone_standards_detail'
LEFT JOIN fact.county_attribute thr   ON thr.county_fips = c.county_fips   AND thr.attribute_key = 'nox_major_source_tpy'
LEFT JOIN fact.county_attribute ratio ON ratio.county_fips = c.county_fips AND ratio.attribute_key = 'nox_offset_ratio'
LEFT JOIN fact.county_attribute price ON price.county_fips = c.county_fips AND price.attribute_key = 'nox_credit_price_per_tpy'
LEFT JOIN fact.county_attribute cost  ON cost.county_fips = c.county_fips  AND cost.attribute_key = 'nox_offset_cost_per_tpy'
LEFT JOIN fact.county_attribute trd   ON trd.county_fips = c.county_fips   AND trd.attribute_key = 'nox_credit_trades'
LEFT JOIN fact.county_attribute tons  ON tons.county_fips = c.county_fips  AND tons.attribute_key = 'nox_credit_tons_traded'
WHERE c.in_ercot = 1
  AND cls.value_num > 0
ORDER BY cls.value_num DESC, c.county_name;
GO
