"""History values keep the source's full precision (unbounded numeric, as observation_usda_fea)."""
from alembic import op

revision = 'a8c2e6f0d4b1'
down_revision = 'f7d1a4c8e2b6'
branch_labels = None
depends_on = None


def upgrade():
    for column in ('value', 'low', 'high', 'moe'):
        op.execute(f'ALTER TABLE area_pilot.observation_history ALTER COLUMN {column} TYPE numeric')


def downgrade():
    for column in ('value', 'low', 'high', 'moe'):
        op.execute(f'ALTER TABLE area_pilot.observation_history ALTER COLUMN {column} TYPE numeric(18,6)')
