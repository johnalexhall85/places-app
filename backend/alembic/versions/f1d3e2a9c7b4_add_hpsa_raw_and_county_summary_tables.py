"""add hpsa raw and county summary tables

Revision ID: f1d3e2a9c7b4
Revises: b5a1c8d71e2f
Create Date: 2026-03-01 15:25:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f1d3e2a9c7b4"
down_revision: Union[str, None] = "b5a1c8d71e2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hpsa_designations_raw",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("designation_type", sa.Text(), nullable=False),
        sa.Column("load_batch_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("source_file", sa.Text(), nullable=True),
        sa.Column("row_hash", sa.Text(), nullable=False),
        sa.Column("county_fips", sa.Text(), nullable=True),
        sa.Column("state_fips", sa.Text(), nullable=True),
        sa.Column("hpsa_score", sa.Integer(), nullable=True),
        sa.Column("designation_status", sa.Text(), nullable=True),
        sa.Column("designated_population", sa.Integer(), nullable=True),
        sa.Column("geo_description", sa.Text(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("load_batch_id", "row_hash", name="uq_hpsa_raw_batch_rowhash"),
    )
    op.create_index(
        "idx_hpsa_raw_county_type",
        "hpsa_designations_raw",
        ["county_fips", "designation_type"],
        unique=False,
    )
    op.create_index(
        "idx_hpsa_raw_status",
        "hpsa_designations_raw",
        ["designation_status"],
        unique=False,
    )

    op.create_table(
        "county_hpsa_summary",
        sa.Column("county_fips", sa.Text(), nullable=False),
        sa.Column("state_fips", sa.Text(), nullable=True),
        sa.Column("pc_designated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("pc_hpsa_score_max", sa.Integer(), nullable=True),
        sa.Column("pc_population_covered", sa.Integer(), nullable=True),
        sa.Column("mh_designated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("mh_hpsa_score_max", sa.Integer(), nullable=True),
        sa.Column("mh_population_covered", sa.Integer(), nullable=True),
        sa.Column("dh_designated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("dh_hpsa_score_max", sa.Integer(), nullable=True),
        sa.Column("dh_population_covered", sa.Integer(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("county_fips ~ '^[0-9]{5}$'", name="ck_county_hpsa_summary_county_fips"),
        sa.CheckConstraint(
            "state_fips IS NULL OR state_fips ~ '^[0-9]{2}$'",
            name="ck_county_hpsa_summary_state_fips",
        ),
        sa.PrimaryKeyConstraint("county_fips"),
    )
    op.create_index(
        "idx_county_hpsa_summary_state_fips",
        "county_hpsa_summary",
        ["state_fips"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_county_hpsa_summary_state_fips", table_name="county_hpsa_summary")
    op.drop_table("county_hpsa_summary")

    op.drop_index("idx_hpsa_raw_status", table_name="hpsa_designations_raw")
    op.drop_index("idx_hpsa_raw_county_type", table_name="hpsa_designations_raw")
    op.drop_table("hpsa_designations_raw")
