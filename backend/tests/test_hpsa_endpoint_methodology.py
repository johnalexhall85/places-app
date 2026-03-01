from __future__ import annotations

from datetime import date, datetime, timezone

from app.routers import hpsa as hpsa_router


class _DummySession:
    pass


def test_hpsa_endpoint_includes_structured_methodology(monkeypatch):
    row = {
        "county_fips": "01001",
        "state_fips": "01",
        "pc_designated": True,
        "pc_hpsa_score_max": 15,
        "pc_population_covered": 50000,
        "pc_coverage_pct": 77.125,
        "mh_designated": False,
        "mh_hpsa_score_max": None,
        "mh_population_covered": None,
        "mh_coverage_pct": None,
        "dh_designated": True,
        "dh_hpsa_score_max": 11,
        "dh_population_covered": 12000,
        "dh_coverage_pct": 18.0,
        "population_denominator_type": "adult_18p",
        "population_denominator": 64832,
        "population_denominator_source": "acs_5yr_adult_18p",
        "coverage_population_aggregation_method": "MAX",
        "coverage_overlap_caveat": (
            "HPSA designated populations may overlap across partial-county, population-group, and "
            "facility designations. Population covered is aggregated conservatively using MAX to "
            "reduce double counting; coverage_pct should be interpreted as an approximate upper-bound "
            "proxy for coverage within the county."
        ),
        "coverage_pct_definition": (
            "coverage_pct = (population_covered / population_denominator) * 100, clamped to 0–100; "
            "population_denominator uses adult 18+ when available, otherwise total population."
        ),
        "pc_coverage_method": "MAX designated population among active designations in county (conservative; overlaps possible)",
        "mh_coverage_method": "MAX designated population among active designations in county (conservative; overlaps possible)",
        "dh_coverage_method": "MAX designated population among active designations in county (conservative; overlaps possible)",
        "raw_rows_in_county_pc": 4,
        "raw_rows_in_county_mh": 1,
        "raw_rows_in_county_dh": 2,
        "as_of_date": date(2026, 3, 1),
        "updated_at": datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    }

    monkeypatch.setattr(hpsa_router, "fetch_county_hpsa_row", lambda _db, _fips: row)
    payload = hpsa_router.get_county_hpsa_summary("01001", db=_DummySession())
    assert payload["county_fips"] == "01001"
    assert payload["primary_care"]["coverage_pct"] == 77.125
    assert payload["methodology"]["source"] == "HRSA HPSA Data Mart; denominator: acs_5yr_adult_18p"
    assert payload["methodology"]["caveats"]
    assert payload["methodology"]["caveats"][0].startswith("HPSA designated populations may overlap")


def test_hpsa_endpoint_domain_detail_includes_tier_and_ratio_fields(monkeypatch):
    row = {
        "county_fips": "01001",
        "state_fips": "01",
        "pc_designated": True,
        "pc_hpsa_score_max": 15,
        "pc_population_covered": 50000,
        "pc_coverage_pct": 77.125,
        "mh_designated": False,
        "mh_hpsa_score_max": None,
        "mh_population_covered": None,
        "mh_coverage_pct": None,
        "dh_designated": False,
        "dh_hpsa_score_max": None,
        "dh_population_covered": None,
        "dh_coverage_pct": None,
        "population_denominator_source": "dim_county_total_pop_18_plus",
        "coverage_overlap_caveat": "Coverage may overlap across designations.",
        "coverage_pct_definition": "coverage_pct = (population_covered / population_denominator) * 100",
        "as_of_date": date(2026, 3, 1),
    }

    monkeypatch.setattr(hpsa_router, "fetch_county_hpsa_row", lambda _db, _fips: row)
    monkeypatch.setattr(
        hpsa_router,
        "fetch_hpsa_domain_quartiles",
        lambda _db, _domain: {
            "q25": 10,
            "q50": 15,
            "q75": 20,
            "n_counties": 100,
            "as_of_date": date(2026, 3, 1),
        },
    )
    monkeypatch.setattr(
        hpsa_router,
        "fetch_hpsa_domain_ratio_fields",
        lambda _db, county_fips, domain: {
            "hpsa_formal_ratio": "3500:1",
            "provider_ratio_goal": "3000:1",
            "fte": 2.5,
        },
    )
    payload = hpsa_router.get_county_hpsa_summary("01001", domain="pc", db=_DummySession())
    assert payload["county_fips"] == "01001"
    assert payload["domain"] == "pc"
    assert payload["score_max"] == 15
    assert payload["tier"] == 2
    assert payload["hpsa_formal_ratio"] == "3500:1"
    assert payload["provider_ratio_goal"] == "3000:1"
    assert payload["fte"] == 2.5
    assert payload["methodology"]["source"].startswith("HRSA HPSA Data Mart")
