"""add profiles tables

Revision ID: 1c5f1af63f2b
Revises: 4f2b8d9c1a77
Create Date: 2026-02-23 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "1c5f1af63f2b"
down_revision: Union[str, None] = "4f2b8d9c1a77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("geography", sa.String(length=16), nullable=False),
        sa.Column("location_id", sa.String(length=16), nullable=False),
        sa.Column("request_signature", sa.String(length=64), nullable=False),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("request_signature", name="uq_profiles_request_signature"),
    )
    op.create_index(
        "idx_profiles_lookup",
        "profiles",
        ["geography", "location_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "profile_assets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=False), nullable=False),
        sa.Column("asset_name", sa.String(length=160), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("asset_path", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["profile_id"], ["profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "asset_name", name="uq_profile_assets_name"),
    )
    op.create_index(
        "idx_profile_assets_profile_id",
        "profile_assets",
        ["profile_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_profile_assets_profile_id", table_name="profile_assets")
    op.drop_table("profile_assets")

    op.drop_index("idx_profiles_lookup", table_name="profiles")
    op.drop_table("profiles")
