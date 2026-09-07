/*  15_classify_ercot.sql  --  Stage 3

    Marks which Texas counties are actually in ERCOT.

    WHY THIS IS NECESSARY
    Texas is not one grid. Roughly 90% of its LOAD is in ERCOT, but a
    meaningful share of its COUNTIES are not: the Panhandle is largely SPP,
    East Texas is MISO and SERC, and El Paso is WECC.

    EIA and Census data are national and cover every county. The ERCOT
    interconnection queue covers only ERCOT. Left unfiltered, a non-ERCOT
    county scores normally on capacity and generation, then receives a perfect
    zero on queue congestion - the heaviest weighted factor - and rises to the
    top of the ranking for a reason that has nothing to do with siting quality.
    El Paso ranked 3rd this way, in a model named after ERCOT.

    THE TEST
    A county is in scope if EITHER is true:
      1. it contains at least one plant reporting balancing authority ERCO, or
      2. it contains at least one ERCOT interconnection request.
    Both are direct evidence of participation in the ERCOT market.

    Using queue PRESENCE to classify is not circular with using queue VOLUME as
    a scoring factor: a county that fails both tests has neither generation nor
    proposed generation, so it would contribute nothing to the ranking either way.
*/

USE ErcotSiting;
GO

IF COL_LENGTH('dim.county', 'in_ercot') IS NULL
    ALTER TABLE dim.county ADD in_ercot BIT NULL;
GO

UPDATE dim.county SET in_ercot = 0;
GO

-- Test 1: an ERCO plant in the county.
UPDATE c SET c.in_ercot = 1
FROM dim.county c
WHERE EXISTS (SELECT 1 FROM fact.generator_capacity g
              WHERE g.county_fips = c.county_fips
                AND g.balancing_authority = 'ERCO');
GO

-- Test 2: an ERCOT interconnection request in the county.
UPDATE c SET c.in_ercot = 1
FROM dim.county c
WHERE EXISTS (SELECT 1 FROM fact.queue_project q
              WHERE q.county_fips = c.county_fips);
GO

SELECT in_ercot, COUNT(*) AS counties
FROM dim.county GROUP BY in_ercot;

-- Counties excluded despite having generation. Sanity check these by eye:
-- they should be Panhandle, East Texas, or far West Texas.
SELECT c.county_name,
       CAST(SUM(g.nameplate_mw) AS DECIMAL(12,0)) AS mw,
              MAX(g.balancing_authority) AS balancing_authority
FROM dim.county c
JOIN fact.generator_capacity g ON g.county_fips = c.county_fips
WHERE c.in_ercot = 0
GROUP BY c.county_name
ORDER BY mw DESC;

-- Counties excluded with no evidence either way: no ERCO plant, no queue
-- request, no generation at all. These are genuinely unclassifiable from the
-- data and are excluded by default.
SELECT COUNT(*) AS counties_with_no_evidence
FROM dim.county c
WHERE c.in_ercot = 0
  AND NOT EXISTS (SELECT 1 FROM fact.generator_capacity g WHERE g.county_fips = c.county_fips);
GO
