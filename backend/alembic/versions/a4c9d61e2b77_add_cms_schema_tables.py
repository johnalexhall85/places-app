"""add cms schema tables

Revision ID: a4c9d61e2b77
Revises: 9f4e6c1b2a10
Create Date: 2026-03-02 10:35:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a4c9d61e2b77"
down_revision: Union[str, None] = "9f4e6c1b2a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CMS_SCHEMA = "cms"


def upgrade() -> None:
    # NOTE: Alembic revisions are static; keep schema literal as "cms".
    # Runtime CMS_SCHEMA overrides require a future controlled migration.
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {CMS_SCHEMA}")

    op.create_table(
        "geo_dim",
        sa.Column("geo_level", sa.Text(), nullable=False),
        sa.Column("geo_code", sa.Text(), nullable=False),
        sa.Column("geo_name", sa.Text(), nullable=False),
        sa.Column("state_fips", sa.CHAR(length=2), nullable=True),
        sa.Column("county_fips", sa.CHAR(length=5), nullable=True),
        sa.CheckConstraint(
            "geo_level IN ('national','state','county')",
            name="geo_dim_geo_level_check",
        ),
        sa.PrimaryKeyConstraint("geo_level", "geo_code"),
        schema=CMS_SCHEMA,
    )
    op.create_index(
        "geo_dim_county_fips_idx",
        "geo_dim",
        ["county_fips"],
        unique=False,
        schema=CMS_SCHEMA,
    )
    op.create_index(
        "geo_dim_state_fips_idx",
        "geo_dim",
        ["state_fips"],
        unique=False,
        schema=CMS_SCHEMA,
    )

    op.create_table(
        "gv_measure_dim",
        sa.Column("measure_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'CMS FFS GV PUF'"),
        ),
        sa.PrimaryKeyConstraint("measure_id"),
        schema=CMS_SCHEMA,
    )

    op.create_table(
        "gv_fact",
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("geo_level", sa.Text(), nullable=False),
        sa.Column("geo_code", sa.Text(), nullable=False),
        sa.Column("age_level", sa.Text(), nullable=False),
        sa.Column("measure_id", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column(
            "is_suppressed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.PrimaryKeyConstraint(
            "year",
            "geo_level",
            "geo_code",
            "age_level",
            "measure_id",
        ),
        sa.ForeignKeyConstraint(
            ["geo_level", "geo_code"],
            [f"{CMS_SCHEMA}.geo_dim.geo_level", f"{CMS_SCHEMA}.geo_dim.geo_code"],
            name="gv_fact_geo_fk",
        ),
        sa.ForeignKeyConstraint(
            ["measure_id"],
            [f"{CMS_SCHEMA}.gv_measure_dim.measure_id"],
            name="gv_fact_measure_fk",
        ),
        schema=CMS_SCHEMA,
    )
    op.create_index(
        "gv_fact_measure_year_geo_idx",
        "gv_fact",
        ["measure_id", "year", "geo_level", "geo_code"],
        unique=False,
        schema=CMS_SCHEMA,
    )
    op.create_index(
        "gv_fact_geo_year_idx",
        "gv_fact",
        ["geo_level", "geo_code", "year"],
        unique=False,
        schema=CMS_SCHEMA,
    )

    op.create_table(
        "ssp_measure_dim",
        sa.Column("measure_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'CMS SSP County FFS PUF'"),
        ),
        sa.PrimaryKeyConstraint("measure_id"),
        schema=CMS_SCHEMA,
    )

    op.create_table(
        "ssp_fact",
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("county_fips", sa.CHAR(length=5), nullable=False),
        sa.Column("enrollment_type", sa.Text(), nullable=False),
        sa.Column("assign_window", sa.Text(), nullable=False),
        sa.Column("measure_id", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column(
            "is_suppressed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.PrimaryKeyConstraint(
            "year",
            "county_fips",
            "enrollment_type",
            "assign_window",
            "measure_id",
        ),
        sa.CheckConstraint(
            "assign_window IN ('calendar','offset')",
            name="ssp_fact_assign_window_check",
        ),
        sa.ForeignKeyConstraint(
            ["measure_id"],
            [f"{CMS_SCHEMA}.ssp_measure_dim.measure_id"],
            name="ssp_fact_measure_fk",
        ),
        schema=CMS_SCHEMA,
    )
    op.create_index(
        "ssp_fact_county_year_idx",
        "ssp_fact",
        ["county_fips", "year"],
        unique=False,
        schema=CMS_SCHEMA,
    )
    op.create_index(
        "ssp_fact_measure_year_idx",
        "ssp_fact",
        ["measure_id", "year"],
        unique=False,
        schema=CMS_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index("ssp_fact_measure_year_idx", table_name="ssp_fact", schema=CMS_SCHEMA)
    op.drop_index("ssp_fact_county_year_idx", table_name="ssp_fact", schema=CMS_SCHEMA)
    op.drop_table("ssp_fact", schema=CMS_SCHEMA)

    op.drop_table("ssp_measure_dim", schema=CMS_SCHEMA)

    op.drop_index("gv_fact_geo_year_idx", table_name="gv_fact", schema=CMS_SCHEMA)
    op.drop_index("gv_fact_measure_year_geo_idx", table_name="gv_fact", schema=CMS_SCHEMA)
    op.drop_table("gv_fact", schema=CMS_SCHEMA)

    op.drop_table("gv_measure_dim", schema=CMS_SCHEMA)

    op.drop_index("geo_dim_state_fips_idx", table_name="geo_dim", schema=CMS_SCHEMA)
    op.drop_index("geo_dim_county_fips_idx", table_name="geo_dim", schema=CMS_SCHEMA)
    op.drop_table("geo_dim", schema=CMS_SCHEMA)

    op.execute(f"DROP SCHEMA IF EXISTS {CMS_SCHEMA}")
