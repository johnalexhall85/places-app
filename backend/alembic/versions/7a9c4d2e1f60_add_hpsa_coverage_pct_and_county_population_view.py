"""add hpsa coverage pct and county population view

Revision ID: 7a9c4d2e1f60
Revises: f1d3e2a9c7b4
Create Date: 2026-03-01 16:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7a9c4d2e1f60"
down_revision: Union[str, None] = "f1d3e2a9c7b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE VIEW v_county_population AS
        SELECT
            location_id::text AS county_fips,
            total_population::bigint AS population_total,
            total_pop_18_plus::bigint AS population_adult_18p
        FROM dim_county
        WHERE location_id ~ '^[0-9]{5}$'
        """
    )

    op.add_column(
        "county_hpsa_summary",
        sa.Column("pc_coverage_pct", sa.Numeric(precision=6, scale=3), nullable=True),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column("mh_coverage_pct", sa.Numeric(precision=6, scale=3), nullable=True),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column("dh_coverage_pct", sa.Numeric(precision=6, scale=3), nullable=True),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column("population_denominator_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "county_hpsa_summary",
        sa.Column("population_denominator", sa.Integer(), nullable=True),
    )

    op.create_check_constraint(
        "ck_county_hpsa_summary_pop_denom_type",
        "county_hpsa_summary",
        "population_denominator_type IS NULL OR population_denominator_type IN ('adult_18p', 'total')",
    )
    op.create_check_constraint(
        "ck_county_hpsa_summary_pc_coverage_pct",
        "county_hpsa_summary",
        "pc_coverage_pct IS NULL OR (pc_coverage_pct >= 0 AND pc_coverage_pct <= 100)",
    )
    op.create_check_constraint(
        "ck_county_hpsa_summary_mh_coverage_pct",
        "county_hpsa_summary",
        "mh_coverage_pct IS NULL OR (mh_coverage_pct >= 0 AND mh_coverage_pct <= 100)",
    )
    op.create_check_constraint(
        "ck_county_hpsa_summary_dh_coverage_pct",
        "county_hpsa_summary",
        "dh_coverage_pct IS NULL OR (dh_coverage_pct >= 0 AND dh_coverage_pct <= 100)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_county_hpsa_summary_dh_coverage_pct",
        "county_hpsa_summary",
        type_="check",
    )
    op.drop_constraint(
        "ck_county_hpsa_summary_mh_coverage_pct",
        "county_hpsa_summary",
        type_="check",
    )
    op.drop_constraint(
        "ck_county_hpsa_summary_pc_coverage_pct",
        "county_hpsa_summary",
        type_="check",
    )
    op.drop_constraint(
        "ck_county_hpsa_summary_pop_denom_type",
        "county_hpsa_summary",
        type_="check",
    )

    op.drop_column("county_hpsa_summary", "population_denominator")
    op.drop_column("county_hpsa_summary", "population_denominator_type")
    op.drop_column("county_hpsa_summary", "dh_coverage_pct")
    op.drop_column("county_hpsa_summary", "mh_coverage_pct")
    op.drop_column("county_hpsa_summary", "pc_coverage_pct")

    op.execute("DROP VIEW IF EXISTS v_county_population")
