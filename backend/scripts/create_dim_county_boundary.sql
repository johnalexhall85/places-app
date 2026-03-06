CREATE TABLE dim_county_boundary (
  location_id VARCHAR(5) PRIMARY KEY,
  geoid VARCHAR(5) NOT NULL,
  name TEXT NOT NULL,
  statefp VARCHAR(2) NOT NULL,
  countyfp VARCHAR(3) NOT NULL,
  geom geometry(MULTIPOLYGON, 4326) NOT NULL
);

CREATE INDEX dim_county_boundary_geom_gist_idx
  ON dim_county_boundary
  USING GIST (geom);

CREATE INDEX dim_county_boundary_statefp_idx
  ON dim_county_boundary (statefp);

CREATE TABLE IF NOT EXISTS dim_state_boundary (
  state_fips VARCHAR(2) PRIMARY KEY,
  state_abbr VARCHAR(2) NOT NULL,
  state_name TEXT NOT NULL,
  geom geometry(MULTIPOLYGON, 4326) NOT NULL
);

CREATE INDEX IF NOT EXISTS dim_state_boundary_geom_gist_idx
  ON dim_state_boundary
  USING GIST (geom);

CREATE INDEX IF NOT EXISTS dim_state_boundary_state_abbr_idx
  ON dim_state_boundary (state_abbr);
