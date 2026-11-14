"""Add release-keyed tract observations and CT planning-region boundaries."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'b42e7c9d1a60'
down_revision = 'a91c7e3f2b40'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    op.add_column('release', sa.Column('parent_county_release_id', UUID(as_uuid=True),
                                       sa.ForeignKey(f'{S}.release.id')), schema=S)
    op.create_table('stage_tract',
                    sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
                    sa.Column('tract_fips', sa.String(11), primary_key=True),
                    sa.Column('record', JSONB, nullable=False), schema=S)
    op.create_table('observation_tract',
                    sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
                    sa.Column('tract_fips', sa.String(11), primary_key=True),
                    sa.Column('measure_id', sa.Text, primary_key=True),
                    sa.Column('observation_period', sa.Text, nullable=False),
                    sa.Column('population', sa.Text, nullable=False),
                    sa.Column('value_type', sa.Text, nullable=False),
                    sa.Column('value', sa.Numeric(6, 2)),
                    sa.Column('ci_low', sa.Numeric(6, 2)),
                    sa.Column('ci_high', sa.Numeric(6, 2)),
                    sa.Column('status', sa.Text, nullable=False),
                    sa.CheckConstraint("status IN ('available','missing','suppressed','not_published')"), schema=S)
    op.create_index('ix_area_tract_observation_selection', 'observation_tract',
                    ['release_id', 'measure_id', 'tract_fips'], schema=S)
    op.execute(f'''CREATE TABLE {S}.tract_boundary_ct_2023 (
        tract_fips varchar(11) PRIMARY KEY,
        county_fips varchar(5) NOT NULL,
        name text NOT NULL,
        source_sha256 varchar(64) NOT NULL,
        geom geometry(MultiPolygon, 4326) NOT NULL
    )''')
    op.execute(f'CREATE INDEX ix_area_ct_tract_geom ON {S}.tract_boundary_ct_2023 USING GIST (geom)')
    op.execute(f'''CREATE FUNCTION {S}.prevent_published_data_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM {S}.release WHERE id=OLD.release_id AND status='published') THEN
        RAISE EXCEPTION 'Published area observations and staging are immutable';
      END IF;
      RETURN OLD;
    END $$''')
    for table in ('stage_county', 'observation', 'stage_tract', 'observation_tract'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('stage_county', 'observation', 'stage_tract', 'observation_tract'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
    op.execute(f'DROP FUNCTION {S}.prevent_published_data_change()')
    op.execute(f'DROP TABLE {S}.tract_boundary_ct_2023')
    op.drop_index('ix_area_tract_observation_selection', table_name='observation_tract', schema=S)
    op.drop_table('observation_tract', schema=S)
    op.drop_table('stage_tract', schema=S)
    op.drop_column('release', 'parent_county_release_id', schema=S)
