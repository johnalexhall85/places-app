from __future__ import annotations

import csv
from decimal import Decimal

from app.usaspending_fed_account import ingest


def _write_csv(tmp_path, filename: str, header: list[str], rows: list[list[str]]):
    path = tmp_path / filename
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_file_discovery_classifies_fy2020_examples(tmp_path) -> None:
    filenames = {
        "FY2020Q1-P12_075_FA_Assistance_AccountBreakdownByAward_2026-04-23_H15M46S14_01.csv": ingest.DATASET_ASSISTANCE,
        "FY2020Q1-P12_075_FA_Contracts_AccountBreakdownByAward_2026-04-23_H15M46S14_01.csv": ingest.DATASET_CONTRACTS,
        "FY2020Q1-P12_075_FA_Unlinked_AccountBreakdownByAward_2026-04-23_H15M46S14_01.csv": ingest.DATASET_UNLINKED,
        "FY2020Q1-P12_075_FA_AccountBalances_2026-04-23_H15M46S14_01.csv": ingest.DATASET_BALANCES,
        "FY2020Q1-P12_075_FA_AccountBreakdownByPA-OC_2026-04-23_H15M46S14_01.csv": ingest.DATASET_PA_OC,
    }
    for filename in filenames:
        _write_csv(tmp_path, filename, ["federal_account_symbol"], [["075-0943"]])

    discovered = ingest.discover_fed_account_files(tmp_path, years=[2020])

    assert {file.path.name: file.dataset_type for file in discovered} == filenames
    assert {file.fiscal_year for file in discovered} == {2020}
    assert {file.source_agency_code for file in discovered} == {"075"}


def test_amount_parser_handles_common_usaspending_formats() -> None:
    assert ingest.parse_amount("$1,234.50") == Decimal("1234.50")
    assert ingest.parse_amount("") is None
    assert ingest.parse_amount(None) is None
    assert ingest.parse_amount("-20") == Decimal("-20.00")
    assert ingest.parse_amount("($20.25)") == Decimal("-20.25")
    assert ingest.parse_amount("not an amount") is None


def test_account_key_normalization_is_stable() -> None:
    row = {
        "federal_account_symbol": " 075-0943 ",
        "federal_account_name": "Centers for Disease Control and Prevention",
    }
    normalized_row = {ingest.normalize_header(key): value for key, value in row.items()}

    assert ingest.normalize_federal_account_key(normalized_row) == "fa:075-0943"
    assert ingest.normalize_federal_account_key({**normalized_row, "federal_account_name": "Other"}) == "fa:075-0943"
    assert (
        ingest.normalize_federal_account_key(
            {"agency_identifier": "075", "main_account_code": "0943", "sub_account_code": "000"}
        )
        == "tas_parts:075:na:0943:000"
    )


def test_dry_run_parses_without_database_writes(tmp_path, capsys) -> None:
    _write_csv(
        tmp_path,
        "FY2020Q1-P12_075_FA_AccountBalances_2026-04-23_H15M46S14_01.csv",
        [
            "owning_agency_name",
            "federal_account_symbol",
            "federal_account_name",
            "obligations_incurred",
            "gross_outlay_amount",
        ],
        [
            [
                "Department of Health and Human Services",
                "075-0943",
                "CDC-wide Activities and Program Support",
                "1,000.00",
                "(25.00)",
            ]
        ],
    )

    summary = ingest.run_ingestion(
        data_dir=tmp_path,
        years=[2020],
        db_url="postgresql+psycopg://should:not@be-used:5432/nope",
        force=False,
        dry_run=True,
        limit_rows=None,
        chunksize=10,
        rebuild_reconciliation=False,
        output_path=tmp_path / "unused.csv",
    )

    captured = capsys.readouterr()
    assert summary.dry_run is True
    assert summary.files_discovered == 1
    assert summary.rows_by_table_or_type["fact_account_balance"] == 1
    assert "no database writes performed" in captured.out

