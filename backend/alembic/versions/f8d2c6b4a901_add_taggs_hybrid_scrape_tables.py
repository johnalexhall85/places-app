"""add taggs hybrid scrape tables

Revision ID: f8d2c6b4a901
Revises: 1e7c9d4b2a11
Create Date: 2026-03-12 18:05:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f8d2c6b4a901"
down_revision: Union[str, None] = "1e7c9d4b2a11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TAGGS_SCHEMA = "taggs"


def upgrade() -> None:
    op.create_table(
        "scrape_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("funding_fiscal_year", sa.Integer(), nullable=False),
        sa.Column("opdiv", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'running'")),
        sa.Column("pages_completed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("rows_parsed", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_page_scraped", sa.Integer(), nullable=True, server_default=sa.text("0")),
        sa.Column(
            "bootstrap_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "fallback_browser_paging",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=TAGGS_SCHEMA,
    )

    op.create_index(
        "taggs_scrape_runs_fy_idx",
        "scrape_runs",
        ["funding_fiscal_year"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_scrape_runs_status_idx",
        "scrape_runs",
        ["status"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_scrape_runs_fy_opdiv_status_idx",
        "scrape_runs",
        ["funding_fiscal_year", "opdiv", "status"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )

    op.create_table(
        "raw_web_rows",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scrape_run_id", sa.BigInteger(), nullable=False),
        sa.Column("funding_fiscal_year", sa.Integer(), nullable=False),
        sa.Column("source_page_number", sa.Integer(), nullable=False),
        sa.Column("source_row_index", sa.Integer(), nullable=False),
        sa.Column("raw_header_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_row_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("fiscal_year_of_activity", sa.Integer(), nullable=True),
        sa.Column("opdiv", sa.Text(), nullable=True),
        sa.Column("program_office", sa.Text(), nullable=True),
        sa.Column("legal_entity_name", sa.Text(), nullable=True),
        sa.Column("legal_entity_city", sa.Text(), nullable=True),
        sa.Column("legal_entity_county", sa.Text(), nullable=True),
        sa.Column("legal_entity_state", sa.Text(), nullable=True),
        sa.Column("legal_entity_country", sa.Text(), nullable=True),
        sa.Column("aln", sa.Text(), nullable=True),
        sa.Column("assistance_listing_title", sa.Text(), nullable=True),
        sa.Column("period_of_performance_start_date", sa.Date(), nullable=True),
        sa.Column("period_of_performance_end_date", sa.Date(), nullable=True),
        sa.Column("award_termination_date", sa.Date(), nullable=True),
        sa.Column("uei", sa.Text(), nullable=True),
        sa.Column("fon", sa.Text(), nullable=True),
        sa.Column("metro_non_metro", sa.Text(), nullable=True),
        sa.Column("recipient_class", sa.Text(), nullable=True),
        sa.Column("recipient_type", sa.Text(), nullable=True),
        sa.Column("recovery_act_flag", sa.Text(), nullable=True),
        sa.Column("award_number", sa.Text(), nullable=True),
        sa.Column("award_title", sa.Text(), nullable=True),
        sa.Column("budget_year", sa.Integer(), nullable=True),
        sa.Column("action_issue_date", sa.Date(), nullable=True),
        sa.Column("award_class", sa.Text(), nullable=True),
        sa.Column("award_activity_type", sa.Text(), nullable=True),
        sa.Column("award_action_type", sa.Text(), nullable=True),
        sa.Column("transaction_aln", sa.Text(), nullable=True),
        sa.Column("transaction_assistance_listing_title", sa.Text(), nullable=True),
        sa.Column("can_code", sa.Text(), nullable=True),
        sa.Column("distinct_award_count", sa.Integer(), nullable=True),
        sa.Column("sum_of_actions", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("award_description_text", sa.Text(), nullable=True),
        sa.Column("award_description_raw_html", sa.Text(), nullable=True),
        sa.Column("award_detail_href", sa.Text(), nullable=True),
        sa.Column(
            "scraped_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["scrape_run_id"],
            [f"{TAGGS_SCHEMA}.scrape_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=TAGGS_SCHEMA,
    )

    op.create_index(
        "taggs_raw_web_rows_scrape_run_id_idx",
        "raw_web_rows",
        ["scrape_run_id"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_raw_web_rows_fy_idx",
        "raw_web_rows",
        ["funding_fiscal_year"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_raw_web_rows_scrape_run_page_row_idx",
        "raw_web_rows",
        ["scrape_run_id", "source_page_number", "source_row_index"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_raw_web_rows_award_number_idx",
        "raw_web_rows",
        ["award_number"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_raw_web_rows_state_idx",
        "raw_web_rows",
        ["legal_entity_state"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )

    op.create_table(
        "award_actions_canonical",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("raw_web_row_id", sa.BigInteger(), nullable=False),
        sa.Column("scrape_run_id", sa.BigInteger(), nullable=False),
        sa.Column("funding_fiscal_year", sa.Integer(), nullable=False),
        sa.Column("source_page_number", sa.Integer(), nullable=False),
        sa.Column("source_row_index", sa.Integer(), nullable=False),
        sa.Column("opdiv", sa.Text(), nullable=True),
        sa.Column("program_office", sa.Text(), nullable=True),
        sa.Column("legal_entity_name", sa.Text(), nullable=True),
        sa.Column("legal_entity_city", sa.Text(), nullable=True),
        sa.Column("legal_entity_county", sa.Text(), nullable=True),
        sa.Column("legal_entity_state", sa.Text(), nullable=True),
        sa.Column("legal_entity_country", sa.Text(), nullable=True),
        sa.Column("legal_entity_state_normalized", sa.Text(), nullable=True),
        sa.Column("legal_entity_county_normalized", sa.Text(), nullable=True),
        sa.Column("aln", sa.Text(), nullable=True),
        sa.Column("assistance_listing_title", sa.Text(), nullable=True),
        sa.Column("award_number", sa.Text(), nullable=True),
        sa.Column("award_title", sa.Text(), nullable=True),
        sa.Column("award_description_text", sa.Text(), nullable=True),
        sa.Column("award_detail_href", sa.Text(), nullable=True),
        sa.Column("award_class", sa.Text(), nullable=True),
        sa.Column("award_activity_type", sa.Text(), nullable=True),
        sa.Column("award_action_type", sa.Text(), nullable=True),
        sa.Column("transaction_aln", sa.Text(), nullable=True),
        sa.Column("transaction_assistance_listing_title", sa.Text(), nullable=True),
        sa.Column("can_code", sa.Text(), nullable=True),
        sa.Column("distinct_award_count", sa.Integer(), nullable=True),
        sa.Column("sum_of_actions", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("action_issue_date", sa.Date(), nullable=True),
        sa.Column("scraped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_web_row_id"],
            [f"{TAGGS_SCHEMA}.raw_web_rows.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["scrape_run_id"],
            [f"{TAGGS_SCHEMA}.scrape_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=TAGGS_SCHEMA,
    )

    op.create_index(
        "taggs_award_actions_canonical_scrape_run_id_idx",
        "award_actions_canonical",
        ["scrape_run_id"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_actions_canonical_fy_idx",
        "award_actions_canonical",
        ["funding_fiscal_year"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_actions_canonical_state_idx",
        "award_actions_canonical",
        ["legal_entity_state_normalized"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_actions_canonical_program_office_idx",
        "award_actions_canonical",
        ["program_office"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_actions_canonical_award_number_idx",
        "award_actions_canonical",
        ["award_number"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )

    op.create_table(
        "award_funding_summary",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("scrape_run_id", sa.BigInteger(), nullable=False),
        sa.Column("funding_fiscal_year", sa.Integer(), nullable=False),
        sa.Column("opdiv", sa.Text(), nullable=True),
        sa.Column("legal_entity_state", sa.Text(), nullable=True),
        sa.Column("program_office", sa.Text(), nullable=True),
        sa.Column("aln", sa.Text(), nullable=True),
        sa.Column("assistance_listing_title", sa.Text(), nullable=True),
        sa.Column(
            "total_sum_of_actions",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("action_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "distinct_award_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["scrape_run_id"],
            [f"{TAGGS_SCHEMA}.scrape_runs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=TAGGS_SCHEMA,
    )

    op.create_index(
        "taggs_award_funding_summary_scrape_run_id_idx",
        "award_funding_summary",
        ["scrape_run_id"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_summary_fy_idx",
        "award_funding_summary",
        ["funding_fiscal_year"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_summary_state_fy_idx",
        "award_funding_summary",
        ["legal_entity_state", "funding_fiscal_year"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_summary_state_fy_program_idx",
        "award_funding_summary",
        ["legal_entity_state", "funding_fiscal_year", "program_office"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "taggs_award_funding_summary_state_fy_program_idx",
        table_name="award_funding_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_summary_state_fy_idx",
        table_name="award_funding_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_summary_fy_idx",
        table_name="award_funding_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_summary_scrape_run_id_idx",
        table_name="award_funding_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_table("award_funding_summary", schema=TAGGS_SCHEMA)

    op.drop_index(
        "taggs_award_actions_canonical_award_number_idx",
        table_name="award_actions_canonical",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_actions_canonical_program_office_idx",
        table_name="award_actions_canonical",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_actions_canonical_state_idx",
        table_name="award_actions_canonical",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_actions_canonical_fy_idx",
        table_name="award_actions_canonical",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_actions_canonical_scrape_run_id_idx",
        table_name="award_actions_canonical",
        schema=TAGGS_SCHEMA,
    )
    op.drop_table("award_actions_canonical", schema=TAGGS_SCHEMA)

    op.drop_index(
        "taggs_raw_web_rows_state_idx",
        table_name="raw_web_rows",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_raw_web_rows_award_number_idx",
        table_name="raw_web_rows",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_raw_web_rows_scrape_run_page_row_idx",
        table_name="raw_web_rows",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_raw_web_rows_fy_idx",
        table_name="raw_web_rows",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_raw_web_rows_scrape_run_id_idx",
        table_name="raw_web_rows",
        schema=TAGGS_SCHEMA,
    )
    op.drop_table("raw_web_rows", schema=TAGGS_SCHEMA)

    op.drop_index(
        "taggs_scrape_runs_fy_opdiv_status_idx",
        table_name="scrape_runs",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_scrape_runs_status_idx",
        table_name="scrape_runs",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_scrape_runs_fy_idx",
        table_name="scrape_runs",
        schema=TAGGS_SCHEMA,
    )
    op.drop_table("scrape_runs", schema=TAGGS_SCHEMA)
