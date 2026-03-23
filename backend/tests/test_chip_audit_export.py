from __future__ import annotations

import csv
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.recon import chip_audit_export
from app.recon.chip_audit_export import AuditExportData


def _dictionary_rows(columns: list[str]) -> list[dict[str, str]]:
    return [
        {
            "column_name": column_name,
            "display_name": column_name,
            "source_system": "test",
            "source_subsystem": "test",
            "source_column_name": column_name,
            "column_group": "test",
            "data_type": "string",
            "format": "",
            "allowed_values": "",
            "null_allowed": "yes",
            "definition": "test",
            "provenance_description": "test",
            "transformation_rule": "test",
            "example_value": "",
            "appears_in_files": "all",
        }
        for column_name in columns
    ]


def _build_row(
    columns: list[str],
    values: dict[str, object],
    *,
    raw_amount: Decimal,
) -> dict[str, object]:
    row = {column_name: values.get(column_name) for column_name in columns}
    row["_raw_amount"] = raw_amount
    return row


def _read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        return next(reader)


def test_write_export_package_keeps_transaction_headers_in_lockstep(tmp_path) -> None:
    columns = [
        *chip_audit_export.CHIP_AUDIT_COLUMNS,
        *chip_audit_export.PROVENANCE_COLUMNS,
        "usaspending_prime_transaction_award_id_fain",
        "taggs_raw_award_award_title",
    ]
    rows = [
        _build_row(
            columns,
            {
                "chip_row_id": "assistance:tx-1",
                "chip_model_version": "test-model",
                "chip_export_timestamp": datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                "chip_export_batch_id": "batch-test",
                "chip_inclusion_flag": True,
                "chip_inclusion_bucket": "included",
                "chip_inclusion_reason": "included_profile_scope",
                "chip_inclusion_reason_detail": "decision_context=core_public_health",
                "chip_review_status": "auto_included",
                "chip_data_source_primary": "USAspending",
                "chip_data_source_secondary": "TAGGS",
                "chip_join_method": "award_number_state_year",
                "chip_join_status": "matched",
                "chip_join_confidence": "high",
                "chip_provenance_notes": "test",
                "chip_funding_fy": 2025,
                "chip_net_amount_for_model": Decimal("60.00"),
                "chip_normalized_amount": Decimal("60.00"),
                "chip_geography_level": "state",
                "chip_state_fips": "01",
                "chip_county_fips": None,
                "chip_county_name_standardized": None,
                "chip_program_area_standardized": "immunization_and_respiratory_diseases",
                "prov_usaspending_source_file": "prime_transactions.csv",
                "prov_usaspending_extract_date": "2026-03-14",
                "prov_usaspending_table_name": "cdc_funding.prime_transactions",
                "prov_usaspending_record_id": "tx-1",
                "prov_taggs_source_file": "CDC-1-4.csv",
                "prov_taggs_extract_date": "2026-03-12",
                "prov_taggs_table_name": "taggs.raw_awards",
                "prov_taggs_record_id": "1001",
                "prov_merge_run_id": "batch-test",
                "prov_transformation_stage": "test-stage",
                "prov_last_modified_by_process": "test-process",
                "usaspending_prime_transaction_award_id_fain": "FAIN-1",
                "taggs_raw_award_award_title": "Test TAGGS award",
            },
            raw_amount=Decimal("100.00"),
        ),
        _build_row(
            columns,
            {
                "chip_row_id": "contracts:tx-2",
                "chip_model_version": "test-model",
                "chip_export_timestamp": datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                "chip_export_batch_id": "batch-test",
                "chip_inclusion_flag": False,
                "chip_inclusion_bucket": "excluded",
                "chip_inclusion_reason": "no_relevant_program_mapping",
                "chip_inclusion_reason_detail": "decision_context=procurement_support_excluded",
                "chip_review_status": "auto_excluded",
                "chip_data_source_primary": "USAspending",
                "chip_data_source_secondary": None,
                "chip_join_method": "not_applicable",
                "chip_join_status": "not_applicable",
                "chip_join_confidence": None,
                "chip_provenance_notes": "test",
                "chip_funding_fy": 2025,
                "chip_net_amount_for_model": Decimal("0.00"),
                "chip_normalized_amount": Decimal("0.00"),
                "chip_geography_level": "state",
                "chip_state_fips": "01",
                "chip_county_fips": None,
                "chip_county_name_standardized": None,
                "chip_program_area_standardized": "other_cdc_programs",
                "prov_usaspending_source_file": "contracts.csv",
                "prov_usaspending_extract_date": "2026-03-14",
                "prov_usaspending_table_name": "usaspending.contract_transactions_raw",
                "prov_usaspending_record_id": "tx-2",
                "prov_taggs_source_file": None,
                "prov_taggs_extract_date": None,
                "prov_taggs_table_name": None,
                "prov_taggs_record_id": None,
                "prov_merge_run_id": "batch-test",
                "prov_transformation_stage": "test-stage",
                "prov_last_modified_by_process": "test-process",
                "usaspending_prime_transaction_award_id_fain": None,
                "taggs_raw_award_award_title": None,
            },
            raw_amount=Decimal("40.00"),
        ),
        _build_row(
            columns,
            {
                "chip_row_id": "assistance:tx-3",
                "chip_model_version": "test-model",
                "chip_export_timestamp": datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                "chip_export_batch_id": "batch-test",
                "chip_inclusion_flag": None,
                "chip_inclusion_bucket": "unresolved",
                "chip_inclusion_reason": "manual_review_required",
                "chip_inclusion_reason_detail": "decision_context=unknown_uncertain",
                "chip_review_status": "manual_review_required",
                "chip_data_source_primary": "USAspending",
                "chip_data_source_secondary": None,
                "chip_join_method": None,
                "chip_join_status": "unmatched",
                "chip_join_confidence": None,
                "chip_provenance_notes": "test",
                "chip_funding_fy": 2025,
                "chip_net_amount_for_model": None,
                "chip_normalized_amount": None,
                "chip_geography_level": "unknown",
                "chip_state_fips": None,
                "chip_county_fips": None,
                "chip_county_name_standardized": None,
                "chip_program_area_standardized": "other_cdc_programs",
                "prov_usaspending_source_file": "prime_transactions.csv",
                "prov_usaspending_extract_date": "2026-03-14",
                "prov_usaspending_table_name": "cdc_funding.prime_transactions",
                "prov_usaspending_record_id": "tx-3",
                "prov_taggs_source_file": None,
                "prov_taggs_extract_date": None,
                "prov_taggs_table_name": None,
                "prov_taggs_record_id": None,
                "prov_merge_run_id": "batch-test",
                "prov_transformation_stage": "test-stage",
                "prov_last_modified_by_process": "test-process",
                "usaspending_prime_transaction_award_id_fain": "FAIN-3",
                "taggs_raw_award_award_title": None,
            },
            raw_amount=Decimal("20.00"),
        ),
    ]
    export_data = AuditExportData(
        rows=rows,
        column_order=columns,
        dictionary_rows=_dictionary_rows(columns),
        model_total_normalized_amount=Decimal("60.00"),
    )

    export_dir = chip_audit_export.write_export_package(
        export_data,
        output_root=tmp_path,
        export_date=date(2026, 3, 20),
        export_timestamp=datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
        export_batch_id="batch-test",
        overwrite=True,
    )

    included_header = _read_header(export_dir / chip_audit_export.EXPORT_FILE_NAMES["included"])
    excluded_header = _read_header(export_dir / chip_audit_export.EXPORT_FILE_NAMES["excluded"])
    unresolved_header = _read_header(export_dir / chip_audit_export.EXPORT_FILE_NAMES["unresolved"])

    assert included_header == columns
    assert included_header == excluded_header == unresolved_header


def test_validate_export_rows_fails_when_included_total_does_not_reconcile() -> None:
    columns = [
        *chip_audit_export.CHIP_AUDIT_COLUMNS,
        *chip_audit_export.PROVENANCE_COLUMNS,
    ]
    rows = [
        _build_row(
            columns,
            {
                "chip_row_id": "assistance:tx-1",
                "chip_model_version": "test-model",
                "chip_export_timestamp": datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                "chip_export_batch_id": "batch-test",
                "chip_inclusion_flag": True,
                "chip_inclusion_bucket": "included",
                "chip_inclusion_reason": "included_profile_scope",
                "chip_inclusion_reason_detail": "detail",
                "chip_review_status": "auto_included",
                "chip_data_source_primary": "USAspending",
                "chip_data_source_secondary": None,
                "chip_join_method": None,
                "chip_join_status": "not_attempted",
                "chip_join_confidence": None,
                "chip_provenance_notes": "test",
                "chip_funding_fy": 2025,
                "chip_net_amount_for_model": Decimal("50.00"),
                "chip_normalized_amount": Decimal("50.00"),
                "chip_geography_level": "state",
                "chip_state_fips": "01",
                "chip_county_fips": None,
                "chip_county_name_standardized": None,
                "chip_program_area_standardized": "other_cdc_programs",
                "prov_usaspending_source_file": "prime_transactions.csv",
                "prov_usaspending_extract_date": "2026-03-14",
                "prov_usaspending_table_name": "cdc_funding.prime_transactions",
                "prov_usaspending_record_id": "tx-1",
                "prov_taggs_source_file": None,
                "prov_taggs_extract_date": None,
                "prov_taggs_table_name": None,
                "prov_taggs_record_id": None,
                "prov_merge_run_id": "batch-test",
                "prov_transformation_stage": "test-stage",
                "prov_last_modified_by_process": "test-process",
            },
            raw_amount=Decimal("50.00"),
        )
    ]

    metrics = chip_audit_export._validation_metrics(  # noqa: SLF001
        rows,
        model_total_normalized_amount=Decimal("75.00"),
    )
    violations = chip_audit_export._validate_export_rows(  # noqa: SLF001
        rows,
        column_order=columns,
        metrics=metrics,
    )

    assert any("does not reconcile" in item for item in violations)


def test_candidate_rows_query_uses_set_based_taggs_matching() -> None:
    query = chip_audit_export._candidate_rows_query()  # noqa: SLF001

    assert "LEFT JOIN LATERAL" not in query
    assert "taggs_candidates AS (" in query
    assert "taggs_best AS (" in query
    assert query.count("UNION ALL") == 3


def test_taggs_best_candidate_ranking_prefers_rank_then_amount_then_lowest_id() -> None:
    sql = f"""
        WITH taggs_candidates (
            source_transaction_id,
            raw_amount,
            id,
            sum_of_actions,
            taggs_record,
            taggs_effective_category,
            taggs_effective_program_name,
            rank,
            join_method,
            join_confidence
        ) AS (
            VALUES
                ('tx-1', 100.0, 10, 130.0, '{{}}', 'cat', 'prog', 2, 'award_number_fiscal_year', 'medium'),
                ('tx-1', 100.0, 20, 110.0, '{{}}', 'cat', 'prog', 1, 'award_number_state_year', 'high'),
                ('tx-1', 100.0, 30, 101.0, '{{}}', 'cat', 'prog', 1, 'award_number_state_year', 'high'),
                ('tx-1', 100.0, 40, 101.0, '{{}}', 'cat', 'prog', 1, 'award_number_state_year', 'high'),
                ('tx-2', 200.0, 50, 220.0, '{{}}', 'cat', 'prog', 3, 'aln_state_year', 'medium'),
                ('tx-2', 200.0, 60, 180.0, '{{}}', 'cat', 'prog', 2, 'award_number_fiscal_year', 'medium'),
                ('tx-2', 200.0, 61, 190.0, '{{}}', 'cat', 'prog', 2, 'award_number_fiscal_year', 'medium')
        ),
        {chip_audit_export._taggs_best_candidates_ctes()}
        SELECT source_transaction_id, id, rank, candidate_count
        FROM taggs_best
        ORDER BY source_transaction_id
    """

    with sqlite3.connect(":memory:") as connection:
        rows = connection.execute(sql).fetchall()

    assert rows == [
        ("tx-1", 30, 1, 3),
        ("tx-2", 61, 2, 2),
    ]
