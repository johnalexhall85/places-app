"""drop cdc searchable text btree indexes

Revision ID: e1b3d2f4a6c1
Revises: c2a8b1f4d9e0
Create Date: 2026-03-07 13:20:00.000000

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e1b3d2f4a6c1"
down_revision: Union[str, None] = "c2a8b1f4d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CDC_FUNDING_SCHEMA = "cdc_funding"


def upgrade() -> None:
    op.execute(
        f"DROP INDEX IF EXISTS {CDC_FUNDING_SCHEMA}.cdc_prime_awards_searchable_text_idx"
    )
    op.execute(
        f"DROP INDEX IF EXISTS {CDC_FUNDING_SCHEMA}.cdc_subawards_searchable_text_idx"
    )


def downgrade() -> None:
    op.create_index(
        "cdc_prime_awards_searchable_text_idx",
        "prime_awards",
        ["searchable_text"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
    op.create_index(
        "cdc_subawards_searchable_text_idx",
        "subawards",
        ["searchable_text"],
        unique=False,
        schema=CDC_FUNDING_SCHEMA,
    )
