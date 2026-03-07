"""add fema nri schema tables

Revision ID: b9f24d31a8e1
Revises: 8d7a9f3c4b21
Create Date: 2026-03-05 20:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b9f24d31a8e1"
down_revision: Union[str, None] = "8d7a9f3c4b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FEMA_NRI_SCHEMA = "fema_nri"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {FEMA_NRI_SCHEMA}")

    op.create_table(
        "nri_county",
        sa.Column("county_geoid", sa.Text(), nullable=False),
        sa.Column("nri_id", sa.Text(), nullable=True),
        sa.Column("state_fips", sa.Text(), nullable=False),
        sa.Column("county_fips", sa.Text(), nullable=False),
        sa.Column("state_abbr", sa.Text(), nullable=True),
        sa.Column("state_name", sa.Text(), nullable=True),
        sa.Column("county_name", sa.Text(), nullable=True),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(geometry_type="MULTIPOLYGON", srid=4326),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("county_geoid"),
        schema=FEMA_NRI_SCHEMA,
    )
    op.create_index(
        "nri_county_state_fips_idx",
        "nri_county",
        ["state_fips"],
        unique=False,
        schema=FEMA_NRI_SCHEMA,
    )
    op.create_index(
        "nri_county_county_fips_idx",
        "nri_county",
        ["county_fips"],
        unique=False,
        schema=FEMA_NRI_SCHEMA,
    )
    op.create_index(
        "nri_county_geom_gist_idx",
        "nri_county",
        ["geom"],
        unique=False,
        schema=FEMA_NRI_SCHEMA,
        postgresql_using="gist",
    )
    op.create_index(
        "nri_county_raw_gin_idx",
        "nri_county",
        ["raw"],
        unique=False,
        schema=FEMA_NRI_SCHEMA,
        postgresql_using="gin",
    )

    op.create_table(
        "nri_tract",
        sa.Column("tract_geoid", sa.Text(), nullable=False),
        sa.Column("nri_id", sa.Text(), nullable=True),
        sa.Column("state_fips", sa.Text(), nullable=False),
        sa.Column("county_fips", sa.Text(), nullable=False),
        sa.Column("county_geoid", sa.Text(), nullable=False),
        sa.Column("tract_code", sa.Text(), nullable=True),
        sa.Column("state_abbr", sa.Text(), nullable=True),
        sa.Column("state_name", sa.Text(), nullable=True),
        sa.Column("county_name", sa.Text(), nullable=True),
        sa.Column("tract_name", sa.Text(), nullable=True),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(geometry_type="MULTIPOLYGON", srid=4326),
            nullable=False,
        ),
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
        sa.PrimaryKeyConstraint("tract_geoid"),
        schema=FEMA_NRI_SCHEMA,
    )
    op.create_index(
        "nri_tract_state_fips_idx",
        "nri_tract",
        ["state_fips"],
        unique=False,
        schema=FEMA_NRI_SCHEMA,
    )
    op.create_index(
        "nri_tract_county_fips_idx",
        "nri_tract",
        ["county_fips"],
        unique=False,
        schema=FEMA_NRI_SCHEMA,
    )
    op.create_index(
        "nri_tract_county_geoid_idx",
        "nri_tract",
        ["county_geoid"],
        unique=False,
        schema=FEMA_NRI_SCHEMA,
    )
    op.create_index(
        "nri_tract_geom_gist_idx",
        "nri_tract",
        ["geom"],
        unique=False,
        schema=FEMA_NRI_SCHEMA,
        postgresql_using="gist",
    )
    op.create_index(
        "nri_tract_raw_gin_idx",
        "nri_tract",
        ["raw"],
        unique=False,
        schema=FEMA_NRI_SCHEMA,
        postgresql_using="gin",
    )

    op.create_table(
        "dataset_meta",
        sa.Column("dataset_key", sa.Text(), nullable=False),
        sa.Column("source_name", sa.Text(), nullable=True),
        sa.Column("vintage", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("county_feature_count", sa.Integer(), nullable=True),
        sa.Column("tract_feature_count", sa.Integer(), nullable=True),
        sa.Column("county_row_count", sa.Integer(), nullable=True),
        sa.Column("tract_row_count", sa.Integer(), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=False), nullable=True),
        sa.PrimaryKeyConstraint("dataset_key"),
        schema=FEMA_NRI_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("dataset_meta", schema=FEMA_NRI_SCHEMA)

    op.drop_index("nri_tract_raw_gin_idx", table_name="nri_tract", schema=FEMA_NRI_SCHEMA)
    op.drop_index("nri_tract_geom_gist_idx", table_name="nri_tract", schema=FEMA_NRI_SCHEMA)
    op.drop_index("nri_tract_county_geoid_idx", table_name="nri_tract", schema=FEMA_NRI_SCHEMA)
    op.drop_index("nri_tract_county_fips_idx", table_name="nri_tract", schema=FEMA_NRI_SCHEMA)
    op.drop_index("nri_tract_state_fips_idx", table_name="nri_tract", schema=FEMA_NRI_SCHEMA)
    op.drop_table("nri_tract", schema=FEMA_NRI_SCHEMA)

    op.drop_index("nri_county_raw_gin_idx", table_name="nri_county", schema=FEMA_NRI_SCHEMA)
    op.drop_index("nri_county_geom_gist_idx", table_name="nri_county", schema=FEMA_NRI_SCHEMA)
    op.drop_index("nri_county_county_fips_idx", table_name="nri_county", schema=FEMA_NRI_SCHEMA)
    op.drop_index("nri_county_state_fips_idx", table_name="nri_county", schema=FEMA_NRI_SCHEMA)
    op.drop_table("nri_county", schema=FEMA_NRI_SCHEMA)

    op.execute(f"DROP SCHEMA IF EXISTS {FEMA_NRI_SCHEMA}")
