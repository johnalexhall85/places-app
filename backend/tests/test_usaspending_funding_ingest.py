from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ingest_usaspending_funding.py"
SPEC = importlib.util.spec_from_file_location("ingest_usaspending_funding", SCRIPT_PATH)
assert SPEC is not None
ingest = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(ingest)


def _raw_row(**overrides):
    row = {
        "federal_action_obligation": "100.50",
        "funding_agency_name": "Department of Health and Human Services",
        "funding_sub_agency_name": "Centers for Disease Control and Prevention",
        "prime_award_transaction_place_of_performance_county_fips_code": "13089",
        "primary_place_of_performance_county_name": "DeKalb",
        "primary_place_of_performance_state_name": "Georgia",
        "prime_award_transaction_recipient_county_fips_code": "06037",
        "recipient_county_name": "Los Angeles",
        "recipient_state_code": "CA",
        "recipient_state_name": "California",
        "obligated_amount_from_COVID-19_supplementals_for_overall_award": "0",
        "obligated_amount_from_IIJA_supplemental_for_overall_award": "0",
    }
    row.update(overrides)
    return row


def test_amount_parsing_handles_common_formats() -> None:
    assert ingest.parse_amount("$1,234.50") == Decimal("1234.50")
    assert ingest.parse_amount("(25.10)") == Decimal("-25.10")
    assert ingest.parse_amount("") is None
    assert ingest.parse_amount("not-a-number") is None


def test_county_fips_zero_padding() -> None:
    assert ingest.normalize_county_fips("123") == "00123"
    assert ingest.normalize_county_fips("06037") == "06037"
    assert ingest.normalize_county_fips("abc") is None
    assert ingest.normalize_county_fips("123456") is None


def test_geography_prefers_place_of_performance_and_derives_state_from_fips() -> None:
    geography = ingest.choose_map_geography(_raw_row(primary_place_of_performance_state_code=""))

    assert geography["map_geography_source"] == "place_of_performance"
    assert geography["map_county_fips"] == "13089"
    assert geography["map_state_code"] == "13"


def test_geography_falls_back_to_recipient_then_unmapped() -> None:
    fallback = ingest.choose_map_geography(
        _raw_row(
            prime_award_transaction_place_of_performance_county_fips_code="",
            primary_place_of_performance_state_code="",
        )
    )
    unmapped = ingest.choose_map_geography(
        _raw_row(
            prime_award_transaction_place_of_performance_county_fips_code="",
            prime_award_transaction_recipient_county_fips_code="",
        )
    )

    assert fallback["map_geography_source"] == "recipient_fallback"
    assert fallback["map_county_fips"] == "06037"
    assert fallback["map_state_code"] == "CA"
    assert unmapped["map_geography_source"] == "unmapped"
    assert unmapped["map_county_fips"] is None


def test_cdc_agency_validation_is_exact() -> None:
    assert ingest.is_cdc_funded(_raw_row()) is True
    assert ingest.is_cdc_funded(_raw_row(funding_sub_agency_name="CDC")) is False


def test_supplemental_flag_detects_covid_iija_and_other_obligated_amounts() -> None:
    covid, iija, other, flag = ingest.supplemental_amounts(
        _raw_row(
            **{
                "obligated_amount_from_COVID-19_supplementals_for_overall_award": "5",
                "obligated_amount_from_IIJA_supplemental_for_overall_award": "2",
                "other_emergency_supplemental_obligated_amount": "3",
                "outlayed_amount_from_COVID-19_supplementals_for_overall_award": "999",
            }
        )
    )

    assert covid == Decimal("5")
    assert iija == Decimal("2")
    assert other == Decimal("3")
    assert flag is True


def test_default_map_eligibility_and_skip_reasons() -> None:
    assert ingest.default_map_eligible(
        is_prime_award=True,
        is_positive_obligation=True,
        is_cdc=True,
        is_supplemental=False,
        map_county_fips="13089",
    )
    assert not ingest.default_map_eligible(
        is_prime_award=True,
        is_positive_obligation=False,
        is_cdc=True,
        is_supplemental=False,
        map_county_fips="13089",
    )
    assert ingest.skip_reasons(
        is_prime_award=True,
        is_positive_obligation=False,
        is_cdc=False,
        is_supplemental=True,
        map_county_fips=None,
    ) == "non_positive_obligation;not_cdc_funded;covid_or_emergency_supplemental;unmapped_county"


def test_canonicalization_outputs_expected_flags() -> None:
    canonical = ingest.canonicalize_prime_row(
        _raw_row(),
        {
            "source_raw_table": "raw_usaspending_assistance_prime_transactions",
            "source_raw_id": 1,
            "source_fiscal_year": 2025,
            "source_file_type": ingest.FILE_TYPE_ASSISTANCE_PRIME,
            "source_file_name": "fixture.csv",
            "source_row_number": 1,
            "row_hash": "abc",
        },
    )

    assert canonical["funding_mechanism"] == "grants_cooperative_agreements"
    assert canonical["federal_action_obligation"] == Decimal("100.50")
    assert canonical["is_cdc_funded"] is True
    assert canonical["is_positive_obligation"] is True
    assert canonical["is_default_map_eligible"] is True
    assert canonical["skip_reason"] is None


def test_raw_row_hash_and_source_row_number_are_repeatable() -> None:
    records = [_raw_row(), _raw_row(federal_action_obligation="2")]
    first = ingest.raw_rows_for_chunk(
        records=records,
        source_fiscal_year=2025,
        source_file_type=ingest.FILE_TYPE_ASSISTANCE_PRIME,
        source_file_path=Path("/tmp/fixture.csv"),
        row_offset=10,
    )
    second = ingest.raw_rows_for_chunk(
        records=records,
        source_fiscal_year=2025,
        source_file_type=ingest.FILE_TYPE_ASSISTANCE_PRIME,
        source_file_path=Path("/tmp/fixture.csv"),
        row_offset=10,
    )

    assert [row["source_row_number"] for row in first] == [11, 12]
    assert [row["row_hash"] for row in first] == [row["row_hash"] for row in second]
