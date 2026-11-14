"""Independent USDA ERS Food Environment Atlas staging and county observations (additive).

The legacy usda_food_env.* tables are not touched; this product has its own release pointer.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'c8f1e4a7d3b6'
down_revision = 'b7e3c5a9d2f4'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    # Every source row of the five reviewed variables is staged, including boundary exceptions.
    op.create_table('stage_usda_fea',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('source_key', sa.Text, primary_key=True),
        sa.Column('source_fips', sa.Text, nullable=False),
        sa.Column('source_state', sa.Text, nullable=False),
        sa.Column('source_county', sa.Text, nullable=False),
        sa.Column('variable_code', sa.Text, nullable=False),
        sa.Column('source_value', sa.Text, nullable=False),
        sa.Column('geoid', sa.String(5)),
        sa.Column('boundary_status', sa.Text, nullable=False),
        sa.Column('exclusion_reason', sa.Text),
        sa.CheckConstraint("boundary_status IN ('matched','source_only')"),
        sa.CheckConstraint("boundary_status = 'source_only' OR (geoid IS NOT NULL AND exclusion_reason IS NULL)"),
        sa.CheckConstraint("boundary_status <> 'source_only' OR (geoid IS NULL AND exclusion_reason IS NOT NULL)"),
        schema=S)
    # Published county values only. Sentinel cells keep a NULL value and their own status.
    # 2024 boundary counties without a USDA row are labelled at read time and never stored.
    op.create_table('observation_usda_fea',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('geoid', sa.String(5), primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('variable_code', sa.Text, nullable=False),
        sa.Column('observation_period', sa.Text, nullable=False),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.Numeric),
        sa.Column('source_value', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('value_note', sa.Text),
        sa.Column('source_state', sa.Text, nullable=False),
        sa.Column('source_county', sa.Text, nullable=False),
        sa.CheckConstraint("geoid ~ '^[0-9]{5}$'"),
        sa.CheckConstraint("status IN ('available','true_zero','not_available','did_not_exist')"),
        sa.CheckConstraint("(value IS NULL) = (status IN ('not_available','did_not_exist'))"),
        sa.CheckConstraint("(value = 0) IS NOT TRUE OR status = 'true_zero'"),
        sa.CheckConstraint("status <> 'true_zero' OR value = 0"),
        sa.CheckConstraint('value IS NULL OR value >= 0'),
        schema=S)
    op.create_index('ix_area_usda_fea_selection', 'observation_usda_fea',
                    ['release_id', 'measure_id', 'geoid'], schema=S)
    for table in ('stage_usda_fea', 'observation_usda_fea'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('stage_usda_fea', 'observation_usda_fea'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
    op.drop_index('ix_area_usda_fea_selection', table_name='observation_usda_fea', schema=S)
    op.drop_table('observation_usda_fea', schema=S)
    op.drop_table('stage_usda_fea', schema=S)
