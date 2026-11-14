"""Independent curated CLH staging and observations in the shared release lifecycle."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'c9f76d3a51e2'
down_revision = 'b75a2e184c60'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    op.create_table('stage_clh',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('level', sa.Text, primary_key=True),
        sa.Column('geoid', sa.String(11), primary_key=True),
        sa.Column('record', JSONB, nullable=False),
        sa.Column('boundary_status', sa.Text, nullable=False),
        sa.Column('exclusion_reason', sa.Text),
        sa.CheckConstraint("level IN ('county','tract')"),
        sa.CheckConstraint("boundary_status IN ('matched','source_only')"), schema=S)
    op.create_table('observation_clh',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('level', sa.Text, primary_key=True),
        sa.Column('geoid', sa.String(11), primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('observation_period', sa.Text, primary_key=True),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.Numeric(12, 4)),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('source_code', sa.Text),
        sa.CheckConstraint("level IN ('county','tract')"),
        sa.CheckConstraint("status IN ('available','true_zero','missing','suppressed','not_published','invalid_source')"),
        sa.CheckConstraint('value IS NULL OR value >= 0'), schema=S)
    op.create_index('ix_area_clh_selection', 'observation_clh',
                    ['release_id', 'level', 'measure_id', 'observation_period', 'geoid'], schema=S)
    for table in ('stage_clh', 'observation_clh'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('stage_clh', 'observation_clh'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
    op.drop_index('ix_area_clh_selection', table_name='observation_clh', schema=S)
    op.drop_table('observation_clh', schema=S)
    op.drop_table('stage_clh', schema=S)
