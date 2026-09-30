/*  09_fact_pipeline_segment.sql  --  Phase 3 (gas access)

    In-service natural gas TRANSMISSION pipe (RRC commodity code NGT), in
    miles, summed by county, operator, system, diameter and interstate flag.
    Source: Railroad Commission of Texas pipeline map (TPMS), pulled by
    scripts/load_pipelines.py. RRC splits lines at county boundaries, so each
    row is pipe physically inside that county.

    This is detail data: the drill-through table ("who runs pipe here, and
    how big"). The county factors in rpt.county_factor are built from it.

    Grain: county_fips + operator_p5 + system_name + diameter_in + interstate.
*/

USE ErcotSiting;
GO

DROP TABLE IF EXISTS fact.pipeline_segment;
GO

CREATE TABLE fact.pipeline_segment (
    county_fips    CHAR(5)        NOT NULL,
    operator_p5    VARCHAR(10)    NOT NULL,   -- RRC operator number (form P-5)
    operator_name  NVARCHAR(80)   NOT NULL,
    system_name    NVARCHAR(80)   NOT NULL,
    diameter_in    DECIMAL(6,2)   NOT NULL,   -- outside diameter, inches (0 = not reported)
    interstate     CHAR(1)        NOT NULL,   -- Y = interstate (FERC), N = intrastate (Texas)
    miles          DECIMAL(12,4)  NOT NULL,
    segments       INT            NOT NULL,
    download_date  DATE           NOT NULL,
    CONSTRAINT fk_pipe_county FOREIGN KEY (county_fips) REFERENCES dim.county (county_fips),
    CONSTRAINT ck_pipe_interstate CHECK (interstate IN ('Y', 'N'))
);
GO

CREATE INDEX ix_pipe_county ON fact.pipeline_segment (county_fips);
GO
