from __future__ import annotations

from app.schemas.map_context import MapContext
from app.services import assistant_context_summary as summary_service


class _DummySession:
    pass


def test_hpsa_primary_care_summary_includes_required_stats_and_copy(monkeypatch):
    monkeypatch.setattr(
        summary_service,
        "fetch_county_hpsa_row",
        lambda _db, _county_fips: {
            "county_fips": "01001",
            "state_fips": "01",
            "pc_designated": True,
            "pc_hpsa_score_max": 18,
            "pc_population_covered": 40210,
            "pc_coverage_pct": 76.4,
            "coverage_overlap_caveat": "Exact caveat from methodology.",
            "coverage_pct_definition": "coverage formula",
            "population_denominator_source": "acs_5yr_adult_18p",
            "as_of_date": "2026-03-01",
        },
    )
    monkeypatch.setattr(
        summary_service,
        "fetch_hpsa_domain_quartiles",
        lambda _db, _domain: {
            "q25": 10,
            "q50": 15,
            "q75": 20,
            "n_counties": 100,
            "as_of_date": "2026-03-01",
        },
    )
    monkeypatch.setattr(
        summary_service,
        "fetch_hpsa_domain_ratio_fields",
        lambda _db, county_fips, domain: {
            "hpsa_formal_ratio": "3500:1",
            "provider_ratio_goal": "3000:1",
            "fte": 2.5,
        },
    )
    monkeypatch.setattr(
        summary_service,
        "_lookup_county_identity",
        lambda _db, _county_fips: {
            "county_fips": "01001",
            "county_name": "Etowah County",
            "state_abbr": "AL",
        },
    )

    map_context = MapContext(
        dataSource="HPSA",
        geoLevel="county",
        selectedArea={
            "countyFips": "01001",
            "name": "Etowah County",
            "stateAbbr": "AL",
        },
        selection={"hpsaDomain": "pc"},
    )
    payload = summary_service.build_context_summary(map_context, _DummySession())

    assert payload is not None
    assert payload["title"].startswith("Primary Care Provider Shortage")
    assert "This county is designated as a Primary Care Health Professional Shortage Area." in payload["bullets"]
    assert "Severity is based on quartiles among designated counties." in payload["bullets"]
    assert "Higher HPSA scores indicate greater provider shortage severity." in payload["bullets"]
    assert "Exact caveat from methodology." in payload["bullets"]

    stats_by_label = {
        stat["label"]: stat["value"]
        for stat in payload["stats"]
    }
    assert stats_by_label["Score"] == "18"
    assert stats_by_label["Tier"] == "3"


def test_hpsa_domain_switch_changes_label_and_domain_fields(monkeypatch):
    monkeypatch.setattr(
        summary_service,
        "fetch_county_hpsa_row",
        lambda _db, _county_fips: {
            "county_fips": "01001",
            "state_fips": "01",
            "mh_designated": True,
            "mh_hpsa_score_max": 7,
            "mh_population_covered": 11111,
            "mh_coverage_pct": 25.0,
            "dh_designated": True,
            "dh_hpsa_score_max": 13,
            "dh_population_covered": 22222,
            "dh_coverage_pct": 50.0,
            "coverage_overlap_caveat": "Domain caveat line.",
            "coverage_pct_definition": "coverage formula",
            "population_denominator_source": "acs_5yr_adult_18p",
            "as_of_date": "2026-03-01",
        },
    )
    monkeypatch.setattr(
        summary_service,
        "fetch_hpsa_domain_quartiles",
        lambda _db, _domain: {
            "q25": 4,
            "q50": 8,
            "q75": 12,
            "n_counties": 100,
            "as_of_date": "2026-03-01",
        },
    )
    monkeypatch.setattr(
        summary_service,
        "fetch_hpsa_domain_ratio_fields",
        lambda _db, county_fips, domain: {
            "hpsa_formal_ratio": "3000:1",
            "provider_ratio_goal": None,
            "fte": None,
        },
    )
    monkeypatch.setattr(
        summary_service,
        "_lookup_county_identity",
        lambda _db, _county_fips: {
            "county_fips": "01001",
            "county_name": "Etowah County",
            "state_abbr": "AL",
        },
    )

    mh_context = MapContext(
        dataSource="HPSA",
        geoLevel="county",
        selectedArea={"countyFips": "01001", "name": "Etowah County", "stateAbbr": "AL"},
        selection={"hpsaDomain": "mh"},
    )
    mh_payload = summary_service.build_context_summary(mh_context, _DummySession())
    assert mh_payload is not None
    assert mh_payload["title"].startswith("Mental Health Provider Shortage")
    mh_stats = {row["label"]: row["value"] for row in mh_payload["stats"]}
    assert mh_stats["Score"] == "7"

    dh_context = MapContext(
        dataSource="HPSA",
        geoLevel="county",
        selectedArea={"countyFips": "01001", "name": "Etowah County", "stateAbbr": "AL"},
        selection={"hpsaDomain": "dh"},
    )
    dh_payload = summary_service.build_context_summary(dh_context, _DummySession())
    assert dh_payload is not None
    assert dh_payload["title"].startswith("Dental Provider Shortage")
    dh_stats = {row["label"]: row["value"] for row in dh_payload["stats"]}
    assert dh_stats["Score"] == "13"


def test_places_summary_regression_path_remains_available(monkeypatch):
    monkeypatch.setattr(
        summary_service,
        "_lookup_county_identity",
        lambda _db, _county_fips: {
            "county_fips": "01001",
            "county_name": "Autauga County",
            "state_abbr": "AL",
        },
    )
    monkeypatch.setattr(
        summary_service,
        "_lookup_places_measure_name",
        lambda _db, _measure_id: "Current asthma among adults",
    )
    monkeypatch.setattr(
        summary_service,
        "get_estimate_county",
        lambda _db, county_fips, measure_id, year, data_value_type_id: {
            "found": True,
            "value": 12.4,
            "ci_low": 11.1,
            "ci_high": 13.8,
        },
    )
    monkeypatch.setattr(
        summary_service,
        "get_estimate_state",
        lambda _db, state_abbr, measure_id, year, data_value_type_id: {
            "found": True,
            "value": 10.3,
            "ci_low": 9.9,
            "ci_high": 10.7,
        },
    )
    monkeypatch.setattr(
        summary_service,
        "get_estimate_nation",
        lambda _db, measure_id, year, data_value_type_id: {
            "found": True,
            "value": 9.8,
            "ci_low": 9.5,
            "ci_high": 10.0,
        },
    )

    map_context = MapContext(
        dataSource="PLACES",
        geoLevel="county",
        selectedArea={"countyFips": "01001", "name": "Autauga County", "stateAbbr": "AL"},
        selection={
            "placesMeasureId": "CASTHMA",
            "placesYear": 2023,
            "placesValueTypeId": "CrdPrv",
        },
    )
    payload = summary_service.build_context_summary(map_context, _DummySession())

    assert payload is not None
    assert payload["dataSource"] == "PLACES"
    stats_by_label = {row["label"]: row["value"] for row in payload["stats"]}
    assert "12.4%" in stats_by_label["County"]
    assert stats_by_label["Year"] == "2023"


def test_missing_context_returns_none_for_fallback():
    map_context = MapContext(
        dataSource="HPSA",
        geoLevel="county",
        selectedArea={},
        selection={"hpsaDomain": "pc"},
    )
    payload = summary_service.build_context_summary(map_context, _DummySession())
    assert payload is None
