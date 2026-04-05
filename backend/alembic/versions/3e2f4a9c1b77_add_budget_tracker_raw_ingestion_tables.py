"""add budget tracker raw ingestion tables

Revision ID: 3e2f4a9c1b77
Revises: 2f4c6d8e1b90
Create Date: 2026-04-05 14:15:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "3e2f4a9c1b77"
down_revision: Union[str, None] = "2f4c6d8e1b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BUDGET_SCHEMA = "budget"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {BUDGET_SCHEMA}")

    op.create_table(
        "cdc_budget_tracker_raw",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("source_sheet", sa.Text(), nullable=False),
        sa.Column("ingest_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("unique_id", sa.Text(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("agency", sa.Text(), nullable=True),
        sa.Column("sub_agency", sa.Text(), nullable=True),
        sa.Column("program", sa.Text(), nullable=True),
        sa.Column("sub_program", sa.Text(), nullable=True),
        sa.Column("sub_program_2", sa.Text(), nullable=True),
        sa.Column("sub_program_3", sa.Text(), nullable=True),
        sa.Column("budget_source", sa.Text(), nullable=True),
        sa.Column("budget_stage", sa.Text(), nullable=True),
        sa.Column("granularity", sa.Text(), nullable=True),
        sa.Column("amount_millions", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("funding_type", sa.Text(), nullable=True),
        sa.Column("program_status", sa.Text(), nullable=True),
        sa.Column("is_non_add", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("date_entered", sa.Date(), nullable=True),
        sa.Column("entered_by", sa.Text(), nullable=True),
        sa.Column("verified", sa.Text(), nullable=True),
        sa.Column("crosswalk_note", sa.Text(), nullable=True),
        sa.Column("amount_dollars", sa.Numeric(precision=20, scale=2), nullable=True),
        sa.Column("row_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_file",
            "source_sheet",
            "unique_id",
            name="uq_cdc_budget_tracker_raw_source_sheet_unique_id",
        ),
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_tracker_raw_fiscal_year_idx",
        "cdc_budget_tracker_raw",
        ["fiscal_year"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_tracker_raw_sub_agency_idx",
        "cdc_budget_tracker_raw",
        ["sub_agency"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_tracker_raw_budget_source_idx",
        "cdc_budget_tracker_raw",
        ["budget_source"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_tracker_raw_budget_stage_idx",
        "cdc_budget_tracker_raw",
        ["budget_stage"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_tracker_raw_funding_type_idx",
        "cdc_budget_tracker_raw",
        ["funding_type"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_tracker_raw_granularity_idx",
        "cdc_budget_tracker_raw",
        ["granularity"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_tracker_raw_source_id_idx",
        "cdc_budget_tracker_raw",
        ["source_id"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_tracker_raw_row_hash_idx",
        "cdc_budget_tracker_raw",
        ["row_hash"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )

    op.create_table(
        "cdc_budget_source_registry_raw",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("source_sheet", sa.Text(), nullable=False),
        sa.Column("ingest_batch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("document_name", sa.Text(), nullable=True),
        sa.Column("source_type", sa.Text(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("agency", sa.Text(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("granularity_available", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("row_hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_file",
            "source_sheet",
            "source_id",
            name="uq_cdc_budget_source_registry_raw_source_sheet_source_id",
        ),
        schema=BUDGET_SCHEMA,
    )
    op.create_index(
        "cdc_budget_source_registry_raw_row_hash_idx",
        "cdc_budget_source_registry_raw",
        ["row_hash"],
        unique=False,
        schema=BUDGET_SCHEMA,
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {BUDGET_SCHEMA}.v_cdc_budget_tracker_raw_latest AS
        SELECT *
        FROM {BUDGET_SCHEMA}.cdc_budget_tracker_raw
        WHERE is_active = TRUE
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {BUDGET_SCHEMA}.v_cdc_budget_tracker_raw_latest")
    op.drop_index(
        "cdc_budget_source_registry_raw_row_hash_idx",
        table_name="cdc_budget_source_registry_raw",
        schema=BUDGET_SCHEMA,
    )
    op.drop_table("cdc_budget_source_registry_raw", schema=BUDGET_SCHEMA)

    op.drop_index("cdc_budget_tracker_raw_row_hash_idx", table_name="cdc_budget_tracker_raw", schema=BUDGET_SCHEMA)
    op.drop_index("cdc_budget_tracker_raw_source_id_idx", table_name="cdc_budget_tracker_raw", schema=BUDGET_SCHEMA)
    op.drop_index("cdc_budget_tracker_raw_granularity_idx", table_name="cdc_budget_tracker_raw", schema=BUDGET_SCHEMA)
    op.drop_index("cdc_budget_tracker_raw_funding_type_idx", table_name="cdc_budget_tracker_raw", schema=BUDGET_SCHEMA)
    op.drop_index("cdc_budget_tracker_raw_budget_stage_idx", table_name="cdc_budget_tracker_raw", schema=BUDGET_SCHEMA)
    op.drop_index("cdc_budget_tracker_raw_budget_source_idx", table_name="cdc_budget_tracker_raw", schema=BUDGET_SCHEMA)
    op.drop_index("cdc_budget_tracker_raw_sub_agency_idx", table_name="cdc_budget_tracker_raw", schema=BUDGET_SCHEMA)
    op.drop_index("cdc_budget_tracker_raw_fiscal_year_idx", table_name="cdc_budget_tracker_raw", schema=BUDGET_SCHEMA)
    op.drop_table("cdc_budget_tracker_raw", schema=BUDGET_SCHEMA)

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = '{BUDGET_SCHEMA}'
                UNION ALL
                SELECT 1
                FROM information_schema.views
                WHERE table_schema = '{BUDGET_SCHEMA}'
            ) THEN
                EXECUTE 'DROP SCHEMA IF EXISTS {BUDGET_SCHEMA}';
            END IF;
        END $$;
        """
    )
