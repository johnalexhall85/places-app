from __future__ import annotations

from app.services.profile_builder import inject_hpsa_context


def test_inject_hpsa_context_sets_profile_methodology_and_dedupes_caveat():
    profile_json = {
        "schema_version": "1.1",
        "methods_caveats": ["Existing caveat"],
    }
    hpsa_payload = {
        "county_fips": "01001",
        "state_fips": "01",
        "primary_care": {
            "designated": True,
            "score_max": 15,
            "population_covered": 50000,
            "coverage_pct": 77.125,
            "raw_rows_in_county": 4,
        },
        "mental_health": {
            "designated": False,
            "score_max": None,
            "population_covered": None,
            "coverage_pct": None,
            "raw_rows_in_county": 1,
        },
        "dental": {
            "designated": True,
            "score_max": 11,
            "population_covered": 12000,
            "coverage_pct": 18.0,
            "raw_rows_in_county": 2,
        },
        "methodology": {
            "source": "HRSA HPSA Data Mart; denominator: acs_5yr_adult_18p",
            "as_of_date": "2026-03-01",
            "calculation": "coverage_pct = (population_covered / population_denominator) * 100",
            "caveats": [
                "HPSA designated populations may overlap across partial-county, population-group, and facility designations."
            ],
            "fields": {
                "pc_coverage_pct": "Percent of county population covered by a Primary Care HPSA designation (conservative; overlaps possible)."
            },
        },
    }

    inject_hpsa_context(profile_json, hpsa_payload)
    inject_hpsa_context(profile_json, hpsa_payload)

    assert "hpsa" in profile_json
    assert profile_json["hpsa"]["county_fips"] == "01001"
    assert profile_json["hpsa"]["primary_care"]["coverage_pct"] == 77.125

    assert profile_json["methodology"]["hpsa"]["source"].startswith("HRSA HPSA Data Mart")
    assert profile_json["methodology"]["hpsa"]["caveats"]

    caveat = hpsa_payload["methodology"]["caveats"][0]
    assert profile_json["methods_caveats"].count(caveat) == 1
