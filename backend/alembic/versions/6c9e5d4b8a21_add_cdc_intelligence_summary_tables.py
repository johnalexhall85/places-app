"""add cdc intelligence summary tables

Revision ID: 6c9e5d4b8a21
Revises: d2e4f6a8b0c1
Create Date: 2026-03-19 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6c9e5d4b8a21"
down_revision: Union[str, None] = "d2e4f6a8b0c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"


def upgrade() -> None:
    op.create_table(
        "intelligence_state_category_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("state_name", sa.Text(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("program_area", sa.Text(), nullable=True),
        sa.Column("mechanism", sa.Text(), nullable=True),
        sa.Column("recipient_type", sa.Text(), nullable=True),
        sa.Column("component", sa.Text(), nullable=False),
        sa.Column(
            "chip_default_include",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_emergency",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "award_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("population", sa.Numeric(precision=18, scale=0), nullable=True),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_category_state_idx",
        "intelligence_state_category_summary",
        ["state_code"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_category_fiscal_year_idx",
        "intelligence_state_category_summary",
        ["fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_category_program_area_idx",
        "intelligence_state_category_summary",
        ["program_area"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_category_mechanism_idx",
        "intelligence_state_category_summary",
        ["mechanism"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_category_recipient_type_idx",
        "intelligence_state_category_summary",
        ["recipient_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_category_component_idx",
        "intelligence_state_category_summary",
        ["component"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_category_emergency_idx",
        "intelligence_state_category_summary",
        ["is_emergency"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_category_lookup_idx",
        "intelligence_state_category_summary",
        [
            "state_code",
            "fiscal_year",
            "program_area",
            "mechanism",
            "recipient_type",
            "component",
            "is_emergency",
            "chip_default_include",
        ],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.create_table(
        "intelligence_state_subcategory_summary",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("state_code", sa.String(length=2), nullable=False),
        sa.Column("state_name", sa.Text(), nullable=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("program_area", sa.Text(), nullable=True),
        sa.Column("program_name", sa.Text(), nullable=True),
        sa.Column("mechanism", sa.Text(), nullable=True),
        sa.Column("recipient_type", sa.Text(), nullable=True),
        sa.Column("component", sa.Text(), nullable=False),
        sa.Column(
            "chip_default_include",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "is_emergency",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "amount",
            sa.Numeric(precision=18, scale=2),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "award_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("population", sa.Numeric(precision=18, scale=0), nullable=True),
        sa.Column(
            "refreshed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_subcategory_state_idx",
        "intelligence_state_subcategory_summary",
        ["state_code"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_subcategory_fiscal_year_idx",
        "intelligence_state_subcategory_summary",
        ["fiscal_year"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_subcategory_program_area_idx",
        "intelligence_state_subcategory_summary",
        ["program_area"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_subcategory_program_name_idx",
        "intelligence_state_subcategory_summary",
        ["program_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_subcategory_mechanism_idx",
        "intelligence_state_subcategory_summary",
        ["mechanism"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_subcategory_recipient_type_idx",
        "intelligence_state_subcategory_summary",
        ["recipient_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_subcategory_component_idx",
        "intelligence_state_subcategory_summary",
        ["component"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_subcategory_emergency_idx",
        "intelligence_state_subcategory_summary",
        ["is_emergency"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_intel_state_subcategory_lookup_idx",
        "intelligence_state_subcategory_summary",
        [
            "state_code",
            "fiscal_year",
            "program_area",
            "mechanism",
            "recipient_type",
            "component",
            "is_emergency",
            "chip_default_include",
        ],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "cdc_intel_state_subcategory_lookup_idx",
        table_name="intelligence_state_subcategory_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_subcategory_emergency_idx",
        table_name="intelligence_state_subcategory_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_subcategory_component_idx",
        table_name="intelligence_state_subcategory_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_subcategory_recipient_type_idx",
        table_name="intelligence_state_subcategory_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_subcategory_mechanism_idx",
        table_name="intelligence_state_subcategory_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_subcategory_program_name_idx",
        table_name="intelligence_state_subcategory_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_subcategory_program_area_idx",
        table_name="intelligence_state_subcategory_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_subcategory_fiscal_year_idx",
        table_name="intelligence_state_subcategory_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_subcategory_state_idx",
        table_name="intelligence_state_subcategory_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("intelligence_state_subcategory_summary", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_intel_state_category_lookup_idx",
        table_name="intelligence_state_category_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_category_emergency_idx",
        table_name="intelligence_state_category_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_category_component_idx",
        table_name="intelligence_state_category_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_category_recipient_type_idx",
        table_name="intelligence_state_category_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_category_mechanism_idx",
        table_name="intelligence_state_category_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_category_program_area_idx",
        table_name="intelligence_state_category_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_category_fiscal_year_idx",
        table_name="intelligence_state_category_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_intel_state_category_state_idx",
        table_name="intelligence_state_category_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("intelligence_state_category_summary", schema=CDC_FUNDING_SCHEMA)
