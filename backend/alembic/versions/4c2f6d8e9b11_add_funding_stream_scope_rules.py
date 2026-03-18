"""add funding stream scope rules and derived recon tables

Revision ID: 4c2f6d8e9b11
Revises: 8f3c2d1b4a6e
Create Date: 2026-03-13 21:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "4c2f6d8e9b11"
down_revision: Union[str, None] = "8f3c2d1b4a6e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

RECON_SCHEMA = "recon"


def upgrade() -> None:
    op.add_column(
        "cdc_profile_calibration",
        sa.Column(
            "classified_profile_scope_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        "cdc_profile_calibration",
        sa.Column(
            "cdc_profile_amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        "cdc_profile_calibration",
        sa.Column(
            "residual_difference",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        "cdc_profile_calibration",
        sa.Column(
            "major_difference_drivers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        "cdc_profile_calibration",
        sa.Column(
            "normalization_method",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'funding_stream_scope_rules'"),
        ),
        schema=RECON_SCHEMA,
    )

    op.add_column(
        "normalized_state_funding",
        sa.Column(
            "normalization_method",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'funding_stream_scope_rules'"),
        ),
        schema=RECON_SCHEMA,
    )
    op.add_column(
        "normalized_state_funding",
        sa.Column(
            "funding_stream_logic_version",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'funding_stream_logic_v2026_03_13'"),
        ),
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "defc_classification_rules",
        sa.Column("defc_code", sa.String(length=16), nullable=False),
        sa.Column("funding_stream", sa.Text(), nullable=False),
        sa.Column("appropriation_type_normalized", sa.Text(), nullable=True),
        sa.Column("is_covid_related", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_arpa_related", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "include_in_cdc_profile_scope_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "default_inclusion_weight",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("defc_code"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_defc_classification_rules_stream_idx",
        "defc_classification_rules",
        ["funding_stream"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "appropriation_type_rules",
        sa.Column("appropriation_type_raw", sa.Text(), nullable=False),
        sa.Column("appropriation_type_normalized", sa.Text(), nullable=False),
        sa.Column("default_funding_stream", sa.Text(), nullable=False),
        sa.Column(
            "default_include_in_cdc_profile_scope",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "default_inclusion_weight",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("appropriation_type_raw"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_appropriation_type_rules_norm_idx",
        "appropriation_type_rules",
        ["appropriation_type_normalized"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "federal_account_inclusion_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("federal_account_symbol", sa.Text(), nullable=True),
        sa.Column("treasury_account_symbol", sa.Text(), nullable=True),
        sa.Column("program_activity_name", sa.Text(), nullable=True),
        sa.Column("can_like_program_hint", sa.Text(), nullable=True),
        sa.Column("default_funding_stream", sa.Text(), nullable=True),
        sa.Column(
            "include_in_cdc_profile_scope_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "default_inclusion_weight",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_federal_account_rules_symbol_idx",
        "federal_account_inclusion_rules",
        ["federal_account_symbol"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_federal_account_rules_tas_idx",
        "federal_account_inclusion_rules",
        ["treasury_account_symbol"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "cdc_profile_scope_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_system", sa.Text(), nullable=False),
        sa.Column("funding_stream", sa.Text(), nullable=True),
        sa.Column("can_code", sa.Text(), nullable=True),
        sa.Column("federal_account_symbol", sa.Text(), nullable=True),
        sa.Column("treasury_account_symbol", sa.Text(), nullable=True),
        sa.Column("program_activity_name", sa.Text(), nullable=True),
        sa.Column("include_in_profile_scope", sa.Boolean(), nullable=False),
        sa.Column(
            "inclusion_weight",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("rationale", sa.Text(), nullable=False),
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
        "recon_cdc_profile_scope_rules_source_idx",
        "cdc_profile_scope_rules",
        ["source_system"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_cdc_profile_scope_rules_stream_idx",
        "cdc_profile_scope_rules",
        ["funding_stream"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_cdc_profile_scope_rules_can_idx",
        "cdc_profile_scope_rules",
        ["can_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "usaspending_funding_streams",
        sa.Column("assistance_transaction_unique_key", sa.Text(), nullable=False),
        sa.Column("assistance_award_unique_key", sa.Text(), nullable=True),
        sa.Column("award_id_fain", sa.Text(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("raw_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("appropriation_type_raw", sa.Text(), nullable=True),
        sa.Column("appropriation_type_normalized", sa.Text(), nullable=True),
        sa.Column("appropriation_subtype_raw", sa.Text(), nullable=True),
        sa.Column("defc_code_normalized", sa.Text(), nullable=True),
        sa.Column("federal_account_symbol", sa.Text(), nullable=True),
        sa.Column("treasury_account_symbol", sa.Text(), nullable=True),
        sa.Column("appropriation_account", sa.Text(), nullable=True),
        sa.Column("program_activity_name", sa.Text(), nullable=True),
        sa.Column("funding_stream", sa.Text(), nullable=False),
        sa.Column(
            "include_in_cdc_profile_scope",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "inclusion_weight",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("inclusion_reason", sa.Text(), nullable=True),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.Column("funding_stream_logic_version", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("assistance_transaction_unique_key"),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_usaspending_funding_streams_fy_idx",
        "usaspending_funding_streams",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_usaspending_funding_streams_state_idx",
        "usaspending_funding_streams",
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_usaspending_funding_streams_stream_idx",
        "usaspending_funding_streams",
        ["funding_stream"],
        unique=False,
        schema=RECON_SCHEMA,
    )

    op.create_table(
        "taggs_funding_streams",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("award_number", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("can_code", sa.Text(), nullable=True),
        sa.Column("raw_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default=sa.text("0")),
        sa.Column("raw_funding_stream", sa.Text(), nullable=True),
        sa.Column("funding_stream", sa.Text(), nullable=False),
        sa.Column(
            "include_in_cdc_profile_scope",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "inclusion_weight",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("profile_scope_reason", sa.Text(), nullable=True),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.Column("funding_stream_logic_version", sa.Text(), nullable=False),
        sa.Column("can_mapping_version", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "award_number",
            "fiscal_year",
            "state_code",
            "can_code",
            name="uq_recon_taggs_funding_streams_award_state_year_can",
        ),
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_taggs_funding_streams_fy_idx",
        "taggs_funding_streams",
        ["fiscal_year"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_taggs_funding_streams_state_idx",
        "taggs_funding_streams",
        ["state_code"],
        unique=False,
        schema=RECON_SCHEMA,
    )
    op.create_index(
        "recon_taggs_funding_streams_stream_idx",
        "taggs_funding_streams",
        ["funding_stream"],
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
            source_system,
            raw_amount,
            classified_profile_scope_amount,
            cdc_profile_amount,
            residual_difference,
            major_difference_drivers,
            normalization_method,
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
            source_system,
            raw_amount,
            classified_profile_scope_amount,
            cdc_profile_amount,
            residual_difference,
            major_difference_drivers,
            normalization_method,
            methodology_version,
            confidence_note
        FROM {RECON_SCHEMA}.cdc_profile_calibration
        WHERE source_system = 'usaspending'
        """
    )


def downgrade() -> None:
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.usaspending_vs_cdc_profiles")
    op.execute(f"DROP VIEW IF EXISTS {RECON_SCHEMA}.taggs_vs_cdc_profiles")

    op.drop_index("recon_taggs_funding_streams_stream_idx", table_name="taggs_funding_streams", schema=RECON_SCHEMA)
    op.drop_index("recon_taggs_funding_streams_state_idx", table_name="taggs_funding_streams", schema=RECON_SCHEMA)
    op.drop_index("recon_taggs_funding_streams_fy_idx", table_name="taggs_funding_streams", schema=RECON_SCHEMA)
    op.drop_table("taggs_funding_streams", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_usaspending_funding_streams_stream_idx",
        table_name="usaspending_funding_streams",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_usaspending_funding_streams_state_idx",
        table_name="usaspending_funding_streams",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_usaspending_funding_streams_fy_idx",
        table_name="usaspending_funding_streams",
        schema=RECON_SCHEMA,
    )
    op.drop_table("usaspending_funding_streams", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_cdc_profile_scope_rules_can_idx",
        table_name="cdc_profile_scope_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_cdc_profile_scope_rules_stream_idx",
        table_name="cdc_profile_scope_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_cdc_profile_scope_rules_source_idx",
        table_name="cdc_profile_scope_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_table("cdc_profile_scope_rules", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_federal_account_rules_tas_idx",
        table_name="federal_account_inclusion_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_index(
        "recon_federal_account_rules_symbol_idx",
        table_name="federal_account_inclusion_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_table("federal_account_inclusion_rules", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_appropriation_type_rules_norm_idx",
        table_name="appropriation_type_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_table("appropriation_type_rules", schema=RECON_SCHEMA)

    op.drop_index(
        "recon_defc_classification_rules_stream_idx",
        table_name="defc_classification_rules",
        schema=RECON_SCHEMA,
    )
    op.drop_table("defc_classification_rules", schema=RECON_SCHEMA)

    op.drop_column("normalized_state_funding", "funding_stream_logic_version", schema=RECON_SCHEMA)
    op.drop_column("normalized_state_funding", "normalization_method", schema=RECON_SCHEMA)

    op.drop_column("cdc_profile_calibration", "normalization_method", schema=RECON_SCHEMA)
    op.drop_column("cdc_profile_calibration", "major_difference_drivers", schema=RECON_SCHEMA)
    op.drop_column("cdc_profile_calibration", "residual_difference", schema=RECON_SCHEMA)
    op.drop_column("cdc_profile_calibration", "cdc_profile_amount", schema=RECON_SCHEMA)
    op.drop_column("cdc_profile_calibration", "classified_profile_scope_amount", schema=RECON_SCHEMA)
