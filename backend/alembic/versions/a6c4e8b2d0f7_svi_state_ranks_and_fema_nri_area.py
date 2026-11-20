"""SVI state-ranked files and the FEMA National Risk Index v1.20 product (additive).

1. stage_cdc_svi gains source_scope ('us' or 'state') so the US-ranked and the
   state-ranked CDC files can both be staged for one FIPS. Existing staged rows are 'us'.
2. FEMA NRI v1.20 staging and observations for states, counties, and tracts. Ratings
   are FEMA's labels, stored beside the value. A blank FEMA cell, or a state percentile
   that FEMA writes as 0 where its score is blank, is 'not_available' with a NULL value.
The legacy fema_nri.* tables are not touched.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'a6c4e8b2d0f7'
down_revision = 'e2b8d4f6a1c3'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    op.add_column('stage_cdc_svi', sa.Column('source_scope', sa.Text, nullable=False, server_default='us'), schema=S)
    op.create_check_constraint('ck_stage_cdc_svi_scope', 'stage_cdc_svi', "source_scope IN ('us','state')", schema=S)
    op.execute(f'ALTER TABLE {S}.stage_cdc_svi DROP CONSTRAINT stage_cdc_svi_pkey')
    op.execute(f'ALTER TABLE {S}.stage_cdc_svi ADD PRIMARY KEY (release_id, source_scope, source_level, source_fips)')

    # Staged record holds only the selected fields plus identifiers, not all ~466 FEMA columns.
    op.create_table('stage_fema_nri',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('source_level', sa.Text, primary_key=True),
        sa.Column('source_fips', sa.Text, primary_key=True),
        sa.Column('record', JSONB, nullable=False),
        sa.Column('geo_level', sa.Text),
        sa.Column('geoid', sa.String(11)),
        sa.Column('boundary_status', sa.Text, nullable=False),
        sa.Column('exclusion_reason', sa.Text),
        sa.CheckConstraint("source_level IN ('state','county','tract')"),
        sa.CheckConstraint("boundary_status IN ('matched','source_only')"),
        sa.CheckConstraint("boundary_status = 'source_only' OR (geoid IS NOT NULL AND exclusion_reason IS NULL)"),
        sa.CheckConstraint("boundary_status <> 'source_only' OR exclusion_reason IS NOT NULL"),
        schema=S)
    op.create_table('observation_fema_nri',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('geo_level', sa.Text, primary_key=True),
        sa.Column('geoid', sa.String(11), primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('observation_period', sa.Text, nullable=False),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.Numeric(20, 4)),
        sa.Column('source_value', sa.Text, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('rating', sa.Text),
        sa.CheckConstraint("geo_level IN ('state','county','tract')"),
        sa.CheckConstraint("status IN ('available','true_zero','not_available')"),
        sa.CheckConstraint("(value IS NULL) = (status = 'not_available')"),
        sa.CheckConstraint("(value = 0) IS NOT TRUE OR status = 'true_zero'"),
        sa.CheckConstraint("status <> 'true_zero' OR value = 0"),
        sa.CheckConstraint('value IS NULL OR value >= 0'),
        schema=S)
    op.create_index('ix_area_fema_nri_selection', 'observation_fema_nri',
                    ['release_id', 'measure_id', 'geo_level', 'geoid'], schema=S)
    for table in ('stage_fema_nri', 'observation_fema_nri'):
        op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.{table}
            FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for table in ('stage_fema_nri', 'observation_fema_nri'):
        op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
    op.drop_index('ix_area_fema_nri_selection', table_name='observation_fema_nri', schema=S)
    op.drop_table('observation_fema_nri', schema=S)
    op.drop_table('stage_fema_nri', schema=S)
    op.execute(f"DELETE FROM {S}.stage_cdc_svi WHERE source_scope = 'state'")
    op.execute(f'ALTER TABLE {S}.stage_cdc_svi DROP CONSTRAINT stage_cdc_svi_pkey')
    op.execute(f'ALTER TABLE {S}.stage_cdc_svi ADD PRIMARY KEY (release_id, source_level, source_fips)')
    op.drop_constraint('ck_stage_cdc_svi_scope', 'stage_cdc_svi', schema=S)
    op.drop_column('stage_cdc_svi', 'source_scope', schema=S)
