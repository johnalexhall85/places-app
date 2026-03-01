from __future__ import annotations

from datetime import date

from app.services.hpsa_summary import build_hpsa_response


def test_build_hpsa_response_snapshot():
    row = {
        "county_fips": "01001",
        "state_fips": "01",
        "pc_designated": True,
        "pc_hpsa_score_max": 15,
        "pc_population_covered": 58731,
        "pc_coverage_pct": 100.0,
        "mh_designated": False,
        "mh_hpsa_score_max": None,
        "mh_population_covered": None,
        "mh_coverage_pct": None,
        "dh_designated": False,
        "dh_hpsa_score_max": None,
        "dh_population_covered": None,
        "dh_coverage_pct": None,
        "raw_rows_in_county_pc": 1,
        "raw_rows_in_county_mh": None,
        "raw_rows_in_county_dh": None,
        "population_denominator_source": "dim_county_total_population",
        "coverage_overlap_caveat": (
            "HPSA designated populations may overlap across partial-county, population-group, and facility "
            "designations. Population covered is aggregated conservatively using MAX to reduce double counting; "
            "coverage_pct should be interpreted as an approximate upper-bound proxy for coverage within the county."
        ),
        "coverage_pct_definition": (
            "coverage_pct = (population_covered / population_denominator) * 100, clamped to 0–100; "
            "population_denominator uses adult 18+ when available, otherwise total population."
        ),
        "as_of_date": date(2026, 3, 1),
    }

    payload = build_hpsa_response(row, include_legacy=False)

    assert payload == {
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
            "calculation": (
                "coverage_pct = (population_covered / population_denominator) * 100, clamped to 0–100; "
                "population_denominator uses adult 18+ when available, otherwise total population."
            ),
            "caveats": [
                "HPSA designated populations may overlap across partial-county, population-group, and facility "
                "designations. Population covered is aggregated conservatively using MAX to reduce double counting; "
                "coverage_pct should be interpreted as an approximate upper-bound proxy for coverage within the county."
            ],
            "fields": {
                "pc_coverage_pct": (
                    "Percent of county population covered by a Primary Care HPSA designation "
                    "(conservative; overlaps possible)."
                ),
                "pc_population_covered": (
                    "Population covered by Primary Care designation; aggregated using MAX among active "
                    "designations in the county."
                ),
                "mh_coverage_pct": (
                    "Percent of county population covered by a Mental Health HPSA designation "
                    "(conservative; overlaps possible)."
                ),
                "mh_population_covered": (
                    "Population covered by Mental Health designation; aggregated using MAX among active "
                    "designations in the county."
                ),
                "dh_coverage_pct": (
                    "Percent of county population covered by a Dental Health HPSA designation "
                    "(conservative; overlaps possible)."
                ),
                "dh_population_covered": (
                    "Population covered by Dental Health designation; aggregated using MAX among active "
                    "designations in the county."
                ),
                "population_denominator_type": "Adult 18+ when available, otherwise total population.",
            },
        },
    }
