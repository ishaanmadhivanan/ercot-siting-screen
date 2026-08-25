/*  00_create_database.sql
    Stage 1 - creates the database and the four schemas the project uses.
    Run this once, from SSMS, connected to your local SQL Server Express instance.

    Schema conventions:
      stg  - raw landing tables, one per source file, everything NVARCHAR
      dim  - conformed dimensions (county, fuel, weights)
      fact - measured/additive tables
      rpt  - views that Power BI connects to. Power BI reads ONLY from rpt.
*/

IF DB_ID('ErcotSiting') IS NULL
    CREATE DATABASE ErcotSiting;
GO

USE ErcotSiting;
GO

IF SCHEMA_ID('stg')  IS NULL EXEC('CREATE SCHEMA stg');
IF SCHEMA_ID('dim')  IS NULL EXEC('CREATE SCHEMA dim');
IF SCHEMA_ID('fact') IS NULL EXEC('CREATE SCHEMA fact');
IF SCHEMA_ID('rpt')  IS NULL EXEC('CREATE SCHEMA rpt');
GO
