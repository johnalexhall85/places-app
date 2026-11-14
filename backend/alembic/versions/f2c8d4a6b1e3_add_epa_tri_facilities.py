"""Release-keyed EPA TRI reporting facilities (additive; separate from area observations and HRSA sites).

Grain per candidate release:
- ``stage_tri_report``: every source form verbatim (JSON array in reviewed header order), keyed by
  DOC_CTRL_NUM. Never read by the API.
- ``tri_report``: one typed row per form, without any release or waste quantity.
- ``tri_chemical``: one row per TRI chemical ID with every published name.
- ``tri_facility``: one row per TRIFD; only ``location_status='mapped'`` rows carry a point.
- ``tri_facility_chemical``: one row per (TRIFD, chemical ID) with the number of forms and form types.
"""
from alembic import op

revision = 'f2c8d4a6b1e3'
down_revision = 'e9b3f6a2c4d8'
branch_labels = None
depends_on = None
S = 'area_pilot'
TABLES = ('stage_tri_report', 'tri_report', 'tri_chemical', 'tri_facility', 'tri_facility_chemical')


def upgrade():
    op.execute(f'''CREATE TABLE {S}.stage_tri_report (
        release_id uuid NOT NULL REFERENCES {S}.release(id),
        doc_ctrl_num text NOT NULL,
        line_number integer NOT NULL,
        record jsonb NOT NULL,
        PRIMARY KEY (release_id, doc_ctrl_num),
        CONSTRAINT stage_tri_report_record_array CHECK (jsonb_typeof(record) = 'array'))''')
    op.execute(f'''CREATE TABLE {S}.tri_report (
        release_id uuid NOT NULL REFERENCES {S}.release(id),
        doc_ctrl_num text NOT NULL,
        facility_id text NOT NULL,
        chemical_id text NOT NULL,
        chemical_name text NOT NULL,
        form_type text NOT NULL,
        industry_sector_code text NOT NULL,
        industry_sector text NOT NULL,
        primary_naics text,
        elemental_metal_included text,
        PRIMARY KEY (release_id, doc_ctrl_num),
        CONSTRAINT tri_report_form_type CHECK (form_type IN ('R','A')))''')
    op.execute(f'CREATE INDEX ix_area_tri_report_facility ON {S}.tri_report (release_id, facility_id)')
    op.execute(f'''CREATE TABLE {S}.tri_chemical (
        release_id uuid NOT NULL REFERENCES {S}.release(id),
        chemical_id text NOT NULL,
        names text[] NOT NULL,
        cas_number text,
        srs_id text,
        classification text,
        attributes jsonb NOT NULL,
        report_count integer NOT NULL,
        facility_count integer NOT NULL,
        PRIMARY KEY (release_id, chemical_id),
        CONSTRAINT tri_chemical_has_name CHECK (cardinality(names) > 0))''')
    op.execute(f'''CREATE TABLE {S}.tri_facility (
        release_id uuid NOT NULL REFERENCES {S}.release(id),
        facility_id text NOT NULL,
        record_sha256 varchar(64) NOT NULL,
        frs_id text,
        facility_name text NOT NULL,
        city text,
        county_name text,
        state_abbr text,
        sector_codes text[] NOT NULL,
        naics_codes text[] NOT NULL,
        report_count integer NOT NULL,
        form_r_count integer NOT NULL,
        form_a_count integer NOT NULL,
        chemical_count integer NOT NULL,
        location_status text NOT NULL,
        exclusion_reason text,
        boundary_check text NOT NULL,
        derived_county_geoid varchar(5),
        source_latitude text,
        source_longitude text,
        coordinate_decimals smallint,
        geom geometry(Point,4326),
        attributes jsonb NOT NULL,
        PRIMARY KEY (release_id, facility_id),
        CONSTRAINT tri_facility_location_status CHECK (location_status IN
            ('mapped','no_published_coordinates','invalid_coordinates','coarse_coordinate')),
        CONSTRAINT tri_facility_boundary_check CHECK (boundary_check IN
            ('within_published_state','outside_published_state','outside_chip_boundary_layer','not_applicable')),
        CONSTRAINT tri_facility_geom_only_when_mapped CHECK ((location_status = 'mapped') = (geom IS NOT NULL)),
        CONSTRAINT tri_facility_reason_iff_excluded CHECK ((location_status = 'mapped') = (exclusion_reason IS NULL)),
        CONSTRAINT tri_facility_mapped_boundary CHECK ((location_status = 'mapped') = (boundary_check <> 'not_applicable')),
        CONSTRAINT tri_facility_counts CHECK (report_count = form_r_count + form_a_count AND report_count > 0
            AND chemical_count > 0 AND cardinality(sector_codes) > 0))''')
    op.execute(f'''CREATE INDEX ix_area_tri_facility_geom ON {S}.tri_facility USING GIST (geom)
        WHERE location_status = 'mapped' ''')
    op.execute(f'''CREATE INDEX ix_area_tri_facility_table_order ON {S}.tri_facility
        (release_id, state_abbr, city, facility_name, facility_id) WHERE location_status = 'mapped' ''')
    op.execute(f'''CREATE TABLE {S}.tri_facility_chemical (
        release_id uuid NOT NULL REFERENCES {S}.release(id),
        facility_id text NOT NULL,
        chemical_id text NOT NULL,
        report_count integer NOT NULL,
        form_types text[] NOT NULL,
        names text[] NOT NULL,
        PRIMARY KEY (release_id, facility_id, chemical_id),
        FOREIGN KEY (release_id, facility_id) REFERENCES {S}.tri_facility (release_id, facility_id),
        FOREIGN KEY (release_id, chemical_id) REFERENCES {S}.tri_chemical (release_id, chemical_id),
        CONSTRAINT tri_facility_chemical_reports CHECK (report_count > 0))''')
    op.execute(f'''CREATE INDEX ix_area_tri_facility_chemical_by_chemical ON {S}.tri_facility_chemical
        (release_id, chemical_id, facility_id)''')
    for table in TABLES:
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in reversed(TABLES):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
        op.execute(f'DROP TABLE {S}.{table}')
