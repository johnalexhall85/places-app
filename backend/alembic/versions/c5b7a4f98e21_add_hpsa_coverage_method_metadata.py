"""add hpsa coverage method metadata

Revision ID: c5b7a4f98e21
Revises: 7a9c4d2e1f60
Create Date: 2026-03-01 16:45:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c5b7a4f98e21"
down_revision: Union[str, None] = "7a9c4d2e1f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COVERAGE_OVERLAP_CAVEAT = (
    "HPSA designated populations may overlap across partial-county, population-group, and "
    "facility designations. Population covered is aggregated conservatively using MAX to reduce "
    "double counting; coverage_pct should be interpreted as an approximate upper-bound proxy for "
    "coverage within the county."
)
COVERAGE_PCT_DEFINITION = (
    "coverage_pct = (population_covered / population_denominator) * 100, clamped to 0-100; "
    "population_denominator uses adult 18+ when available, otherwise total population."
)
COVERAGE_METHOD_TEXT = (
    "MAX designated population among active designations in county (conservative; overlaps possible)"
)


def upgrade() -> None:
    op.add_column(
        "county_hpsa_summary",
        sa.Column("population_denominator_source", sa.Text(), nullable=True),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column(
            "coverage_population_aggregation_method",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'MAX'"),
        ),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column(
            "coverage_overlap_caveat",
            sa.Text(),
            nullable=False,
            server_default=sa.text(f"'{COVERAGE_OVERLAP_CAVEAT}'"),
        ),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column(
            "coverage_pct_definition",
            sa.Text(),
            nullable=False,
            server_default=sa.text(f"'{COVERAGE_PCT_DEFINITION}'"),
        ),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column(
            "pc_coverage_method",
            sa.Text(),
            nullable=False,
            server_default=sa.text(f"'{COVERAGE_METHOD_TEXT}'"),
        ),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column(
            "mh_coverage_method",
            sa.Text(),
            nullable=False,
            server_default=sa.text(f"'{COVERAGE_METHOD_TEXT}'"),
        ),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column(
            "dh_coverage_method",
            sa.Text(),
            nullable=False,
            server_default=sa.text(f"'{COVERAGE_METHOD_TEXT}'"),
        ),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column("raw_rows_in_county_pc", sa.Integer(), nullable=True),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column("raw_rows_in_county_mh", sa.Integer(), nullable=True),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column("raw_rows_in_county_dh", sa.Integer(), nullable=True),
    )

    op.create_check_constraint(
        "ck_county_hpsa_summary_cov_agg_method",
        "county_hpsa_summary",
        "coverage_population_aggregation_method = 'MAX'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_county_hpsa_summary_cov_agg_method",
        "county_hpsa_summary",
        type_="check",
    )

    op.drop_column("county_hpsa_summary", "raw_rows_in_county_dh")
    op.drop_column("county_hpsa_summary", "raw_rows_in_county_mh")
    op.drop_column("county_hpsa_summary", "raw_rows_in_county_pc")
    op.drop_column("county_hpsa_summary", "dh_coverage_method")
    op.drop_column("county_hpsa_summary", "mh_coverage_method")
    op.drop_column("county_hpsa_summary", "pc_coverage_method")
    op.drop_column("county_hpsa_summary", "coverage_pct_definition")
    op.drop_column("county_hpsa_summary", "coverage_overlap_caveat")
    op.drop_column("county_hpsa_summary", "coverage_population_aggregation_method")
    op.drop_column("county_hpsa_summary", "population_denominator_source")
