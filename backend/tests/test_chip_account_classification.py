from __future__ import annotations

import csv
from decimal import Decimal

import pytest

from app.usaspending_fed_account import classification
from app.cdc_funding import chip_v1


def test_classifier_identifies_obvious_cdc_core_account() -> None:
    row = {
        "federal_account_name": "CDC-wide Activities and Program Support",
        "account_title": "Chronic Disease Prevention and Health Promotion",
        "bureau_name": "Centers for Disease Control and Prevention",
    }

    classified = classification.classify_account_candidate(row)

    assert classified["is_cdc_related"] is True
    assert classified["cdc_scope_category"] == "cdc_core"
    assert classified["funding_scope"] == "regular_appropriation"
    assert classified["include_in_chip_baseline"] is True
    assert classified["include_in_public_map"] is True


def test_classifier_excludes_medicare_medicaid_cms_accounts() -> None:
    row = {
        "federal_account_name": "Grants to States for Medicaid",
        "bureau_name": "Centers for Medicare & Medicaid Services",
    }

    classified = classification.classify_account_candidate(row)

    assert classified["is_cdc_related"] is False
    assert classified["cdc_scope_category"] == "non_cdc_hhs"
    assert classified["include_in_chip_total"] is False
    assert classified["confidence"] == Decimal("0.90")


def test_classifier_flags_covid_cares_arp_as_emergency() -> None:
    row = {
        "federal_account_name": "CDC Coronavirus Response Activities",
        "bureau_name": "Centers for Disease Control and Prevention",
        "top_program_activities": "COVID-19 CARES and American Rescue Plan response",
    }

    classified = classification.classify_account_candidate(row)

    assert classified["cdc_scope_category"] == "cdc_emergency"
    assert classified["funding_scope"] == "emergency_supplemental"
    assert classified["include_in_chip_emergency"] is True
    assert classified["include_in_public_map"] is False


def test_classifier_flags_pphf_as_transfer_scope() -> None:
    row = {
        "federal_account_name": "CDC Prevention and Public Health Fund",
        "bureau_name": "Centers for Disease Control and Prevention",
    }

    classified = classification.classify_account_candidate(row)

    assert classified["is_cdc_related"] is True
    assert classified["cdc_scope_category"] == "cdc_transfer"
    assert classified["funding_scope"] == "pphf"
    assert classified["include_in_chip_baseline"] is False
    assert classified["include_in_chip_total"] is True


def test_classifier_flags_non_cdc_business_support() -> None:
    row = {
        "federal_account_name": "Departmental Management",
        "bureau_name": "Office of the Secretary",
    }

    classified = classification.classify_account_candidate(row)

    assert classified["is_cdc_related"] is False
    assert classified["cdc_scope_category"] == "non_cdc_hhs"
    assert classified["funding_scope"] == "business_support"
    assert classified["confidence"] == Decimal("0.75")


def test_controlled_value_validation_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="Invalid cdc_scope_category"):
        classification.validate_controlled_value("cdc_scope_category", "cdc-ish")


def test_candidate_export_writer_writes_expected_columns(tmp_path) -> None:
    output_path = tmp_path / "candidates.csv"
    row = {column: "" for column in classification.CANDIDATE_EXPORT_COLUMNS}
    row.update(
        {
            "fiscal_year": 2024,
            "normalized_account_key": "fa:075-0943",
            "is_cdc_related": True,
            "cdc_scope_category": "cdc_core",
            "funding_scope": "regular_appropriation",
            "include_in_chip_baseline": True,
            "include_in_chip_emergency": False,
            "include_in_chip_total": True,
            "include_in_public_map": True,
            "review_status": "candidate",
            "confidence": Decimal("0.85"),
            "source": classification.DEFAULT_SOURCE,
            "classification_version": classification.DEFAULT_CLASSIFICATION_VERSION,
        }
    )

    classification.write_candidate_rows_to_csv([row], output_path)

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert reader.fieldnames == classification.CANDIDATE_EXPORT_COLUMNS
    assert rows[0]["is_cdc_related"] == "true"
    assert rows[0]["confidence"] == "0.85"


def test_ingest_reviewed_classification_dry_run_validates_without_database(tmp_path) -> None:
    input_path = tmp_path / "reviewed.csv"
    row = {column: "" for column in classification.CANDIDATE_EXPORT_COLUMNS}
    row.update(
        {
            "fiscal_year": "2024",
            "normalized_account_key": "fa:075-0943",
            "federal_account_name": "CDC-wide Activities and Program Support",
            "agency_name": "Department of Health and Human Services",
            "bureau_name": "Centers for Disease Control and Prevention",
            "is_cdc_related": "yes",
            "cdc_scope_category": "cdc_core",
            "funding_scope": "regular_appropriation",
            "include_in_chip_baseline": "true",
            "include_in_chip_emergency": "false",
            "include_in_chip_total": "true",
            "include_in_public_map": "1",
            "review_status": "candidate",
            "confidence": "0.85",
            "classification_reason": "Test row.",
            "source": classification.DEFAULT_SOURCE,
            "classification_version": classification.DEFAULT_CLASSIFICATION_VERSION,
        }
    )
    with input_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=classification.CANDIDATE_EXPORT_COLUMNS)
        writer.writeheader()
        writer.writerow(row)

    summary = classification.ingest_reviewed_classification(
        input_path=input_path,
        db_url="postgresql+psycopg://should:not@be-used:5432/nope",
        dry_run=True,
        allow_candidates=True,
    )

    assert summary.dry_run is True
    assert summary.rows_read == 1
    assert summary.cdc_related_count == 1
    assert summary.baseline_included_count == 1
    assert summary.public_map_included_count == 1


def test_chip_v1_default_scope_filters_are_regular_fy2023_grants_coops(monkeypatch) -> None:
    monkeypatch.setattr(chip_v1, "default_fiscal_year", lambda *_args, **_kwargs: 2023)

    filters = chip_v1._normalize_filters(  # noqa: SLF001
        object(),
        fiscal_year=None,
        metric="total_funding",
        geography_level="state",
    )

    assert filters.fiscal_year == 2023
    assert filters.funding_scope_preset == "regular_grants_coops"
    assert filters.award_type == "grants_coops"
    assert filters.emergency_supplemental_scope == "exclude"
    assert filters.review_status == "reviewed_plus_needs_review"
    assert filters.include_pphf is True
    assert filters.transfers_scope == "cdc_relevant_only"
    assert filters.data_source_scope == "combined"


def test_chip_v1_all_obligations_preset_expands_award_type(monkeypatch) -> None:
    monkeypatch.setattr(chip_v1, "default_fiscal_year", lambda *_args, **_kwargs: 2023)

    filters = chip_v1._normalize_filters(  # noqa: SLF001
        object(),
        fiscal_year=None,
        metric="total_funding",
        geography_level="state",
        funding_scope_preset="all_obligations",
    )

    where_sql, _params = chip_v1._scope_where_clause(filters)  # noqa: SLF001

    assert filters.award_type == "all_award_types"
    assert filters.emergency_supplemental_scope == "include_both"
    assert "award_source_type IN ('assistance', 'contracts', 'unlinked')" in where_sql
    assert "emergency_supplemental" not in where_sql


def test_chip_v1_custom_scope_respects_explicit_filters(monkeypatch) -> None:
    monkeypatch.setattr(chip_v1, "default_fiscal_year", lambda *_args, **_kwargs: 2023)

    filters = chip_v1._normalize_filters(  # noqa: SLF001
        object(),
        fiscal_year=2024,
        metric="total_funding",
        geography_level="state",
        funding_scope_preset="custom",
        award_type="contracts",
        emergency_supplemental_scope="include_both",
        review_status="reviewed_only",
        include_pphf=False,
        transfers_scope="exclude",
        data_source_scope="usaspending_only",
    )

    where_sql, _params = chip_v1._scope_where_clause(filters)  # noqa: SLF001

    assert filters.fiscal_year == 2024
    assert filters.funding_scope_preset == "custom"
    assert filters.award_type == "contracts"
    assert filters.emergency_supplemental_scope == "include_both"
    assert filters.review_status == "reviewed_only"
    assert filters.include_pphf is False
    assert filters.transfers_scope == "exclude"
    assert filters.data_source_scope == "usaspending_only"
    assert "award_source_type = 'contracts'" in where_sql
    assert "review_status = 'reviewed'" in where_sql
    assert "funding_scope IS DISTINCT FROM 'pphf'" in where_sql


def test_chip_v1_pending_review_scope_includes_candidate_rows(monkeypatch) -> None:
    monkeypatch.setattr(chip_v1, "default_fiscal_year", lambda *_args, **_kwargs: 2023)

    filters = chip_v1._normalize_filters(  # noqa: SLF001
        object(),
        fiscal_year=None,
        metric="total_funding",
        geography_level="state",
        funding_scope_preset="custom",
        review_status="reviewed_plus_needs_review",
    )

    where_sql, _params = chip_v1._scope_where_clause(filters)  # noqa: SLF001

    assert "review_status IN ('reviewed', 'candidate', 'needs_review')" in where_sql
