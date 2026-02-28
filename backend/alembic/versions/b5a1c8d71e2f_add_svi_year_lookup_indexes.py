"""add svi year lookup indexes

Revision ID: b5a1c8d71e2f
Revises: 0d78b6f9a4c2
Create Date: 2026-02-28 15:10:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b5a1c8d71e2f"
down_revision: Union[str, None] = "0d78b6f9a4c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_svi_county_year_geoid",
        "svi_estimates_county",
        ["year", "geoid"],
        unique=False,
    )
    op.create_index(
        "idx_svi_tract_year_geoid",
        "svi_estimates_tract",
        ["year", "geoid"],
        unique=False,
    )
    # Expression indexes for year + state FIPS lookups without storing duplicate state columns.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_svi_county_year_statefips "
        "ON svi_estimates_county (year, left(geoid, 2))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_svi_tract_year_statefips "
        "ON svi_estimates_tract (year, left(geoid, 2))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_svi_tract_year_statefips")
    op.execute("DROP INDEX IF EXISTS idx_svi_county_year_statefips")
    op.drop_index("idx_svi_tract_year_geoid", table_name="svi_estimates_tract")
    op.drop_index("idx_svi_county_year_geoid", table_name="svi_estimates_county")
