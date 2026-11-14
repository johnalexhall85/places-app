"""Release-keyed HRSA health center site points (additive; separate from area observations).

Every source row is kept twice per candidate release: verbatim in ``stage_hrsa_site`` (never read
by the API) and as a typed read-model row in ``site_hrsa``. Only ``location_status='mapped'`` rows
carry a point geometry. Suppressed locations keep no coordinates in the read model at all.
"""
from alembic import op

revision = 'e9b3f6a2c4d8'
down_revision = 'd3a7e5c1b9f2'
branch_labels = None
depends_on = None
S = 'area_pilot'
STATUSES = ("'mapped','suppressed_source_policy','no_published_coordinates','invalid_coordinates',"
            "'approximate_shared_coordinate','coarse_coordinate','published_county_not_in_boundary_layer',"
            "'outside_published_county'")


def upgrade():
    op.execute(f'''CREATE TABLE {S}.stage_hrsa_site (
        release_id uuid NOT NULL REFERENCES {S}.release(id),
        site_id text NOT NULL,
        line_number integer NOT NULL,
        record jsonb NOT NULL,
        PRIMARY KEY (release_id, site_id))''')
    op.execute(f'''CREATE TABLE {S}.site_hrsa (
        release_id uuid NOT NULL REFERENCES {S}.release(id),
        site_id text NOT NULL,
        record_sha256 varchar(64) NOT NULL,
        health_center_number text NOT NULL,
        organization_name text NOT NULL,
        site_name text NOT NULL,
        program_code text NOT NULL,
        site_type_code text NOT NULL,
        location_type_code text NOT NULL,
        setting_code text NOT NULL,
        site_status text NOT NULL,
        eligible boolean NOT NULL,
        location_status text NOT NULL,
        exclusion_reason text,
        boundary_check text NOT NULL,
        source_x text,
        source_y text,
        coordinate_decimals smallint,
        geom geometry(Point,4326),
        state_abbr text,
        city text,
        attributes jsonb NOT NULL,
        PRIMARY KEY (release_id, site_id),
        CONSTRAINT site_hrsa_location_status CHECK (location_status IN ({STATUSES})),
        CONSTRAINT site_hrsa_boundary_check CHECK (boundary_check IN
            ('within_published_county','outside_chip_boundary_layer','not_applicable')),
        CONSTRAINT site_hrsa_geom_only_when_mapped CHECK ((location_status = 'mapped') = (geom IS NOT NULL)),
        CONSTRAINT site_hrsa_reason_iff_excluded CHECK ((location_status = 'mapped') = (exclusion_reason IS NULL)),
        CONSTRAINT site_hrsa_mapped_boundary CHECK (location_status <> 'mapped' OR boundary_check <> 'not_applicable'),
        CONSTRAINT site_hrsa_suppressed_has_no_location CHECK (location_status <> 'suppressed_source_policy'
            OR (source_x IS NULL AND source_y IS NULL AND geom IS NULL
                AND attributes->>'site_address' IS NULL AND attributes->>'site_postal_code' IS NULL)))''')
    op.execute(f'''CREATE INDEX ix_area_site_hrsa_geom ON {S}.site_hrsa USING GIST (geom)
        WHERE location_status = 'mapped' ''')
    op.execute(f'''CREATE INDEX ix_area_site_hrsa_selection ON {S}.site_hrsa
        (release_id, location_status, eligible, program_code, site_type_code)''')
    op.execute(f'''CREATE INDEX ix_area_site_hrsa_table_order ON {S}.site_hrsa
        (release_id, state_abbr, city, site_name, site_id) WHERE location_status = 'mapped' ''')
    for table in ('stage_hrsa_site', 'site_hrsa'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('site_hrsa', 'stage_hrsa_site'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
        op.execute(f'DROP TABLE {S}.{table}')
