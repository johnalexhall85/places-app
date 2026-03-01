from __future__ import annotations

from datetime import date, datetime, timezone
import math

from app.services.profile_builder import _sanitize_for_json, inject_hpsa_context


def test_sanitize_for_json_converts_date_and_datetime_recursively():
    payload = {
        "as_of_date": date(2026, 3, 1),
        "updated_at": datetime(2026, 3, 1, 12, 34, 56, tzinfo=timezone.utc),
        "nested": {
            "list_values": [date(2026, 2, 28), datetime(2026, 3, 1, 8, 0, 0)],
            "tuple_values": (date(2026, 1, 1),),
        },
        "bad_float": math.nan,
    }

    sanitized = _sanitize_for_json(payload)

    assert sanitized["as_of_date"] == "2026-03-01"
    assert sanitized["updated_at"] == "2026-03-01T12:34:56+00:00"
    assert sanitized["nested"]["list_values"][0] == "2026-02-28"
    assert sanitized["nested"]["list_values"][1] == "2026-03-01T08:00:00"
    assert sanitized["nested"]["tuple_values"][0] == "2026-01-01"
    assert sanitized["bad_float"] is None


def test_hpsa_methodology_as_of_date_is_string_after_sanitize():
    profile_json: dict[str, object] = {"methods_caveats": []}
    hpsa_payload = {
        "county_fips": "01001",
        "state_fips": "01",
        "primary_care": {
            "designated": True,
            "score_max": 15,
            "population_covered": 58731,
            "coverage_pct": 100.0,
            "raw_rows_in_county": 1,
        },
        "mental_health": {
            "designated": False,
            "score_max": None,
            "population_covered": None,
            "coverage_pct": None,
            "raw_rows_in_county": None,
        },
        "dental": {
            "designated": False,
            "score_max": None,
            "population_covered": None,
            "coverage_pct": None,
            "raw_rows_in_county": None,
        },
        "methodology": {
            "source": "HRSA HPSA Data Mart; denominator: dim_county_total_population",
            "as_of_date": date(2026, 3, 1),
            "calculation": "coverage_pct = (population_covered / population_denominator) * 100",
            "caveats": ["HPSA designated populations may overlap."],
            "fields": {},
        },
    }

    inject_hpsa_context(profile_json, hpsa_payload)
    sanitized = _sanitize_for_json(profile_json)

    assert sanitized["methodology"]["hpsa"]["as_of_date"] == "2026-03-01"
