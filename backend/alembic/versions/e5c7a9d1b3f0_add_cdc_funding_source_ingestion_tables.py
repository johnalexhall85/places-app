"""add cdc funding source ingestion tables

Revision ID: e5c7a9d1b3f0
Revises: d4f9b2c6a8e1
Create Date: 2026-07-19 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "e5c7a9d1b3f0"
down_revision: Union[str, None] = "d4f9b2c6a8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"

MONEY_COLUMNS = {
    "transaction_obligated_amount",
    "gross_outlay_amount_fyb_to_period_end",
    "ussgl487200_downward_adj_prior_year_prepaid_undeliv_order_oblig",
    "ussgl497200_downward_adj_of_prior_year_paid_deliv_orders_oblig",
    "cfp_obligations",
    "usaspending_obligations",
    "difference_usaspending_minus_cfp",
}
PERCENT_COLUMNS = {"percent_difference"}
DATE_COLUMNS = {
    "award_base_action_date",
    "award_latest_action_date",
    "period_of_performance_start_date",
    "period_of_performance_current_end_date",
    "ordering_period_end_date",
    "last_modified_date",
}
INT_COLUMNS = {
    "fiscal_year",
    "award_base_action_date_fiscal_year",
    "award_latest_action_date_fiscal_year",
    "row_count",
    "numeric_obligation_rows",
    "reference_detail_rows",
    "mapped_account_rows",
}
BOOL_COLUMNS = {"name_matches_expectation"}

AWARD_COLUMNS = [
    "grant_or_contract",
    "owning_agency_name",
    "reporting_agency_name",
    "submission_period",
    "federal_account_symbol",
    "federal_account_name",
    "program_activity_reporting_key",
    "agency_identifier_name",
    "budget_function",
    "budget_subfunction",
    "program_activity_code",
    "program_activity_name",
    "object_class_code",
    "object_class_name",
    "direct_or_reimbursable_funding_source",
    "disaster_emergency_fund_code",
    "disaster_emergency_fund_name",
    "transaction_obligated_amount",
    "gross_outlay_amount_fyb_to_period_end",
    "ussgl487200_downward_adj_prior_year_prepaid_undeliv_order_oblig",
    "ussgl497200_downward_adj_of_prior_year_paid_deliv_orders_oblig",
    "award_unique_key",
    "award_id_piid",
    "parent_award_id_piid",
    "award_id_fain",
    "award_id_uri",
    "award_base_action_date",
    "award_base_action_date_fiscal_year",
    "award_latest_action_date",
    "award_latest_action_date_fiscal_year",
    "period_of_performance_start_date",
    "period_of_performance_current_end_date",
    "ordering_period_end_date",
    "award_type_code",
    "award_type",
    "idv_type_code",
    "idv_type",
    "prime_award_base_transaction_description",
    "awarding_agency_code",
    "awarding_agency_name",
    "awarding_subagency_code",
    "awarding_subagency_name",
    "awarding_office_code",
    "awarding_office_name",
    "funding_agency_code",
    "funding_agency_name",
    "funding_sub_agency_code",
    "funding_sub_agency_name",
    "funding_office_code",
    "funding_office_name",
    "recipient_uei",
    "recipient_duns",
    "recipient_name",
    "recipient_name_raw",
    "recipient_parent_uei",
    "recipient_parent_duns",
    "recipient_parent_name",
    "recipient_parent_name_raw",
    "recipient_country",
    "recipient_state",
    "recipient_county",
    "recipient_city",
    "prime_award_summary_recipient_cd_original",
    "prime_award_summary_recipient_cd_current",
    "recipient_zip_code",
    "primary_place_of_performance_country",
    "primary_place_of_performance_state",
    "primary_place_of_performance_county",
    "prime_award_summary_place_of_performance_cd_original",
    "prime_award_summary_place_of_performance_cd_current",
    "primary_place_of_performance_zip_code",
    "cfda_number",
    "cfda_title",
    "product_or_service_code",
    "product_or_service_code_description",
    "naics_code",
    "naics_description",
    "national_interest_action_code",
    "national_interest_action",
    "usaspending_permalink",
    "last_modified_date",
    "emergency",
]

ACCOUNT_ANNUAL_COLUMNS = [
    "fiscal_year",
    "grant_or_contract",
    "emergency",
    "federal_account_symbol",
    "federal_account_name",
    "row_count",
    "numeric_obligation_rows",
    "transaction_obligated_amount",
    "gross_outlay_amount_fyb_to_period_end",
]
ACCOUNT_MONTHLY_COLUMNS = [
    "fiscal_year",
    "submission_period",
    "fiscal_quarter",
    "period_label",
    "grant_or_contract",
    "emergency",
    "federal_account_symbol",
    "federal_account_name",
    "row_count",
    "numeric_obligation_rows",
    "transaction_obligated_amount",
]
ACCOUNT_QUARTERLY_COLUMNS = [
    "fiscal_year",
    "fiscal_quarter",
    "grant_or_contract",
    "emergency",
    "federal_account_symbol",
    "federal_account_name",
    "row_count",
    "numeric_obligation_rows",
    "transaction_obligated_amount",
]
CATEGORY_COMPARISON_COLUMNS = [
    "fiscal_year",
    "category",
    "mapping_status",
    "reference_detail_rows",
    "mapped_account_rows",
    "cfp_obligations",
    "usaspending_obligations",
    "difference_usaspending_minus_cfp",
    "percent_difference",
]
CATEGORY_MONTHLY_COLUMNS = [
    "fiscal_year",
    "submission_period",
    "fiscal_quarter",
    "period_label",
    "category",
    "row_count",
    "numeric_obligation_rows",
    "transaction_obligated_amount",
]
CATEGORY_QUARTERLY_COLUMNS = [
    "fiscal_year",
    "fiscal_quarter",
    "category",
    "row_count",
    "numeric_obligation_rows",
    "transaction_obligated_amount",
]
CATEGORY_MAPPING_COLUMNS = [
    "fiscal_year",
    "category",
    "mapping_status",
    "grant_or_contract",
    "emergency",
    "federal_account_symbol",
    "federal_account_name",
    "transaction_obligated_amount",
    "row_count",
    "name_matches_expectation",
    "notes",
]
UNMAPPED_COLUMNS = [
    "fiscal_year",
    "grant_or_contract",
    "emergency",
    "federal_account_symbol",
    "federal_account_name",
    "row_count",
    "numeric_obligation_rows",
    "transaction_obligated_amount",
    "gross_outlay_amount_fyb_to_period_end",
    "reason",
]


def _source_column(name: str) -> sa.Column:
    if name in MONEY_COLUMNS:
        col_type = sa.Numeric(24, 2)
    elif name in PERCENT_COLUMNS:
        col_type = sa.Numeric(12, 4)
    elif name in DATE_COLUMNS:
        col_type = sa.Date()
    elif name in INT_COLUMNS:
        col_type = sa.Integer()
    elif name in BOOL_COLUMNS:
        col_type = sa.Boolean()
    else:
        col_type = sa.Text()
    return sa.Column(name, col_type, nullable=name != "fiscal_year")


def _provenance_columns(include_fiscal_year: bool = False) -> list[sa.Column]:
    columns: list[sa.Column] = []
    if include_fiscal_year:
        columns.append(sa.Column("fiscal_year", sa.Integer(), nullable=False))
    columns.extend(
        [
            sa.Column(
                "import_run_id",
                sa.BigInteger(),
                sa.ForeignKey(f"{CDC_FUNDING_SCHEMA}.cdc_funding_import_runs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source_file_name", sa.Text(), nullable=False),
            sa.Column("source_row_number", sa.Integer(), nullable=False),
            sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        ]
    )
    return columns


def _create_source_table(
    table_name: str,
    source_columns: list[str],
    *constraints: sa.Constraint,
    include_fiscal_year: bool = False,
) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        *_provenance_columns(include_fiscal_year=include_fiscal_year),
        *[_source_column(name) for name in source_columns],
        sa.UniqueConstraint("fiscal_year", "source_file_name", "source_row_number", name=f"uq_{table_name}_source_row"),
        *constraints,
        schema=CDC_FUNDING_SCHEMA,
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {CDC_FUNDING_SCHEMA}")

    op.create_table(
        "cdc_funding_import_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("source_directory", sa.Text(), nullable=False),
        sa.Column("import_status", sa.String(32), nullable=False),
        sa.Column("import_mode", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elapsed_seconds", sa.Numeric(18, 3), nullable=True),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index("ix_cdc_funding_import_runs_fy_status", "cdc_funding_import_runs", ["fiscal_year", "import_status"], schema=CDC_FUNDING_SCHEMA)

    op.create_table(
        "cdc_funding_import_files",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "import_run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{CDC_FUNDING_SCHEMA}.cdc_funding_import_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256_checksum", sa.String(64), nullable=False),
        sa.Column("expected_row_count", sa.Integer(), nullable=True),
        sa.Column("loaded_row_count", sa.Integer(), nullable=True),
        sa.Column("load_status", sa.String(32), nullable=False),
        sa.Column("validation_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("fiscal_year", "file_name", "sha256_checksum", name="uq_cdc_funding_import_files_fy_file_sha"),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index("ix_cdc_funding_import_files_run", "cdc_funding_import_files", ["import_run_id"], schema=CDC_FUNDING_SCHEMA)

    _create_source_table(
        "cdc_funding_awards",
        AWARD_COLUMNS,
        include_fiscal_year=True,
    )
    _create_source_table(
        "cdc_funding_account_annual",
        ACCOUNT_ANNUAL_COLUMNS,
        sa.UniqueConstraint("fiscal_year", "grant_or_contract", "emergency", "federal_account_symbol", name="uq_cdc_funding_account_annual_key"),
    )
    _create_source_table(
        "cdc_funding_account_monthly",
        ACCOUNT_MONTHLY_COLUMNS,
        sa.UniqueConstraint("fiscal_year", "submission_period", "grant_or_contract", "emergency", "federal_account_symbol", name="uq_cdc_funding_account_monthly_key"),
    )
    _create_source_table(
        "cdc_funding_account_quarterly",
        ACCOUNT_QUARTERLY_COLUMNS,
        sa.UniqueConstraint("fiscal_year", "fiscal_quarter", "grant_or_contract", "emergency", "federal_account_symbol", name="uq_cdc_funding_account_quarterly_key"),
    )
    _create_source_table(
        "cdc_funding_category_comparison",
        CATEGORY_COMPARISON_COLUMNS,
        sa.UniqueConstraint("fiscal_year", "category", name="uq_cdc_funding_category_comparison_key"),
    )
    _create_source_table(
        "cdc_funding_category_monthly",
        CATEGORY_MONTHLY_COLUMNS,
        sa.UniqueConstraint("fiscal_year", "submission_period", "category", name="uq_cdc_funding_category_monthly_key"),
    )
    _create_source_table(
        "cdc_funding_category_quarterly",
        CATEGORY_QUARTERLY_COLUMNS,
        sa.UniqueConstraint("fiscal_year", "fiscal_quarter", "category", name="uq_cdc_funding_category_quarterly_key"),
    )
    _create_source_table("cdc_funding_category_mapping", CATEGORY_MAPPING_COLUMNS)
    _create_source_table(
        "cdc_funding_unmapped_accounts",
        UNMAPPED_COLUMNS,
        sa.UniqueConstraint("fiscal_year", "grant_or_contract", "emergency", "federal_account_symbol", name="uq_cdc_funding_unmapped_accounts_key"),
    )

    op.create_table(
        "cdc_funding_audits",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column(
            "import_run_id",
            sa.BigInteger(),
            sa.ForeignKey(f"{CDC_FUNDING_SCHEMA}.cdc_funding_import_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("audit_type", sa.String(128), nullable=False),
        sa.Column("source_file_name", sa.Text(), nullable=False),
        sa.Column("sha256_checksum", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("fiscal_year", "source_file_name", name="uq_cdc_funding_audits_file"),
        schema=CDC_FUNDING_SCHEMA,
    )

    # Award query indexes.
    op.create_index("ix_cfa_fy", "cdc_funding_awards", ["fiscal_year"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_period", "cdc_funding_awards", ["submission_period"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_fy_period", "cdc_funding_awards", ["fiscal_year", "submission_period"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_fy_account", "cdc_funding_awards", ["fiscal_year", "federal_account_symbol"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_fy_grant_contract", "cdc_funding_awards", ["fiscal_year", "grant_or_contract"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_fy_emergency", "cdc_funding_awards", ["fiscal_year", "emergency"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_award_key", "cdc_funding_awards", ["award_unique_key"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_recipient_state", "cdc_funding_awards", ["recipient_state"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_recipient_state_county", "cdc_funding_awards", ["recipient_state", "recipient_county"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_pop_state", "cdc_funding_awards", ["primary_place_of_performance_state"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_pop_state_county", "cdc_funding_awards", ["primary_place_of_performance_state", "primary_place_of_performance_county"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_cfda", "cdc_funding_awards", ["cfda_number"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_funding_office", "cdc_funding_awards", ["funding_office_code"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfa_awarding_office", "cdc_funding_awards", ["awarding_office_code"], schema=CDC_FUNDING_SCHEMA)

    # Summary and category indexes for later read-only API/dashboard work.
    op.create_index("ix_cfaa_fy_account_src_emg", "cdc_funding_account_annual", ["fiscal_year", "federal_account_symbol", "grant_or_contract", "emergency"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfam_fy_period", "cdc_funding_account_monthly", ["fiscal_year", "submission_period"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfaq_fy_quarter", "cdc_funding_account_quarterly", ["fiscal_year", "fiscal_quarter"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfcc_fy_category", "cdc_funding_category_comparison", ["fiscal_year", "category"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfcm_fy_period", "cdc_funding_category_monthly", ["fiscal_year", "submission_period"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfcm_fy_cat_period", "cdc_funding_category_monthly", ["fiscal_year", "category", "submission_period"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfcq_fy_quarter", "cdc_funding_category_quarterly", ["fiscal_year", "fiscal_quarter"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfcq_fy_cat_quarter", "cdc_funding_category_quarterly", ["fiscal_year", "category", "fiscal_quarter"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfmap_fy_account_src_emg", "cdc_funding_category_mapping", ["fiscal_year", "federal_account_symbol", "grant_or_contract", "emergency"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfunmap_fy_account_src_emg", "cdc_funding_unmapped_accounts", ["fiscal_year", "federal_account_symbol", "grant_or_contract", "emergency"], schema=CDC_FUNDING_SCHEMA)
    op.create_index("ix_cfaudits_fy_type", "cdc_funding_audits", ["fiscal_year", "audit_type"], schema=CDC_FUNDING_SCHEMA)


def downgrade() -> None:
    for table_name in (
        "cdc_funding_audits",
        "cdc_funding_unmapped_accounts",
        "cdc_funding_category_mapping",
        "cdc_funding_category_quarterly",
        "cdc_funding_category_monthly",
        "cdc_funding_category_comparison",
        "cdc_funding_account_quarterly",
        "cdc_funding_account_monthly",
        "cdc_funding_account_annual",
        "cdc_funding_awards",
        "cdc_funding_import_files",
        "cdc_funding_import_runs",
    ):
        op.drop_table(table_name, schema=CDC_FUNDING_SCHEMA)
