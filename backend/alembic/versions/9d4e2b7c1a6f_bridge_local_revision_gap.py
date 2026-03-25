"""bridge missing local revision gap

Revision ID: 9d4e2b7c1a6f
Revises: 6f2a4b9c1d55
Create Date: 2026-03-23 01:10:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "9d4e2b7c1a6f"
down_revision: Union[str, None] = "6f2a4b9c1d55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Preserve upgrade continuity for databases stamped with a removed local revision."""


def downgrade() -> None:
    """No-op downgrade for the legacy bridge revision."""
