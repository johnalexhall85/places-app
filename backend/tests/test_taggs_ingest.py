from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from app.taggs import ingest as taggs_ingest


def _write_taggs_csv(
    tmp_path,
    filename: str,
    *,
    header: list[str],
    body_rows: list[list[str]],
    banner_lines: list[str] | None = None,
) -> Path:
    csv_path = tmp_path / filename
    lines = banner_lines or [
        "TAGGS Advanced Search Export",
        "; CAN Fiscal Year: 2026, 2025, 2024, 2023, 2022, 2021; OPDIV: CDC; States: AL",
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for line in lines:
            writer.writerow([line] + [""] * (len(header) - 1))
        writer.writerow(header)
        for row in body_rows:
            writer.writerow(row)
    return csv_path


def _main_award_row(
    *,
    header: list[str],
    issue_year: str = "2026",
    opdiv: str = "CDC",
    award_number: str = "NU90TEST000001",
    award_title: str = "Example award title",
    funding_fy: str = "2025",
    can_code: str = "9390PMD",
    sum_of_actions: str = "$1,234.50",
    state: str = "AL",
    county: str = "Montgomery",
) -> list[str]:
    row = [""] * len(header)
    columns = {column: index for index, column in enumerate(header)}
    values = {
        "Issue Date Fiscal Year": issue_year,
        "OPDIV": opdiv,
        "Program Office": "COTPER",
        "Legal Entity Name": "Example Recipient",
        "Legal Entity City": "Montgomery",
        "Legal Entity State": state,
        "Legal Entity ZIP Code": "36104",
        "Legal Entity Congressional District": "02",
        "Legal Entity County": county,
        "Legal Entity Country": "United States",
        "Period of Performance Start Date": "7/1/2021",
        "Period of Performance End Date": "6/30/2025",
        "Award Termination Date": "6/30/2025",
        "UEI": "ABC123XYZ789",
        "FON": "CDC-RFA-TEST",
        "Metro/Non-Metro": "Metro",
        "Recipient Class": "State Government",
        "Recipient Type": "Health Department",
        "Recovery Act Flag": "NON",
        "Award Number": award_number,
        "Award Title": award_title,
        "Award Code": "02",
        "Award Class": "DISCRETIONARY",
        "Award Activity Type": "HEALTH SERVICES",
        "ALN": "93.354",
        "Assistance Listing Title": "Sample Listing",
        "Funding Fiscal Year": funding_fy,
        "Common Accounting Number (CAN)": can_code,
        "Sum of Actions": sum_of_actions,
    }
    for column_name, value in values.items():
        if column_name in columns:
            row[columns[column_name]] = value
    return row


def _description_row(header: list[str], text: str) -> list[str]:
    return [text] + [""] * (len(header) - 1)


def test_metadata_banner_parsing() -> None:
    banner = (
        "TAGGS Advanced Search Export\r\n"
        "; CAN Fiscal Year: 2026, 2025, 2024; OPDIV: CDC; States: AL"
    )
    parsed = taggs_ingest.parse_metadata_banner(banner)

    assert parsed["banner_valid"] is True
    assert parsed["listed_fiscal_years"] == [2026, 2025, 2024]
    assert parsed["opdiv"] == "CDC"
    assert parsed["states"] == ["AL"]


def test_header_extraction_reads_true_header_after_multiline_banner(tmp_path) -> None:
    csv_path = _write_taggs_csv(
        tmp_path,
        "HHS-OS.csv",
        header=taggs_ingest.EXPECTED_ALT_HEADER,
        body_rows=[_main_award_row(header=taggs_ingest.EXPECTED_ALT_HEADER, opdiv="DHHS/OS", award_number="TP1AH000293", can_code="19999SQ")],
        banner_lines=[
            "TAGGS Advanced Search Export",
            "; CAN Fiscal Year: 2026, 2025, 2024; OPDIV: DHHS/OS",
        ],
    )

    structure = taggs_ingest.inspect_file_structure(csv_path)

    assert structure.normalized_header == taggs_ingest.EXPECTED_ALT_HEADER
    assert structure.source_opdiv_hint == "DHHS/OS"
    assert structure.source_state_hint is None
    assert structure.source_is_territory_file is False


def test_header_validation_accepts_two_reconcilable_header_sets(tmp_path) -> None:
    cdc_path = _write_taggs_csv(
        tmp_path,
        "CDC-1-4.csv",
        header=taggs_ingest.EXPECTED_BASE_HEADER,
        body_rows=[_main_award_row(header=taggs_ingest.EXPECTED_BASE_HEADER)],
    )
    hrsa_path = _write_taggs_csv(
        tmp_path,
        "HRSA-1-4.csv",
        header=taggs_ingest.EXPECTED_ALT_HEADER,
        body_rows=[_main_award_row(header=taggs_ingest.EXPECTED_ALT_HEADER, opdiv="HRSA", can_code="3721UB4")],
        banner_lines=[
            "TAGGS Advanced Search Export",
            "; CAN Fiscal Year: 2026, 2025, 2024; OPDIV: HRSA; States: AL",
        ],
    )

    structures = [
        taggs_ingest.inspect_file_structure(cdc_path),
        taggs_ingest.inspect_file_structure(hrsa_path),
    ]
    validation = taggs_ingest.collect_header_validation(structures)

    assert validation["is_reconcilable"] is True
    assert validation["fatal_errors"] == []
    assert len(validation["observed_header_sets"]) == 2


def test_main_row_and_description_row_pairing(tmp_path) -> None:
    csv_path = _write_taggs_csv(
        tmp_path,
        "CDC-1-4.csv",
        header=taggs_ingest.EXPECTED_BASE_HEADER,
        body_rows=[
            _main_award_row(header=taggs_ingest.EXPECTED_BASE_HEADER),
            _description_row(taggs_ingest.EXPECTED_BASE_HEADER, "Award description text."),
            _description_row(taggs_ingest.EXPECTED_BASE_HEADER, "Second description line."),
        ],
    )

    records, stats, _encoding = taggs_ingest.parse_taggs_csv_file(csv_path)

    assert len(records) == 1
    assert records[0]["award_description"] == "Award description text.\nSecond description line."
    assert records[0]["raw_row_json"]["description_rows"] == [
        "Award description text.",
        "Second description line.",
    ]
    assert stats.main_award_rows == 1
    assert stats.description_rows_paired == 2
    assert stats.repeated_description_rows == 1
    assert stats.orphan_description_rows == 0


def test_orphan_description_rows_are_logged(tmp_path) -> None:
    csv_path = _write_taggs_csv(
        tmp_path,
        "CDC-1-4.csv",
        header=taggs_ingest.EXPECTED_BASE_HEADER,
        body_rows=[_description_row(taggs_ingest.EXPECTED_BASE_HEADER, "Orphan description.")],
    )

    records, stats, _encoding = taggs_ingest.parse_taggs_csv_file(csv_path)

    assert records == []
    assert stats.orphan_description_rows == 1
    assert stats.anomalies[0]["kind"] == "orphan_description_row"


def test_footer_rows_are_skipped_without_extra_records(tmp_path) -> None:
    csv_path = _write_taggs_csv(
        tmp_path,
        "CDC-1-4.csv",
        header=taggs_ingest.EXPECTED_BASE_HEADER,
        body_rows=[
            _main_award_row(header=taggs_ingest.EXPECTED_BASE_HEADER),
            _description_row(taggs_ingest.EXPECTED_BASE_HEADER, "Award description text."),
            [""] * (len(taggs_ingest.EXPECTED_BASE_HEADER) - 1) + ["Page Total: $1,234.50"],
            _description_row(
                taggs_ingest.EXPECTED_BASE_HEADER,
                "Exported on 03/12/2026 from the HHS Tracking Accountability in Government Grants System (TAGGS)",
            ),
        ],
    )

    records, stats, _encoding = taggs_ingest.parse_taggs_csv_file(csv_path)

    assert len(records) == 1
    assert stats.footer_rows == 2
    assert stats.skipped_singleton_rows == 0


def test_amount_parsing() -> None:
    assert taggs_ingest._parse_amount("$1,234,567.89") == Decimal("1234567.89")
    assert taggs_ingest._parse_amount("-$45.10") == Decimal("-45.10")
    assert taggs_ingest._parse_amount("$0") == Decimal("0.00")


def test_date_parsing() -> None:
    assert taggs_ingest._parse_date("2025-03-01").isoformat() == "2025-03-01"
    assert taggs_ingest._parse_date("7/1/2021").isoformat() == "2021-07-01"
    assert taggs_ingest._parse_date("not-a-date") is None


def test_state_normalization() -> None:
    assert taggs_ingest._normalize_state_value("al") == "AL"
    assert taggs_ingest._normalize_state_value("District of Columbia") == "DC"
    assert taggs_ingest._normalize_state_value("Puerto Rico") == "PR"


def test_state_and_territory_inference() -> None:
    state_scope = taggs_ingest.infer_source_scope(
        Path("Alabama.csv"),
        {"states": ["AL"]},
    )
    territory_scope = taggs_ingest.infer_source_scope(
        Path("CDC-USTs.csv"),
        {"states": ["AS", "GU", "PR", "VI"]},
    )

    assert state_scope["source_state_hint"] == "AL"
    assert state_scope["source_is_territory_file"] is False
    assert territory_scope["source_state_hint"] == "US-TERRITORIES"
    assert territory_scope["source_is_territory_file"] is True


def test_repeated_awards_aggregate_into_summary_tables(tmp_path) -> None:
    csv_path = _write_taggs_csv(
        tmp_path,
        "CDC-1-4.csv",
        header=taggs_ingest.EXPECTED_BASE_HEADER,
        body_rows=[
            _main_award_row(
                header=taggs_ingest.EXPECTED_BASE_HEADER,
                award_number="NU90TEST000111",
                sum_of_actions="$1,000",
            ),
            _description_row(taggs_ingest.EXPECTED_BASE_HEADER, "First description."),
            _main_award_row(
                header=taggs_ingest.EXPECTED_BASE_HEADER,
                award_number="NU90TEST000111",
                sum_of_actions="$250",
            ),
            _description_row(taggs_ingest.EXPECTED_BASE_HEADER, "Second description."),
        ],
    )

    records, _stats, _encoding = taggs_ingest.parse_taggs_csv_file(csv_path)
    award_summary_rows = taggs_ingest.build_award_funding_summary_rows(records)
    state_summary_rows = taggs_ingest.build_state_funding_summary_rows(award_summary_rows)

    assert len(award_summary_rows) == 1
    assert award_summary_rows[0]["award_number"] == "NU90TEST000111"
    assert award_summary_rows[0]["opdiv"] == "CDC"
    assert award_summary_rows[0]["total_sum_of_actions"] == Decimal("1250.00")
    assert award_summary_rows[0]["raw_row_count"] == 2
    assert "Second description." in str(award_summary_rows[0]["award_description"])

    assert len(state_summary_rows) == 1
    assert state_summary_rows[0]["legal_entity_state_normalized"] == "AL"
    assert state_summary_rows[0]["opdiv"] == "CDC"
    assert state_summary_rows[0]["award_count"] == 1
    assert state_summary_rows[0]["unique_recipient_count"] == 1
    assert state_summary_rows[0]["unique_county_count"] == 1


def test_can_inventory_build_tracks_dominant_values(tmp_path) -> None:
    csv_path = _write_taggs_csv(
        tmp_path,
        "CDC-1-4.csv",
        header=taggs_ingest.EXPECTED_BASE_HEADER,
        body_rows=[
            _main_award_row(
                header=taggs_ingest.EXPECTED_BASE_HEADER,
                award_number="NU90TEST000201",
                can_code="Q99TWRA",
                sum_of_actions="$2,000",
            ),
            _main_award_row(
                header=taggs_ingest.EXPECTED_BASE_HEADER,
                award_number="NU90TEST000202",
                can_code="Q99TWRA",
                sum_of_actions="$500",
            ),
            _main_award_row(
                header=taggs_ingest.EXPECTED_BASE_HEADER,
                award_number="NU90TEST000203",
                can_code="9390PMD",
                sum_of_actions="$100",
            ),
        ],
    )

    records, _stats, _encoding = taggs_ingest.parse_taggs_csv_file(csv_path)
    can_rows = taggs_ingest.build_can_classification_rows(records)
    lookup = {row["can_code"]: row for row in can_rows}

    assert lookup["Q99TWRA"]["observed_first_fy"] == 2025
    assert lookup["Q99TWRA"]["observed_last_fy"] == 2025
    assert lookup["Q99TWRA"]["observed_row_count"] == 2
    assert lookup["Q99TWRA"]["observed_total_funding"] == Decimal("2500.00")
    assert lookup["Q99TWRA"]["dominant_opdiv"] == "CDC"
    assert lookup["Q99TWRA"]["dominant_program_office"] == "COTPER"
    assert lookup["Q99TWRA"]["dominant_aln"] == "93.354"
    assert lookup["Q99TWRA"]["dominant_assistance_listing_title"] == "Sample Listing"


def test_ingest_adds_schema_reset_notice_when_drop_and_recreate_requested(tmp_path) -> None:
    _write_taggs_csv(
        tmp_path,
        "CDC-1-4.csv",
        header=taggs_ingest.EXPECTED_BASE_HEADER,
        body_rows=[_main_award_row(header=taggs_ingest.EXPECTED_BASE_HEADER)],
    )
    summary_path = tmp_path / "taggs_redo_ingestion_summary.json"

    summary = taggs_ingest.ingest(
        db_url="postgresql+psycopg://ignored",
        input_dir=tmp_path,
        summary_path=summary_path,
        chunk_size=100,
        truncate=True,
        drop_and_recreate=True,
        dry_run=True,
        verbose=False,
        limit_files=None,
        rebuild_summaries=True,
        rebuild_can_table=True,
    )

    assert summary["schema_reset_notice"] == taggs_ingest.SCHEMA_RESET_NOTICE
    assert taggs_ingest.SCHEMA_RESET_NOTICE in summary_path.read_text(encoding="utf-8")


def test_ingest_omits_schema_reset_notice_by_default(tmp_path) -> None:
    _write_taggs_csv(
        tmp_path,
        "CDC-1-4.csv",
        header=taggs_ingest.EXPECTED_BASE_HEADER,
        body_rows=[_main_award_row(header=taggs_ingest.EXPECTED_BASE_HEADER)],
    )

    summary = taggs_ingest.ingest(
        db_url="postgresql+psycopg://ignored",
        input_dir=tmp_path,
        summary_path=tmp_path / "taggs_redo_ingestion_summary.json",
        chunk_size=100,
        truncate=True,
        drop_and_recreate=False,
        dry_run=True,
        verbose=False,
        limit_files=None,
        rebuild_summaries=True,
        rebuild_can_table=True,
    )

    assert "schema_reset_notice" not in summary
