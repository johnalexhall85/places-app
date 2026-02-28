"""add svi tables

Revision ID: 0d78b6f9a4c2
Revises: 1c5f1af63f2b
Create Date: 2026-02-28 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0d78b6f9a4c2"
down_revision: Union[str, None] = "1c5f1af63f2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "svi_measures",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("measure_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("theme", sa.String(), nullable=True),
        sa.Column("value_type", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("geography_level", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "measure_id",
            "year",
            "geography_level",
            name="uq_svi_measure",
        ),
    )
    op.create_index(
        "idx_svi_measures_year_geo",
        "svi_measures",
        ["year", "geography_level"],
        unique=False,
    )

    op.create_table(
        "svi_estimates_county",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("geoid", sa.String(length=5), nullable=False),
        sa.Column("measure_id", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "geoid",
            "measure_id",
            "year",
            name="uq_svi_county_estimate",
        ),
    )
    op.create_index(
        "idx_svi_county_year_measure",
        "svi_estimates_county",
        ["year", "measure_id"],
        unique=False,
    )
    op.create_index(
        "idx_svi_county_geoid",
        "svi_estimates_county",
        ["geoid"],
        unique=False,
    )

    op.create_table(
        "svi_estimates_tract",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("geoid", sa.String(length=11), nullable=False),
        sa.Column("measure_id", sa.String(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "geoid",
            "measure_id",
            "year",
            name="uq_svi_tract_estimate",
        ),
    )
    op.create_index(
        "idx_svi_tract_year_measure",
        "svi_estimates_tract",
        ["year", "measure_id"],
        unique=False,
    )
    op.create_index(
        "idx_svi_tract_geoid",
        "svi_estimates_tract",
        ["geoid"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_svi_tract_geoid", table_name="svi_estimates_tract")
    op.drop_index("idx_svi_tract_year_measure", table_name="svi_estimates_tract")
    op.drop_table("svi_estimates_tract")

    op.drop_index("idx_svi_county_geoid", table_name="svi_estimates_county")
    op.drop_index("idx_svi_county_year_measure", table_name="svi_estimates_county")
    op.drop_table("svi_estimates_county")

    op.drop_index("idx_svi_measures_year_geo", table_name="svi_measures")
    op.drop_table("svi_measures")

