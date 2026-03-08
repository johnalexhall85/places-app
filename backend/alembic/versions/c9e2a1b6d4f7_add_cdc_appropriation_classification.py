"""add cdc appropriation classification fields and table

Revision ID: c9e2a1b6d4f7
Revises: b8e1c4d7a2f3
Create Date: 2026-03-07 22:10:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c9e2a1b6d4f7"
down_revision: Union[str, None] = "b8e1c4d7a2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"


def upgrade() -> None:
    op.add_column(
        "prime_awards",
        sa.Column("disaster_emergency_fund_codes_raw", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_awards",
        sa.Column("appropriation_type", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_awards",
        sa.Column("appropriation_subtype", sa.String(length=64), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_awards",
        sa.Column("appropriation_reason_code", sa.String(length=64), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_awards",
        sa.Column("appropriation_classification_source", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_awards",
        sa.Column("appropriation_classifier_version", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_awards_appropriation_type_idx",
        "prime_awards",
        ["appropriation_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.add_column(
        "prime_transactions",
        sa.Column("disaster_emergency_fund_codes_raw", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_transactions",
        sa.Column("appropriation_type", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_transactions",
        sa.Column("appropriation_subtype", sa.String(length=64), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_transactions",
        sa.Column("appropriation_reason_code", sa.String(length=64), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_transactions",
        sa.Column("appropriation_classification_source", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "prime_transactions",
        sa.Column("appropriation_classifier_version", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_transactions_appropriation_type_idx",
        "prime_transactions",
        ["appropriation_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.add_column(
        "subawards",
        sa.Column("prime_award_disaster_emergency_fund_codes_raw", sa.Text(), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "subawards",
        sa.Column("appropriation_type", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "subawards",
        sa.Column("appropriation_subtype", sa.String(length=64), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "subawards",
        sa.Column("appropriation_reason_code", sa.String(length=64), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "subawards",
        sa.Column("appropriation_classification_source", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.add_column(
        "subawards",
        sa.Column("appropriation_classifier_version", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_appropriation_type_idx",
        "subawards",
        ["appropriation_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.add_column(
        "prime_transaction_state_summary",
        sa.Column("appropriation_type", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_state_summary_appropriation_type_idx",
        "prime_transaction_state_summary",
        ["appropriation_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.add_column(
        "prime_transaction_county_summary",
        sa.Column("appropriation_type", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_summary_appropriation_type_idx",
        "prime_transaction_county_summary",
        ["appropriation_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.add_column(
        "prime_transaction_county_summary_allocated",
        sa.Column("appropriation_type", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_prime_tx_county_alloc_summary_appropriation_type_idx",
        "prime_transaction_county_summary_allocated",
        ["appropriation_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.add_column(
        "subaward_state_summary",
        sa.Column("appropriation_type", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_state_summary_appropriation_type_idx",
        "subaward_state_summary",
        ["appropriation_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.add_column(
        "subaward_county_summary",
        sa.Column("appropriation_type", sa.String(length=32), nullable=True),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subaward_county_summary_appropriation_type_idx",
        "subaward_county_summary",
        ["appropriation_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )

    op.create_table(
        "appropriation_classification",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("record_type", sa.String(length=32), nullable=False),
        sa.Column("record_id", sa.Text(), nullable=False),
        sa.Column("assistance_award_unique_key", sa.Text(), nullable=True),
        sa.Column("award_id_fain", sa.Text(), nullable=True),
        sa.Column("raw_emergency_code", sa.Text(), nullable=True),
        sa.Column("appropriation_type", sa.String(length=32), nullable=False),
        sa.Column("appropriation_subtype", sa.String(length=64), nullable=True),
        sa.Column("appropriation_reason_code", sa.String(length=64), nullable=True),
        sa.Column("classification_source", sa.String(length=32), nullable=False),
        sa.Column("classifier_version", sa.String(length=32), nullable=False),
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
            "record_type",
            "record_id",
            name="uq_cdc_appropriation_classification_record",
        ),
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_appropriation_classification_record_type_idx",
        "appropriation_classification",
        ["record_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_appropriation_classification_award_key_idx",
        "appropriation_classification",
        ["assistance_award_unique_key"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_appropriation_classification_fain_idx",
        "appropriation_classification",
        ["award_id_fain"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_appropriation_classification_type_idx",
        "appropriation_classification",
        ["appropriation_type"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_appropriation_classification_raw_code_idx",
        "appropriation_classification",
        ["raw_emergency_code"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "cdc_appropriation_classification_raw_code_idx",
        table_name="appropriation_classification",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_appropriation_classification_type_idx",
        table_name="appropriation_classification",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_appropriation_classification_fain_idx",
        table_name="appropriation_classification",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_appropriation_classification_award_key_idx",
        table_name="appropriation_classification",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_index(
        "cdc_appropriation_classification_record_type_idx",
        table_name="appropriation_classification",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_table("appropriation_classification", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_subaward_county_summary_appropriation_type_idx",
        table_name="subaward_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_column("subaward_county_summary", "appropriation_type", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_subaward_state_summary_appropriation_type_idx",
        table_name="subaward_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_column("subaward_state_summary", "appropriation_type", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_prime_tx_county_alloc_summary_appropriation_type_idx",
        table_name="prime_transaction_county_summary_allocated",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_column(
        "prime_transaction_county_summary_allocated",
        "appropriation_type",
        schema=CDC_FUNDING_SCHEMA,
    )

    op.drop_index(
        "cdc_prime_tx_county_summary_appropriation_type_idx",
        table_name="prime_transaction_county_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_column("prime_transaction_county_summary", "appropriation_type", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_prime_tx_state_summary_appropriation_type_idx",
        table_name="prime_transaction_state_summary",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_column("prime_transaction_state_summary", "appropriation_type", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_subawards_appropriation_type_idx",
        table_name="subawards",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_column("subawards", "appropriation_classifier_version", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("subawards", "appropriation_classification_source", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("subawards", "appropriation_reason_code", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("subawards", "appropriation_subtype", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("subawards", "appropriation_type", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("subawards", "prime_award_disaster_emergency_fund_codes_raw", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_prime_transactions_appropriation_type_idx",
        table_name="prime_transactions",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_column("prime_transactions", "appropriation_classifier_version", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_transactions", "appropriation_classification_source", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_transactions", "appropriation_reason_code", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_transactions", "appropriation_subtype", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_transactions", "appropriation_type", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_transactions", "disaster_emergency_fund_codes_raw", schema=CDC_FUNDING_SCHEMA)

    op.drop_index(
        "cdc_prime_awards_appropriation_type_idx",
        table_name="prime_awards",
        schema=CDC_FUNDING_SCHEMA,
    )
    op.drop_column("prime_awards", "appropriation_classifier_version", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_awards", "appropriation_classification_source", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_awards", "appropriation_reason_code", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_awards", "appropriation_subtype", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_awards", "appropriation_type", schema=CDC_FUNDING_SCHEMA)
    op.drop_column("prime_awards", "disaster_emergency_fund_codes_raw", schema=CDC_FUNDING_SCHEMA)
