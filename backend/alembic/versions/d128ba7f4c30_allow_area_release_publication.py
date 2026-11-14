"""Correct release trigger return value on databases upgraded during Phase 2."""
from alembic import op

revision = 'd128ba7f4c30'
down_revision = 'c7d39e6a2b41'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('''CREATE OR REPLACE FUNCTION area_pilot.prevent_published_release_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.status='published' THEN
        RAISE EXCEPTION 'Published area release metadata are immutable';
      END IF;
      RETURN NEW;
    END $$''')


def downgrade():
    pass
