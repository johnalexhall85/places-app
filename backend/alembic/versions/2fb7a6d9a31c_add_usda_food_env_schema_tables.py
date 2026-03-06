"""add usda food environment schema tables

Revision ID: 2fb7a6d9a31c
Revises: d4a3e8c11f90
Create Date: 2026-03-05 16:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2fb7a6d9a31c"
down_revision: Union[str, None] = "d4a3e8c11f90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USDA_ENV_SCHEMA = "usda_food_env"


def upgrade() -> None:
    # NOTE: Alembic revisions are static; keep schema literal as "usda_food_env".
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {USDA_ENV_SCHEMA}")

    op.create_table(
        "variable_lookup",
        sa.Column("var_name", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=True),
        sa.Column("year_start", sa.Integer(), nullable=True),
        sa.Column("year_end", sa.Integer(), nullable=True),
        sa.Column(
            "is_mapped",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("var_name"),
        schema=USDA_ENV_SCHEMA,
    )

    op.create_table(
        "county_values",
        sa.Column("geoid", sa.Text(), nullable=False),
        sa.Column("state_fips", sa.Text(), nullable=False),
        sa.Column("county_fips", sa.Text(), nullable=False),
        sa.Column("state_abbr", sa.Text(), nullable=True),
        sa.Column("county_name", sa.Text(), nullable=True),
        sa.Column("state_name", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("geoid"),
        schema=USDA_ENV_SCHEMA,
    )
    op.create_index(
        "county_values_state_fips_idx",
        "county_values",
        ["state_fips"],
        unique=False,
        schema=USDA_ENV_SCHEMA,
    )
    op.create_index(
        "county_values_raw_gin_idx",
        "county_values",
        ["raw"],
        unique=False,
        schema=USDA_ENV_SCHEMA,
        postgresql_using="gin",
    )

    op.create_table(
        "state_values",
        sa.Column("state_fips", sa.Text(), nullable=False),
        sa.Column("state_abbr", sa.Text(), nullable=True),
        sa.Column("state_name", sa.Text(), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("state_fips"),
        schema=USDA_ENV_SCHEMA,
    )
    op.create_index(
        "state_values_state_fips_idx",
        "state_values",
        ["state_fips"],
        unique=False,
        schema=USDA_ENV_SCHEMA,
    )
    op.create_index(
        "state_values_raw_gin_idx",
        "state_values",
        ["raw"],
        unique=False,
        schema=USDA_ENV_SCHEMA,
        postgresql_using="gin",
    )

    op.create_table(
        "dataset_meta",
        sa.Column("dataset_key", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("vintage", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("row_count_county", sa.Integer(), nullable=True),
        sa.Column("row_count_state", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("dataset_key"),
        schema=USDA_ENV_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("dataset_meta", schema=USDA_ENV_SCHEMA)

    op.drop_index("state_values_raw_gin_idx", table_name="state_values", schema=USDA_ENV_SCHEMA)
    op.drop_index("state_values_state_fips_idx", table_name="state_values", schema=USDA_ENV_SCHEMA)
    op.drop_table("state_values", schema=USDA_ENV_SCHEMA)

    op.drop_index("county_values_raw_gin_idx", table_name="county_values", schema=USDA_ENV_SCHEMA)
    op.drop_index("county_values_state_fips_idx", table_name="county_values", schema=USDA_ENV_SCHEMA)
    op.drop_table("county_values", schema=USDA_ENV_SCHEMA)

    op.drop_table("variable_lookup", schema=USDA_ENV_SCHEMA)

    op.execute(f"DROP SCHEMA IF EXISTS {USDA_ENV_SCHEMA}")
