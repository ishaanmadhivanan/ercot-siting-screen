/*  14_load_queue.sql  --  Stage 3
    Loads the output of scripts/load_ercot_queue.py.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS stg.queue_project;
GO

CREATE TABLE stg.queue_project (
    inr           NVARCHAR(40),
    county_fips   NVARCHAR(10),
    status        NVARCHAR(40),
    size_category NVARCHAR(40),
    fuel          NVARCHAR(40),
    technology    NVARCHAR(40),
    cdr_zone      NVARCHAR(40),
    capacity_mw   NVARCHAR(40)
);
GO

DECLARE @repo NVARCHAR(400) = N'D:\sql\ercot-siting-screen';   -- <<< EDIT IF YOUR PATH DIFFERS

EXEC('BULK INSERT stg.queue_project
      FROM ''' + @repo + '\data\processed\fact_queue_project.csv''
      WITH (FIRSTROW = 2, FIELDTERMINATOR = '','', ROWTERMINATOR = ''0x0a'',
            FIELDQUOTE = ''"'', FORMAT = ''CSV'', TABLOCK);');
GO

TRUNCATE TABLE fact.queue_project;

INSERT INTO fact.queue_project
    (inr, county_fips, status, size_category, fuel, technology, cdr_zone, capacity_mw)
SELECT
    s.inr,
    s.county_fips,
    s.status,
    NULLIF(s.size_category, ''),
    NULLIF(s.fuel, ''),
    NULLIF(s.technology, ''),
    NULLIF(s.cdr_zone, ''),
    TRY_CAST(s.capacity_mw AS DECIMAL(12,3))
FROM stg.queue_project s
WHERE s.inr IS NOT NULL AND s.inr <> '';
GO

-- Active total should land near 438,000 MW; inactive near 37,000 MW.
SELECT status,
       COUNT(*)                                  AS projects,
       CAST(SUM(capacity_mw) AS DECIMAL(18,0))   AS total_mw,
       COUNT(DISTINCT county_fips)               AS counties
FROM fact.queue_project
GROUP BY status;

-- The ten most contested counties in ERCOT.
SELECT TOP 10 c.county_name,
       CAST(SUM(q.capacity_mw) AS DECIMAL(18,0)) AS active_queue_mw,
       COUNT(*) AS projects
FROM fact.queue_project q
JOIN dim.county c ON c.county_fips = q.county_fips
WHERE q.status = 'Active'
GROUP BY c.county_name
ORDER BY active_queue_mw DESC;
GO
