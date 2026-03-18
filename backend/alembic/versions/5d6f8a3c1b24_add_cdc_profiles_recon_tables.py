"""add cdc funding profile reference and reconciliation tables

Revision ID: 5d6f8a3c1b24
Revises: 2c7b4d9e1a55
Create Date: 2026-03-13 18:20:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "5d6f8a3c1b24"
down_revision: Union[str, None] = "2c7b4d9e1a55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_PROFILES_SCHEMA = "cdc_profiles"
RECON_SCHEMA = "recon"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {CDC_PROFILES_SCHEMA}")
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {RECON_SCHEMA}")

    op.create_table(
        "raw_profile_rows",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("source_file_name", sa.Text(), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("project_number", sa.Text(), nullable=True),
        sa.Column("reference_number", sa.Text(), nullable=True),
        sa.Column("nofo_number", sa.Text(), nullable=True),
        sa.Column("nofo_title", sa.Text(), nullable=True),
        sa.Column("project_title", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("subcategory", sa.Text(), nullable=True),
        sa.Column("grantee_name", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("city", sa.Text(), nullable=True),
        sa.Column("county", sa.Text(), nullable=True),
        sa.Column("state_name", sa.Text(), nullable=True),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("zipcode", sa.Text(), nullable=True),
        sa.Column("congressional_district", sa.Text(), nullable=True),
        sa.Column("geography", sa.Text(), nullable=True),
        sa.Column("grantee_type", sa.Text(), nullable=True),
        sa.Column("covid_flag", sa.Text(), nullable=True),
        sa.Column(
            "raw",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fiscal_year",
            "source_file_name",
            "source_row_number",
            name="uq_cdc_profile_raw_row_source",
        ),
        schema=CDC_PROFILES_SCHEMA,
    )
    op.create_index(
        "cdc_profile_raw_rows_fy_idx",
        "raw_profile_rows",
        ["fiscal_year"],
        unique=False,
        schema=CDC_PROFILES_SCHEMA,
    )
    op.create_index(
        "cdc_profile_raw_rows_state_code_idx",
        "raw_profile_rows",
        ["state_code"],
        unique=False,
        schema=CDC_PROFILES_SCHEMA,
    )
    op.create_index(
        "cdc_profile_raw_rows_project_number_idx",
        "raw_profile_rows",
        ["project_number"],
        unique=False,
        schema=CDC_PROFILES_SCHEMA,
    )
    op.create_index(
        "cdc_profile_raw_rows_category_idx",
        "raw_profile_rows",
        ["category"],
        unique=False,
        schema=CDC_PROFILES_SCHEMA,
    )
    op.create_index(
        "cdc_profile_raw_rows_subcategory_idx",
        "raw_profile_rows",
        ["subcategory"],
        unique=False,
        schema=CDC_PROFILES_SCHEMA,
    )

    op.create_table(
        "state_year_totals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("state_name", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fiscal_year", "state_code", name="uq_cdc_profile_state_year_total"),
        schema=CDC_PROFILES_SCHEMA,
    )
    op.create_index(
        "cdc_profile_state_year_totals_fy_idx",
        "state_year_totals",
        ["fiscal_year"],
        unique=False,
        schema=CDC_PROFILES_SCHEMA,
    )
    op.create_index(
        "cdc_profile_state_year_totals_state_code_idx",
        "state_year_totals",
        ["state_code"],
        unique=False,
        schema=CDC_PROFILES_SCHEMA,
    )

    op.create_table(
        "methodology_documents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("source_file_name", sa.Text(), nullable=False),
        sa.Column("source_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fiscal_year",
            "document_type",
            "source_file_name",
            name="uq_cdc_profile_methodology_doc",
        ),
        schema=CDC_PROFILES_SCHEMA,
    )
    op.create_index(
        "cdc_profile_methodology_docs_fy_idx",
        "methodology_documents",
        ["fiscal_year"],
        unique=False,
        schema=CDC_PROFILES_SCHEMA,
    )
    op.create_index(
        "cdc_profile_methodology_docs_type_idx",
        "methodology_documents",
        ["document_type"],
        unique=False,
        schema=CDC_PROFILES_SCHEMA,
    )

    op.create_table(
        "cdc_profile_calibration",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("raw_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "normalized_amount_target",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("raw_minus_target", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "domestic_exclusion_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "included_special_stream_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "action_duplication_adjustment",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("vfc_adjustment", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "other_identified_adjustment",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "unresolved_residual",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("normalization_factor", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.Column("confidence_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "fiscal_year",
            "state_code",
            "source_system",
            name="uq_recon_cdc_profile_calibration_state_year_source",
        ),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_cdc_profile_calibration_fy_idx",
        "cdc_profile_calibration",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_cdc_profile_calibration_state_idx",
        "cdc_profile_calibration",
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_cdc_profile_calibration_source_idx",
        "cdc_profile_calibration",
        ["source_system"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "normalization_rules_by_year",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("rule_name", sa.Text(), nullable=False),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column(
            "parameter_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("effective_start", sa.Date(), nullable=True),
        sa.Column("effective_end", sa.Date(), nullable=True),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_normalization_rules_fy_idx",
        "normalization_rules_by_year",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_normalization_rules_source_idx",
        "normalization_rules_by_year",
        ["source_system"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_normalization_rules_name_idx",
        "normalization_rules_by_year",
        ["rule_name"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "normalized_state_funding",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("raw_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("normalized_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("normalized_amount_type", sa.Text(), nullable=False),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.Column("confidence_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_system",
            "fiscal_year",
            "state_code",
            name="uq_recon_normalized_state_funding_source_year_state",
        ),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_normalized_state_funding_fy_idx",
        "normalized_state_funding",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_normalized_state_funding_state_idx",
        "normalized_state_funding",
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_normalized_state_funding_source_idx",
        "normalized_state_funding",
        ["source_system"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "normalization_methodology_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.Column(
            "logged_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_normalization_methodology_log_version_idx",
        "normalization_methodology_log",
        ["methodology_version"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_normalization_methodology_log_logged_at_idx",
        "normalization_methodology_log",
        ["logged_at"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.taggs_vs_cdc_profiles")
    op.execute(
        f"""
        CREATE VIEW {RECON_SCHEMA}.taggs_vs_cdc_profiles AS
        SELECT
            fiscal_year,
            state_code,
            raw_amount,
            normalized_amount_target AS cdc_profile_amount,
            domestic_exclusion_amount,
            included_special_stream_amount,
            action_duplication_adjustment,
            vfc_adjustment,
            other_identified_adjustment,
            unresolved_residual,
            normalization_factor,
            methodology_version,
            confidence_note
        FROM {RECON_SCHEMA}.cdc_profile_calibration
        WHERE source_system = 'taggs'
        """
    )
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.usaspending_vs_cdc_profiles")
    op.execute(
        f"""
        CREATE VIEW {RECON_SCHEMA}.usaspending_vs_cdc_profiles AS
        SELECT
            fiscal_year,
            state_code,
            raw_amount,
            normalized_amount_target AS cdc_profile_amount,
            domestic_exclusion_amount,
            included_special_stream_amount,
            action_duplication_adjustment,
            vfc_adjustment,
            other_identified_adjustment,
            unresolved_residual,
            normalization_factor,
            methodology_version,
            confidence_note
        FROM {RECON_SCHEMA}.cdc_profile_calibration
        WHERE source_system = 'usaspending'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.usaspending_vs_cdc_profiles")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.taggs_vs_cdc_profiles")

    op.drop_index(
        "recon_normalization_methodology_log_logged_at_idx",
        table_name="normalization_methodology_log",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_normalization_methodology_log_version_idx",
        table_name="normalization_methodology_log",
        schema=RECON_SCHEMA,
    )
    op.drop_table("normalization_methodology_log", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_normalized_state_funding_source_idx",
        table_name="normalized_state_funding",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_normalized_state_funding_state_idx",
        table_name="normalized_state_funding",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_normalized_state_funding_fy_idx",
        table_name="normalized_state_funding",
        schema=RECON_SCHEMA,
    )
    op.drop_table("normalized_state_funding", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_normalization_rules_name_idx",
        table_name="normalization_rules_by_year",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_normalization_rules_source_idx",
        table_name="normalization_rules_by_year",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_normalization_rules_fy_idx",
        table_name="normalization_rules_by_year",
        schema=RECON_SCHEMA,
    )
    op.drop_table("normalization_rules_by_year", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_cdc_profile_calibration_source_idx",
        table_name="cdc_profile_calibration",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_cdc_profile_calibration_state_idx",
        table_name="cdc_profile_calibration",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_cdc_profile_calibration_fy_idx",
        table_name="cdc_profile_calibration",
        schema=RECON_SCHEMA,
    )
    op.drop_table("cdc_profile_calibration", schema=RECON_SCHEMA)

    op.drop_index(
        "cdc_profile_methodology_docs_type_idx",
        table_name="methodology_documents",
        schema=CDC_PROFILES_SCHEMA,
    )
    op.drop_index(
        "cdc_profile_methodology_docs_fy_idx",
        table_name="methodology_documents",
        schema=CDC_PROFILES_SCHEMA,
    )
    op.drop_table("methodology_documents", schema=CDC_PROFILES_SCHEMA)

    op.drop_index(
        "cdc_profile_state_year_totals_state_code_idx",
        table_name="state_year_totals",
        schema=CDC_PROFILES_SCHEMA,
    )
    op.drop_index(
        "cdc_profile_state_year_totals_fy_idx",
        table_name="state_year_totals",
        schema=CDC_PROFILES_SCHEMA,
    )
    op.drop_table("state_year_totals", schema=CDC_PROFILES_SCHEMA)

    op.drop_index(
        "cdc_profile_raw_rows_subcategory_idx",
        table_name="raw_profile_rows",
        schema=CDC_PROFILES_SCHEMA,
    )
    op.drop_index(
        "cdc_profile_raw_rows_category_idx",
        table_name="raw_profile_rows",
        schema=CDC_PROFILES_SCHEMA,
    )
    op.drop_index(
        "cdc_profile_raw_rows_project_number_idx",
        table_name="raw_profile_rows",
        schema=CDC_PROFILES_SCHEMA,
    )
    op.drop_index(
        "cdc_profile_raw_rows_state_code_idx",
        table_name="raw_profile_rows",
        schema=CDC_PROFILES_SCHEMA,
    )
    op.drop_index(
        "cdc_profile_raw_rows_fy_idx",
        table_name="raw_profile_rows",
        schema=CDC_PROFILES_SCHEMA,
    )
    op.drop_table("raw_profile_rows", schema=CDC_PROFILES_SCHEMA)
