"""add hpsa domain quartiles table

Revision ID: 9f4e6c1b2a10
Revises: c5b7a4f98e21
Create Date: 2026-03-01 18:05:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f4e6c1b2a10"
down_revision: Union[str, None] = "c5b7a4f98e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hpsa_domain_quartiles",
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("q25", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("q50", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("q75", sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column("n_counties", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("domain IN ('pc', 'mh', 'dh')", name="ck_hpsa_domain_quartiles_domain"),
        sa.CheckConstraint("n_counties >= 0", name="ck_hpsa_domain_quartiles_n_counties"),
        sa.PrimaryKeyConstraint("domain"),
    )


def downgrade() -> None:
    op.drop_table("hpsa_domain_quartiles")
