"""Mortality products: CDC heart disease and stroke, NCI cancer, NCHS drug poisoning (additive).

Each product has its own staging table, observation table, and release pointer.
Suppressed or insufficient-data cells keep a NULL value and status 'suppressed', never zero.
CHIP stores published rates only; it computes no rates, ranks, or totals.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = 'c3e7a1f5b9d2'
down_revision = 'a6c4e8b2d0f7'
branch_labels = None
depends_on = None
S = 'area_pilot'

# product -> (allowed levels, has a 95% interval)
PRODUCTS = {
    'cdc_hds_mortality': (('national', 'state', 'county'), False),
    'nci_cancer_mortality': (('national', 'state', 'county'), True),
    'nchs_drug_poisoning': (('county',), True),
}


def _levels(levels):
    return ', '.join(f"'{x}'" for x in levels)


def upgrade():
    for product, (levels, has_ci) in PRODUCTS.items():
        # Every selected source row is staged, including rows that do not match a 2024 boundary.
        op.create_table(f'stage_{product}',
            sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
            sa.Column('source_file', sa.Text, primary_key=True),
            sa.Column('source_level', sa.Text, primary_key=True),
            sa.Column('source_code', sa.Text, primary_key=True),
            sa.Column('source_period', sa.Text, primary_key=True),
            sa.Column('record', JSONB, nullable=False),
            sa.Column('geo_level', sa.Text),
            sa.Column('geoid', sa.String(5)),
            sa.Column('boundary_status', sa.Text, nullable=False),
            sa.Column('exclusion_reason', sa.Text),
            sa.CheckConstraint("boundary_status IN ('matched','national_reference','source_only')"),
            sa.CheckConstraint("boundary_status = 'source_only' OR (geoid IS NOT NULL AND exclusion_reason IS NULL)"),
            sa.CheckConstraint("boundary_status <> 'source_only' OR exclusion_reason IS NOT NULL"),
            schema=S)
        cols = [
            sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
            sa.Column('geo_level', sa.Text, primary_key=True),
            sa.Column('geoid', sa.String(5), primary_key=True),
            sa.Column('measure_id', sa.Text, primary_key=True),
            sa.Column('observation_period', sa.Text, primary_key=True),
            sa.Column('population', sa.Text, nullable=False),
            sa.Column('value_type', sa.Text, nullable=False),
            sa.Column('value', sa.Numeric(12, 5)),
            sa.Column('source_value', sa.Text, nullable=False),
            sa.Column('status', sa.Text, nullable=False),
        ]
        checks = [
            sa.CheckConstraint(f"geo_level IN ({_levels(levels)})"),
            sa.CheckConstraint("status IN ('available','suppressed')"),
            sa.CheckConstraint("(value IS NULL) = (status = 'suppressed')"),
            sa.CheckConstraint('value IS NULL OR value > 0'),
        ]
        if has_ci:
            cols += [sa.Column('ci_low', sa.Numeric(12, 5)), sa.Column('ci_high', sa.Numeric(12, 5))]
            checks += [
                sa.CheckConstraint('(ci_low IS NULL) = (ci_high IS NULL)'),
                sa.CheckConstraint('ci_low IS NULL OR value IS NULL OR (ci_low <= value AND value <= ci_high)'),
            ]
        op.create_table(f'observation_{product}', *cols, *checks, schema=S)
        op.create_index(f'ix_area_{product}_selection', f'observation_{product}',
                        ['release_id', 'measure_id', 'geo_level', 'geoid'], schema=S)
        for table in (f'stage_{product}', f'observation_{product}'):
            op.execute(f'''CREATE TRIGGER prevent_published_change BEFORE INSERT OR UPDATE OR DELETE ON {S}.{table}
                FOR EACH ROW EXECUTE FUNCTION {S}.prevent_published_data_change()''')


def downgrade():
    for product in PRODUCTS:
        for table in (f'stage_{product}', f'observation_{product}'):
            op.execute(f'DROP TRIGGER IF EXISTS prevent_published_change ON {S}.{table}')
        op.drop_index(f'ix_area_{product}_selection', table_name=f'observation_{product}', schema=S)
        op.drop_table(f'observation_{product}', schema=S)
        op.drop_table(f'stage_{product}', schema=S)
