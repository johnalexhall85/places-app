"""add cdc ingestion provenance and stable subaward key

Revision ID: f6a2b9d4c8e1
Revises: c9e2a1b6d4f7
Create Date: 2026-03-07 23:40:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a2b9d4c8e1"
down_revision: Union[str, None] = "c9e2a1b6d4f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"


def upgrade() -> None:
    op.add_column(
        "prime_awards",
        sa.Column("source_file_name", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_awards",
        sa.Column("source_import_batch_id", sa.String(length=64), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_awards",
        sa.Column("source_imported_at", sa.DateTime(timezone=False), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_source_file_idx",
        "prime_awards",
        ["source_file_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.add_column(
        "prime_transactions",
        sa.Column("source_file_name", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_transactions",
        sa.Column("source_import_batch_id", sa.String(length=64), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_transactions",
        sa.Column("source_imported_at", sa.DateTime(timezone=False), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_source_file_idx",
        "prime_transactions",
        ["source_file_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.add_column(
        "subawards",
        sa.Column("subaward_unique_key", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "subawards",
        sa.Column("source_file_name", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "subawards",
        sa.Column("source_import_batch_id", sa.String(length=64), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "subawards",
        sa.Column("source_imported_at", sa.DateTime(timezone=False), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )

    # Keep subaward idempotency stable across file reruns by deriving a deterministic key.
    op.execute(
        f"""
        UPDATE {CDC_FUNDING_SCHEMA}.subawards
        SET subaward_unique_key = (
            COALESCE(prime_award_unique_key, '') || '|' ||
            COALESCE(subaward_number, '') || '|' ||
            COALESCE(TO_CHAR(subaward_action_date, 'YYYY-MM-DD'), '') || '|' ||
            COALESCE(subawardee_name, '') || '|' ||
            COALESCE(subaward_amount::text, '')
        )
        """
    )

    op.alter_column(
        "subawards",
        "subaward_unique_key",
        existing_type=sa.Text(),
        nullable=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_unique_constraint(
        "uq_cdc_subawards_unique_key",
        "subawards",
        ["subaward_unique_key"],
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_source_file_idx",
        "subawards",
        ["source_file_name"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "cdc_subawards_source_file_idx",
        table_name="subawards",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_constraint(
        "uq_cdc_subawards_unique_key",
        "subawards",
        schema=CDC_FUNDING_SCHEMA,
        type_="unique",
    )
    op.drop_column("subawards", "source_imported_at", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("subawards", "source_import_batch_id", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("subawards", "source_file_name", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("subawards", "subaward_unique_key", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_prime_transactions_source_file_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_column("prime_transactions", "source_imported_at", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_transactions", "source_import_batch_id", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_transactions", "source_file_name", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_prime_awards_source_file_idx",
        table_name="prime_awards",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_column("prime_awards", "source_imported_at", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_awards", "source_import_batch_id", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_awards", "source_file_name", schema=CDC_FUNDING_SCHEMA)
