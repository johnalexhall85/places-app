"""merge funding builder and chip v11 heads

Revision ID: 0ab1c2d3e4f5
Revises: 91d3f4c2ab10, f9a1c3b7d2e5
Create Date: 2026-03-23 00:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "0ab1c2d3e4f5"
down_revision: Union[str, tuple[str, str], None] = ("91d3f4c2ab10", "f9a1c3b7d2e5")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
