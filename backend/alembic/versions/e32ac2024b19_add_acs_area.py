"""Isolated ACS observations and 2024 boundaries in the shared area release lifecycle."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'e32ac2024b19'
down_revision = 'd128ba7f4c30'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    op.create_table('stage_acs',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('level', sa.Text, primary_key=True),
        sa.Column('geoid', sa.String(11), primary_key=True),
        sa.Column('record', JSONB, nullable=False),
        sa.CheckConstraint("level IN ('state','county','tract')"), schema=S)
    op.create_table('observation_acs',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('level', sa.Text, primary_key=True),
        sa.Column('geoid', sa.String(11), primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('observation_period', sa.Text, nullable=False),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.Numeric(12, 0)),
        sa.Column('moe', sa.Numeric(12, 0)),
        sa.Column('estimate_annotation', sa.Text),
        sa.Column('moe_annotation', sa.Text),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('moe_confidence', sa.SmallInteger, nullable=False, server_default='90'),
        sa.CheckConstraint("status IN ('available','true_zero','open_ended','missing','suppressed','not_applicable')"),
        sa.CheckConstraint('moe_confidence = 90'), schema=S)
    op.create_index('ix_area_acs_selection', 'observation_acs',
                    ['release_id', 'level', 'measure_id', 'geoid'], schema=S)
    op.execute(f'''CREATE TABLE {S}.acs_boundary_2024 (
        level text NOT NULL CHECK (level IN ('state','county','tract')),
        geoid varchar(11) NOT NULL,
        name text NOT NULL,
        source_sha256 varchar(64) NOT NULL,
        geom geometry(MultiPolygon,4326) NOT NULL,
        PRIMARY KEY (level,geoid)
    )''')
    op.execute(f'CREATE INDEX ix_area_acs_boundary_geom ON {S}.acs_boundary_2024 USING GIST (geom)')
    for table in ('stage_acs', 'observation_acs'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('stage_acs', 'observation_acs'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
    op.execute(f'DROP TABLE {S}.acs_boundary_2024')
    op.drop_index('ix_area_acs_selection', table_name='observation_acs', schema=S)
    op.drop_table('observation_acs', schema=S)
    op.drop_table('stage_acs', schema=S)
