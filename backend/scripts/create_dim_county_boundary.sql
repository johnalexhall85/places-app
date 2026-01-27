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
