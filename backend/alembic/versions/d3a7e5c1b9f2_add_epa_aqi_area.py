"""Independent EPA AirData annual county AQI staging and observations (additive)."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'd3a7e5c1b9f2'
down_revision = 'c9f76d3a51e2'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    # Every source row is staged, including legitimate exclusions, with its mapping evidence.
    op.create_table('stage_epa_aqi',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('source_state', sa.Text, primary_key=True),
        sa.Column('source_county', sa.Text, primary_key=True),
        sa.Column('record', JSONB, nullable=False),
        sa.Column('epa_code', sa.String(5)),
        sa.Column('geoid', sa.String(5)),
        sa.Column('match_method', sa.Text, nullable=False),
        sa.Column('boundary_status', sa.Text, nullable=False),
        sa.Column('exclusion_reason', sa.Text),
        sa.Column('mapping', JSONB, nullable=False),
        sa.CheckConstraint("boundary_status IN ('matched','source_only')"),
        sa.CheckConstraint("boundary_status <> 'matched' OR (geoid IS NOT NULL AND exclusion_reason IS NULL)"),
        schema=S)
    # Only published source observations are stored; counties without a source row are never
    # filled with zeros. The read API labels them as having no reported value.
    op.create_table('observation_epa_aqi',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('geoid', sa.String(5), primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('observation_period', sa.Text, nullable=False),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.Integer, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('days_with_aqi', sa.Integer, nullable=False),
        sa.Column('value_note', sa.Text),
        sa.Column('source_state', sa.Text, nullable=False),
        sa.Column('source_county', sa.Text, nullable=False),
        sa.CheckConstraint("status IN ('available','true_zero')"),
        sa.CheckConstraint('value >= 0'),
        sa.CheckConstraint("(value = 0) = (status = 'true_zero')"),
        sa.CheckConstraint('days_with_aqi BETWEEN 1 AND 366'),
        schema=S)
    op.create_index('ix_area_epa_aqi_selection', 'observation_epa_aqi',
                    ['release_id', 'measure_id', 'geoid'], schema=S)
    for table in ('stage_epa_aqi', 'observation_epa_aqi'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('stage_epa_aqi', 'observation_epa_aqi'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
    op.drop_index('ix_area_epa_aqi_selection', table_name='observation_epa_aqi', schema=S)
    op.drop_table('observation_epa_aqi', schema=S)
    op.drop_table('stage_epa_aqi', schema=S)
