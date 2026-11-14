"""Distinguish metadata checks from full observation verification."""
from alembic import op
import sqlalchemy as sa

revision = 'a6c52d9e7b10'
down_revision = 'f4b8e21c9a70'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('source_check', sa.Column('mode', sa.Text, nullable=False,
                                            server_default='metadata'), schema='area_pilot')
    op.create_check_constraint('ck_area_source_check_mode', 'source_check',
                               "mode IN ('metadata','content')", schema='area_pilot')
    op.create_index('ix_area_source_check_mode_latest', 'source_check',
                    ['dataset_id', 'mode', 'started_at'], schema='area_pilot')


def downgrade():
    op.drop_index('ix_area_source_check_mode_latest', table_name='source_check', schema='area_pilot')
    op.drop_constraint('ck_area_source_check_mode', 'source_check', schema='area_pilot')
    op.drop_column('source_check', 'mode', schema='area_pilot')
