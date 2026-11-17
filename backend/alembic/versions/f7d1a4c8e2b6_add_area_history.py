"""Historical periods for shared area products (additive).

Earlier periods live in their own release per product (dataset_id '<current>:history') and their
own observation table, so the current pointers, observation tables, and profiles are untouched.
Older boundaries (TIGER 2020 counties and tracts with the old Connecticut geography, TIGER 2019
tracts on the 2010 Census basis) are kept apart from acs_boundary_2024.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'f7d1a4c8e2b6'
down_revision = 'e6b3a8d0f2c5'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    op.execute(f'''CREATE TABLE {S}.history_boundary (
        vintage text NOT NULL CHECK (vintage IN ('2019','2020')),
        level text NOT NULL CHECK (level IN ('county','tract')),
        geoid varchar(11) NOT NULL,
        name text NOT NULL,
        source_sha256 varchar(64) NOT NULL,
        geom geometry(MultiPolygon,4326) NOT NULL,
        PRIMARY KEY (vintage, level, geoid),
        CHECK ((level = 'county' AND length(geoid) = 5) OR (level = 'tract' AND length(geoid) = 11)))''')
    op.execute(f'CREATE INDEX ix_area_history_boundary_geom ON {S}.history_boundary USING gist (geom)')

    op.create_table('observation_history',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('level', sa.Text, primary_key=True),
        sa.Column('geoid', sa.String(11), primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('observation_period', sa.Text, primary_key=True),
        sa.Column('part', sa.Text, nullable=False),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.Numeric(18, 6)),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('uncertainty_kind', sa.Text, nullable=False),
        sa.Column('low', sa.Numeric(18, 6)),
        sa.Column('high', sa.Numeric(18, 6)),
        sa.Column('moe', sa.Numeric(18, 6)),
        sa.Column('source_value', sa.Text, nullable=False),
        sa.Column('boundary_vintage', sa.Text, nullable=False),
        sa.CheckConstraint("level IN ('state','county','tract')"),
        sa.CheckConstraint("uncertainty_kind IN ('ci95','moe90','none')"),
        sa.CheckConstraint("boundary_vintage IN ('2019','2020','2024')"),
        sa.CheckConstraint("uncertainty_kind <> 'none' OR (low IS NULL AND high IS NULL AND moe IS NULL)"),
        sa.CheckConstraint("uncertainty_kind <> 'ci95' OR moe IS NULL"),
        sa.CheckConstraint("uncertainty_kind <> 'moe90' OR (low IS NULL AND high IS NULL)"),
        schema=S)
    op.create_index('ix_area_history_selection', 'observation_history',
                    ['release_id', 'measure_id', 'observation_period', 'level', 'geoid'], schema=S)
    op.create_index('ix_area_history_part', 'observation_history', ['release_id', 'part'], schema=S)
    op.create_index('ix_area_history_area', 'observation_history',
                    ['release_id', 'level', 'geoid', 'measure_id'], schema=S)
    op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.observation_history
        FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.observation_history')
    op.drop_table('observation_history', schema=S)
    op.execute(f'DROP TABLE {S}.history_boundary')
