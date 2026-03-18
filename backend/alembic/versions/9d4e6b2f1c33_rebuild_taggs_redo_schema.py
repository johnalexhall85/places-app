"""expand taggs schema for redo csv rebuild

Revision ID: 9d4e6b2f1c33
Revises: 6f2a4b9c1d55
Create Date: 2026-03-14 20:15:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "9d4e6b2f1c33"
down_revision: Union[str, None] = "6f2a4b9c1d55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TAGGS_SCHEMA = "taggs"


def _get_inspector():
    return sa.inspect(op.get_bind())


def _column_exists(schema_name: str, table_name: str, column_name: str) -> bool:
    return any(
        column.get("name") == column_name
        for column in _get_inspector().get_columns(table_name, schema=schema_name)
    )


def _index_exists(schema_name: str, table_name: str, index_name: str) -> bool:
    return any(
        index.get("name") == index_name
        for index in _get_inspector().get_indexes(table_name, schema=schema_name)
    )


def _add_column_if_missing(table_name: str, column: sa.Column, *, schema: str) -> None:
    if _column_exists(schema, table_name, str(column.name)):
        return
    op.add_column(table_name, column, schema=schema)


def _create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
    schema: str,
) -> None:
    if _index_exists(schema, table_name, index_name):
        return
    op.create_index(index_name, table_name, columns, unique=unique, schema=schema)


def upgrade() -> None:
    _add_column_if_missing(
        "raw_awards",
        sa.Column("source_opdiv_hint", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("legal_entity_zip_code", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("legal_entity_congressional_district", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("period_of_performance_start_date", sa.Date(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("period_of_performance_end_date", sa.Date(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("award_termination_date", sa.Date(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("fon", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("action_issue_date", sa.Date(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("award_code", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("award_action_type", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("transaction_aln", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("transaction_assistance_listing_title", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column("distinct_award_count", sa.Integer(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column(
            "raw_header_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema=TAGGS_SCHEMA,
    )
    _add_column_if_missing(
        "raw_awards",
        sa.Column(
            "raw_row_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        schema=TAGGS_SCHEMA,
    )
    _create_index_if_missing(
        "taggs_raw_awards_issue_date_fiscal_year_idx",
        "raw_awards",
        ["issue_date_fiscal_year"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )
    _create_index_if_missing(
        "taggs_raw_awards_opdiv_idx",
        "raw_awards",
        ["opdiv"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )

    _add_column_if_missing(
        "award_funding_summary",
        sa.Column("opdiv", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _create_index_if_missing(
        "taggs_award_funding_summary_opdiv_idx",
        "award_funding_summary",
        ["opdiv"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )

    _add_column_if_missing(
        "state_funding_summary",
        sa.Column("opdiv", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    _create_index_if_missing(
        "taggs_state_funding_summary_opdiv_idx",
        "state_funding_summary",
        ["opdiv"],
        unique=False,
        schema=TAGGS_SCHEMA,
    )

    _add_column_if_missing(
        "can_classification",
        sa.Column("dominant_opdiv", sa.Text(), nullable=True),
        schema=TAGGS_SCHEMA,
    )
    if _column_exists(TAGGS_SCHEMA, "can_classification", "observed_row_count"):
        op.execute(
            sa.text(
                f"""
                UPDATE {TAGGS_SCHEMA}.can_classification
                SET observed_row_count = 0
                WHERE observed_row_count IS NULL
                """
            )
        )
        op.alter_column(
            "can_classification",
            "observed_row_count",
            existing_type=sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
            schema=TAGGS_SCHEMA,
        )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for the TAGGS redo schema rebuild.")
