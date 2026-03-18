"""add taggs schema tables

Revision ID: 6b2c4f9a1d3e
Revises: d1f4c7b9e2a6
Create Date: 2026-03-12 16:20:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6b2c4f9a1d3e"
down_revision: Union[str, None] = "d1f4c7b9e2a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TAGGS_SCHEMA = "taggs"


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {TAGGS_SCHEMA}")

    op.create_table(
        "raw_awards",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source_file", sa.Text(), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("source_funding_year_hint", sa.Integer(), nullable=True),
        sa.Column("row_number_main", sa.Integer(), nullable=True),
        sa.Column("issue_date_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("opdiv", sa.Text(), nullable=True),
        sa.Column("program_office", sa.Text(), nullable=True),
        sa.Column("legal_entity_name", sa.Text(), nullable=True),
        sa.Column("legal_entity_state", sa.Text(), nullable=True),
        sa.Column("legal_entity_county", sa.Text(), nullable=True),
        sa.Column("period_of_performance_start_date", sa.Date(), nullable=True),
        sa.Column("period_of_performance_end_date", sa.Date(), nullable=True),
        sa.Column("award_termination_date", sa.Date(), nullable=True),
        sa.Column("uei", sa.Text(), nullable=True),
        sa.Column("metro_non_metro", sa.Text(), nullable=True),
        sa.Column("recipient_class", sa.Text(), nullable=True),
        sa.Column("recipient_type", sa.Text(), nullable=True),
        sa.Column("award_number", sa.Text(), nullable=True),
        sa.Column("award_title", sa.Text(), nullable=True),
        sa.Column("award_description", sa.Text(), nullable=True),
        sa.Column("award_class", sa.Text(), nullable=True),
        sa.Column("award_activity_type", sa.Text(), nullable=True),
        sa.Column("award_action_type", sa.Text(), nullable=True),
        sa.Column("aln", sa.Text(), nullable=True),
        sa.Column("assistance_listing_title", sa.Text(), nullable=True),
        sa.Column("funding_fiscal_year", sa.Integer(), nullable=True),
        sa.Column("sum_of_actions", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("legal_entity_county_normalized", sa.Text(), nullable=True),
        sa.Column("legal_entity_state_normalized", sa.Text(), nullable=True),
        sa.Column("award_uri", sa.Text(), nullable=True),
        sa.Column(
            "description_contains_html",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "loaded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=TAGGS_SCHEMA,
    )

    op.create_index(
        "taggs_raw_awards_funding_fiscal_year_idx",
        "raw_awards",
        ["funding_fiscal_year"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_raw_awards_award_number_idx",
        "raw_awards",
        ["award_number"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_raw_awards_program_office_idx",
        "raw_awards",
        ["program_office"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_raw_awards_legal_entity_state_idx",
        "raw_awards",
        ["legal_entity_state"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_raw_awards_legal_entity_county_normalized_idx",
        "raw_awards",
        ["legal_entity_county_normalized"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_raw_awards_aln_idx",
        "raw_awards",
        ["aln"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )

    op.create_table(
        "award_funding_year_summary",
        sa.Column("award_number", sa.Text(), nullable=False),
        sa.Column("funding_fiscal_year", sa.Integer(), nullable=False),
        sa.Column("opdiv", sa.Text(), nullable=True),
        sa.Column("program_office", sa.Text(), nullable=True),
        sa.Column("legal_entity_name", sa.Text(), nullable=True),
        sa.Column("legal_entity_state", sa.Text(), nullable=True),
        sa.Column("legal_entity_county_normalized", sa.Text(), nullable=True),
        sa.Column("award_title", sa.Text(), nullable=True),
        sa.Column("award_description", sa.Text(), nullable=True),
        sa.Column("award_class", sa.Text(), nullable=True),
        sa.Column("award_activity_type", sa.Text(), nullable=True),
        sa.Column("award_action_type", sa.Text(), nullable=True),
        sa.Column("aln", sa.Text(), nullable=True),
        sa.Column("assistance_listing_title", sa.Text(), nullable=True),
        sa.Column("total_sum_of_actions", sa.Numeric(precision=18, scale=2), nullable=True),
        sa.Column("award_row_count", sa.Integer(), nullable=False),
        sa.Column("source_file_count", sa.Integer(), nullable=False),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint(
            "award_number",
            "funding_fiscal_year",
            name="pk_taggs_award_funding_year_summary",
        ),
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_year_summary_funding_fiscal_year_idx",
        "award_funding_year_summary",
        ["funding_fiscal_year"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_year_summary_program_office_idx",
        "award_funding_year_summary",
        ["program_office"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_year_summary_state_idx",
        "award_funding_year_summary",
        ["legal_entity_state"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_year_summary_county_idx",
        "award_funding_year_summary",
        ["legal_entity_county_normalized"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_year_summary_aln_idx",
        "award_funding_year_summary",
        ["aln"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "taggs_award_funding_year_summary_aln_idx",
        table_name="award_funding_year_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_year_summary_county_idx",
        table_name="award_funding_year_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_year_summary_state_idx",
        table_name="award_funding_year_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_year_summary_program_office_idx",
        table_name="award_funding_year_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_year_summary_funding_fiscal_year_idx",
        table_name="award_funding_year_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_table("award_funding_year_summary", schema=TAGGS_SCHEMA)

    op.drop_index("taggs_raw_awards_aln_idx", table_name="raw_awards", schema=TAGGS_SCHEMA)
    op.drop_index(
        "taggs_raw_awards_legal_entity_county_normalized_idx",
        table_name="raw_awards",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_raw_awards_legal_entity_state_idx",
        table_name="raw_awards",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_raw_awards_program_office_idx",
        table_name="raw_awards",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_raw_awards_award_number_idx",
        table_name="raw_awards",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_raw_awards_funding_fiscal_year_idx",
        table_name="raw_awards",
        schema=TAGGS_SCHEMA,
    )
    op.drop_table("raw_awards", schema=TAGGS_SCHEMA)

    op.execute(f"DROP SCHEMA IF EXISTS {TAGGS_SCHEMA}")
