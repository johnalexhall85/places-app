"""add acs nmf county estimates

Revision ID: e7c9a7d21f45
Revises: 9b1d2f7ce4ab
Create Date: 2026-02-22 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import geoalchemy2
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7c9a7d21f45"
down_revision: Union[str, None] = "9b1d2f7ce4ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "acs_nmf_county_estimates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("year_window", sa.String(), nullable=False),
        sa.Column("state_abbr", sa.String(length=2), nullable=False),
        sa.Column("location_id", sa.String(), nullable=False),
        sa.Column("location_name", sa.String(), nullable=False),
        sa.Column("category_id", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("measure_id", sa.String(), nullable=False),
        sa.Column("measure", sa.String(), nullable=False),
        sa.Column("data_value_type_id", sa.String(), nullable=False),
        sa.Column("data_value_type", sa.String(), nullable=False),
        sa.Column("data_value_unit", sa.String(), nullable=True),
        sa.Column("data_value", sa.Float(), nullable=True),
        sa.Column("moe", sa.Float(), nullable=True),
        sa.Column("total_population", sa.Integer(), nullable=True),
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
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "year_window",
            "location_id",
            "measure_id",
            "data_value_type_id",
            name="uq_acs_nmf_county_estimate",
        ),
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_acs_nmf_year_measure_type "
        "ON acs_nmf_county_estimates (year_window, measure_id, data_value_type_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_acs_nmf_location_id "
        "ON acs_nmf_county_estimates (location_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_acs_nmf_measure_location "
        "ON acs_nmf_county_estimates (measure_id, location_id)"
    )


def downgrade() -> None:
    op.drop_index("idx_acs_nmf_measure_location", table_name="acs_nmf_county_estimates")
    op.drop_index("idx_acs_nmf_location_id", table_name="acs_nmf_county_estimates")
    op.drop_index("idx_acs_nmf_year_measure_type", table_name="acs_nmf_county_estimates")
    op.drop_table("acs_nmf_county_estimates")
