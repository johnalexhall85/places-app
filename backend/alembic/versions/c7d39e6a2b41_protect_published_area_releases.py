"""Prevent changes or late inserts to published pilot content."""
from alembic import op

revision = 'c7d39e6a2b41'
down_revision = 'b42e7c9d1a60'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    op.execute(f'''CREATE OR REPLACE FUNCTION {S}.prevent_published_data_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE target_release uuid;
    BEGIN
      target_release := CASE WHEN TG_OP = 'INSERT' THEN NEW.release_id ELSE OLD.release_id END;
      IF EXISTS (SELECT 1 FROM {S}.release WHERE id=target_release AND status='published') THEN
        RAISE EXCEPTION 'Published area observations and staging are immutable';
      END IF;
      IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
      RETURN NEW;
    END $$''')
    for table in ('stage_county', 'observation', 'stage_tract', 'observation_tract'):
        op.execute(f'DROP TRIGGER prevent_published_change ON {S}.{table}')
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')
    op.execute(f'''CREATE FUNCTION {S}.prevent_published_release_change() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      IF OLD.status='published' THEN
        RAISE EXCEPTION 'Published area release metadata are immutable';
      END IF;
      RETURN NEW;
    END $$''')
    op.execute(f'''CREATE TRIGGER prevent_published_release_change BEFORE UPDATE OR DELETE ON {S}.release
        FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_release_change()''')


def downgrade():
    op.execute(f'DROP TRIGGER prevent_published_release_change ON {S}.release')
    op.execute(f'DROP FUNCTION {S}.prevent_published_release_change()')
    for table in ('stage_county', 'observation', 'stage_tract', 'observation_tract'):
        op.execute(f'DROP TRIGGER prevent_published_change ON {S}.{table}')
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')
    op.execute(f'''CREATE OR REPLACE FUNCTION {S}.prevent_published_data_change() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF EXISTS (SELECT 1 FROM {S}.release WHERE id=OLD.release_id AND status='published') THEN
        RAISE EXCEPTION 'Published area observations and staging are immutable';
      END IF;
      RETURN OLD;
    END $$''')
