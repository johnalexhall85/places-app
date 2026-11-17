-- Read-only database role for the CHIP MCP server. Run once per database as a superuser:
--   psql "<admin url>/places_staging" -v ro_password="'<secret>'" -f infra/mcp/mcp_readonly_role.sql
-- The password is supplied at run time and stored only in ~/.config/chip/mcp-*.env (mode 600).
-- Rerunnable. Grants SELECT on the shared published-data schema and the two county-search tables only.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'chip_mcp_ro') THEN
    CREATE ROLE chip_mcp_ro LOGIN;
  END IF;
END $$;
ALTER ROLE chip_mcp_ro WITH LOGIN PASSWORD :ro_password NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT CONNECTION LIMIT 20;
ALTER ROLE chip_mcp_ro SET default_transaction_read_only = on;
ALTER ROLE chip_mcp_ro SET statement_timeout = '5s';
ALTER ROLE chip_mcp_ro SET idle_in_transaction_session_timeout = '30s';
GRANT CONNECT ON DATABASE :"DBNAME" TO chip_mcp_ro;
REVOKE CREATE ON SCHEMA public FROM chip_mcp_ro;
GRANT USAGE ON SCHEMA area_pilot TO chip_mcp_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA area_pilot TO chip_mcp_ro;
GRANT USAGE ON SCHEMA public TO chip_mcp_ro;
GRANT SELECT ON public.dim_county TO chip_mcp_ro;
DO $$ BEGIN
  IF to_regclass('public.dim_county_boundary') IS NOT NULL THEN
    EXECUTE 'GRANT SELECT ON public.dim_county_boundary TO chip_mcp_ro';
  END IF;
END $$;
-- Tables added to area_pilot by later migrations are readable without rerunning this script.
-- Must be run by the role that owns those tables (the application role):
--   ALTER DEFAULT PRIVILEGES IN SCHEMA area_pilot GRANT SELECT ON TABLES TO chip_mcp_ro;
