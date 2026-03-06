"""add dim_state_boundary table

Revision ID: 8d7a9f3c4b21
Revises: 2fb7a6d9a31c
Create Date: 2026-03-05 18:20:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "8d7a9f3c4b21"
down_revision: Union[str, None] = "2fb7a6d9a31c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dim_state_boundary (
            state_fips VARCHAR(2) PRIMARY KEY,
            state_abbr VARCHAR(2) NOT NULL,
            state_name TEXT NOT NULL,
            geom geometry(MULTIPOLYGON, 4326) NOT NULL
        )
        """
    )

    op.execute(
        """
        INSERT INTO dim_state_boundary (
            state_fips,
            state_abbr,
            state_name,
            geom
        )
        SELECT
            b.statefp AS state_fips,
            COALESCE(MAX(c.state_abbr), b.statefp) AS state_abbr,
            COALESCE(MAX(c.state_desc), b.statefp) AS state_name,
            ST_Multi(ST_UnaryUnion(ST_Collect(b.geom)))::geometry(MULTIPOLYGON, 4326) AS geom
        FROM dim_county_boundary AS b
        LEFT JOIN dim_county AS c
            ON c.location_id = b.location_id
        WHERE b.geom IS NOT NULL
        GROUP BY b.statefp
        ON CONFLICT (state_fips) DO UPDATE
        SET state_abbr = EXCLUDED.state_abbr,
            state_name = EXCLUDED.state_name,
            geom = EXCLUDED.geom
        """
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS dim_state_boundary_geom_gist_idx
          ON dim_state_boundary
          USING GIST (geom)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS dim_state_boundary_state_abbr_idx
          ON dim_state_boundary (state_abbr)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS dim_state_boundary_state_abbr_idx")
    op.execute("DROP INDEX IF EXISTS dim_state_boundary_geom_gist_idx")
    op.execute("DROP TABLE IF EXISTS dim_state_boundary")
