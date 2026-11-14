"""Independent CMS Original Medicare Geographic Variation staging and observations (additive).

The legacy cms.gv_* tables are not touched; this product has its own release pointer.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'b7e3c5a9d2f4'
down_revision = 'a4d9e7c2b6f1'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    # Every selected source row (latest year, All age level) is staged, including exclusions.
    op.create_table('stage_cms_gv',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('source_level', sa.Text, primary_key=True),
        sa.Column('source_code', sa.Text, primary_key=True),
        sa.Column('source_desc', sa.Text, primary_key=True),
        sa.Column('record', JSONB, nullable=False),
        sa.Column('geo_level', sa.Text),
        sa.Column('geoid', sa.String(5)),
        sa.Column('boundary_status', sa.Text, nullable=False),
        sa.Column('exclusion_reason', sa.Text),
        sa.CheckConstraint("boundary_status IN ('matched','national_reference','source_only')"),
        sa.CheckConstraint("boundary_status = 'source_only' OR (geoid IS NOT NULL AND exclusion_reason IS NULL)"),
        sa.CheckConstraint("boundary_status <> 'source_only' OR exclusion_reason IS NOT NULL"),
        schema=S)
    # Published values only. Suppressed and missing cells keep a NULL value and their own status.
    # Boundary areas without a CMS row are labelled at read time and never stored.
    op.create_table('observation_cms_gv',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('geo_level', sa.Text, primary_key=True),
        sa.Column('geoid', sa.String(5), primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('observation_period', sa.Text, nullable=False),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.Numeric(18, 4)),
        sa.Column('source_value', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('source_desc', sa.Text, nullable=False),
        sa.CheckConstraint("geo_level IN ('national','state','county')"),
        sa.CheckConstraint("status IN ('available','true_zero','suppressed','missing')"),
        sa.CheckConstraint("(value IS NULL) = (status IN ('suppressed','missing'))"),
        sa.CheckConstraint("(value = 0) IS NOT TRUE OR status = 'true_zero'"),
        sa.CheckConstraint("status <> 'true_zero' OR value = 0"),
        sa.CheckConstraint('value IS NULL OR value >= 0'),
        schema=S)
    op.create_index('ix_area_cms_gv_selection', 'observation_cms_gv',
                    ['release_id', 'measure_id', 'geo_level', 'geoid'], schema=S)
    for table in ('stage_cms_gv', 'observation_cms_gv'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('stage_cms_gv', 'observation_cms_gv'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
    op.drop_index('ix_area_cms_gv_selection', table_name='observation_cms_gv', schema=S)
    op.drop_table('observation_cms_gv', schema=S)
    op.drop_table('stage_cms_gv', schema=S)
