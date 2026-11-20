"""CDC/ATSDR Social Vulnerability Index 2022 staging and observations (additive).

The legacy svi_* tables are not touched; this product has its own release pointer.
Only the US-wide percentile ranks (RPL_*) are published. CDC's -999 is kept as
status 'not_available' with a NULL value, never zero.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'e2b8d4f6a1c3'
down_revision = 'f7c3a1d9e5b2'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    # Every source row is staged, including rows that do not match a 2024 boundary.
    op.create_table('stage_cdc_svi',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('source_level', sa.Text, primary_key=True),
        sa.Column('source_fips', sa.Text, primary_key=True),
        sa.Column('record', JSONB, nullable=False),
        sa.Column('geo_level', sa.Text),
        sa.Column('geoid', sa.String(11)),
        sa.Column('boundary_status', sa.Text, nullable=False),
        sa.Column('exclusion_reason', sa.Text),
        sa.CheckConstraint("source_level IN ('county','tract')"),
        sa.CheckConstraint("boundary_status IN ('matched','source_only')"),
        sa.CheckConstraint("boundary_status = 'source_only' OR (geoid IS NOT NULL AND exclusion_reason IS NULL)"),
        sa.CheckConstraint("boundary_status <> 'source_only' OR exclusion_reason IS NOT NULL"),
        schema=S)
    # Published ranks only (0-1). -999 cells keep a NULL value and status 'not_available'.
    op.create_table('observation_cdc_svi',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('geo_level', sa.Text, primary_key=True),
        sa.Column('geoid', sa.String(11), primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('observation_period', sa.Text, nullable=False),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.Numeric(6, 4)),
        sa.Column('source_value', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.CheckConstraint("geo_level IN ('county','tract')"),
        sa.CheckConstraint("status IN ('available','true_zero','not_available')"),
        sa.CheckConstraint("(value IS NULL) = (status = 'not_available')"),
        sa.CheckConstraint("(value = 0) IS NOT TRUE OR status = 'true_zero'"),
        sa.CheckConstraint("status <> 'true_zero' OR value = 0"),
        sa.CheckConstraint('value IS NULL OR (value >= 0 AND value <= 1)'),
        schema=S)
    op.create_index('ix_area_cdc_svi_selection', 'observation_cdc_svi',
                    ['release_id', 'measure_id', 'geo_level', 'geoid'], schema=S)
    for table in ('stage_cdc_svi', 'observation_cdc_svi'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('stage_cdc_svi', 'observation_cdc_svi'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
    op.drop_index('ix_area_cdc_svi_selection', table_name='observation_cdc_svi', schema=S)
    op.drop_table('observation_cdc_svi', schema=S)
    op.drop_table('stage_cdc_svi', schema=S)
