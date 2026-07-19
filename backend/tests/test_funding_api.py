from __future__ import annotations

from decimal import Decimal

from app.main import app
from app.funding import router, services
from app.funding.classification import classify_funding_row
from app.funding.state_lookup import normalize_state


class _FakeResult:
    def __init__(self, rows=None, scalar_value=None):
        self._rows = rows or []
        self._scalar_value = scalar_value

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        if self._scalar_value is not None:
            return self._scalar_value
        if not self._rows:
            return None
        first = self._rows[0]
        if isinstance(first, dict):
            return next(iter(first.values()))
        return first[0]


class _FundingSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def execute(self, statement, params=None):
        sql = str(statement)
        bound = dict(params or {})
        self.calls.append((sql, bound))

        if "MAX(source_fiscal_year)" in sql:
            return _FakeResult(scalar_value=2026)
        if "SELECT DISTINCT source_fiscal_year" in sql:
            return _FakeResult([{"source_fiscal_year": 2026}, {"source_fiscal_year": 2025}])
        if "GROUP BY state_fips, state_code, state_name" in sql:
            return _FakeResult(
                [
                    {
                        "state_fips": "01",
                        "state_code": "AL",
                        "state_name": "Alabama",
                        "total_obligations": Decimal("100.25"),
                        "transaction_count": 3,
                        "award_count": 2,
                        "recipient_count": 2,
                        "likely_vfc_obligations": Decimal("10.00"),
                    }
                ]
            )
        if "assistance_listing_number" in sql and "SUM(transaction_count)" in sql:
            return _FakeResult(
                [
                    {
                        "assistance_listing_number": "93.940",
                        "assistance_listing_title": "HIV Prevention",
                        "total_obligations": Decimal("100.25"),
                        "transaction_count": 3,
                    }
                ]
            )
        if (
            "SUM(COALESCE(obligations_from_awards_with_supplemental_history" in sql
            and "funding_profiles_excluded_obligations" in sql
            and "GROUP BY" not in sql
        ):
            return _FakeResult(
                [
                    {
                        "obligations_from_awards_with_supplemental_history": Decimal("80.00"),
                        "likely_vfc_obligations": Decimal("10.00"),
                        "funding_profiles_excluded_obligations": Decimal("70.00"),
                        "covid_era_immunization_response_excluded_obligations": Decimal("7.00"),
                        "covid_era_immunization_response_excluded_transaction_count": 1,
                    }
                ]
            )
        if "covid_era_immunization_response_excluded_obligations" in sql and "FROM normalized_fact AS fact" in sql:
            return _FakeResult(
                [
                    {
                        "covid_era_immunization_response_excluded_obligations": Decimal("7.00"),
                        "covid_era_immunization_response_excluded_transaction_count": 1,
                    }
                ]
            )
        if "FROM normalized_fact AS fact" in sql and "GROUP BY fact.recipient_name" in sql:
            return _FakeResult(
                [
                    {
                        "recipient_name": "ALABAMA DEPARTMENT OF HEALTH",
                        "recipient_uei": "UEI",
                        "total_obligations": Decimal("100.25"),
                        "transaction_count": 3,
                        "award_count": 2,
                    }
                ]
            )
        if "state_unmapped_obligations" in sql:
            return _FakeResult(
                [
                    {
                        "state_unmapped_obligations": Decimal("25.50"),
                        "state_unmapped_transaction_count": 2,
                        "possible_global_or_foreign_obligations": Decimal("20.00"),
                        "possible_global_or_foreign_transaction_count": 1,
                    }
                ]
            )
        if "FROM normalized_fact AS fact" in sql and "LIMIT :limit OFFSET :offset" in sql:
            return _FakeResult(
                [
                    {
                        "source_fiscal_year": 2026,
                        "funding_mechanism": "grants_cooperative_agreements",
                        "award_unique_key": "AWARD-1",
                        "generated_unique_award_id": None,
                        "recipient_name": "ALABAMA DEPARTMENT OF HEALTH",
                        "recipient_uei": "UEI",
                        "federal_action_obligation": Decimal("100.25"),
                        "action_date": None,
                        "assistance_listing_number": "93.940",
                        "assistance_listing_title": "HIV Prevention",
                        "award_type_code": None,
                        "award_type_description": None,
                        "transaction_description": "Funding",
                        "prime_award_base_transaction_description": "Base",
                        "usaspending_permalink": "https://example.test",
                        "map_geography_source": "recipient_fallback",
                        "normalized_state_fips": "01",
                        "normalized_state_code": "AL",
                        "normalized_state_name": "Alabama",
                        "map_county_fips": "01001",
                        "map_county_name": "Autauga",
                        "is_covid_or_emergency_supplemental": False,
                        "covid_supplemental_obligated_amount": Decimal("0"),
                        "iija_supplemental_obligated_amount": Decimal("0"),
                        "defc_codes": ["Q", "N"],
                        "defc_classification": "mixed_regular_and_supplemental_award",
                        "has_overall_award_supplemental_history": True,
                        "is_likely_vfc": False,
                        "is_covid_era_immunization_response": False,
                        "is_profile_aligned_emergency_supplemental": False,
                        "funding_profiles_comparison_excluded": False,
                        "funding_profiles_exclusion_reason": "defc_mixed_supplemental_history",
                    }
                ]
            )
        if "SELECT COUNT(*)::bigint" in sql and "normalized_fact" in sql:
            return _FakeResult(scalar_value=1)
        if "raw_usaspending_" in sql:
            return _FakeResult([{"source_fiscal_year": 2026, "source_file_type": bound["file_type"], "row_count": 1}])
        if "source_fiscal_year, funding_mechanism, COUNT(*)" in sql:
            return _FakeResult([{"source_fiscal_year": 2026, "funding_mechanism": "grants_cooperative_agreements", "row_count": 1}])
        if "is_positive_obligation AS bucket" in sql:
            return _FakeResult([{"bucket": True, "row_count": 1}])
        if "is_cdc_funded AS bucket" in sql:
            return _FakeResult([{"bucket": True, "row_count": 1}])
        if "map_geography_source" in sql and "COUNT(*)" in sql:
            return _FakeResult([{"map_geography_source": "place_of_performance", "row_count": 1}])
        if "state_identifiable" in sql:
            return _FakeResult([{"state_identifiable": True, "row_count": 1}])
        if "is_covid_or_emergency_supplemental AS bucket" in sql:
            return _FakeResult([{"bucket": False, "row_count": 1}])
        if "is_default_map_eligible AS bucket" in sql:
            return _FakeResult([{"bucket": True, "row_count": 1}])
        if "funding_view_mode_totals_by_year" in sql or "standard_usaspending_state_total" in sql:
            return _FakeResult(
                [
                    {
                        "source_fiscal_year": 2026,
                        "standard_usaspending_state_total": Decimal("100.25"),
                        "funding_profiles_comparable_state_total": Decimal("90.25"),
                        "likely_vfc_amount": Decimal("5"),
                        "covid_era_immunization_response_amount": Decimal("7"),
                        "covid_era_immunization_response_transaction_count": 1,
                        "funding_profiles_comparison_excluded_amount": Decimal("10"),
                        "amount_from_awards_with_overall_supplemental_history": Decimal("20"),
                    }
                ]
            )
        if "defc_classification_totals_by_year" in sql or "COALESCE(defc_classification" in sql:
            return _FakeResult(
                [
                    {
                        "source_fiscal_year": 2026,
                        "defc_classification": "mixed_regular_and_supplemental_award",
                        "total_obligations": Decimal("20"),
                        "transaction_count": 1,
                    }
                ]
            )
        return _FakeResult([])


def test_state_lookup_normalizes_fips_and_postal_codes() -> None:
    assert normalize_state("1").state_fips == "01"
    assert normalize_state("AL").state_name == "Alabama"
    assert normalize_state("zz") is None


def test_state_funding_routes_are_registered_with_api_alias() -> None:
    route_paths = {route.path for route in app.routes}

    assert "/funding/filters" in route_paths
    assert "/funding/map/state" in route_paths
    assert "/funding/summary" in route_paths
    assert "/api/funding/filters" in route_paths
    assert "/api/funding/map/state" in route_paths
    assert "/api/funding/summary" in route_paths


def test_filters_default_values() -> None:
    payload = services.fetch_filters(_FundingSession())

    assert payload["default_geography_level"] == "state"
    assert payload["available_geography_levels"] == ["state", "county_future"]
    assert payload["default_fiscal_year"] == 2026
    assert payload["default_funding_mechanism"] == "grants_cooperative_agreements"
    assert payload["default_funding_view_mode"] == "standard_usaspending"
    assert payload["funding_view_modes"][0]["value"] == "standard_usaspending"
    assert payload["default_include_supplemental"] is False
    assert payload["states"][0]["state_fips"] == "01"


def test_state_map_standard_usaspending_does_not_exclude_supplemental_history() -> None:
    db = _FundingSession()
    payload = services.fetch_state_map(db)

    assert payload["geography_level"] == "state"
    assert payload["funding_view_mode"] == "standard_usaspending"
    assert payload["filters"]["fiscal_years"] == [2026]
    assert payload["summary"]["total_obligations"] == 100.25
    assert payload["summary"]["state_mapped_obligations"] == 100.25
    assert payload["summary"]["state_unmapped_obligations"] == 25.5
    assert payload["summary"]["total_obligations_including_unmapped"] == 125.75
    assert not any("is_covid_or_emergency_supplemental IS FALSE" in sql for sql, _params in db.calls)
    assert not any("funding_profiles_comparison_excluded" in sql for sql, _params in db.calls)


def test_state_map_funding_profiles_comparable_excludes_comparison_flag() -> None:
    db = _FundingSession()
    services.fetch_state_map(db, funding_view_mode="funding_profiles_comparable")

    assert any("funding_profiles_comparison_excluded" in sql for sql, _params in db.calls)


def test_supplemental_history_filter_applies_within_view_mode() -> None:
    db = _FundingSession()
    services.fetch_state_map(db, supplemental_history_filter="only_awards_with_supplemental_history")

    assert any("has_overall_award_supplemental_history" in sql for sql, _params in db.calls)


def test_fiscal_year_comma_parsing_and_mechanism_all() -> None:
    db = _FundingSession()
    payload = services.fetch_state_map(db, fiscal_year="2025,2026", funding_mechanism="all")

    assert payload["filters"]["fiscal_years"] == [2025, 2026]
    assert not any("funding_mechanism = :funding_mechanism" in sql for sql, _params in db.calls)


def test_state_filter_by_postal_and_fips() -> None:
    postal_db = _FundingSession()
    fips_db = _FundingSession()
    services.fetch_state_map(postal_db, state="AL")
    services.fetch_state_map(fips_db, state="01")

    assert any(params.get("state_fips") == "01" for _sql, params in postal_db.calls)
    assert any(params.get("state_fips") == "01" for _sql, params in fips_db.calls)


def test_assistance_listing_number_filter() -> None:
    db = _FundingSession()
    payload = services.fetch_state_map(db, assistance_listing_number="93.940")

    assert payload["filters"]["assistance_listing_number"] == "93.940"
    assert any(params.get("assistance_listing_number") == "93.940" for _sql, params in db.calls)


def test_state_awards_pagination_and_county_fips() -> None:
    payload = services.fetch_state_awards(_FundingSession(), "01", limit=10, offset=5)

    assert payload["limit"] == 10
    assert payload["offset"] == 5
    assert payload["total_count"] == 1
    assert payload["rows"][0]["normalized_state_code"] == "AL"
    assert payload["rows"][0]["map_county_fips"] == "01001"
    assert payload["rows"][0]["has_overall_award_supplemental_history"] is True


def test_summary_response_shape() -> None:
    payload = services.fetch_summary(_FundingSession())

    assert payload["geography_level"] == "state"
    assert payload["top_states"]
    assert payload["top_assistance_listings"]
    assert payload["top_recipients"]
    assert payload["state_mapped_obligations"] == 100.25
    assert payload["total_obligations_including_unmapped"] == 125.75
    assert payload["vfc_immunization_cooperative_agreement_obligations"] == 10.0
    assert payload["vaccine_purchase_obligations"] is None
    assert payload["funding_profiles_excluded_obligations"] == 70.0
    assert payload["covid_era_immunization_response_excluded_obligations"] == 7.0
    assert payload["covid_era_immunization_response_excluded_transaction_count"] == 1
    assert payload["likely_vfc_obligations"] == 10.0
    assert payload["obligations_from_awards_with_supplemental_history"] == 80.0
    assert payload["state_unmapped_obligations"] == 25.5
    assert payload["state_unmapped_transaction_count"] == 2
    assert payload["possible_global_or_foreign_obligations"] == 20.0
    assert payload["possible_global_or_foreign_transaction_count"] == 1


def test_comparable_summary_total_includes_unmapped_separately_from_state_map_rows() -> None:
    payload = services.fetch_summary(_FundingSession(), funding_view_mode="funding_profiles_comparable")

    assert payload["state_mapped_obligations"] == 100.25
    assert payload["state_unmapped_obligations"] == 25.5
    assert payload["total_obligations"] == 125.75
    assert payload["total_obligations_including_unmapped"] == 125.75
    assert payload["top_states"][0]["total_obligations"] == 100.25


def test_validation_response_shape() -> None:
    payload = services.fetch_validation(_FundingSession())

    assert "raw_row_counts" in payload
    assert "canonical_row_counts" in payload
    assert "state_aggregate_row_counts" in payload
    assert "county_aggregate_row_counts" in payload
    assert "funding_view_mode_totals_by_year" in payload
    assert "defc_classification_totals_by_year" in payload


def test_router_passes_awards_pagination(monkeypatch) -> None:
    captured = {}

    def _fake_fetch(_db, state, **kwargs):
        captured["state"] = state
        captured.update(kwargs)
        return {"rows": []}

    monkeypatch.setattr(router.services, "fetch_state_awards", _fake_fetch)
    router.get_state_awards("AL", fiscal_year="2026", limit=25, offset=50, db=object())

    assert captured["state"] == "AL"
    assert captured["limit"] == 25
    assert captured["offset"] == 50


def test_classification_parses_defc_and_vfc_and_profile_exclusion() -> None:
    payload = classify_funding_row(
        {
            "disaster_emergency_fund_codes_for_overall_award": "Q: Not Designated; N: Emergency P.L. 116-136",
            "cfda_number": "93.268",
            "cfda_title": "Immunization Cooperative Agreements",
            "transaction_description": "Vaccines for Children support",
            "obligated_amount_from_COVID-19_supplementals_for_overall_award": "10",
        }
    )

    assert payload["defc_codes"] == ["Q", "N"]
    assert payload["defc_classification"] == "mixed_regular_and_supplemental_award"
    assert payload["has_defc_covid"] is True
    assert payload["is_likely_vfc"] is True
    assert payload["has_overall_award_supplemental_history"] is True
    assert payload["funding_profiles_comparison_excluded"] is False
    assert "likely_vfc" not in payload["funding_profiles_exclusion_reason"]
    assert "overall_award_covid_supplemental_amount" in payload["funding_profiles_exclusion_reason"]


def test_classification_flags_fy2021_covid_era_immunization_response() -> None:
    payload = classify_funding_row(
        {
            "source_fiscal_year": 2021,
            "funding_mechanism": "grants_cooperative_agreements",
            "cfda_number": "93.268",
            "cfda_title": "Immunization Cooperative Agreements",
            "transaction_description": "COVID-19 vaccine implementation supplemental support",
            "obligated_amount_from_COVID-19_supplementals_for_overall_award": "10",
            "disaster_emergency_fund_codes_for_overall_award": "Q: Not Designated; V: Non-emergency P.L. 117-2",
        }
    )

    assert payload["is_likely_vfc"] is True
    assert payload["is_covid_era_immunization_response"] is True
    assert payload["funding_profiles_comparison_excluded"] is True
    assert "fy2021_covid_era_immunization_response" in payload["funding_profiles_exclusion_reason"]


def test_classification_keeps_vfc_immunization_without_comparable_exclusion() -> None:
    payload = classify_funding_row(
        {
            "cfda_number": "93.268",
            "cfda_title": "Immunization Cooperative Agreements",
            "transaction_description": "Routine immunization cooperative agreement",
        }
    )

    assert payload["is_likely_vfc"] is True
    assert payload["is_covid_era_immunization_response"] is False
    assert payload["funding_profiles_comparison_excluded"] is False
    assert payload["funding_profiles_exclusion_reason"] is None


def test_classification_keeps_fy2023_vfc_immunization_with_covid_history() -> None:
    payload = classify_funding_row(
        {
            "source_fiscal_year": 2023,
            "funding_mechanism": "grants_cooperative_agreements",
            "cfda_number": "93.268",
            "cfda_title": "Immunization Cooperative Agreements",
            "transaction_description": "Vaccines for Children support",
            "obligated_amount_from_COVID-19_supplementals_for_overall_award": "10",
        }
    )

    assert payload["is_likely_vfc"] is True
    assert payload["is_covid_era_immunization_response"] is False
    assert payload["funding_profiles_comparison_excluded"] is False


def test_classification_excludes_non_vfc_overall_award_covid_amount() -> None:
    payload = classify_funding_row(
        {
            "cfda_number": "93.940",
            "cfda_title": "HIV Prevention Activities Health Department Based",
            "transaction_description": "HIV prevention funding",
            "obligated_amount_from_COVID-19_supplementals_for_overall_award": "10",
        }
    )

    assert payload["is_likely_vfc"] is False
    assert payload["has_overall_award_supplemental_history"] is True
    assert payload["funding_profiles_comparison_excluded"] is True
    assert payload["funding_profiles_exclusion_reason"] == "overall_award_covid_supplemental_amount"


def test_profile_aligned_emergency_does_not_trigger_on_phep_emergency_word_only() -> None:
    payload = classify_funding_row(
        {
            "cfda_number": "93.069",
            "cfda_title": "Public Health Emergency Preparedness",
            "transaction_description": "Public Health Emergency Preparedness Cooperative Agreement",
        }
    )

    assert payload["is_profile_aligned_emergency_supplemental"] is False
    assert payload["funding_profiles_comparison_excluded"] is False
