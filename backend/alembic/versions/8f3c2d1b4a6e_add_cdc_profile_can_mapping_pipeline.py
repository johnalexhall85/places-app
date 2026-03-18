"""add cdc profile assisted can mapping pipeline tables and columns

Revision ID: 8f3c2d1b4a6e
Revises: 5d6f8a3c1b24
Create Date: 2026-03-13 22:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "8f3c2d1b4a6e"
down_revision: Union[str, None] = "5d6f8a3c1b24"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_PROFILES_SCHEMA = "cdc_profiles"
TAGGS_SCHEMA = "taggs"


def upgrade() -> None:
    op.add_column(
        "raw_profile_rows",
        sa.Column("funding_opportunity_title", sa.Text(), nullable=True),
        schema=CDC_PROFILES_SCHEMA,
    )
    op.execute(
        f"""
        UPDATE {CDC_PROFILES_SCHEMA}.raw_profile_rows
        SET funding_opportunity_title = project_title
        WHERE funding_opportunity_title IS NULL
          AND project_title IS NOT NULL
        """
    )

    for table_name in ("award_funding_summary", "state_funding_summary"):
        op.add_column(table_name, sa.Column("effective_program_name", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
        op.add_column(table_name, sa.Column("effective_category", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
        op.add_column(table_name, sa.Column("effective_subcategory", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
        op.add_column(table_name, sa.Column("effective_mapping_method", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
        op.add_column(table_name, sa.Column("funding_stream", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
        op.add_column(table_name, sa.Column("appropriation_type", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
        op.add_column(
            table_name,
            sa.Column(
                "has_profile_assisted_mapping",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            schema=TAGGS_SCHEMA,
        )
        op.add_column(
            table_name,
            sa.Column(
                "has_fallback_inference",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
            schema=TAGGS_SCHEMA,
        )
        op.add_column(table_name, sa.Column("can_mapping_version", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)

    op.create_index(
        "taggs_award_funding_summary_effective_category_idx",
        "award_funding_summary",
        ["effective_category"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_summary_funding_stream_idx",
        "award_funding_summary",
        ["funding_stream"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_state_funding_summary_effective_category_idx",
        "state_funding_summary",
        ["effective_category"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_state_funding_summary_funding_stream_idx",
        "state_funding_summary",
        ["funding_stream"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )

    op.add_column("can_classification", sa.Column("observed_first_fy", sa.Integer(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("observed_last_fy", sa.Integer(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("observed_row_count", sa.Integer(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column(
        "can_classification",
        sa.Column("observed_total_funding", sa.Numeric(precision=18, scale=2), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    op.add_column("can_classification", sa.Column("dominant_program_office", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("dominant_aln", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column(
        "can_classification",
        sa.Column("dominant_assistance_listing_title", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    op.add_column(
        "can_classification",
        sa.Column("profile_inferred_program_name", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    op.add_column("can_classification", sa.Column("profile_inferred_category", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("profile_inferred_subcategory", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("profile_match_count", sa.Integer(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column(
        "can_classification",
        sa.Column("profile_match_confidence", sa.Numeric(precision=5, scale=2), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    op.add_column(
        "can_classification",
        sa.Column(
            "profile_match_evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema=TAGGS_SCHEMA,
    )
    op.add_column(
        "can_classification",
        sa.Column("fallback_inferred_program_name", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    op.add_column("can_classification", sa.Column("fallback_inferred_category", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("fallback_inferred_subcategory", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column(
        "can_classification",
        sa.Column("fallback_guess_confidence", sa.Numeric(precision=5, scale=2), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    op.add_column(
        "can_classification",
        sa.Column(
            "fallback_guess_evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema=TAGGS_SCHEMA,
    )
    op.add_column("can_classification", sa.Column("manual_program_name", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("manual_category", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("manual_subcategory", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("manual_notes", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column(
        "can_classification",
        sa.Column(
            "is_manually_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema=TAGGS_SCHEMA,
    )
    op.add_column("can_classification", sa.Column("effective_program_name", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("effective_category", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("effective_subcategory", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("effective_mapping_method", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)
    op.add_column("can_classification", sa.Column("can_mapping_version", sa.Text(), nullable=True), schema=TAGGS_SCHEMA)

    op.create_index(
        "taggs_can_classification_effective_category_idx",
        "can_classification",
        ["effective_category"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_can_classification_effective_method_idx",
        "can_classification",
        ["effective_mapping_method"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )

    op.execute(
        f"""
        UPDATE {TAGGS_SCHEMA}.can_classification
        SET
            manual_category = COALESCE(manual_category, category_override),
            manual_subcategory = COALESCE(manual_subcategory, subcategory_override),
            manual_notes = COALESCE(manual_notes, notes),
            effective_category = COALESCE(effective_category, category_override),
            effective_subcategory = COALESCE(effective_subcategory, subcategory_override),
            effective_mapping_method = COALESCE(
                effective_mapping_method,
                CASE
                    WHEN category_override IS NOT NULL OR subcategory_override IS NOT NULL THEN 'manual_override'
                    ELSE 'unknown'
                END
            )
        """
    )

    op.create_table(
        "can_profile_match_audit",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("can_code", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("state_code", sa.Text(), nullable=False),
        sa.Column("matched_profile_row_id", sa.BigInteger(), nullable=False),
        sa.Column("matched_taggs_row_id", sa.BigInteger(), nullable=False),
        sa.Column("match_score", sa.Numeric(precision=6, scale=4), nullable=False),
        sa.Column("match_strength", sa.Text(), nullable=False),
        sa.Column("match_method", sa.Text(), nullable=True),
        sa.Column(
            "evidence_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("can_mapping_version", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "matched_profile_row_id",
            "can_mapping_version",
            name="uq_taggs_can_profile_match_audit_profile_row_version",
        ),
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_can_profile_match_audit_can_idx",
        "can_profile_match_audit",
        ["can_code"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_can_profile_match_audit_fy_idx",
        "can_profile_match_audit",
        ["fiscal_year"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_can_profile_match_audit_state_idx",
        "can_profile_match_audit",
        ["state_code"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_can_profile_match_audit_strength_idx",
        "can_profile_match_audit",
        ["match_strength"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )

    op.execute(
        f"""
        CREATE OR REPLACE VIEW {CDC_PROFILES_SCHEMA}.profile_detail_rows AS
        SELECT
            id,
            fiscal_year,
            source_file_name,
            source_row_number,
            project_number,
            reference_number,
            nofo_number,
            nofo_title,
            COALESCE(funding_opportunity_title, project_title) AS funding_opportunity_title,
            project_title,
            amount,
            category,
            subcategory,
            grantee_name,
            address,
            city,
            county,
            state_name,
            state_code,
            zipcode,
            congressional_district,
            geography,
            grantee_type,
            covid_flag,
            raw,
            created_at
        FROM {CDC_PROFILES_SCHEMA}.raw_profile_rows
        """
    )
    op.execute(
        f"""
        CREATE OR REPLACE VIEW {CDC_PROFILES_SCHEMA}.profile_state_totals AS
        SELECT
            id,
            fiscal_year,
            state_code,
            state_name,
            amount,
            row_count,
            methodology_version,
            refreshed_at
        FROM {CDC_PROFILES_SCHEMA}.state_year_totals
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {CDC_PROFILES_SCHEMA}.profile_state_totals")
    op.execute(f"DROP VIEW IF EXISTS {CDC_PROFILES_SCHEMA}.profile_detail_rows")

    op.drop_index(
        "taggs_can_profile_match_audit_strength_idx",
        table_name="can_profile_match_audit",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_can_profile_match_audit_state_idx",
        table_name="can_profile_match_audit",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_can_profile_match_audit_fy_idx",
        table_name="can_profile_match_audit",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_can_profile_match_audit_can_idx",
        table_name="can_profile_match_audit",
        schema=TAGGS_SCHEMA,
    )
    op.drop_table("can_profile_match_audit", schema=TAGGS_SCHEMA)

    op.drop_index(
        "taggs_can_classification_effective_method_idx",
        table_name="can_classification",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_can_classification_effective_category_idx",
        table_name="can_classification",
        schema=TAGGS_SCHEMA,
    )

    for column_name in (
        "can_mapping_version",
        "effective_mapping_method",
        "effective_subcategory",
        "effective_category",
        "effective_program_name",
        "is_manually_verified",
        "manual_notes",
        "manual_subcategory",
        "manual_category",
        "manual_program_name",
        "fallback_guess_evidence_json",
        "fallback_guess_confidence",
        "fallback_inferred_subcategory",
        "fallback_inferred_category",
        "fallback_inferred_program_name",
        "profile_match_evidence_json",
        "profile_match_confidence",
        "profile_match_count",
        "profile_inferred_subcategory",
        "profile_inferred_category",
        "profile_inferred_program_name",
        "dominant_assistance_listing_title",
        "dominant_aln",
        "dominant_program_office",
        "observed_total_funding",
        "observed_row_count",
        "observed_last_fy",
        "observed_first_fy",
    ):
        op.drop_column("can_classification", column_name, schema=TAGGS_SCHEMA)

    op.drop_index(
        "taggs_state_funding_summary_funding_stream_idx",
        table_name="state_funding_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_state_funding_summary_effective_category_idx",
        table_name="state_funding_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_summary_funding_stream_idx",
        table_name="award_funding_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_summary_effective_category_idx",
        table_name="award_funding_summary",
        schema=TAGGS_SCHEMA,
    )

    for table_name in ("state_funding_summary", "award_funding_summary"):
        for column_name in (
            "can_mapping_version",
            "has_fallback_inference",
            "has_profile_assisted_mapping",
            "appropriation_type",
            "funding_stream",
            "effective_mapping_method",
            "effective_subcategory",
            "effective_category",
            "effective_program_name",
        ):
            op.drop_column(table_name, column_name, schema=TAGGS_SCHEMA)

    op.drop_column("raw_profile_rows", "funding_opportunity_title", schema=CDC_PROFILES_SCHEMA)
