"""ACS 2020-2024 community characteristics and 119th Congress district boundaries (additive).

A new independent product with its own staging, observation, and boundary tables and its own
release pointer. The published B19013 product (stage_acs, observation_acs) is not touched.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'd5a2f7c9e1b4'
down_revision = 'c8f1e4a7d3b6'
branch_labels = None
depends_on = None
S = 'area_pilot'
LEVELS = "level IN ('state','county','tract','cd')"
KEYS = ("(level='state' AND geoid ~ '^[0-9]{2}$') OR (level='county' AND geoid ~ '^[0-9]{5}$') OR "
        "(level='tract' AND geoid ~ '^[0-9]{11}$') OR (level='cd' AND geoid ~ '^[0-9]{4}$')")


def upgrade():
    # Official TIGER/Line 2024 shapes for the 119th Congress: 435 districts plus the DC and PR delegates.
    op.create_table('cd_boundary_119',
        sa.Column('geoid', sa.String(4), primary_key=True),
        sa.Column('state_fips', sa.String(2), nullable=False),
        sa.Column('district_code', sa.String(2), nullable=False),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('source_sha256', sa.String(64), nullable=False),
        sa.CheckConstraint("geoid ~ '^[0-9]{4}$' AND geoid = state_fips || district_code"),
        schema=S)
    op.execute(f"SELECT AddGeometryColumn('{S}','cd_boundary_119','geom',4326,'MULTIPOLYGON',2)")
    op.execute(f'ALTER TABLE {S}.cd_boundary_119 ALTER COLUMN geom SET NOT NULL')
    op.execute(f'CREATE INDEX ix_area_cd_boundary_119_geom ON {S}.cd_boundary_119 USING gist (geom)')
    # One original API row per published geography.
    op.create_table('stage_acs_profile',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('level', sa.Text, primary_key=True),
        sa.Column('geoid', sa.Text, primary_key=True),
        sa.Column('record', JSONB, nullable=False),
        sa.CheckConstraint(LEVELS), sa.CheckConstraint(KEYS),
        schema=S)
    # Published estimates only. A Census code instead of an estimate keeps a NULL value and its own status.
    op.create_table('observation_acs_profile',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('level', sa.Text, primary_key=True),
        sa.Column('geoid', sa.Text, primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('observation_period', sa.Text, nullable=False),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.Numeric),
        sa.Column('moe', sa.Numeric),
        sa.Column('estimate_annotation', sa.Text),
        sa.Column('moe_annotation', sa.Text),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('moe_confidence', sa.SmallInteger, nullable=False),
        sa.CheckConstraint(LEVELS), sa.CheckConstraint(KEYS),
        sa.CheckConstraint("status IN ('available','true_zero','missing','suppressed','not_applicable')"),
        sa.CheckConstraint("(value IS NULL) = (status IN ('missing','suppressed','not_applicable'))"),
        sa.CheckConstraint("(value = 0) = (status = 'true_zero') OR value IS NULL"),
        sa.CheckConstraint('value IS NULL OR value >= 0'),
        sa.CheckConstraint('moe IS NULL OR (moe >= 0 AND value IS NOT NULL)'),
        sa.CheckConstraint('moe_confidence = 90'),
        schema=S)
    op.create_index('ix_area_acs_profile_selection', 'observation_acs_profile',
                    ['release_id', 'level', 'measure_id', 'geoid'], schema=S)
    for table in ('stage_acs_profile', 'observation_acs_profile'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('stage_acs_profile', 'observation_acs_profile'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
    op.drop_index('ix_area_acs_profile_selection', table_name='observation_acs_profile', schema=S)
    op.drop_table('observation_acs_profile', schema=S)
    op.drop_table('stage_acs_profile', schema=S)
    op.drop_table('cd_boundary_119', schema=S)
