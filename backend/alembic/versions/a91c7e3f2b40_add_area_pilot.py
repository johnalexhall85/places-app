"""Isolated, release-keyed county pilot storage."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'a91c7e3f2b40'
down_revision = 'e8f1a3c5d7b9'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    op.execute(f'CREATE SCHEMA IF NOT EXISTS {S}')
    op.create_table('release', sa.Column('id', UUID(as_uuid=True), primary_key=True), sa.Column('dataset_id', sa.Text, nullable=False), sa.Column('source_release_id', sa.Text, nullable=False), sa.Column('status', sa.Text, nullable=False), sa.Column('semantic_sha256', sa.String(64), nullable=False), sa.Column('schema_sha256', sa.String(64), nullable=False), sa.Column('metadata_sha256', sa.String(64), nullable=False), sa.Column('keyset_sha256', sa.String(64), nullable=False), sa.Column('source_before', JSONB, nullable=False), sa.Column('source_after', JSONB, nullable=False), sa.Column('report', JSONB, nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column('published_at', sa.DateTime(timezone=True)), schema=S)
    op.create_table('run', sa.Column('id', UUID(as_uuid=True), primary_key=True), sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id')), sa.Column('action', sa.Text, nullable=False), sa.Column('status', sa.Text, nullable=False), sa.Column('detail', JSONB, nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()), schema=S)
    op.create_table('source_file', sa.Column('id', UUID(as_uuid=True), primary_key=True), sa.Column('run_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.run.id'), nullable=False), sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id')), sa.Column('role', sa.Text, nullable=False), sa.Column('path', sa.Text, nullable=False), sa.Column('url', sa.Text, nullable=False), sa.Column('sha256', sa.String(64), nullable=False), sa.Column('byte_count', sa.Integer, nullable=False), sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False), schema=S)
    op.create_table('validation', sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True), sa.Column('check_name', sa.Text, primary_key=True), sa.Column('passed', sa.Boolean, nullable=False), sa.Column('detail', JSONB, nullable=False), schema=S)
    op.create_table('stage_county', sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True), sa.Column('county_fips', sa.String(5), primary_key=True), sa.Column('record', JSONB, nullable=False), schema=S)
    op.create_table('observation', sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True), sa.Column('county_fips', sa.String(5), primary_key=True), sa.Column('measure_id', sa.Text, primary_key=True), sa.Column('observation_period', sa.Text, nullable=False), sa.Column('population', sa.Text, nullable=False), sa.Column('value_type', sa.Text, nullable=False), sa.Column('value', sa.Numeric(6,2)), sa.Column('ci_low', sa.Numeric(6,2)), sa.Column('ci_high', sa.Numeric(6,2)), sa.Column('status', sa.Text, nullable=False), sa.CheckConstraint("status IN ('available','missing','suppressed','not_published')"), schema=S)
    op.create_index('ix_area_observation_selection', 'observation', ['release_id', 'measure_id', 'county_fips'], schema=S)
    op.create_table('active_release', sa.Column('dataset_id', sa.Text, primary_key=True), sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), schema=S)


def downgrade():
    for name in ('active_release','observation','stage_county','validation','source_file','run','release'):
        op.drop_table(name, schema=S)
    op.execute(f'DROP SCHEMA {S}')
