from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd

from app.budget.ingest import (
    BUDGET_TRACKER_COLUMNS,
    SOURCE_REGISTRY_COLUMNS,
    _coerce_budget_tracker_row,
    _find_header_row_index,
)


def test_find_header_row_index_supports_title_row_before_source_registry_header() -> None:
    preview = pd.DataFrame(
        [
            ["Source Registry  —  One row per document.", None, None],
            ["source_id", "document_name", "source_type"],
            ["S001", "Doc", "Report"],
        ]
    )

    assert _find_header_row_index(
        preview,
        expected_columns=SOURCE_REGISTRY_COLUMNS,
        required_columns={"source_id"},
    ) == 1


def test_find_header_row_index_supports_budget_data_header_in_first_row() -> None:
    preview = pd.DataFrame(
        [
            BUDGET_TRACKER_COLUMNS[:6],
            ["CDC-000001", 1, 2024, "HHS", "CDC", "Program A"],
        ]
    )

    assert _find_header_row_index(
        preview,
        expected_columns=BUDGET_TRACKER_COLUMNS,
        required_columns={"unique_id"},
    ) == 0


def test_coerce_budget_tracker_row_derives_numeric_and_date_fields() -> None:
    row = {
        "unique_id": " CDC-000001 ",
        "record_id": "1",
        "fiscal_year": 2024.0,
        "agency": " HHS ",
        "sub_agency": " CDC ",
        "program": "Program A",
        "sub_program": "",
        "sub_program_2": None,
        "sub_program_3": None,
        "budget_source": "Congressional Justification",
        "budget_stage": "Request",
        "granularity": "program_level",
        "amount_millions": "750.93",
        "funding_type": "Discretionary",
        "program_status": "Active",
        "is_non_add": "No",
        "notes": "  ",
        "source_id": "S002",
        "source_page": 66.0,
        "date_entered": "2026-03-08",
        "entered_by": "YG",
        "verified": "No",
        "crosswalk_note": None,
    }

    coerced = _coerce_budget_tracker_row(row)

    assert coerced["unique_id"] == "CDC-000001"
    assert coerced["record_id"] == 1
    assert coerced["fiscal_year"] == 2024
    assert coerced["agency"] == "HHS"
    assert coerced["sub_agency"] == "CDC"
    assert coerced["sub_program"] is None
    assert coerced["notes"] is None
    assert coerced["source_page"] == 66
    assert coerced["date_entered"] == date(2026, 3, 8)
    assert coerced["amount_millions"] == Decimal("750.930000")
    assert coerced["amount_dollars"] == Decimal("750930000.00")
    assert len(coerced["row_hash"]) == 64
