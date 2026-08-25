/*  90_check_fips_coverage.sql
    THE CHECK THAT SAVES THE PROJECT.

    Texas has 254 counties. If a source spells one differently and it silently
    drops, you will not notice by eye - you will just quietly be scoring 249
    counties and wondering why a county you know has a big plant looks empty.

    Run this after every load. Every query below should return ZERO rows.
    Wire it into your routine now, while there is one fact table, not in week
    three when there are four.
*/

USE ErcotSiting;
GO

PRINT '--- CHECK 1: fact rows whose county_fips is not in dim.county ---';
SELECT DISTINCT f.county_fips
FROM fact.generator_capacity f
LEFT JOIN dim.county c ON c.county_fips = f.county_fips
WHERE c.county_fips IS NULL;

PRINT '--- CHECK 2: technologies present in fact but missing from dim.fuel ---';
SELECT DISTINCT f.technology
FROM fact.generator_capacity f
LEFT JOIN dim.fuel d ON d.technology = f.technology
WHERE d.technology IS NULL
  AND f.technology IS NOT NULL;

PRINT '--- CHECK 3: duplicate generator keys within a vintage ---';
SELECT data_vintage_year, plant_code, generator_id, COUNT(*) AS n
FROM fact.generator_capacity
GROUP BY data_vintage_year, plant_code, generator_id
HAVING COUNT(*) > 1;

PRINT '--- CHECK 4: operating generators with null or zero capacity ---';
SELECT plant_code, generator_id, plant_name, nameplate_mw
FROM fact.generator_capacity
WHERE status_group = 'Operating'
  AND (nameplate_mw IS NULL OR nameplate_mw <= 0);

PRINT '--- INFO: county coverage (expect 254 in dim, fewer with generators) ---';
SELECT
    (SELECT COUNT(*) FROM dim.county) AS counties_in_dim,
    (SELECT COUNT(DISTINCT county_fips) FROM fact.generator_capacity) AS counties_with_generators;
GO
