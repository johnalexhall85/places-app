"""Record lightweight source checks independently of candidate ingestion."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'f4b8e21c9a70'
down_revision = 'e32ac2024b19'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('source_check',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('dataset_id', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('detail', JSONB, nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('running','checked','held','failed','interrupted')"),
        schema='area_pilot')
    op.create_index('ix_area_source_check_latest', 'source_check',
                    ['dataset_id', 'started_at'], schema='area_pilot')


def downgrade():
    op.drop_index('ix_area_source_check_latest', table_name='source_check', schema='area_pilot')
    op.drop_table('source_check', schema='area_pilot')
