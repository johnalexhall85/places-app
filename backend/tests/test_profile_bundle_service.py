from __future__ import annotations

from app.services import profile_bundle


class _DummySession:
    pass


def _stub_geo(level: str = "county") -> profile_bundle._ResolvedGeo:
    if level == "county":
        return profile_bundle._ResolvedGeo(
            geography="county",
            location_id="01001",
            county_fips="01001",
            tract_geoid=None,
            name="Autauga County",
            county_name="Autauga County",
            state_abbr="AL",
            state_name="Alabama",
            state_fips="01",
        )
    return profile_bundle._ResolvedGeo(
        geography="tract",
        location_id="01001020100",
        county_fips="01001",
        tract_geoid="01001020100",
        name="Census Tract 201",
        county_name="Autauga County",
        state_abbr="AL",
        state_name="Alabama",
        state_fips="01",
    )


def test_build_profile_bundle_includes_comparison_payloads(monkeypatch):
    monkeypatch.setattr(profile_bundle, "_resolve_county_geo", lambda _db, _id: _stub_geo("county"))
    monkeypatch.setattr(profile_bundle, "_resolve_places_snapshot", lambda _db, geography, location_id: (2023, "CrdPrv"))
    monkeypatch.setattr(profile_bundle, "_resolve_acs_snapshot", lambda _db, geography, location_id: ("2019-2023", "Percent"))
    monkeypatch.setattr(profile_bundle, "_resolve_svi_snapshot", lambda _db, geography, location_id: 2022)
    monkeypatch.setattr(
        profile_bundle,
        "_build_places_section",
        lambda _db, geo, places_year, places_data_value_type_id: {
            "year": places_year,
            "data_value_type_id": places_data_value_type_id,
            "measure_count": 2,
            "comparison_availability": {"state": True, "us": True},
            "top_concerns": [],
            "categories": [],
            "measures": [
                {
                    "measure_id": "M1",
                    "measure": "Measure 1",
                    "short_question_text": "Measure 1",
                    "unit": "%",
                    "local": {"value": 12.5},
                    "comparisons": {
                        "state": {"value": 10.0, "available": True},
                        "us": {"value": 9.0, "available": True},
                    },
                },
                {
                    "measure_id": "M2",
                    "measure": "Measure 2",
                    "short_question_text": "Measure 2",
                    "unit": "%",
                    "local": {"value": None},
                    "comparisons": {
                        "state": {"value": None, "available": False},
                        "us": {"value": None, "available": False},
                    },
                },
            ],
        },
    )
    monkeypatch.setattr(
        profile_bundle,
        "_build_acs_section",
        lambda _db, geo, year_window, data_value_type_id: {
            "year_window": year_window,
            "data_value_type_id": data_value_type_id,
            "factor_count": 1,
            "comparison_availability": {"state": True, "us": True},
            "top_context_tiles": [],
            "factors": [
                {
                    "measure_id": "A1",
                    "measure": "ACS Factor",
                    "unit": "%",
                    "local": {"value": 18.0},
                    "comparisons": {
                        "state": {"value": 16.0, "available": True},
                        "us": {"value": 14.0, "available": True},
                    },
                    "us_quintile": 5,
                }
            ],
        },
    )
    monkeypatch.setattr(
        profile_bundle,
        "_build_svi_section",
        lambda _db, geo, svi_year: {
            "year": svi_year,
            "available": True,
            "interpretation": "Higher percentile = higher vulnerability.",
            "overall": {"measure_id": "RPL_THEMES", "value": 0.84},
            "themes": [],
            "state_comparison_available": False,
        },
    )
    monkeypatch.setattr(
        profile_bundle,
        "_build_hpsa_section",
        lambda _db, geo: {"available": False, "domains": {}, "overlap_caveat": None},
    )

    payload = profile_bundle.build_profile_bundle(
        _DummySession(),
        geography="county",
        identifier="01001",
    )

    assert payload["geo"]["level"] == "county"
    assert payload["as_of"]["places_year"] == 2023
    assert payload["places"]["comparison_availability"]["state"] is True
    assert payload["places"]["comparison_availability"]["us"] is True
    assert payload["acs"]["comparison_availability"]["state"] is True
    assert payload["acs"]["comparison_availability"]["us"] is True
    assert payload["narrative"]["executive_summary"]["key_takeaways"]


def test_build_profile_bundle_handles_missing_comparisons(monkeypatch):
    monkeypatch.setattr(profile_bundle, "_resolve_county_geo", lambda _db, _id: _stub_geo("county"))
    monkeypatch.setattr(profile_bundle, "_resolve_places_snapshot", lambda _db, geography, location_id: (2023, "CrdPrv"))
    monkeypatch.setattr(profile_bundle, "_resolve_acs_snapshot", lambda _db, geography, location_id: ("2019-2023", "Percent"))
    monkeypatch.setattr(profile_bundle, "_resolve_svi_snapshot", lambda _db, geography, location_id: None)
    monkeypatch.setattr(
        profile_bundle,
        "_build_places_section",
        lambda _db, geo, places_year, places_data_value_type_id: {
            "year": places_year,
            "data_value_type_id": places_data_value_type_id,
            "measure_count": 1,
            "comparison_availability": {"state": False, "us": False},
            "top_concerns": [],
            "categories": [],
            "measures": [
                {
                    "measure_id": "M1",
                    "measure": "Measure 1",
                    "short_question_text": "Measure 1",
                    "unit": "%",
                    "local": {"value": None},
                    "comparisons": {
                        "state": {"value": None, "available": False},
                        "us": {"value": None, "available": False},
                    },
                }
            ],
        },
    )
    monkeypatch.setattr(
        profile_bundle,
        "_build_acs_section",
        lambda _db, geo, year_window, data_value_type_id: {
            "year_window": year_window,
            "data_value_type_id": data_value_type_id,
            "factor_count": 0,
            "comparison_availability": {"state": False, "us": False},
            "top_context_tiles": [],
            "factors": [],
        },
    )
    monkeypatch.setattr(
        profile_bundle,
        "_build_svi_section",
        lambda _db, geo, svi_year: {
            "year": None,
            "available": False,
            "interpretation": "Unavailable.",
            "overall": None,
            "themes": [],
            "state_comparison_available": False,
        },
    )
    monkeypatch.setattr(
        profile_bundle,
        "_build_hpsa_section",
        lambda _db, geo: {"available": False, "domains": {}, "overlap_caveat": None},
    )

    payload = profile_bundle.build_profile_bundle(
        _DummySession(),
        geography="county",
        identifier="01001",
    )

    assert payload["places"]["comparison_availability"]["state"] is False
    assert payload["places"]["comparison_availability"]["us"] is False
    assert isinstance(payload["narrative"]["executive_summary"]["how_factors_connect"], str)


def test_hpsa_section_for_tract_reports_not_available_message(monkeypatch):
    tract_geo = _stub_geo("tract")
    monkeypatch.setattr(profile_bundle, "fetch_county_hpsa_row", lambda _db, _fips: None)

    section = profile_bundle._build_hpsa_section(_DummySession(), geo=tract_geo)

    assert section["available"] is False
    assert section["not_available_message"] == (
        "HPSA designations are not available at the tract level in this report. "
        "County-level access metrics are shown in the county profile."
    )
