from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "inspect_usaspending_funding_files.py"
SPEC = importlib.util.spec_from_file_location("inspect_usaspending_funding_files", SCRIPT_PATH)
assert SPEC is not None
profiler = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(profiler)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def test_infers_fiscal_year_and_file_type() -> None:
    path = Path("/tmp/chipfunding/fy24/All_Assistance_PrimeTransactions_2026-07-02.csv")

    assert profiler.infer_fiscal_year(path) == "fy24"
    assert profiler.infer_file_type(path.name) == profiler.FILE_TYPE_ASSISTANCE_PRIME
    assert (
        profiler.infer_file_type("All_Contracts_Subawards_2026-07-02.csv")
        == profiler.FILE_TYPE_CONTRACTS_SUBAWARDS
    )
    assert profiler.infer_file_type("notes.csv") == profiler.FILE_TYPE_UNKNOWN


def test_detects_field_groups() -> None:
    columns = [
        "assistance_transaction_unique_key",
        "assistance_award_unique_key",
        "federal_action_obligation",
        "action_date_fiscal_year",
        "recipient_county_name",
        "primary_place_of_performance_county_name",
        "funding_agency_name",
        "awarding_sub_agency_name",
        "federal_accounts_funding_this_award",
        "treasury_accounts_funding_this_award",
        "cfda_number",
        "assistance_type_code",
        "recipient_business_types",
        "obligated_amount_from_COVID-19_supplementals_for_overall_award",
    ]

    groups = profiler.detect_field_groups(columns)

    assert groups["likely_transaction_id_fields"] == ["assistance_transaction_unique_key"]
    assert "assistance_award_unique_key" in groups["likely_award_id_fields"]
    assert "federal_action_obligation" in groups["likely_positive_obligation_field"]
    assert "recipient_county_name" in groups["likely_recipient_geography_fields"]
    assert "primary_place_of_performance_county_name" in groups[
        "likely_place_of_performance_geography_fields"
    ]
    assert "obligated_amount_from_COVID-19_supplementals_for_overall_award" in groups[
        "likely_covid_emergency_iija_supplemental_fields"
    ]


def test_prime_profile_reports_missing_columns_and_sample_statistics(tmp_path) -> None:
    header = [
        "assistance_transaction_unique_key",
        "assistance_award_unique_key",
        "federal_action_obligation",
        "action_date_fiscal_year",
        "funding_agency_name",
        "funding_sub_agency_name",
        "prime_award_transaction_place_of_performance_county_fips_code",
        "prime_award_transaction_recipient_county_fips_code",
        "recipient_county_name",
        "recipient_state_code",
        "obligated_amount_from_COVID-19_supplementals_for_overall_award",
        "obligated_amount_from_IIJA_supplemental_for_overall_award",
        "cfda_number",
        "cfda_title",
        "assistance_type_code",
        "assistance_type_description",
    ]
    csv_path = _write_csv(
        tmp_path / "fy25" / "All_Assistance_PrimeTransactions_fixture.csv",
        header,
        [
            [
                "tx-1",
                "award-1",
                "100",
                "2025",
                "Department of Health and Human Services",
                "Centers for Disease Control and Prevention",
                "13089",
                "",
                "",
                "GA",
                "0",
                "5",
                "93.000",
                "Example",
                "02",
                "Cooperative Agreement",
            ],
            [
                "tx-2",
                "award-2",
                "-20",
                "2025",
                "Other Agency",
                "Other Subagency",
                "",
                "06037",
                "Los Angeles",
                "CA",
                "10",
                "0",
                "93.000",
                "Example",
                "02",
                "Cooperative Agreement",
            ],
            [
                "tx-3",
                "award-3",
                "0",
                "2025",
                "Department of Health and Human Services",
                "Centers for Disease Control and Prevention",
                "",
                "",
                "",
                "",
                "",
                "",
                "93.000",
                "Example",
                "02",
                "Cooperative Agreement",
            ],
        ],
    )

    profile = profiler.profile_csv_file(csv_path, chunksize=2, sample_rows=10)

    assert profile["inferred_fiscal_year"] == "fy25"
    assert profile["inferred_file_type"] == profiler.FILE_TYPE_ASSISTANCE_PRIME
    assert profile["row_count"] == 3
    assert profile["column_count"] == len(header)
    assert "primary_place_of_performance_state_code" in profile["missing_required_columns"]
    stats = profile["sample_statistics"]
    assert stats["sampled_rows"] == 3
    assert stats["positive_federal_action_obligation_rows"] == 1
    assert stats["non_positive_federal_action_obligation_rows"] == 2
    assert stats["non_hhs_cdc_funding_agency_subagency_rows"] == 1
    assert stats["missing_place_of_performance_county_fips_rows"] == 2
    assert stats["missing_recipient_county_fips_rows"] == 2
    assert stats["missing_place_of_performance_but_recipient_geography_available_rows"] == 1
    assert stats["covid_supplemental_obligated_amount_positive_rows"] == 1
    assert stats["iija_supplemental_obligated_amount_positive_rows"] == 1


def test_build_report_writes_repeatable_json(tmp_path) -> None:
    header = ["prime_award_unique_key", "prime_award_amount"]
    _write_csv(
        tmp_path / "input" / "fy19" / "All_Assistance_Subawards_fixture.csv",
        header,
        [["award-1", "10"], ["award-2", "20"]],
    )
    output_path = tmp_path / "profiles" / "profile.json"

    first_report = profiler.build_report(
        input_root=tmp_path / "input",
        output_path=output_path,
        chunksize=10,
        sample_rows=10,
    )
    profiler.write_report(first_report, output_path)
    second_report = profiler.build_report(
        input_root=tmp_path / "input",
        output_path=output_path,
        chunksize=10,
        sample_rows=10,
    )
    profiler.write_report(second_report, output_path)

    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["output_path"] == str(output_path)
    assert payload["detected_fiscal_years"] == ["fy19"]
    assert len(payload["files"]) == 1
    assert payload["files"][0]["row_count"] == 2
    assert payload["summary_by_file_type"][profiler.FILE_TYPE_ASSISTANCE_SUBAWARDS]["file_count"] == 1
    assert "recommended_next_schema" in payload
