"""CDC BRFSS state prevalence (additive).

A new independent product with its own staging and observation tables and its own release
pointer. No existing table is changed.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'e6b3a8d0f2c5'
down_revision = 'd5a2f7c9e1b4'
branch_labels = None
depends_on = None
S = 'area_pilot'
KEY = "geoid ~ '^[0-9]{2}$'"


def upgrade():
    # One original source row per (measure, location).
    op.create_table('stage_brfss',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('geoid', sa.Text, primary_key=True),
        sa.Column('record', JSONB, nullable=False),
        sa.CheckConstraint(KEY),
        schema=S)
    # Published values only. `geoid` is CDC's two-digit location code: a state FIPS, a territory
    # without a CHIP boundary (source_only), or one of CDC's two median rows (98, 99).
    op.create_table('observation_brfss',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('geoid', sa.Text, primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('observation_period', sa.Text, nullable=False),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.Numeric),
        sa.Column('ci_low', sa.Numeric),
        sa.Column('ci_high', sa.Numeric),
        sa.Column('sample_size', sa.Integer),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('location_kind', sa.Text, nullable=False),
        sa.CheckConstraint(KEY),
        sa.CheckConstraint("status IN ('available','true_zero','not_available')"),
        sa.CheckConstraint("location_kind IN ('state','source_only','median')"),
        sa.CheckConstraint("(value IS NULL) = (status = 'not_available')"),
        sa.CheckConstraint("(value = 0) = (status = 'true_zero') OR value IS NULL"),
        sa.CheckConstraint('value IS NULL OR (value >= 0 AND value <= 100)'),
        sa.CheckConstraint('(ci_low IS NULL) = (ci_high IS NULL)'),
        sa.CheckConstraint('ci_low IS NULL OR (value IS NOT NULL AND ci_low <= value AND value <= ci_high)'),
        # CDC publishes its medians without confidence limits; every other published value has them.
        sa.CheckConstraint("(location_kind = 'median' AND ci_low IS NULL) OR "
                           "(location_kind <> 'median' AND (ci_low IS NULL) = (value IS NULL))"),
        sa.CheckConstraint("value_type = 'crude_prevalence'"),
        sa.CheckConstraint('sample_size IS NULL OR sample_size >= 0'),
        schema=S)
    op.create_index('ix_area_brfss_selection', 'observation_brfss', ['release_id', 'measure_id', 'geoid'], schema=S)
    for table in ('stage_brfss', 'observation_brfss'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('stage_brfss', 'observation_brfss'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
    op.drop_index('ix_area_brfss_selection', table_name='observation_brfss', schema=S)
    op.drop_table('observation_brfss', schema=S)
    op.drop_table('stage_brfss', schema=S)
