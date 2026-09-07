/*  06_fact_queue_project.sql  --  Stage 3

    The ERCOT generation interconnection queue: what developers have ASKED to
    build, as opposed to EIA-860 which records what exists.

    GRAIN: one row per interconnection request (INR) per status.

    WHAT THIS TABLE CANNOT TELL YOU
    Large Gen excludes projects that have not requested a Full Interconnection
    Study, per ERCOT confidentiality provisions. The active queue here is a
    lower bound on real activity, not a census. Any county-level congestion
    figure derived from it understates by an unknown amount.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS fact.queue_project;
GO

CREATE TABLE fact.queue_project (
    queue_sk      INT IDENTITY(1,1) PRIMARY KEY,
    inr           NVARCHAR(20)  NOT NULL,   -- ERCOT request number, e.g. 24INR0481
    county_fips   CHAR(5)       NOT NULL,
    status        NVARCHAR(20)  NOT NULL,   -- Active | Inactive
    size_category NVARCHAR(20)  NULL,       -- Large | Small
    fuel          NVARCHAR(20)  NULL,       -- SOL, WIN, GAS, OTH ...
    technology    NVARCHAR(20)  NULL,       -- PV, BA, CC ...
    cdr_zone      NVARCHAR(20)  NULL,       -- ERCOT's own region: NORTH/SOUTH/WEST/COASTAL
    capacity_mw   DECIMAL(12,3) NULL,
    CONSTRAINT fk_queue_county FOREIGN KEY (county_fips) REFERENCES dim.county (county_fips),
    CONSTRAINT uq_queue_inr_status UNIQUE (inr, status)
);
GO

CREATE INDEX ix_queue_county ON fact.queue_project (county_fips);
CREATE INDEX ix_queue_status ON fact.queue_project (status) INCLUDE (capacity_mw);
GO
