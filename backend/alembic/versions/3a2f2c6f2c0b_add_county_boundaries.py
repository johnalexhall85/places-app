"""add county boundaries

Revision ID: 3a2f2c6f2c0b
Revises: 7268d05ee4cc
Create Date: 2026-02-11 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = "3a2f2c6f2c0b"
down_revision: Union[str, None] = "7268d05ee4cc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dim_county_boundary",
        sa.Column("location_id", sa.String(), nullable=False),
        sa.Column("geoid", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("statefp", sa.String(), nullable=False),
        sa.Column("countyfp", sa.String(), nullable=False),
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
        sa.PrimaryKeyConstraint("location_id"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_dim_county_boundary_geom "
        "ON dim_county_boundary USING gist (geom)"
    )


def downgrade() -> None:
    op.drop_index(
        "idx_dim_county_boundary_geom",
        table_name="dim_county_boundary",
        postgresql_using="gist",
    )
    op.drop_table("dim_county_boundary")
