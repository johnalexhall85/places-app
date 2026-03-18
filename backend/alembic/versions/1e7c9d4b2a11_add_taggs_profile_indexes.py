"""add taggs profile indexes

Revision ID: 1e7c9d4b2a11
Revises: 6b2c4f9a1d3e
Create Date: 2026-03-12 16:55:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "1e7c9d4b2a11"
down_revision: Union[str, None] = "6b2c4f9a1d3e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TAGGS_SCHEMA = "taggs"


def upgrade() -> None:
    op.create_index(
        "taggs_award_funding_year_summary_state_fy_idx",
        "award_funding_year_summary",
        ["legal_entity_state", "funding_fiscal_year"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_year_summary_state_fy_program_office_idx",
        "award_funding_year_summary",
        ["legal_entity_state", "funding_fiscal_year", "program_office"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_year_summary_state_fy_aln_idx",
        "award_funding_year_summary",
        ["legal_entity_state", "funding_fiscal_year", "aln"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_year_summary_assistance_listing_title_idx",
        "award_funding_year_summary",
        ["assistance_listing_title"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    op.create_index(
        "taggs_award_funding_year_summary_legal_entity_name_idx",
        "award_funding_year_summary",
        ["legal_entity_name"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "taggs_award_funding_year_summary_legal_entity_name_idx",
        table_name="award_funding_year_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_year_summary_assistance_listing_title_idx",
        table_name="award_funding_year_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_year_summary_state_fy_aln_idx",
        table_name="award_funding_year_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_year_summary_state_fy_program_office_idx",
        table_name="award_funding_year_summary",
        schema=TAGGS_SCHEMA,
    )
    op.drop_index(
        "taggs_award_funding_year_summary_state_fy_idx",
        table_name="award_funding_year_summary",
        schema=TAGGS_SCHEMA,
    )
