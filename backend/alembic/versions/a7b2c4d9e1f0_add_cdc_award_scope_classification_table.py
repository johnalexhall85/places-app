"""add cdc award scope classification table

Revision ID: a7b2c4d9e1f0
Revises: f3c1d9a7b2e4
Create Date: 2026-03-07 17:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a7b2c4d9e1f0"
down_revision: Union[str, None] = "f3c1d9a7b2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"


def upgrade() -> None:
    op.create_table(
        "award_scope_classification",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assistance_award_unique_key", sa.Text(), nullable=False),
        sa.Column("award_id_fain", sa.Text(), nullable=True),
        sa.Column("scope_classification", sa.String(length=32), nullable=False),
        sa.Column("scope_score", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("scope_confidence", sa.String(length=16), nullable=False, server_default=sa.text("'low'")),
        sa.Column(
            "reason_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "is_allocatable_to_counties",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("allocation_method_default", sa.Text(), nullable=True),
        sa.Column("classifier_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "assistance_award_unique_key",
            name="uq_cdc_award_scope_classification_award_key",
        ),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_award_scope_classification_award_key_idx",
        "award_scope_classification",
        ["assistance_award_unique_key"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_award_scope_classification_scope_idx",
        "award_scope_classification",
        ["scope_classification"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_award_scope_classification_allocatable_idx",
        "award_scope_classification",
        ["is_allocatable_to_counties"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "cdc_award_scope_classification_allocatable_idx",
        table_name="award_scope_classification",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_award_scope_classification_scope_idx",
        table_name="award_scope_classification",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_award_scope_classification_award_key_idx",
        table_name="award_scope_classification",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("award_scope_classification", schema=CDC_FUNDING_SCHEMA)
