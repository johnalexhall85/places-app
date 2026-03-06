"""add usda food access schema tables

Revision ID: d4a3e8c11f90
Revises: a4c9d61e2b77
Create Date: 2026-03-05 10:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d4a3e8c11f90"
down_revision: Union[str, None] = "a4c9d61e2b77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

USDA_SCHEMA = "usda_food_access"


def upgrade() -> None:
    # NOTE: Alembic revisions are static; keep schema literal as "usda_food_access".
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {USDA_SCHEMA}")

    op.create_table(
        "tract_atlas",
        sa.Column("geoid", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("county", sa.Text(), nullable=True),
        sa.Column("urban", sa.SmallInteger(), nullable=True),
        sa.Column("pop2010", sa.Integer(), nullable=True),
        sa.Column("low_income_tracts", sa.SmallInteger(), nullable=True),
        sa.Column("poverty_rate", sa.Float(), nullable=True),
        sa.Column("median_family_income", sa.Float(), nullable=True),
        sa.Column("la1and10", sa.Float(), nullable=True),
        sa.Column("lahalfand10", sa.Float(), nullable=True),
        sa.Column("la1and20", sa.Float(), nullable=True),
        sa.Column("lilatracts_1and10", sa.SmallInteger(), nullable=True),
        sa.Column("lilatracts_halfand10", sa.SmallInteger(), nullable=True),
        sa.Column("lilatracts_1and20", sa.SmallInteger(), nullable=True),
        sa.Column("lilatracts_vehicle", sa.SmallInteger(), nullable=True),
        sa.Column("lapop1_10", sa.Float(), nullable=True),
        sa.Column("lapop05_10", sa.Float(), nullable=True),
        sa.Column("lapop1_20", sa.Float(), nullable=True),
        sa.Column("lalowi1_10", sa.Float(), nullable=True),
        sa.Column("lalowi05_10", sa.Float(), nullable=True),
        sa.Column("lalowi1_20", sa.Float(), nullable=True),
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
        schema=USDA_SCHEMA,
    )
    op.create_index(
        "tract_atlas_state_idx",
        "tract_atlas",
        ["state"],
        unique=False,
        schema=USDA_SCHEMA,
    )
    op.create_index(
        "tract_atlas_county_idx",
        "tract_atlas",
        ["county"],
        unique=False,
        schema=USDA_SCHEMA,
    )
    op.create_index(
        "tract_atlas_raw_gin_idx",
        "tract_atlas",
        ["raw"],
        unique=False,
        schema=USDA_SCHEMA,
        postgresql_using="gin",
    )

    op.create_table(
        "variable_lookup",
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("long_name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("field"),
        schema=USDA_SCHEMA,
    )

    op.create_table(
        "dataset_meta",
        sa.Column("dataset_key", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("vintage", sa.Text(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=False), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("dataset_key"),
        schema=USDA_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("dataset_meta", schema=USDA_SCHEMA)
    op.drop_table("variable_lookup", schema=USDA_SCHEMA)

    op.drop_index("tract_atlas_raw_gin_idx", table_name="tract_atlas", schema=USDA_SCHEMA)
    op.drop_index("tract_atlas_county_idx", table_name="tract_atlas", schema=USDA_SCHEMA)
    op.drop_index("tract_atlas_state_idx", table_name="tract_atlas", schema=USDA_SCHEMA)
    op.drop_table("tract_atlas", schema=USDA_SCHEMA)

    op.execute(f"DROP SCHEMA IF EXISTS {USDA_SCHEMA}")
