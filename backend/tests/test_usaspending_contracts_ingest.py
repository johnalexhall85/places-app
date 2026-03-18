from __future__ import annotations

import csv
from decimal import Decimal

from app.usaspending import ingest as contracts_ingest


def _write_contract_csv(tmp_path, filename: str, header: list[str], rows: list[list[str]]):
    csv_path = tmp_path / filename
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return csv_path


def test_inspect_contract_csv_distinguishes_prime_transactions_from_other_csvs(tmp_path) -> None:
    prime_header = [
        "contract_transaction_unique_key",
        "contract_award_unique_key",
        "award_id_piid",
        "action_date",
        "action_date_fiscal_year",
        "federal_action_obligation",
        "recipient_name",
    ]
    other_header = [
        "prime_award_unique_key",
        "subaward_number",
        "subaward_action_date",
    ]
    prime_path = _write_contract_csv(
        tmp_path,
        "Contracts_PrimeTransactions_test.csv",
        prime_header,
        [["tx-1", "awd-1", "PIID-1", "2024-01-01", "2024", "10.00", "Example"]],
    )
    other_path = _write_contract_csv(
        tmp_path,
        "Contracts_Subawards_test.csv",
        other_header,
        [["prime-1", "sub-1", "2024-01-01"]],
    )

    prime_inspection = contracts_ingest.inspect_contract_csv(prime_path)
    other_inspection = contracts_ingest.inspect_contract_csv(other_path)
    validation = contracts_ingest.validate_csv_headers([prime_inspection, other_inspection])

    assert prime_inspection.is_matching_contract_transaction is True
    assert other_inspection.is_matching_contract_transaction is False
    assert validation["matching_files"] == ["Contracts_PrimeTransactions_test.csv"]
    assert validation["skipped_nonmatching_files"] == ["Contracts_Subawards_test.csv"]


def test_amount_parsing() -> None:
    assert contracts_ingest._parse_decimal("$1,234.50") == Decimal("1234.50")
    assert contracts_ingest._parse_decimal("($20)") == Decimal("-20.00")
    assert contracts_ingest._parse_decimal("not-a-number") is None


def test_date_parsing() -> None:
    assert str(contracts_ingest._parse_date("2024-03-01")) == "2024-03-01"
    assert str(contracts_ingest._parse_date("03/01/2024")) == "2024-03-01"
    assert contracts_ingest._parse_date("2024-13-01") is None


def test_state_normalization() -> None:
    assert contracts_ingest._normalize_state_code("ga") == "GA"
    assert contracts_ingest._normalize_state_code(" Georgia ") is None
    assert contracts_ingest._normalize_state_code("G-A") == "GA"


def test_contract_category_guessing() -> None:
    vfc_record = {
        "award_description": "Vaccines for Children vaccine procurement",
        "product_or_service_code_description": None,
        "naics_description": None,
    }
    janitorial_record = {
        "award_description": "Janitorial services for CDC facilities",
        "product_or_service_code_description": None,
        "naics_description": None,
    }
    blank_record = {}

    vfc = contracts_ingest.classify_contract_record(vfc_record)
    janitorial = contracts_ingest.classify_contract_record(janitorial_record)
    blank = contracts_ingest.classify_contract_record(blank_record)

    assert vfc["contract_category_guess"] == contracts_ingest.CATEGORY_LIKELY_VFC
    assert vfc["likely_profile_relevant"] is True
    assert janitorial["contract_category_guess"] == contracts_ingest.CATEGORY_ADMIN
    assert blank["contract_category_guess"] == contracts_ingest.CATEGORY_UNKNOWN


def test_federal_account_inventory_build() -> None:
    records = [
        {
            "normalized_federal_account_symbol": "075-0943;075-4553",
            "treasury_account_symbol": "075-2020/2022-0943-000",
            "appropriation_type": None,
            "fiscal_year": 2024,
            "transaction_obligated_amount": Decimal("100.00"),
            "generated_unique_award_id": "award-1",
        },
        {
            "normalized_federal_account_symbol": "075-0943",
            "treasury_account_symbol": "075-2020/2022-0943-000",
            "appropriation_type": None,
            "fiscal_year": 2025,
            "transaction_obligated_amount": Decimal("25.00"),
            "generated_unique_award_id": "award-2",
        },
    ]

    inventory_rows = contracts_ingest.build_federal_account_inventory_rows(records)

    assert inventory_rows == [
        {
            "federal_account_symbol": "075-0943",
            "treasury_account_symbol": "075-2020/2022-0943-000",
            "appropriation_type": None,
            "first_fiscal_year": 2024,
            "last_fiscal_year": 2025,
            "total_transaction_obligated_amount": Decimal("125.00"),
            "transaction_count": 2,
            "unique_award_count": 2,
        },
        {
            "federal_account_symbol": "075-4553",
            "treasury_account_symbol": "075-2020/2022-0943-000",
            "appropriation_type": None,
            "first_fiscal_year": 2024,
            "last_fiscal_year": 2024,
            "total_transaction_obligated_amount": Decimal("100.00"),
            "transaction_count": 1,
            "unique_award_count": 1,
        },
    ]


def test_summary_aggregation() -> None:
    records = [
        {
            "fiscal_year": 2024,
            "normalized_recipient_state": "GA",
            "recipient_state_code": "GA",
            "normalized_federal_account_symbol": "075-0943",
            "funding_agency_name": "Department of Health and Human Services",
            "awarding_agency_name": "Department of Health and Human Services",
            "award_description": "Vaccines for Children vaccine procurement",
            "transaction_obligated_amount": Decimal("100.00"),
            "generated_unique_award_id": "award-1",
        },
        {
            "fiscal_year": 2024,
            "normalized_recipient_state": "GA",
            "recipient_state_code": "GA",
            "normalized_federal_account_symbol": "075-0943",
            "funding_agency_name": "Department of Health and Human Services",
            "awarding_agency_name": "Department of Health and Human Services",
            "award_description": "Vaccines for Children vaccine procurement",
            "transaction_obligated_amount": Decimal("25.00"),
            "generated_unique_award_id": "award-1",
        },
        {
            "fiscal_year": 2024,
            "normalized_recipient_state": "GA",
            "recipient_state_code": "GA",
            "normalized_federal_account_symbol": "075-0943",
            "funding_agency_name": "Department of Health and Human Services",
            "awarding_agency_name": "Department of Health and Human Services",
            "award_description": "Janitorial services",
            "transaction_obligated_amount": Decimal("10.00"),
            "generated_unique_award_id": "award-2",
        },
    ]

    summary_rows = contracts_ingest.build_state_year_summary_rows(records)

    assert summary_rows == [
        {
            "fiscal_year": 2024,
            "recipient_state_code": "GA",
            "federal_account_symbol": "075-0943",
            "funding_agency_name": "Department of Health and Human Services",
            "awarding_agency_name": "Department of Health and Human Services",
            "contract_category_guess": contracts_ingest.CATEGORY_ADMIN,
            "total_transaction_obligated_amount": Decimal("10.00"),
            "transaction_count": 1,
            "unique_award_count": 1,
        },
        {
            "fiscal_year": 2024,
            "recipient_state_code": "GA",
            "federal_account_symbol": "075-0943",
            "funding_agency_name": "Department of Health and Human Services",
            "awarding_agency_name": "Department of Health and Human Services",
            "contract_category_guess": contracts_ingest.CATEGORY_LIKELY_VFC,
            "total_transaction_obligated_amount": Decimal("125.00"),
            "transaction_count": 2,
            "unique_award_count": 1,
        },
    ]
