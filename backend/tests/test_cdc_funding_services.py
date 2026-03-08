from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.cdc_funding import ingest as cdc_ingest
from app.cdc_funding import services as cdc_services
from app.cdc_funding.appropriation import classify_official_emergency_code


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def one(self):
        if not self._rows:
            raise RuntimeError("No rows")
        return self._rows[0]

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeSessionForSearch:
    def __init__(self):
        self.sql_calls: list[str] = []
        self.params_calls: list[dict] = []

    def execute(self, statement, params=None):
        sql_text = str(statement)
        self.sql_calls.append(sql_text)
        self.params_calls.append(dict(params or {}))

        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])
        if "FROM public.dim_county" in sql_text and "WHERE location_id = :county_fips" in sql_text:
            return _FakeResult([{"state_abbr": "AL"}])
        if "SELECT *" in sql_text and "FROM (" in sql_text:
            return _FakeResult(
                [
                    {
                        "record_id": "PRIME-1",
                        "record_type": "prime_award",
                        "fain": "FAIN-PRIME-1",
                        "entity_name": "Prime Recipient",
                        "assistance_type_description": "Project Grants",
                        "amount": 1500.00,
                        "latest_action_date": date(2025, 10, 1),
                        "state_code": "AL",
                        "state_name": "Alabama",
                        "county_fips": "01001",
                        "county_name": "Autauga",
                        "description": "Prime description",
                        "usaspending_permalink": "https://example.com/prime",
                        "fiscal_year": 2026,
                        "center_name": "NCIRD",
                        "awarding_office_name": "Office A",
                        "funding_office_name": "Office B",
                    },
                    {
                        "record_id": "2",
                        "record_type": "subaward",
                        "fain": "FAIN-PRIME-1",
                        "entity_name": "Subaward Entity",
                        "assistance_type_description": None,
                        "amount": 250.50,
                        "latest_action_date": date(2025, 11, 3),
                        "state_code": "AL",
                        "state_name": "Alabama",
                        "county_fips": None,
                        "county_name": None,
                        "description": "Subaward description",
                        "usaspending_permalink": "https://example.com/sub",
                        "fiscal_year": 2026,
                        "center_name": "NCIRD",
                        "awarding_office_name": "Office A",
                        "funding_office_name": "Office B",
                    },
                ]
            )
        if "SELECT COUNT(*)::integer AS total_count" in sql_text:
            return _FakeResult([{"total_count": 2}])
        return _FakeResult([])


class _CaptureConnection:
    def __init__(self):
        self.sqls: list[str] = []

    def execute(self, statement, _params=None):
        sql_text = str(statement)
        self.sqls.append(sql_text)

        class _Result:
            rowcount = 0

        return _Result()


class _FakeSessionForTop:
    def __init__(self):
        self.last_sql = ""
        self.last_params = {}

    def execute(self, statement, params=None):
        sql_text = str(statement)
        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])
        if "FROM public.dim_county" in sql_text and "WHERE county.location_id = :county_fips" in sql_text:
            return _FakeResult(
                [
                    {
                        "county_fips": "01001",
                        "county_name": "Autauga",
                        "state_code": "AL",
                        "county_population": 10000,
                        "state_population": 200000,
                        "population_weight": 0.05,
                    }
                ]
            )
        if "LIMIT :limit" in sql_text:
            self.last_sql = sql_text
            self.last_params = dict(params or {})
        return _FakeResult(
            [
                {
                    "record_id": "PRIME-1",
                    "record_type": "prime_award",
                    "fain": "FAIN-PRIME-1",
                    "entity_name": "Prime Recipient",
                    "assistance_type_description": "Project Grants",
                    "fy_obligated_amount": 2000.00,
                    "fy_outlayed_amount_estimated": 1300.00,
                    "transaction_count": 3,
                    "distinct_award_count": 1,
                    "lifetime_total_funding_amount": 5000.00,
                    "latest_action_date": date(2025, 12, 12),
                    "state_code": "AL",
                    "state_name": "Alabama",
                    "county_fips": "01001",
                    "county_name": "Autauga",
                    "description": "Prime description",
                    "usaspending_permalink": "https://example.com/prime",
                    "includes_statewide_allocation": True,
                    "scope_classification": "statewide",
                    "award_fy_obligated_amount": 40000.00,
                    "award_fy_outlayed_amount_estimated": 20000.00,
                }
            ]
        )


class _FakeSessionForTrend:
    def __init__(self):
        self.sql_calls: list[str] = []
        self.params_calls: list[dict] = []

    def execute(self, statement, params=None):
        sql_text = str(statement)
        bound_params = dict(params or {})
        self.sql_calls.append(sql_text)
        self.params_calls.append(bound_params)

        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])

        if "MIN(s.fiscal_year) AS min_fiscal_year" in sql_text:
            return _FakeResult([{"min_fiscal_year": 2020, "max_fiscal_year": 2026}])

        if "FROM public.dim_state_boundary AS sb" in sql_text:
            return _FakeResult(
                [
                    {
                        "geography_id": "AL",
                        "geography_name": "Alabama",
                        "state_code": "AL",
                        "state_name": "Alabama",
                    }
                ]
            )

        if "FROM public.dim_county AS county" in sql_text and "WHERE county.location_id = :geography_id" in sql_text:
            return _FakeResult(
                [
                    {
                        "geography_id": "01001",
                        "county_name": "Autauga",
                        "state_code": "AL",
                        "state_name": "Alabama",
                    }
                ]
            )

        if "WITH years AS (" in sql_text and "generate_series" in sql_text:
            start_fy = int(bound_params.get("start_fy", 2020))
            end_fy = int(bound_params.get("end_fy", 2026))
            rows = []
            for fiscal_year in range(start_fy, end_fy + 1):
                has_rows = 0 if fiscal_year == start_fy else 1
                base_value = 0 if has_rows == 0 else (fiscal_year - 2019) * 100
                if "COALESCE(aggregated.subaward_count, 0)::numeric AS subaward_count" in sql_text:
                    rows.append(
                        {
                            "fiscal_year": fiscal_year,
                            "value": base_value,
                            "subaward_count": 0 if has_rows == 0 else (fiscal_year - start_fy + 3),
                            "distinct_award_count": 0 if has_rows == 0 else (fiscal_year - start_fy + 1),
                            "matched_rows": has_rows,
                        }
                    )
                else:
                    rows.append(
                        {
                            "fiscal_year": fiscal_year,
                            "value": base_value,
                            "transaction_count": 0 if has_rows == 0 else (fiscal_year - start_fy + 5),
                            "distinct_award_count": 0 if has_rows == 0 else (fiscal_year - start_fy + 2),
                            "matched_rows": has_rows,
                        }
                    )
            return _FakeResult(rows)

        return _FakeResult([])


class _FakeSessionForMapLegendNational:
    def __init__(self):
        self.sql_calls: list[str] = []
        self.params_calls: list[dict] = []

    def execute(self, statement, params=None):
        sql_text = str(statement)
        bound_params = dict(params or {})
        self.sql_calls.append(sql_text)
        self.params_calls.append(bound_params)

        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])

        if "MAX(action_date_fiscal_year) AS fiscal_year" in sql_text:
            return _FakeResult([{"fiscal_year": 2025}])

        if "FROM public.dim_county_boundary AS b" in sql_text:
            return _FakeResult(
                [
                    {
                        "id": "01001",
                        "area_name": "Autauga",
                        "state_code": "AL",
                        "state_name": "Alabama",
                        "metric_value": 1000.0,
                        "metric_per_capita": 10.0,
                        "population": 100.0,
                        "funding_per_capita": 10.0,
                        "fy_obligated_amount": 1000.0,
                        "fy_outlayed_amount_estimated": 700.0,
                        "transaction_count": 12,
                        "distinct_award_count": 5,
                        "total_funding_amount": 1000.0,
                        "total_obligated_amount": 1000.0,
                        "total_outlayed_amount": 700.0,
                        "award_count": 5,
                        "total_subaward_amount": 0.0,
                        "subaward_count": 0,
                        "geometry": {"type": "Polygon", "coordinates": []},
                    }
                ]
            )

        if "FROM public.dim_state_boundary AS sb" in sql_text:
            return _FakeResult(
                [
                    {
                        "id": "AL",
                        "area_name": "Alabama",
                        "state_code": "AL",
                        "state_name": "Alabama",
                        "metric_value": 1000.0,
                        "metric_per_capita": 10.0,
                        "population": 100.0,
                        "funding_per_capita": 10.0,
                        "fy_obligated_amount": 1000.0,
                        "fy_outlayed_amount_estimated": 700.0,
                        "transaction_count": 12,
                        "distinct_award_count": 5,
                        "total_funding_amount": 1000.0,
                        "total_obligated_amount": 1000.0,
                        "total_outlayed_amount": 700.0,
                        "award_count": 5,
                        "total_subaward_amount": 0.0,
                        "subaward_count": 0,
                        "geometry": {"type": "Polygon", "coordinates": []},
                    }
                ]
            )

        if "SELECT\n                    summary.geography_id," in sql_text and "FROM summary" in sql_text:
            return _FakeResult(
                [
                    {
                        "geography_id": "AL",
                        "metric_value": 1000.0,
                        "metric_per_capita": 10.0,
                        "population": 100.0,
                        "funding_per_capita": 10.0,
                        "fy_obligated_amount": 1000.0,
                        "fy_outlayed_amount_estimated": 700.0,
                        "transaction_count": 12,
                        "distinct_award_count": 5,
                        "total_funding_amount": 1000.0,
                        "total_obligated_amount": 1000.0,
                        "total_outlayed_amount": 700.0,
                        "award_count": 5,
                        "total_subaward_amount": 0.0,
                        "subaward_count": 0,
                    }
                ]
            )

        if "SUM(summary.metric_value) AS metric_value" in sql_text and "FROM summary" in sql_text:
            return _FakeResult(
                [
                    {
                        "metric_value": 1000.0,
                        "metric_per_capita": 10.0,
                        "population": 100.0,
                        "total_funding_amount": 1000.0,
                        "funding_per_capita": 10.0,
                        "fy_obligated_amount": 1000.0,
                        "fy_outlayed_amount_estimated": 700.0,
                        "transaction_count": 12,
                        "distinct_award_count": 5,
                        "total_subaward_amount": 0.0,
                        "subaward_count": 0,
                    }
                ]
            )

        return _FakeResult([])


class _FakeSessionForScopeDebug:
    def __init__(self):
        self.sql_calls: list[str] = []
        self.params_calls: list[dict] = []

    def execute(self, statement, params=None):
        sql_text = str(statement)
        self.sql_calls.append(sql_text)
        self.params_calls.append(dict(params or {}))

        if "to_regclass" in sql_text:
            return _FakeResult([{"exists": "ok"}])
        if "SELECT COUNT(*)::integer AS total_count" in sql_text:
            return _FakeResult([{"total_count": 1}])
        if "FROM cdc_funding.award_scope_classification AS c" in sql_text:
            return _FakeResult(
                [
                    {
                        "assistance_award_unique_key": "PRIME-KEY-STATEWIDE",
                        "award_id_fain": "FAIN-STATE-1",
                        "recipient_name": "State of Example Department of Health",
                        "cfda_program_title": "State Public Health Infrastructure",
                        "scope_classification": "statewide",
                        "scope_score": 11,
                        "scope_confidence": "high",
                        "reason_codes": ["STATE_HEALTH_AGENCY", "DESC_STATEWIDE"],
                        "is_allocatable_to_counties": True,
                        "allocation_method_default": "total_population",
                        "classifier_version": "v1",
                    }
                ]
            )
        return _FakeResult([])


def test_read_prime_and_subaward_rows_counts_and_normalization(tmp_path) -> None:
    prime_path = tmp_path / "prime.csv"
    tx_path = tmp_path / "tx.csv"
    sub_path = tmp_path / "sub.csv"

    with prime_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "assistance_award_unique_key",
                "award_id_fain",
                "recipient_state_code",
                "prime_award_summary_recipient_county_fips_code",
                "award_latest_action_date_fiscal_year",
                "total_funding_amount",
                "cfda_numbers_and_titles",
                "disaster_emergency_fund_codes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "assistance_award_unique_key": "PRIME-KEY-1",
                "award_id_fain": "FAIN-1",
                "recipient_state_code": "al",
                "prime_award_summary_recipient_county_fips_code": "1001",
                "award_latest_action_date_fiscal_year": "2026",
                "total_funding_amount": "1234.56",
                "cfda_numbers_and_titles": "93.354: Public Health Emergency Response",
                "disaster_emergency_fund_codes": "Q: Not Designated Nonemergency/Emergency/Disaster/Wildfire Suppression",
            }
        )
        writer.writerow(
            {
                "assistance_award_unique_key": "",
                "award_id_fain": "FAIN-SKIP",
            }
        )

    with sub_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "prime_award_unique_key",
                "prime_award_fain",
                "subaward_amount",
                "subaward_action_date_fiscal_year",
                "subawardee_state_code",
                "prime_award_disaster_emergency_fund_codes",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "prime_award_unique_key": "PRIME-KEY-1",
                "prime_award_fain": "FAIN-1",
                "subaward_amount": "150.25",
                "subaward_action_date_fiscal_year": "2026",
                "subawardee_state_code": "al",
                "prime_award_disaster_emergency_fund_codes": "N: Emergency P.L. 116-136",
            }
        )
        writer.writerow(
            {
                "prime_award_unique_key": "",
                "prime_award_fain": "FAIN-SKIP",
            }
        )

    with tx_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "assistance_transaction_unique_key",
                "assistance_award_unique_key",
                "award_id_fain",
                "action_date_fiscal_year",
                "recipient_state_code",
                "prime_award_transaction_recipient_county_fips_code",
                "federal_action_obligation",
                "cfda_number",
                "disaster_emergency_fund_codes_for_overall_award",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "assistance_transaction_unique_key": "TX-1",
                "assistance_award_unique_key": "PRIME-KEY-1",
                "award_id_fain": "FAIN-1",
                "action_date_fiscal_year": "2026",
                "recipient_state_code": "al",
                "prime_award_transaction_recipient_county_fips_code": "1001",
                "federal_action_obligation": "99.75",
                "cfda_number": "93.276",
                "disaster_emergency_fund_codes_for_overall_award": "N: Emergency P.L. 116-136",
            }
        )
        writer.writerow({"assistance_transaction_unique_key": ""})

    prime_rows = cdc_ingest._read_prime_rows(prime_path)
    tx_rows = cdc_ingest._read_prime_transaction_rows(tx_path)
    sub_rows = cdc_ingest._read_subaward_rows(sub_path)

    assert len(prime_rows) == 1
    assert prime_rows[0]["recipient_state_code"] == "AL"
    assert prime_rows[0]["recipient_county_fips"] == "01001"
    assert prime_rows[0]["award_latest_action_date_fiscal_year"] == 2026
    assert str(prime_rows[0]["total_funding_amount"]) == "1234.56"
    assert prime_rows[0]["cfda_program_num"] == "93.354"
    assert prime_rows[0]["appropriation_type"] == "regular"

    assert len(tx_rows) == 1
    assert tx_rows[0]["assistance_transaction_unique_key"] == "TX-1"
    assert tx_rows[0]["assistance_award_unique_key"] == "PRIME-KEY-1"
    assert tx_rows[0]["recipient_state_code"] == "AL"
    assert tx_rows[0]["prime_award_transaction_recipient_county_fips_code"] == "01001"
    assert tx_rows[0]["action_date_fiscal_year"] == 2026
    assert str(tx_rows[0]["federal_action_obligation"]) == "99.75"
    assert tx_rows[0]["appropriation_type"] == "covid_emergency"
    assert tx_rows[0]["disaster_emergency_fund_codes_raw"] == "N: Emergency P.L. 116-136"

    assert len(sub_rows) == 1
    assert sub_rows[0]["subawardee_state_code"] == "AL"
    assert sub_rows[0]["subaward_action_date_fiscal_year"] == 2026
    assert str(sub_rows[0]["subaward_amount"]) == "150.25"
    assert sub_rows[0]["appropriation_type"] == "covid_emergency"
    assert sub_rows[0]["prime_award_disaster_emergency_fund_codes_raw"] == "N: Emergency P.L. 116-136"


def test_refresh_summary_tables_uses_recipient_and_subawardee_geography() -> None:
    connection = _CaptureConnection()
    cdc_ingest._refresh_summary_tables(connection)
    sql_blob = "\n".join(connection.sqls)

    assert "FROM cdc_funding.prime_awards AS p" in sql_blob
    assert "p.recipient_state_code AS geography_id" in sql_blob
    assert "p.recipient_county_fips AS geography_id" in sql_blob
    assert "WHERE p.recipient_county_fips IS NOT NULL" in sql_blob

    assert "FROM cdc_funding.prime_transactions AS t" in sql_blob
    assert "LEFT JOIN cdc_funding.prime_awards AS p" in sql_blob
    assert "tx.resolved_state_code AS geography_id" in sql_blob
    assert "INSERT INTO cdc_funding.prime_transaction_county_summary (" in sql_blob
    assert "INSERT INTO cdc_funding.prime_transaction_county_summary_allocated (" in sql_blob
    assert "INSERT INTO cdc_funding.prime_transaction_national_summary (" in sql_blob
    assert "LEFT JOIN cdc_funding.award_scope_classification AS cls" in sql_blob
    assert "tx.scope_classification = 'statewide'" in sql_blob
    assert "tx.scope_classification <> 'statewide'" in sql_blob
    assert "dim_county AS county" in sql_blob
    assert "v_geography_population" in sql_blob
    assert "funding_per_capita" in sql_blob

    assert "FROM cdc_funding.subawards AS s" in sql_blob
    assert "s.subawardee_state_code AS geography_id" in sql_blob
    assert "s.subawardee_county_fips AS geography_id" in sql_blob
    assert "INSERT INTO cdc_funding.subaward_national_summary (" in sql_blob
    assert "WHERE s.subawardee_county_fips IS NOT NULL" in sql_blob
    assert "appropriation_type" in sql_blob


def test_refresh_appropriation_classification_includes_prime_tx_and_subawards() -> None:
    connection = _CaptureConnection()
    cdc_ingest._refresh_appropriation_classification(connection)
    sql_blob = "\n".join(connection.sqls)

    assert "TRUNCATE TABLE cdc_funding.appropriation_classification" in sql_blob
    assert "'prime_transaction' AS record_type" in sql_blob
    assert "'subaward' AS record_type" in sql_blob
    assert "'prime_award' AS record_type" in sql_blob
    assert "tx.disaster_emergency_fund_codes_raw" in sql_blob
    assert "s.prime_award_disaster_emergency_fund_codes_raw" in sql_blob


def test_appropriation_mapping_null_blank_and_known_codes() -> None:
    regular_blank = classify_official_emergency_code(None)
    assert regular_blank["appropriation_type"] == "regular"
    assert regular_blank["appropriation_subtype"] is None

    regular_q = classify_official_emergency_code(
        "Q: Not Designated Nonemergency/Emergency/Disaster/Wildfire Suppression"
    )
    assert regular_q["appropriation_type"] == "regular"
    assert regular_q["appropriation_subtype"] is None

    covid_known = classify_official_emergency_code("N: Emergency P.L. 116-136")
    assert covid_known["appropriation_type"] == "covid_emergency"
    assert covid_known["appropriation_subtype"] == "CARES"

    other_known = classify_official_emergency_code("E: Emergency P.L. 116-20")
    assert other_known["appropriation_type"] == "other_emergency"
    assert other_known["appropriation_subtype"] == "OTHER_EMERGENCY"

    unknown_unmapped = classify_official_emergency_code("ZZZ: Experimental Funding Code")
    assert unknown_unmapped["appropriation_type"] == "unknown"
    assert unknown_unmapped["appropriation_subtype"] == "UNKNOWN"


def test_scope_classifier_marks_state_health_department_as_statewide() -> None:
    scope = cdc_ingest._classify_award_scope(
        recipient_name="State of Georgia Department of Public Health",
        assistance_type_description="Block Grant",
        recipient_state_code="GA",
        recipient_county_fips=None,
        transaction_descriptions="Supports statewide public health system capacity across the state.",
        transaction_base_descriptions=None,
        transaction_cfda_titles="Public Health Block Grant",
        prime_award_base_transaction_description="State infrastructure support",
        cfda_program_title="Preventive Health and Health Services Block Grant",
    )

    assert scope["scope_classification"] == "statewide"
    assert scope["is_allocatable_to_counties"] is True
    assert "STATE_HEALTH_AGENCY" in scope["reason_codes"]
    assert "DESC_STATEWIDE" in scope["reason_codes"]


def test_scope_classifier_marks_county_local_language_as_local_county() -> None:
    scope = cdc_ingest._classify_award_scope(
        recipient_name="Fulton County Health Department",
        assistance_type_description="Project Grants",
        recipient_state_code="GA",
        recipient_county_fips="13121",
        transaction_descriptions="Local county community-based service expansion.",
        transaction_base_descriptions=None,
        transaction_cfda_titles="Health Services",
        prime_award_base_transaction_description=None,
        cfda_program_title=None,
    )

    assert scope["scope_classification"] == "local_county"
    assert scope["is_allocatable_to_counties"] is False
    assert "DESC_LOCAL" in scope["reason_codes"]
    assert "COUNTY_PRESENT" in scope["reason_codes"]


def test_scope_classifier_marks_national_entity_as_multi_state() -> None:
    scope = cdc_ingest._classify_award_scope(
        recipient_name="National Public Health Consortium",
        assistance_type_description="Cooperative Agreement",
        recipient_state_code=None,
        recipient_county_fips=None,
        transaction_descriptions="National network with multi-state coordination and regional support.",
        transaction_base_descriptions=None,
        transaction_cfda_titles=None,
        prime_award_base_transaction_description=None,
        cfda_program_title=None,
    )

    assert scope["scope_classification"] == "multi_state"
    assert scope["is_allocatable_to_counties"] is False
    assert "DESC_REGIONAL" in scope["reason_codes"]


def test_scope_classifier_marks_ambiguous_case_as_unknown() -> None:
    scope = cdc_ingest._classify_award_scope(
        recipient_name="Example Health Initiative",
        assistance_type_description="Cooperative Agreement",
        recipient_state_code="GA",
        recipient_county_fips=None,
        transaction_descriptions="Program operations support",
        transaction_base_descriptions=None,
        transaction_cfda_titles=None,
        prime_award_base_transaction_description=None,
        cfda_program_title=None,
    )

    assert scope["scope_classification"] == "unknown"
    assert scope["is_allocatable_to_counties"] is False


def test_summary_table_uses_allocated_county_table_only_for_statewide_mode() -> None:
    assert cdc_services._summary_table(
        basis="prime",
        geography="county",
        funding_geography_mode="recipient_location",
    ) == "cdc_funding.prime_transaction_county_summary"
    assert cdc_services._summary_table(
        basis="prime",
        geography="county",
        funding_geography_mode="statewide_allocation",
    ) == "cdc_funding.prime_transaction_county_summary_allocated"
    assert cdc_services._summary_table(
        basis="prime",
        geography="state",
        funding_geography_mode="recipient_location",
    ) == "cdc_funding.prime_transaction_state_summary"
    assert cdc_services._summary_table(
        basis="prime",
        geography="state",
        funding_geography_mode="statewide_allocation",
    ) == "cdc_funding.prime_transaction_state_summary"


def test_summary_filters_include_appropriation_type_when_requested() -> None:
    sql, params = cdc_services._summary_filters_sql(
        basis="prime",
        geography="county",
        appropriation_type="regular",
        assistance_type=None,
        fiscal_year=2026,
        awarding_office=None,
        funding_office=None,
        center=None,
        state=None,
    )

    assert "s.appropriation_type = :appropriation_type" in sql
    assert params["appropriation_type"] == "regular"
    assert params["fiscal_year"] == 2026


def test_fetch_trend_returns_ordered_prime_state_series() -> None:
    fake_db = _FakeSessionForTrend()
    payload = cdc_services.fetch_trend(
        fake_db,
        basis="prime",
        geography="state",
        geography_id="al",
        metric="fy_obligated",
        appropriation_type="all",
        funding_geography_mode="recipient_location",
        start_fy=None,
        end_fy=None,
    )

    assert payload["basis"] == "prime"
    assert payload["geography_type"] == "state"
    assert payload["geography_id"] == "AL"
    assert payload["geography_name"] == "Alabama"
    assert payload["start_fiscal_year"] == 2020
    expected_end_fy = min(2026, cdc_services._latest_completed_federal_fiscal_year())
    assert payload["end_fiscal_year"] == expected_end_fy
    assert payload["has_data"] is True

    years = [point["fiscal_year"] for point in payload["series"]]
    assert years == list(range(2020, expected_end_fy + 1))
    assert payload["series"][0]["value"] == 0
    assert payload["series"][0]["transaction_count"] == 0
    assert payload["series"][1]["transaction_count"] > 0


def test_fetch_trend_caps_requested_end_year_to_latest_completed_fiscal_year() -> None:
    fake_db = _FakeSessionForTrend()
    latest_completed_fy = cdc_services._latest_completed_federal_fiscal_year()
    start_fy = min(2020, latest_completed_fy)
    payload = cdc_services.fetch_trend(
        fake_db,
        basis="prime",
        geography="state",
        geography_id="AL",
        metric="fy_obligated",
        start_fy=start_fy,
        end_fy=latest_completed_fy + 1,
    )

    trend_params = next(
        params
        for sql, params in zip(fake_db.sql_calls, fake_db.params_calls)
        if "WITH years AS (" in sql and "generate_series" in sql
    )
    assert payload["end_fiscal_year"] == latest_completed_fy
    assert trend_params["end_fy"] == latest_completed_fy


def test_fetch_trend_applies_filters_and_uses_allocated_county_summary_when_requested() -> None:
    fake_db = _FakeSessionForTrend()
    cdc_services.fetch_trend(
        fake_db,
        basis="prime",
        geography="county",
        geography_id="1001",
        metric="transaction_count",
        appropriation_type="regular",
        funding_geography_mode="statewide_allocation",
        assistance_type="Project Grants",
        awarding_office="Office A",
        funding_office="Office B",
        center="NCIRD",
        state="AL",
        start_fy=2021,
        end_fy=2023,
    )

    trend_sql = next(
        sql for sql in fake_db.sql_calls if "WITH years AS (" in sql and "generate_series" in sql
    )
    trend_params = next(
        params
        for sql, params in zip(fake_db.sql_calls, fake_db.params_calls)
        if "WITH years AS (" in sql and "generate_series" in sql
    )

    assert "FROM cdc_funding.prime_transaction_county_summary_allocated AS s" in trend_sql
    assert "s.assistance_type_description = :assistance_type" in trend_sql
    assert "s.appropriation_type = :appropriation_type" in trend_sql
    assert "s.awarding_office_name = :awarding_office" in trend_sql
    assert "s.funding_office_name = :funding_office" in trend_sql
    assert "(s.awarding_sub_agency_name = :center OR s.funding_sub_agency_name = :center)" in trend_sql
    assert "s.state_code = :state_code" in trend_sql
    assert trend_params["geography_id"] == "01001"
    assert trend_params["start_fy"] == 2021
    assert trend_params["end_fy"] == 2023
    assert trend_params["appropriation_type"] == "regular"
    assert trend_params["assistance_type"] == "Project Grants"
    assert trend_params["state_code"] == "AL"


def test_fetch_trend_supports_subaward_county_series() -> None:
    fake_db = _FakeSessionForTrend()
    payload = cdc_services.fetch_trend(
        fake_db,
        basis="subaward",
        geography="county",
        geography_id="01001",
        metric="subaward_count",
        funding_geography_mode="statewide_allocation",
    )

    assert payload["basis"] == "subaward"
    assert payload["geography_type"] == "county"
    assert payload["geography_id"] == "01001"
    assert payload["geography_name"] == "Autauga, AL"
    assert payload["funding_geography_mode"] == "recipient_location"
    assert payload["series"][0]["subaward_count"] == 0
    assert "transaction_count" not in payload["series"][0]


def test_fetch_trend_rejects_invalid_metric_for_subaward_basis() -> None:
    fake_db = _FakeSessionForTrend()
    with pytest.raises(HTTPException) as exc:
        cdc_services.fetch_trend(
            fake_db,
            basis="subaward",
            geography="state",
            geography_id="AL",
            metric="fy_obligated",
        )
    assert "For basis=subaward" in str(exc.value)


def test_fetch_map_geojson_switches_between_total_and_per_capita_values() -> None:
    total_db = _FakeSessionForMapLegendNational()
    total_payload = cdc_services.fetch_map_geojson(
        total_db,
        basis="prime",
        geography="state",
        metric="fy_obligated",
        display_mode="total",
        appropriation_type="regular",
        fiscal_year=2025,
    )
    total_props = total_payload["features"][0]["properties"]
    assert total_props["value"] == 1000.0
    assert total_props["metric_value"] == 1000.0
    assert total_props["metric_per_capita"] == 10.0
    assert total_payload["display_mode"] == "total"
    assert total_payload["meta"]["metric_label"] == "Fiscal Year Obligated"

    per_capita_db = _FakeSessionForMapLegendNational()
    per_capita_payload = cdc_services.fetch_map_geojson(
        per_capita_db,
        basis="prime",
        geography="state",
        metric="fy_obligated",
        display_mode="per_capita",
        appropriation_type="regular",
        fiscal_year=2025,
    )
    per_capita_props = per_capita_payload["features"][0]["properties"]
    assert per_capita_props["value"] == 10.0
    assert per_capita_props["metric_value"] == 1000.0
    assert per_capita_props["metric_per_capita"] == 10.0
    assert per_capita_payload["display_mode"] == "per_capita"
    assert per_capita_payload["meta"]["metric_label"] == "Fiscal Year Obligated per capita"
    assert "Per-capita values use the app population denominator" in (per_capita_payload["meta"]["note"] or "")


def test_fetch_map_geojson_supports_county_per_capita_rendering() -> None:
    fake_db = _FakeSessionForMapLegendNational()
    payload = cdc_services.fetch_map_geojson(
        fake_db,
        basis="prime",
        geography="county",
        metric="fy_obligated",
        display_mode="per_capita",
        appropriation_type="regular",
        fiscal_year=2025,
    )
    assert payload["level"] == "county"
    assert payload["display_mode"] == "per_capita"
    assert len(payload["features"]) == 1
    props = payload["features"][0]["properties"]
    assert props["id"] == "01001"
    assert props["value"] == 10.0
    assert props["population"] == 100.0
    assert props["funding_per_capita"] == 10.0


def test_fetch_map_geojson_rejects_per_capita_for_count_metric() -> None:
    fake_db = _FakeSessionForMapLegendNational()
    with pytest.raises(HTTPException) as exc:
        cdc_services.fetch_map_geojson(
            fake_db,
            basis="prime",
            geography="state",
            metric="transaction_count",
            display_mode="per_capita",
        )
    assert "dollar-based metrics" in str(exc.value)


def test_fetch_legend_stats_includes_national_summary_for_per_capita_mode() -> None:
    fake_db = _FakeSessionForMapLegendNational()
    payload = cdc_services.fetch_legend_stats(
        fake_db,
        basis="prime",
        geography="state",
        funding_geography_mode="recipient_location",
        metric="fy_obligated",
        display_mode="per_capita",
        appropriation_type="regular",
        assistance_type="Project Grants",
        fiscal_year=2025,
        awarding_office="Office A",
        funding_office="Office B",
        center="NCIRD",
    )

    assert payload["display_mode"] == "per_capita"
    assert payload["metric_label"] == "Fiscal Year Obligated per capita"
    assert payload["min"] == 10.0
    assert payload["max"] == 10.0
    assert payload["mapped_geographies"] == 1
    assert payload["national_summary"]["geography_id"] == "US"
    assert payload["national_summary"]["value"] == 10.0
    assert payload["national_summary"]["metric_value"] == 1000.0
    assert payload["national_summary"]["metric_per_capita"] == 10.0
    assert payload["national_summary"]["total_funding_amount"] == 1000.0
    assert payload["national_summary"]["funding_per_capita"] == 10.0
    assert "Per-capita values use the app population denominator" in (payload["note"] or "")


def test_fetch_national_summary_applies_filters_server_side() -> None:
    fake_db = _FakeSessionForMapLegendNational()
    payload = cdc_services.fetch_national_summary(
        fake_db,
        basis="prime",
        funding_geography_mode="recipient_location",
        metric="fy_obligated",
        display_mode="per_capita",
        appropriation_type="regular",
        assistance_type="Project Grants",
        fiscal_year=2025,
        awarding_office="Office A",
        funding_office="Office B",
        center="NCIRD",
    )

    assert payload["basis"] == "prime"
    assert payload["display_mode"] == "per_capita"
    assert payload["appropriation_type"] == "regular"
    assert payload["summary"]["geography_id"] == "US"
    assert payload["summary"]["value"] == 10.0
    assert payload["summary"]["metric_value"] == 1000.0
    assert payload["summary"]["metric_per_capita"] == 10.0
    assert payload["summary"]["population"] == 100.0
    assert payload["summary"]["funding_per_capita"] == 10.0

    national_sql = next(
        sql
        for sql in fake_db.sql_calls
        if "FROM cdc_funding.prime_transaction_national_summary AS s" in sql
    )
    assert "s.appropriation_type = :appropriation_type" in national_sql
    assert "s.assistance_type_description = :assistance_type" in national_sql
    assert "s.fiscal_year = :fiscal_year" in national_sql
    assert "s.awarding_office_name = :awarding_office" in national_sql
    assert "s.funding_office_name = :funding_office" in national_sql
    assert "(s.awarding_sub_agency_name = :center OR s.funding_sub_agency_name = :center)" in national_sql

    national_params = next(
        params
        for sql, params in zip(fake_db.sql_calls, fake_db.params_calls)
        if "SUM(summary.metric_value) AS metric_value" in sql and "FROM summary" in sql
    )
    assert national_params["appropriation_type"] == "regular"
    assert national_params["assistance_type"] == "Project Grants"
    assert national_params["fiscal_year"] == 2025
    assert national_params["awarding_office"] == "Office A"
    assert national_params["funding_office"] == "Office B"
    assert national_params["center"] == "NCIRD"


def test_search_returns_prime_and_subaward_rows() -> None:
    fake_db = _FakeSessionForSearch()
    payload = cdc_services.search_awards(
        fake_db,
        q="recipient",
        basis="all",
        assistance_type="Project Grants",
        fiscal_year=2026,
        state="AL",
        page=1,
        page_size=25,
    )

    assert payload["basis"] == "all"
    assert payload["total"] == 2
    assert [row["record_type"] for row in payload["results"]] == ["prime_award", "subaward"]
    assert payload["results"][0]["latest_action_date"] == "2025-10-01"
    assert payload["results"][1]["latest_action_date"] == "2025-11-03"

    combined_sql = next(sql for sql in fake_db.sql_calls if "SELECT *" in sql and "FROM (" in sql)
    assert "p.assistance_type_description = :assistance_type" in combined_sql
    assert "FROM cdc_funding.prime_transactions AS tx_filter" in combined_sql
    assert "tx_filter.action_date_fiscal_year = :fiscal_year" in combined_sql
    assert "s.subaward_action_date_fiscal_year = :fiscal_year" in combined_sql
    assert "p.recipient_state_code = :state_filter_code" in combined_sql
    assert "s.subawardee_state_code = :state_filter_code" in combined_sql


def test_scope_debug_endpoint_returns_classifier_rows() -> None:
    fake_db = _FakeSessionForScopeDebug()
    payload = cdc_services.fetch_scope_classification_debug(
        fake_db,
        q="state",
        scope_classification="statewide",
        min_score=6,
        page=1,
        page_size=25,
    )

    assert payload["total"] == 1
    assert payload["scope_classification"] == "statewide"
    assert payload["results"][0]["assistance_award_unique_key"] == "PRIME-KEY-STATEWIDE"
    assert payload["results"][0]["scope_classification"] == "statewide"
    assert payload["results"][0]["reason_codes"] == ["STATE_HEALTH_AGENCY", "DESC_STATEWIDE"]

    query_sql = next(
        sql for sql in fake_db.sql_calls if "FROM cdc_funding.award_scope_classification AS c" in sql
    )
    assert "c.scope_classification = :scope_classification" in query_sql
    assert "c.scope_score >= :min_score" in query_sql


def test_search_applies_office_and_center_filters() -> None:
    fake_db = _FakeSessionForSearch()
    cdc_services.search_awards(
        fake_db,
        q="recipient",
        basis="all",
        assistance_type=None,
        fiscal_year=None,
        awarding_office="Office A",
        funding_office="Office B",
        center="NCIRD",
        state=None,
        page=1,
        page_size=25,
    )

    combined_sql = next(sql for sql in fake_db.sql_calls if "SELECT *" in sql and "FROM (" in sql)
    assert "p.awarding_office_name = :awarding_office" in combined_sql
    assert "s.prime_award_awarding_office_name = :awarding_office" in combined_sql
    assert "p.funding_office_name = :funding_office" in combined_sql
    assert "s.prime_award_funding_office_name = :funding_office" in combined_sql
    assert "p.awarding_sub_agency_name = :center OR p.funding_sub_agency_name = :center" in combined_sql
    assert (
        "s.prime_award_awarding_sub_agency_name = :center "
        "OR s.prime_award_funding_sub_agency_name = :center"
    ) in combined_sql


def test_search_applies_appropriation_filter_to_prime_and_subaward() -> None:
    fake_db = _FakeSessionForSearch()
    cdc_services.search_awards(
        fake_db,
        q="recipient",
        basis="all",
        appropriation_type="covid_emergency",
        assistance_type=None,
        fiscal_year=2026,
        state=None,
        page=1,
        page_size=25,
    )

    combined_sql = next(sql for sql in fake_db.sql_calls if "SELECT *" in sql and "FROM (" in sql)
    assert "tx_filter.appropriation_type = :appropriation_type" in combined_sql
    assert "s.appropriation_type = :appropriation_type" in combined_sql


def test_search_prefers_selected_county_scope_over_selected_state_scope() -> None:
    fake_db = _FakeSessionForSearch()
    cdc_services.search_awards(
        fake_db,
        q="recipient",
        basis="all",
        assistance_type=None,
        fiscal_year=None,
        state=None,
        selected_state_code="AL",
        selected_county_fips="01001",
        page=1,
        page_size=25,
    )

    combined_sql = next(sql for sql in fake_db.sql_calls if "SELECT *" in sql and "FROM (" in sql)
    assert "p.recipient_county_fips = :selected_county_fips" in combined_sql
    assert "s.subawardee_county_fips = :selected_county_fips" in combined_sql
    assert "p.recipient_state_code = :selected_state_code" not in combined_sql
    assert "s.subawardee_state_code = :selected_state_code" not in combined_sql


def test_search_allocation_mode_includes_statewide_contributors_for_selected_county() -> None:
    fake_db = _FakeSessionForSearch()
    payload = cdc_services.search_awards(
        fake_db,
        q="recipient",
        basis="prime",
        funding_geography_mode="statewide_allocation",
        assistance_type=None,
        fiscal_year=None,
        state=None,
        selected_county_fips="01001",
        page=1,
        page_size=25,
    )

    combined_sql = next(sql for sql in fake_db.sql_calls if "SELECT *" in sql and "FROM (" in sql)
    assert "cls.scope_classification = 'statewide'" in combined_sql
    assert "p.recipient_state_code = :selected_county_state_code" in combined_sql
    assert payload["funding_geography_mode"] == "statewide_allocation"


def test_top_awards_applies_filters_for_prime_state_query() -> None:
    fake_db = _FakeSessionForTop()
    payload = cdc_services.fetch_top_awards(
        fake_db,
        basis="prime",
        geography="state",
        geography_id="AL",
        metric="fy_obligated",
        assistance_type="Project Grants",
        fiscal_year=2026,
        awarding_office="Office A",
        funding_office="Office B",
        center="NCIRD",
        limit=5,
    )

    assert payload["basis"] == "prime"
    assert payload["geography"] == "state"
    assert payload["geography_id"] == "AL"
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["record_type"] == "prime_award"

    assert "tx.resolved_state_code = :geography_id" in fake_db.last_sql
    assert "tx.assistance_type_description = :assistance_type" in fake_db.last_sql
    assert "tx.action_date_fiscal_year = :fiscal_year" in fake_db.last_sql
    assert "tx.awarding_office_name = :awarding_office" in fake_db.last_sql
    assert "tx.funding_office_name = :funding_office" in fake_db.last_sql
    assert "tx.awarding_sub_agency_name = :center OR tx.funding_sub_agency_name = :center" in fake_db.last_sql


def test_top_awards_applies_appropriation_filter_for_prime_query() -> None:
    fake_db = _FakeSessionForTop()
    cdc_services.fetch_top_awards(
        fake_db,
        basis="prime",
        geography="state",
        geography_id="AL",
        metric="fy_obligated",
        appropriation_type="regular",
        fiscal_year=2026,
        limit=5,
    )

    assert "tx.appropriation_type = :appropriation_type" in fake_db.last_sql


def test_top_awards_county_allocation_mode_uses_statewide_contribution_logic() -> None:
    fake_db = _FakeSessionForTop()
    payload = cdc_services.fetch_top_awards(
        fake_db,
        basis="prime",
        geography="county",
        funding_geography_mode="statewide_allocation",
        geography_id="01001",
        metric="fy_obligated",
        assistance_type=None,
        fiscal_year=2026,
        limit=5,
    )

    assert payload["funding_geography_mode"] == "statewide_allocation"
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["includes_statewide_allocation"] is True
    assert "scope_classification = 'statewide'" in fake_db.last_sql
    assert "county_population_weight" in fake_db.last_sql
    assert "CAST(:county_population_weight AS numeric)" in fake_db.last_sql
    assert ":county_population_weight::numeric" not in fake_db.last_sql


def test_top_awards_county_allocation_mode_orders_by_aggregated_alias_for_outlay_metric() -> None:
    fake_db = _FakeSessionForTop()
    cdc_services.fetch_top_awards(
        fake_db,
        basis="prime",
        geography="county",
        funding_geography_mode="statewide_allocation",
        geography_id="01001",
        metric="fy_outlayed_estimated",
        fiscal_year=2026,
        limit=5,
    )

    assert "ORDER BY fy_outlayed_amount_estimated DESC NULLS LAST" in fake_db.last_sql
    assert "ORDER BY county_contribution_fy_outlayed_amount_estimated" not in fake_db.last_sql


def test_discover_source_files_detects_supported_csvs_and_filename_years(tmp_path) -> None:
    data_dir = tmp_path / "cdc"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "Assistance_PrimeTransactions_FY26_foo.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (data_dir / "Assistance_PrimeTransactions_2026-03-07_H19M32S44_1.csv").write_text(
        "a,b\n1,2\n",
        encoding="utf-8",
    )
    (data_dir / "Assistance_PrimeAwardSummaries_fiscal_year_2024_export.csv").write_text(
        "a,b\n1,2\n",
        encoding="utf-8",
    )
    (data_dir / "Assistance_Subawards_FY25_sample.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (data_dir / "Assistance_Subawards_FY25_sample.csv:Zone.Identifier").write_text(
        "[ZoneTransfer]",
        encoding="utf-8",
    )

    discovered = cdc_ingest.discover_source_files(data_dir)

    assert len(discovered["prime_award"]) == 1
    assert len(discovered["prime_transaction"]) == 2
    assert len(discovered["subaward"]) == 1
    by_name = {
        Path(item["path"]).name: item["filename_fiscal_years"]
        for item in discovered["prime_transaction"] + discovered["prime_award"] + discovered["subaward"]
    }
    assert by_name["Assistance_PrimeTransactions_FY26_foo.csv"] == [2026]
    assert by_name["Assistance_PrimeTransactions_2026-03-07_H19M32S44_1.csv"] == []
    assert by_name["Assistance_PrimeAwardSummaries_fiscal_year_2024_export.csv"] == [2024]
    assert by_name["Assistance_Subawards_FY25_sample.csv"] == [2025]


def test_read_prime_transactions_filters_fiscal_year_and_adds_source_metadata(tmp_path) -> None:
    tx_path = tmp_path / "Assistance_PrimeTransactions_FY26_unit.csv"
    with tx_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "assistance_transaction_unique_key",
                "assistance_award_unique_key",
                "action_date",
                "action_date_fiscal_year",
                "recipient_state_code",
                "prime_award_transaction_recipient_county_fips_code",
                "disaster_emergency_fund_codes_for_overall_award",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "assistance_transaction_unique_key": "TX-2025",
                "assistance_award_unique_key": "AWARD-1",
                "action_date": "2025-02-01",
                "action_date_fiscal_year": "2025",
                "recipient_state_code": "AL",
                "prime_award_transaction_recipient_county_fips_code": "1001",
                "disaster_emergency_fund_codes_for_overall_award": "Q: Not Designated Nonemergency/Emergency/Disaster/Wildfire Suppression",
            }
        )
        writer.writerow(
            {
                "assistance_transaction_unique_key": "TX-2026",
                "assistance_award_unique_key": "AWARD-1",
                "action_date": "2025-10-15",
                "action_date_fiscal_year": "2026",
                "recipient_state_code": "AL",
                "prime_award_transaction_recipient_county_fips_code": "1001",
                "disaster_emergency_fund_codes_for_overall_award": "N: Emergency P.L. 116-136",
            }
        )

    rows = cdc_ingest._read_prime_transaction_rows(
        tx_path,
        allowed_fiscal_years={2026},
        import_batch_id="batch-1",
        import_started_at=datetime(2026, 3, 7, 12, 0, 0),
        filename_fiscal_years={2026},
    )

    assert len(rows) == 1
    assert rows[0]["assistance_transaction_unique_key"] == "TX-2026"
    assert rows[0]["action_date_fiscal_year"] == 2026
    assert rows[0]["source_file_name"] == tx_path.name
    assert rows[0]["source_import_batch_id"] == "batch-1"
    assert rows[0]["source_imported_at"] == datetime(2026, 3, 7, 12, 0, 0)


def test_read_prime_transactions_infers_fiscal_year_from_action_date_when_column_missing(tmp_path) -> None:
    tx_path = tmp_path / "Assistance_PrimeTransactions_unit.csv"
    with tx_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "assistance_transaction_unique_key",
                "assistance_award_unique_key",
                "action_date",
                "recipient_state_code",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "assistance_transaction_unique_key": "TX-INFER",
                "assistance_award_unique_key": "AWARD-2",
                "action_date": "2024-10-01",
                "recipient_state_code": "GA",
            }
        )

    rows = cdc_ingest._read_prime_transaction_rows(tx_path)
    assert len(rows) == 1
    assert rows[0]["action_date_fiscal_year"] == 2025


def test_read_prime_transactions_fails_loudly_when_critical_column_missing(tmp_path) -> None:
    tx_path = tmp_path / "Assistance_PrimeTransactions_invalid.csv"
    with tx_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["assistance_award_unique_key", "action_date"],
        )
        writer.writeheader()
        writer.writerow({"assistance_award_unique_key": "AWARD-3", "action_date": "2025-01-01"})

    with pytest.raises(ValueError) as exc:
        cdc_ingest._read_prime_transaction_rows(tx_path)
    assert "missing required column" in str(exc.value).lower()
    assert "assistance_transaction_unique_key" in str(exc.value)


def test_read_subawards_emits_stable_unique_key_and_source_metadata(tmp_path) -> None:
    sub_path = tmp_path / "Assistance_Subawards_FY25_unit.csv"
    with sub_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "prime_award_unique_key",
                "prime_award_fain",
                "subaward_number",
                "subaward_amount",
                "subaward_action_date",
                "subaward_action_date_fiscal_year",
                "subawardee_name",
                "subawardee_state_code",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "prime_award_unique_key": "PA-1",
                "prime_award_fain": "FAIN-PA-1",
                "subaward_number": "SUB-1",
                "subaward_amount": "101.50",
                "subaward_action_date": "2025-04-01",
                "subaward_action_date_fiscal_year": "2025",
                "subawardee_name": "Example Subawardee",
                "subawardee_state_code": "AL",
            }
        )

    rows = cdc_ingest._read_subaward_rows(
        sub_path,
        import_batch_id="batch-2",
        import_started_at=datetime(2026, 3, 7, 12, 5, 0),
        filename_fiscal_years={2025},
    )
    assert len(rows) == 1
    assert rows[0]["subaward_unique_key"] == "PA-1|SUB-1|2025-04-01|Example Subawardee|101.50"
    assert rows[0]["source_file_name"] == sub_path.name
    assert rows[0]["source_import_batch_id"] == "batch-2"


def test_upsert_subawards_uses_stable_unique_key_conflict_constraint() -> None:
    connection = _CaptureConnection()
    cdc_ingest._upsert_subaward_rows(
        connection,
        rows=[
            {
                "prime_award_unique_key": "PA-1",
                "subaward_unique_key": "PA-1|SUB-1|2025-04-01|Example|10.00",
                "prime_award_fain": "FAIN-1",
                "subaward_number": "SUB-1",
                "subaward_amount": "10.00",
                "subaward_action_date": "2025-04-01",
                "subaward_action_date_fiscal_year": 2025,
                "subawardee_name": "Example",
                "subawardee_state_code": "AL",
                "subawardee_state_name": "Alabama",
                "subawardee_city_name": None,
                "subawardee_county_fips": "01001",
                "subaward_primary_place_of_performance_state_code": "AL",
                "subaward_primary_place_of_performance_state_name": "Alabama",
                "subaward_description": None,
                "prime_award_awarding_sub_agency_name": None,
                "prime_award_funding_sub_agency_name": None,
                "prime_award_awarding_office_name": None,
                "prime_award_funding_office_name": None,
                "prime_award_base_transaction_description": None,
                "usaspending_permalink": None,
                "prime_award_amount": "100.00",
                "prime_award_total_outlayed_amount": "50.00",
                "prime_award_disaster_emergency_fund_codes_raw": None,
                "appropriation_type": "regular",
                "appropriation_subtype": None,
                "appropriation_reason_code": "regular_not_designated",
                "appropriation_classification_source": "official_field",
                "appropriation_classifier_version": "v1_official_defc",
                "source_file_name": "Assistance_Subawards_FY25_unit.csv",
                "source_import_batch_id": "batch-3",
                "source_imported_at": datetime(2026, 3, 7, 12, 10, 0),
                "searchable_text": "Example",
                "raw": {"example": "value"},
            }
        ],
        chunk_size=1000,
    )
    sql_blob = "\n".join(connection.sqls)
    assert "ON CONFLICT ON CONSTRAINT uq_cdc_subawards_unique_key" in sql_blob


def test_normalize_requested_fiscal_years_merges_discrete_and_range() -> None:
    years = cdc_ingest._normalize_requested_fiscal_years(
        fiscal_years=[2026, 2024],
        fiscal_year_range=(2020, 2022),
    )
    assert years == {2020, 2021, 2022, 2024, 2026}
