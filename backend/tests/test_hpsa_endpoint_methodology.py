from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.routers import hpsa as hpsa_router


class _DummySession:
    pass


def _override_db():
    yield _DummySession()


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
    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)

    try:
        response = client.get("/hpsa/counties/01001")
        assert response.status_code == 200
        payload = response.json()
        assert payload["county_fips"] == "01001"
        assert payload["primary_care"]["coverage_pct"] == 77.125
        assert payload["methodology"]["source"] == "HRSA HPSA Data Mart; denominator: acs_5yr_adult_18p"
        assert payload["methodology"]["caveats"]
        assert payload["methodology"]["caveats"][0].startswith("HPSA designated populations may overlap")
    finally:
        app.dependency_overrides.clear()
