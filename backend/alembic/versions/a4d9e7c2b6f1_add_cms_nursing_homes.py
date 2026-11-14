"""Independent CMS nursing home point release and immutable source staging."""
from alembic import op

revision = 'a4d9e7c2b6f1'
down_revision = 'f2c8d4a6b1e3'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE TABLE area_pilot.stage_cms_nursing_home (
        release_id uuid NOT NULL REFERENCES area_pilot.release(id),
        ccn text NOT NULL, line_number integer NOT NULL, record jsonb NOT NULL,
        PRIMARY KEY (release_id, ccn))''')
    op.execute('''CREATE TABLE area_pilot.cms_nursing_home (
        release_id uuid NOT NULL REFERENCES area_pilot.release(id),
        ccn text NOT NULL CHECK (ccn ~ '^[0-9A-Za-z]{6}$'),
        record_sha256 varchar(64) NOT NULL,
        provider_name text NOT NULL, provider_address text, city text, state_abbr text,
        zip_code text, county_name text, provider_type text, ownership_type text,
        certified_beds integer CHECK (certified_beds >= 0),
        overall_rating smallint CHECK (overall_rating BETWEEN 1 AND 5),
        health_inspection_rating smallint CHECK (health_inspection_rating BETWEEN 1 AND 5),
        staffing_rating smallint CHECK (staffing_rating BETWEEN 1 AND 5),
        quality_measure_rating smallint CHECK (quality_measure_rating BETWEEN 1 AND 5),
        rating_footnotes jsonb NOT NULL, geocoding_footnote text,
        processing_date date NOT NULL, source_latitude text, source_longitude text,
        location_status text NOT NULL CHECK (location_status IN
          ('mapped','zip_based_coordinate','no_published_coordinates','invalid_coordinates')),
        geom geometry(Point,4326),
        PRIMARY KEY (release_id, ccn),
        CONSTRAINT cms_nursing_home_geom_status CHECK ((location_status='mapped')=(geom IS NOT NULL))
    )''')
    op.execute("CREATE INDEX ix_cms_nursing_home_geom ON area_pilot.cms_nursing_home USING GIST (geom) WHERE location_status='mapped'")
    op.execute("CREATE INDEX ix_cms_nursing_home_filter ON area_pilot.cms_nursing_home (release_id,location_status,overall_rating,provider_type,ownership_type)")
    op.execute("CREATE INDEX ix_cms_nursing_home_table ON area_pilot.cms_nursing_home (release_id,state_abbr,city,provider_name,ccn) WHERE location_status='mapped'")
    for table in ('stage_cms_nursing_home', 'cms_nursing_home'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE
            ON area_pilot.{table} FOR EACH ROW EXECUTE FUNCTION area_pilot.prevent_published_data_change()''')


def downgrade():
    for table in ('cms_nursing_home', 'stage_cms_nursing_home'):
        op.execute(f'DROP TABLE area_pilot.{table}')
