"""County AHRF observations in the shared area release lifecycle."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'b75a2e184c60'
down_revision = 'a6c52d9e7b10'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    op.create_table('stage_ahrf',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('geoid', sa.String(5), primary_key=True),
        sa.Column('record', JSONB, nullable=False), schema=S)
    op.create_table('observation_ahrf',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('geoid', sa.String(5), primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('observation_period', sa.Text, nullable=False),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.BigInteger),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('source_code', sa.Text),
        sa.CheckConstraint("status IN ('available','true_zero','missing','suppressed','not_published')"),
        sa.CheckConstraint('value IS NULL OR value >= 0'), schema=S)
    op.create_index('ix_area_ahrf_selection','observation_ahrf',
                    ['release_id','measure_id','geoid'],schema=S)
    for table in ('stage_ahrf','observation_ahrf'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('stage_ahrf','observation_ahrf'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
    op.drop_index('ix_area_ahrf_selection',table_name='observation_ahrf',schema=S)
    op.drop_table('observation_ahrf',schema=S)
    op.drop_table('stage_ahrf',schema=S)
