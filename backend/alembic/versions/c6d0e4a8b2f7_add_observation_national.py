"""National values published by a source itself (ACS 5-year U.S., CMS OM GV national), every period.

Read only through app.area_pilot.lookup.national_series. Built by `python -m app.area_pilot.national_cli`
under dataset pointer `chip_national_reference`. No value here is computed from states or counties.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = 'c6d0e4a8b2f7'
down_revision = 'b3f9d2a7c1e4'
branch_labels = None
depends_on = None
S = 'area_pilot'


def upgrade():
    op.create_table(
        'observation_national',
        sa.Column('release_id', UUID(as_uuid=True), sa.ForeignKey(f'{S}.release.id'), primary_key=True),
        sa.Column('product', sa.Text, primary_key=True),
        sa.Column('measure_id', sa.Text, primary_key=True),
        sa.Column('observation_period', sa.Text, primary_key=True),
        sa.Column('geoid', sa.Text, nullable=False),
        sa.Column('population', sa.Text, nullable=False),
        sa.Column('value_type', sa.Text, nullable=False),
        sa.Column('value', sa.Numeric),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('uncertainty_kind', sa.Text, nullable=False),
        sa.Column('low', sa.Numeric),
        sa.Column('high', sa.Numeric),
        sa.Column('moe', sa.Numeric),
        sa.Column('source_value', sa.Text, nullable=False),
        sa.Column('source_role', sa.Text, nullable=False),
        sa.CheckConstraint("geoid = 'US'"),
        sa.CheckConstraint("product IN ('acs','acs_profile','cms_gv')"),
        sa.CheckConstraint("uncertainty_kind IN ('moe90','none')"),
        sa.CheckConstraint("value IS NOT NULL OR status IN ('missing','suppressed','not_applicable')"),
        schema=S)


def downgrade():
    op.drop_table('observation_national', schema=S)
