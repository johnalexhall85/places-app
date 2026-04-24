from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import uuid

from app.budget import classification


def _build_raw_row(**overrides):
    row = {
        "id": 1,
        "unique_id": "CDC-TEST-0001",
        "fiscal_year": 2024,
        "source_file": "HHS_Budget_Tracker_04_2026_LATEST.xlsx",
        "source_sheet": "BUDGET DATA",
        "agency": "HHS",
        "sub_agency": "CDC",
        "program": "Immunization and Respiratory Diseases",
        "sub_program": "Section 317 Immunization Program",
        "sub_program_2": None,
        "sub_program_3": None,
        "budget_source": "Operational Plan",
        "budget_stage": "Enacted",
        "granularity": "sub_program_level",
        "amount_millions": Decimal("123.456789"),
        "amount_dollars": Decimal("123456789.00"),
        "funding_type": "Discretionary",
        "program_status": "Active",
        "is_non_add": "No",
        "notes": None,
        "verified": "Yes",
        "crosswalk_note": None,
        "source_id": "APT-24-01",
        "source_page": 30,
    }
    row.update(overrides)
    return row


def test_normalize_rule_text_replaces_punctuation_and_collapses_whitespace() -> None:
    normalized = classification.normalize_rule_text("  Prevention/Public Health Fund (PPHF), FY-2026  ")
    assert normalized == "prevention public health fund pphf fy 2026"


def test_build_classification_row_marks_operating_plan_discretionary_as_regular() -> None:
    raw_row = _build_raw_row()
    continuity_lookup = classification.build_program_continuity_lookup(
        [
            raw_row,
            _build_raw_row(id=2, unique_id="CDC-TEST-0002", fiscal_year=2025),
        ]
    )

    classified = classification.build_classification_row(
        raw_row,
        classification_version=classification.DEFAULT_CLASSIFICATION_VERSION,
        classification_batch_id=uuid.uuid4(),
        classified_at=datetime.now(timezone.utc),
        continuity_lookup=continuity_lookup,
    )

    assert classified["appropriation_category"] == "REGULAR"
    assert classified["appropriation_subtype"] == "operating_plan_discretionary"
    assert classified["is_regular_appropriation"] is True
    assert classified["primary_rule_code"] == "REGULAR_001"
    assert classified["signal_budget_stage_operating_plan"] is True


def test_build_classification_row_prioritizes_pphf_over_transfer_keywords() -> None:
    raw_row = _build_raw_row(
        funding_type="PPHF",
        sub_program="Million Hearts Transfer from the Prevention and Public Health Fund",
    )
    continuity_lookup = classification.build_program_continuity_lookup([raw_row])

    classified = classification.build_classification_row(
        raw_row,
        classification_version=classification.DEFAULT_CLASSIFICATION_VERSION,
        classification_batch_id=uuid.uuid4(),
        classified_at=datetime.now(timezone.utc),
        continuity_lookup=continuity_lookup,
    )

    assert classified["appropriation_category"] == "PPHF"
    assert classified["appropriation_subtype"] == "prevention_fund"
    assert classified["primary_rule_code"] == "PPHF_001"
    assert "TRANSFER_001" in classified["supporting_rule_codes"]


def test_total_leaf_like_rows_fall_back_to_unknown_instead_of_regular() -> None:
    raw_row = _build_raw_row(
        funding_type="Total",
        notes="Total for Section 317 Immunization Program.",
    )
    continuity_lookup = classification.build_program_continuity_lookup(
        [
            raw_row,
            _build_raw_row(
                id=2,
                unique_id="CDC-TEST-0002",
                fiscal_year=2025,
                funding_type="Total",
                notes="Total for Section 317 Immunization Program.",
            ),
        ]
    )

    classified = classification.build_classification_row(
        raw_row,
        classification_version=classification.DEFAULT_CLASSIFICATION_VERSION,
        classification_batch_id=uuid.uuid4(),
        classified_at=datetime.now(timezone.utc),
        continuity_lookup=continuity_lookup,
    )

    assert classified["signal_record_is_leaf_like"] is True
    assert classified["appropriation_category"] == "UNKNOWN"
    assert classified["primary_rule_code"] == "UNKNOWN_001"
