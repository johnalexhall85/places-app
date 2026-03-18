"""rebuild taggs schema for state csv pipeline

Revision ID: 2c7b4d9e1a55
Revises: f8d2c6b4a901
Create Date: 2026-03-12 23:20:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "2c7b4d9e1a55"
down_revision: Union[str, None] = "f8d2c6b4a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TAGGS_SCHEMA = "taggs"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {TAGGS_SCHEMA}")

    for table_name in (
        "ingestion_runs",
        "can_classification",
        "state_funding_summary",
        "award_funding_summary",
        "award_funding_year_summary",
        "award_actions_canonical",
        "raw_web_rows",
        "scrape_runs",
        "raw_awards",
    ):
        op.execute(f"DROP TABLE IF EXISTS {TAGGS_SCHEMA}.{table_name} CASCADE")

    op.create_table(
        "raw_awards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("source_state_hint", sa.Text(), nullable=True),
        sa.Column("source_is_territory_file", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "source_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("row_number_main", sa.Integer(), nullable=True),
        sa.Column("issue_date_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("opdiv", sa.Text(), nullable=True),
        sa.Column("program_office", sa.Text(), nullable=True),
        sa.Column("legal_entity_name", sa.Text(), nullable=True),
        sa.Column("legal_entity_city", sa.Text(), nullable=True),
        sa.Column("legal_entity_state", sa.Text(), nullable=True),
        sa.Column("legal_entity_county", sa.Text(), nullable=True),
        sa.Column("legal_entity_country", sa.Text(), nullable=True),
        sa.Column("uei", sa.Text(), nullable=True),
        sa.Column("metro_non_metro", sa.Text(), nullable=True),
        sa.Column("recipient_class", sa.Text(), nullable=True),
        sa.Column("recipient_type", sa.Text(), nullable=True),
        sa.Column("recovery_act_flag", sa.Text(), nullable=True),
        sa.Column("award_number", sa.Text(), nullable=True),
        sa.Column("award_title", sa.Text(), nullable=True),
        sa.Column("award_description", sa.Text(), nullable=True),
        sa.Column("budget_year", sa.Integer(), nullable=True),
        sa.Column("award_class", sa.Text(), nullable=True),
        sa.Column("award_activity_type", sa.Text(), nullable=True),
        sa.Column("aln", sa.Text(), nullable=True),
        sa.Column("assistance_listing_title", sa.Text(), nullable=True),
        sa.Column("funding_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("can_code", sa.Text(), nullable=True),
        sa.Column("sum_of_actions", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("legal_entity_state_normalized", sa.Text(), nullable=True),
        sa.Column("legal_entity_county_normalized", sa.Text(), nullable=True),
        sa.Column("legal_entity_country_normalized", sa.Text(), nullable=True),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        schema=TAGGS_SCHEMA,
    )
    op.create_index("taggs_raw_awards_funding_fiscal_year_idx", "raw_awards", ["funding_fiscal_year"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_raw_awards_award_number_idx", "raw_awards", ["award_number"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_raw_awards_can_code_idx", "raw_awards", ["can_code"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_raw_awards_program_office_idx", "raw_awards", ["program_office"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_raw_awards_legal_entity_state_normalized_idx", "raw_awards", ["legal_entity_state_normalized"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_raw_awards_legal_entity_county_normalized_idx", "raw_awards", ["legal_entity_county_normalized"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_raw_awards_aln_idx", "raw_awards", ["aln"], unique=False, schema=TAGGS_SCHEMA)

    op.create_table(
        "award_funding_summary",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("award_number", sa.Text(), nullable=False),
        sa.Column("funding_fiscal_year", sa.Integer(), nullable=False),
        sa.Column("can_code", sa.Text(), nullable=True),
        sa.Column("legal_entity_state_normalized", sa.Text(), nullable=True),
        sa.Column("legal_entity_county_normalized", sa.Text(), nullable=True),
        sa.Column("legal_entity_country_normalized", sa.Text(), nullable=True),
        sa.Column("program_office", sa.Text(), nullable=True),
        sa.Column("aln", sa.Text(), nullable=True),
        sa.Column("assistance_listing_title", sa.Text(), nullable=True),
        sa.Column("award_title", sa.Text(), nullable=True),
        sa.Column("award_description", sa.Text(), nullable=True),
        sa.Column("legal_entity_name", sa.Text(), nullable=True),
        sa.Column("legal_entity_city", sa.Text(), nullable=True),
        sa.Column("total_sum_of_actions", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("raw_row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_domestic_scope", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        schema=TAGGS_SCHEMA,
    )
    op.create_index("taggs_award_funding_summary_fy_idx", "award_funding_summary", ["funding_fiscal_year"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_award_funding_summary_state_fy_idx", "award_funding_summary", ["legal_entity_state_normalized", "funding_fiscal_year"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_award_funding_summary_can_code_idx", "award_funding_summary", ["can_code"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_award_funding_summary_program_office_idx", "award_funding_summary", ["program_office"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_award_funding_summary_aln_idx", "award_funding_summary", ["aln"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_award_funding_summary_award_number_idx", "award_funding_summary", ["award_number"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_award_funding_summary_domestic_scope_idx", "award_funding_summary", ["is_domestic_scope"], unique=False, schema=TAGGS_SCHEMA)

    op.create_table(
        "state_funding_summary",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("funding_fiscal_year", sa.Integer(), nullable=False),
        sa.Column("legal_entity_state_normalized", sa.Text(), nullable=False),
        sa.Column("can_code", sa.Text(), nullable=True),
        sa.Column("program_office", sa.Text(), nullable=True),
        sa.Column("aln", sa.Text(), nullable=True),
        sa.Column("total_sum_of_actions", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("award_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unique_recipient_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("unique_county_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_domestic_scope", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        schema=TAGGS_SCHEMA,
    )
    op.create_index("taggs_state_funding_summary_fy_idx", "state_funding_summary", ["funding_fiscal_year"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_state_funding_summary_state_fy_idx", "state_funding_summary", ["legal_entity_state_normalized", "funding_fiscal_year"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_state_funding_summary_can_code_idx", "state_funding_summary", ["can_code"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_state_funding_summary_program_office_idx", "state_funding_summary", ["program_office"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_state_funding_summary_aln_idx", "state_funding_summary", ["aln"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_state_funding_summary_domestic_scope_idx", "state_funding_summary", ["is_domestic_scope"], unique=False, schema=TAGGS_SCHEMA)

    op.create_table(
        "can_classification",
        sa.Column("can_code", sa.Text(), nullable=False),
        sa.Column("funding_stream", sa.Text(), nullable=True),
        sa.Column("appropriation_type", sa.Text(), nullable=True),
        sa.Column("category_override", sa.Text(), nullable=True),
        sa.Column("subcategory_override", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_covid_related", sa.Boolean(), nullable=True),
        sa.Column("is_arpa_related", sa.Boolean(), nullable=True),
        sa.Column("is_supplemental", sa.Boolean(), nullable=True),
        sa.Column("is_regular_appropriation", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("can_code"),
        schema=TAGGS_SCHEMA,
    )
    op.create_index("taggs_can_classification_funding_stream_idx", "can_classification", ["funding_stream"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_can_classification_appropriation_type_idx", "can_classification", ["appropriation_type"], unique=False, schema=TAGGS_SCHEMA)

    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column("input_dir", sa.Text(), nullable=False),
        sa.Column("summary_path", sa.Text(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("truncate_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("drop_and_recreate", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("rebuild_summaries", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("rebuild_can_table", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("files_discovered", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("files_processed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("raw_main_rows_parsed", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("description_rows_paired", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("orphan_description_rows", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("raw_rows_loaded", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("award_summary_rows_loaded", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("state_summary_rows_loaded", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("distinct_can_codes", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        schema=TAGGS_SCHEMA,
    )
    op.create_index("taggs_ingestion_runs_status_idx", "ingestion_runs", ["status"], unique=False, schema=TAGGS_SCHEMA)
    op.create_index("taggs_ingestion_runs_started_at_idx", "ingestion_runs", ["started_at"], unique=False, schema=TAGGS_SCHEMA)


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for the TAGGS CSV schema rebuild.")
