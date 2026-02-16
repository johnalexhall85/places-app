"""add tract tables

Revision ID: 9b1d2f7ce4ab
Revises: 3a2f2c6f2c0b
Create Date: 2026-02-16 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import geoalchemy2
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9b1d2f7ce4ab"
down_revision: Union[str, None] = "3a2f2c6f2c0b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tract_shapes",
        sa.Column("geoid11", sa.String(length=11), nullable=False),
        sa.Column("statefp", sa.String(length=2), nullable=False),
        sa.Column("countyfp", sa.String(length=3), nullable=False),
        sa.Column("tractce", sa.String(length=6), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="MULTIPOLYGON",
                srid=4326,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("geoid11"),
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tract_shapes_geoid11 "
        "ON tract_shapes (geoid11)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tract_shapes_geom "
        "ON tract_shapes USING gist (geom)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tract_shapes_state_county "
        "ON tract_shapes (statefp, countyfp)"
    )

    op.create_table(
        "tract_estimates",
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("locationid", sa.String(length=11), nullable=False),
        sa.Column("measure_id", sa.String(), nullable=False),
        sa.Column("data_value_type_id", sa.String(), nullable=False),
        sa.Column("state_abbr", sa.String(length=2), nullable=True),
        sa.Column("state_desc", sa.String(), nullable=True),
        sa.Column("county_name", sa.String(), nullable=True),
        sa.Column("county_fips", sa.String(length=5), nullable=True),
        sa.Column("location_name", sa.String(length=11), nullable=True),
        sa.Column("data_source", sa.String(), nullable=True),
        sa.Column("category", sa.String(), nullable=True),
        sa.Column("category_id", sa.String(), nullable=True),
        sa.Column("measure", sa.String(), nullable=True),
        sa.Column("data_value_unit", sa.String(), nullable=True),
        sa.Column("data_value_type", sa.String(), nullable=True),
        sa.Column("data_value", sa.Float(), nullable=True),
        sa.Column("low_confidence_limit", sa.Float(), nullable=True),
        sa.Column("high_confidence_limit", sa.Float(), nullable=True),
        sa.Column("total_population", sa.BigInteger(), nullable=True),
        sa.Column("total_pop_18_plus", sa.BigInteger(), nullable=True),
        sa.Column("short_question_text", sa.String(), nullable=True),
        sa.Column(
            "geolocation",
            geoalchemy2.types.Geometry(
                geometry_type="POINT",
                srid=4326,
                from_text="ST_GeomFromEWKT",
                name="geometry",
            ),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint(
            "year",
            "locationid",
            "measure_id",
            "data_value_type_id",
            name="pk_tract_estimates",
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tract_estimates_filters "
        "ON tract_estimates (year, measure_id, data_value_type_id, state_abbr, county_fips)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tract_estimates_locationid "
        "ON tract_estimates (locationid)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tract_estimates_geolocation "
        "ON tract_estimates USING gist (geolocation)"
    )


def downgrade() -> None:
    op.drop_index(
        "idx_tract_estimates_geolocation",
        table_name="tract_estimates",
        postgresql_using="gist",
    )
    op.drop_index("idx_tract_estimates_locationid", table_name="tract_estimates")
    op.drop_index("idx_tract_estimates_filters", table_name="tract_estimates")
    op.drop_table("tract_estimates")

    op.drop_index("idx_tract_shapes_state_county", table_name="tract_shapes")
    op.drop_index("idx_tract_shapes_geom", table_name="tract_shapes", postgresql_using="gist")
    op.drop_index("uq_tract_shapes_geoid11", table_name="tract_shapes")
    op.drop_table("tract_shapes")
