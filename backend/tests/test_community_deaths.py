"""Unit and read-only PostGIS staging tests for /community/{county,state}/{geoid}/deaths."""
from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.area_pilot import lookup
from app.community.router import router
from app.db import SessionLocal, get_db
from app.demo_access.middleware import _is_public_path


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)

    def scalar_one(self):
        return self.rows


class FakeDb:
    """Fake SQLAlchemy session serving area_pilot boundary, release, and mortality observation tables."""

    def __init__(self, *, areas=None, hds_rows=None, cancer_rows=None, drug_rows=None, releases=None):
        self.areas = areas or []
        self.tables = {
            "observation_cdc_hds_mortality": hds_rows or [],
            "observation_nci_cancer_mortality": cancer_rows or [],
            "observation_nchs_drug_poisoning": drug_rows or [],
        }
        self.releases = releases

    def execute(self, statement, params=None):
        sql = str(statement)
        params = params or {}
        if "active_release" in sql:
            if self.releases is not None:
                return FakeResult(self.releases)
            return FakeResult([
                {
                    "dataset_id": spec.load()["dataset_id"],
                    "id": f"rel-{spec.key}",
                    "source_release_id": spec.load().get("source_release_id") or f"label-{spec.key}",
                    "published_at": None,
                }
                for spec in lookup.SPECS
                if spec.key in {"cdc_hds_mortality", "nci_cancer_mortality", "nchs_drug_poisoning"}
            ])
        if "acs_boundary_2024" in sql and "ST_XMin" in sql:
            level = params.get("level")
            geoids = set(params.get("geoids") or [])
            return FakeResult([
                row for row in self.areas if row["level"] == level and row["geoid"] in geoids
            ])
        for table_name, rows in self.tables.items():
            if f"area_pilot.{table_name}" in sql:
                if "geo_level='national'" in sql:
                    return FakeResult([
                        row for row in rows if row.get("geo_level") == "national" and row["geoid"] == "US"
                    ])
                level = params.get("level")
                geoids = set(params.get("geoids") or [])
                return FakeResult([
                    row
                    for row in rows
                    if row["geoid"] in geoids and (level is None or row.get("geo_level", level) == level)
                ])
        return FakeResult([])


def _area_row(level: str, geoid: str, name: str, state_name: str) -> dict:
    return {
        "level": level,
        "geoid": geoid,
        "name": name,
        "state_name": state_name,
        "county_name": name if level == "county" else None,
        "west": -79.0,
        "south": 35.9,
        "east": -78.7,
        "north": 36.2,
        "lon": -78.9,
        "lat": 36.0,
    }


def _spec_config_and_measures(spec_key: str) -> tuple[dict, dict[str, dict]]:
    spec = next(s for s in lookup.SPECS if s.key == spec_key)
    config = spec.load()
    measures = {m["measure_id"]: lookup._measure_meta(spec, config, m) for m in config["measures"]}
    return config, measures


def _hds_obs(level: str, geoid: str, measure_id: str, value: Decimal | None,
             status: str = "available", source_value: str | None = None) -> dict:
    config, measures = _spec_config_and_measures("cdc_hds_mortality")
    meta = measures[measure_id]
    return {
        "geo_level": level,
        "geoid": geoid,
        "measure_id": measure_id,
        "observation_period": meta["period"],
        "population": meta["population"],
        "value_type": config["value_type_by_level"][level],
        "value": value,
        "status": status,
        "source_value": source_value if source_value is not None else (str(value) if value is not None else ""),
    }


def _cancer_obs(level: str, geoid: str, measure_id: str, value: Decimal | None,
                ci_low: Decimal | None = None, ci_high: Decimal | None = None,
                status: str = "available", source_value: str | None = None) -> dict:
    _, measures = _spec_config_and_measures("nci_cancer_mortality")
    meta = measures[measure_id]
    return {
        "geo_level": level,
        "geoid": geoid,
        "measure_id": measure_id,
        "observation_period": meta["period"],
        "population": meta["population"],
        "value_type": meta["value_type"],
        "value": value,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "status": status,
        "source_value": source_value if source_value is not None else (str(value) if value is not None else "*"),
    }


def _drug_obs(geoid: str, value: Decimal | None, ci_low: Decimal | None = None,
              ci_high: Decimal | None = None, status: str = "available",
              source_value: str | None = None) -> dict:
    _, measures = _spec_config_and_measures("nchs_drug_poisoning")
    meta = measures["drug_poisoning_death_rate"]
    return {
        "geo_level": "county",
        "geoid": geoid,
        "measure_id": "drug_poisoning_death_rate",
        "observation_period": meta["period"],
        "population": meta["population"],
        "value_type": meta["value_type"],
        "value": value,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "status": status,
        "source_value": source_value if source_value is not None else (str(value) if value is not None else ""),
    }


def _make_client(db) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_county_deaths_shape_order_and_references():
    geoid = "37063"
    state_geoid = "37"
    hds_rows = [
        _hds_obs("county", geoid, "heart_disease_death_rate", Decimal("227.2")),
        _hds_obs("county", geoid, "stroke_death_rate", Decimal("71.2")),
        _hds_obs("state", state_geoid, "heart_disease_death_rate", Decimal("305.4")),
        _hds_obs("state", state_geoid, "stroke_death_rate", Decimal("84.6")),
        _hds_obs("national", "US", "heart_disease_death_rate", Decimal("315.3")),
        _hds_obs("national", "US", "stroke_death_rate", Decimal("75.9")),
    ]
    cancer_rows = [
        _cancer_obs("county", geoid, "cancer_death_rate_all", Decimal("132.6"), Decimal("127.2"), Decimal("138.2")),
        _cancer_obs("county", geoid, "cancer_death_rate_lung", Decimal("25.1"), Decimal("22.8"), Decimal("27.5")),
        _cancer_obs("county", geoid, "cancer_death_rate_colorectal", Decimal("11.8"), Decimal("10.2"), Decimal("13.5")),
        _cancer_obs("state", state_geoid, "cancer_death_rate_all", Decimal("147.8"), Decimal("146.9"), Decimal("148.8")),
        _cancer_obs("state", state_geoid, "cancer_death_rate_lung", Decimal("35.1"), Decimal("34.6"), Decimal("35.6")),
        _cancer_obs("state", state_geoid, "cancer_death_rate_colorectal", Decimal("12.4"), Decimal("12.1"), Decimal("12.7")),
        _cancer_obs("national", "US", "cancer_death_rate_all", Decimal("143.2"), Decimal("143.0"), Decimal("143.4")),
        _cancer_obs("national", "US", "cancer_death_rate_lung", Decimal("30.2"), Decimal("30.2"), Decimal("30.3")),
        _cancer_obs("national", "US", "cancer_death_rate_colorectal", Decimal("12.7"), Decimal("12.7"), Decimal("12.8")),
    ]
    drug_rows = [
        _drug_obs(geoid, Decimal("23.87115"), Decimal("22.12165"), Decimal("25.75957")),
    ]
    db = FakeDb(
        areas=[_area_row("county", geoid, "Durham", "North Carolina")],
        hds_rows=hds_rows,
        cancer_rows=cancer_rows,
        drug_rows=drug_rows,
    )
    client = _make_client(db)

    response = client.get(f"/community/county/{geoid}/deaths")
    assert response.status_code == 200
    body = response.json()

    assert body["level"] == "county"
    assert body["geoid"] == geoid
    assert body["name"] == "Durham"
    assert body["state"] == {"geoid": state_geoid, "name": "North Carolina"}

    # Heart & stroke group
    assert [row["measure_id"] for row in body["heart_stroke"]] == [
        "heart_disease_death_rate",
        "stroke_death_rate",
    ]
    hd = body["heart_stroke"][0]
    assert hd["county"]["value"] == pytest.approx(227.2)
    assert hd["county"]["value_type"] == "Age-adjusted, Spatially Smoothed, 3-year Average Rate"
    assert hd["state"]["value"] == pytest.approx(305.4)
    assert hd["state"]["value_type"] == "Age-adjusted, 3-year Average Rate"
    assert hd["us"]["value"] == pytest.approx(315.3)
    assert hd["us"]["value_type"] == "Age-adjusted, 3-year Average Rate"
    assert hd["county"]["citation"].startswith("Source: ")
    assert hd["state"]["citation"].startswith("Source: ")
    assert hd["us"]["citation"].startswith("Source: ")
    assert hd["uncertainty"]["kind"] == "none"

    # Cancer group
    assert [row["measure_id"] for row in body["cancer"]] == [
        "cancer_death_rate_all",
        "cancer_death_rate_lung",
        "cancer_death_rate_colorectal",
    ]
    all_cancer = body["cancer"][0]
    assert all_cancer["county"]["value"] == pytest.approx(132.6)
    assert all_cancer["county"]["uncertainty"] == {
        "kind": "ci95",
        "low": pytest.approx(127.2),
        "high": pytest.approx(138.2),
        "label": "95% confidence interval",
    }
    assert all_cancer["state"]["value"] == pytest.approx(147.8)
    assert all_cancer["us"]["value"] == pytest.approx(143.2)

    # Drug poisoning group: county only, no state or us keys
    assert [row["measure_id"] for row in body["drug_poisoning"]] == ["drug_poisoning_death_rate"]
    drug = body["drug_poisoning"][0]
    assert drug["county"]["value"] == pytest.approx(23.87115)
    assert drug["county"]["uncertainty"] == {
        "kind": "ci95",
        "low": pytest.approx(22.12165),
        "high": pytest.approx(25.75957),
        "label": "95% interval from NCHS's model",
    }
    assert "state" not in drug
    assert "us" not in drug
    assert drug["citation"].startswith("Source: ")

    assert set(body["sources"]) == {"cdc_hds_mortality", "nci_cancer_mortality", "nchs_drug_poisoning"}
    assert set(body["limitations"]) == {"cdc_hds_mortality", "nci_cancer_mortality", "nchs_drug_poisoning"}
    assert len(body["limitations"]["cdc_hds_mortality"]) == 4
    assert len(body["limitations"]["nci_cancer_mortality"]) == 3
    assert len(body["limitations"]["nchs_drug_poisoning"]) == 4

    # 404 / 400 / demo access gate match /hazards
    assert client.get("/community/county/99999/deaths").status_code == 404
    assert client.get("/community/county/bad/deaths").status_code == 400
    assert not _is_public_path("/community/county/37063/deaths")
    assert not _is_public_path("/api/community/county/37063/deaths")


def test_county_deaths_suppressed_rows_keep_null_and_status_text():
    geoid = "48269"
    hds_rows = [
        _hds_obs("county", geoid, "heart_disease_death_rate", None, status="suppressed", source_value=""),
        _hds_obs("county", geoid, "stroke_death_rate", None, status="suppressed", source_value=""),
        _hds_obs("state", "48", "heart_disease_death_rate", Decimal("320.1")),
        _hds_obs("state", "48", "stroke_death_rate", Decimal("78.4")),
        _hds_obs("national", "US", "heart_disease_death_rate", Decimal("315.3")),
        _hds_obs("national", "US", "stroke_death_rate", Decimal("75.9")),
    ]
    cancer_rows = [
        _cancer_obs("county", geoid, "cancer_death_rate_all", None, None, None, status="suppressed", source_value="*"),
        _cancer_obs("county", geoid, "cancer_death_rate_lung", None, None, None, status="suppressed", source_value="*"),
        _cancer_obs("county", geoid, "cancer_death_rate_colorectal", None, None, None, status="suppressed", source_value="*"),
        _cancer_obs("state", "48", "cancer_death_rate_all", Decimal("138.0"), Decimal("137.4"), Decimal("138.6")),
        _cancer_obs("state", "48", "cancer_death_rate_lung", Decimal("27.5"), Decimal("27.2"), Decimal("27.8")),
        _cancer_obs("state", "48", "cancer_death_rate_colorectal", Decimal("12.9"), Decimal("12.7"), Decimal("13.1")),
        _cancer_obs("national", "US", "cancer_death_rate_all", Decimal("143.2"), Decimal("143.0"), Decimal("143.4")),
        _cancer_obs("national", "US", "cancer_death_rate_lung", Decimal("30.2"), Decimal("30.2"), Decimal("30.3")),
        _cancer_obs("national", "US", "cancer_death_rate_colorectal", Decimal("12.7"), Decimal("12.7"), Decimal("12.8")),
    ]
    db = FakeDb(
        areas=[_area_row("county", geoid, "King", "Texas")],
        hds_rows=hds_rows,
        cancer_rows=cancer_rows,
        drug_rows=[],
    )
    client = _make_client(db)

    response = client.get(f"/community/county/{geoid}/deaths")
    assert response.status_code == 200
    body = response.json()

    hds_hd = body["heart_stroke"][0]
    assert hds_hd["county"]["value"] is None
    assert hds_hd["county"]["status"] == "suppressed"
    assert hds_hd["county"]["status_text"] == "Insufficient data (CDC Heart Disease and Stroke Atlas)"
    assert hds_hd["state"]["value"] == pytest.approx(320.1)

    cancer_all = body["cancer"][0]
    assert cancer_all["county"]["value"] is None
    assert cancer_all["county"]["status"] == "suppressed"
    assert cancer_all["county"]["status_text"] == "Suppressed by NCI (fewer than 16 deaths in 2020–2024)"
    assert cancer_all["county"]["uncertainty"]["low"] is None
    assert cancer_all["county"]["uncertainty"]["high"] is None


def test_deaths_returns_empty_group_when_product_has_no_active_release():
    geoid = "37063"
    # Only cdc_hds_mortality has an active release; cancer and drug poisoning have none.
    only_hds_release = [
        {
            "dataset_id": "cdc_hds_mortality_2022_2024",
            "id": "rel-hds",
            "source_release_id": "CDC Atlas 2022-2024",
            "published_at": None,
        }
    ]
    hds_rows = [
        _hds_obs("county", geoid, "heart_disease_death_rate", Decimal("227.2")),
        _hds_obs("county", geoid, "stroke_death_rate", Decimal("71.2")),
        _hds_obs("state", "37", "heart_disease_death_rate", Decimal("305.4")),
        _hds_obs("state", "37", "stroke_death_rate", Decimal("84.6")),
        _hds_obs("national", "US", "heart_disease_death_rate", Decimal("315.3")),
        _hds_obs("national", "US", "stroke_death_rate", Decimal("75.9")),
    ]
    db = FakeDb(
        areas=[
            _area_row("county", geoid, "Durham", "North Carolina"),
            _area_row("state", "37", "North Carolina", "North Carolina"),
        ],
        hds_rows=hds_rows,
        releases=only_hds_release,
    )
    client = _make_client(db)

    county_resp = client.get(f"/community/county/{geoid}/deaths")
    assert county_resp.status_code == 200
    county_body = county_resp.json()
    assert len(county_body["heart_stroke"]) == 2
    assert county_body["cancer"] == []
    assert county_body["drug_poisoning"] == []
    assert set(county_body["sources"]) == {"cdc_hds_mortality"}
    assert set(county_body["limitations"]) == {"cdc_hds_mortality"}

    state_resp = client.get("/community/state/37/deaths")
    assert state_resp.status_code == 200
    state_body = state_resp.json()
    assert len(state_body["heart_stroke"]) == 2
    assert state_body["cancer"] == []
    assert "drug_poisoning" not in state_body
    assert set(state_body["sources"]) == {"cdc_hds_mortality"}

    # None published at all: all groups empty, still 200
    empty_db = FakeDb(
        areas=[_area_row("county", geoid, "Durham", "North Carolina")],
        releases=[],
    )
    empty_body = _make_client(empty_db).get(f"/community/county/{geoid}/deaths").json()
    assert empty_body["heart_stroke"] == []
    assert empty_body["cancer"] == []
    assert empty_body["drug_poisoning"] == []
    assert empty_body["sources"] == {}
    assert empty_body["limitations"] == {}


def test_state_deaths_has_no_drug_poisoning_and_includes_state_and_us():
    geoid = "37"
    hds_rows = [
        _hds_obs("state", geoid, "heart_disease_death_rate", Decimal("305.4")),
        _hds_obs("state", geoid, "stroke_death_rate", Decimal("84.6")),
        _hds_obs("national", "US", "heart_disease_death_rate", Decimal("315.3")),
        _hds_obs("national", "US", "stroke_death_rate", Decimal("75.9")),
    ]
    cancer_rows = [
        _cancer_obs("state", geoid, "cancer_death_rate_all", Decimal("147.8"), Decimal("146.9"), Decimal("148.8")),
        _cancer_obs("state", geoid, "cancer_death_rate_lung", Decimal("35.1"), Decimal("34.6"), Decimal("35.6")),
        _cancer_obs("state", geoid, "cancer_death_rate_colorectal", Decimal("12.4"), Decimal("12.1"), Decimal("12.7")),
        _cancer_obs("national", "US", "cancer_death_rate_all", Decimal("143.2"), Decimal("143.0"), Decimal("143.4")),
        _cancer_obs("national", "US", "cancer_death_rate_lung", Decimal("30.2"), Decimal("30.2"), Decimal("30.3")),
        _cancer_obs("national", "US", "cancer_death_rate_colorectal", Decimal("12.7"), Decimal("12.7"), Decimal("12.8")),
    ]
    db = FakeDb(
        areas=[_area_row("state", geoid, "North Carolina", "North Carolina")],
        hds_rows=hds_rows,
        cancer_rows=cancer_rows,
    )
    client = _make_client(db)

    response = client.get(f"/community/state/{geoid}/deaths")
    assert response.status_code == 200
    body = response.json()

    assert "drug_poisoning" not in body
    assert body["level"] == "state"
    assert body["geoid"] == geoid
    assert body["name"] == "North Carolina"
    assert [row["measure_id"] for row in body["heart_stroke"]] == [
        "heart_disease_death_rate",
        "stroke_death_rate",
    ]
    assert [row["measure_id"] for row in body["cancer"]] == [
        "cancer_death_rate_all",
        "cancer_death_rate_lung",
        "cancer_death_rate_colorectal",
    ]
    assert "county" not in body["heart_stroke"][0]
    assert body["heart_stroke"][0]["state"]["value"] == pytest.approx(305.4)
    assert body["heart_stroke"][0]["us"]["value"] == pytest.approx(315.3)
    assert body["cancer"][0]["state"]["value"] == pytest.approx(147.8)
    assert body["cancer"][0]["us"]["value"] == pytest.approx(143.2)
    assert set(body["sources"]) == {"cdc_hds_mortality", "nci_cancer_mortality"}
    assert set(body["limitations"]) == {"cdc_hds_mortality", "nci_cancer_mortality"}

    assert client.get("/community/state/99/deaths").status_code == 404
    assert client.get("/community/state/bad/deaths").status_code == 400
    assert not _is_public_path("/community/state/37/deaths")


@pytest.fixture(scope="module")
def staging_db():
    try:
        with SessionLocal() as db:
            if db.execute(text("select current_database()")).scalar_one() != "places_staging":
                pytest.skip("mortality staging check requires places_staging")
            yield db
    except OSError as error:
        pytest.skip(f"staging DB unavailable: {error}")


def test_postgis_staging_durham_county_and_north_carolina(staging_db):
    client = _make_client(staging_db)

    county = client.get("/community/county/37063/deaths")
    assert county.status_code == 200
    body = county.json()

    assert [row["measure_id"] for row in body["heart_stroke"]] == [
        "heart_disease_death_rate",
        "stroke_death_rate",
    ]
    hd = {row["measure_id"]: row for row in body["heart_stroke"]}
    assert hd["heart_disease_death_rate"]["county"]["value"] == pytest.approx(227.2, abs=1e-4)
    assert hd["heart_disease_death_rate"]["us"]["value"] == pytest.approx(315.3, abs=1e-4)
    assert hd["heart_disease_death_rate"]["state"]["value"] is not None
    assert hd["stroke_death_rate"]["county"]["value"] == pytest.approx(71.2, abs=1e-4)
    assert hd["stroke_death_rate"]["us"]["value"] == pytest.approx(75.9, abs=1e-4)

    assert [row["measure_id"] for row in body["cancer"]] == [
        "cancer_death_rate_all",
        "cancer_death_rate_lung",
        "cancer_death_rate_colorectal",
    ]
    cancer_all = body["cancer"][0]
    assert cancer_all["county"]["value"] == pytest.approx(132.6, abs=1e-4)
    assert cancer_all["county"]["uncertainty"]["low"] == pytest.approx(127.2, abs=1e-4)
    assert cancer_all["county"]["uncertainty"]["high"] == pytest.approx(138.2, abs=1e-4)
    assert cancer_all["state"]["value"] is not None
    assert cancer_all["us"]["value"] == pytest.approx(143.2, abs=1e-4)

    assert [row["measure_id"] for row in body["drug_poisoning"]] == ["drug_poisoning_death_rate"]
    drug = body["drug_poisoning"][0]
    assert drug["county"]["value"] == pytest.approx(23.87115, abs=1e-5)
    assert drug["county"]["uncertainty"]["low"] == pytest.approx(22.12165, abs=1e-5)
    assert drug["county"]["uncertainty"]["high"] == pytest.approx(25.75957, abs=1e-5)
    assert drug["county"]["uncertainty"]["label"] == "95% interval from NCHS's model"
    assert "state" not in drug
    assert "us" not in drug

    state = client.get("/community/state/37/deaths")
    assert state.status_code == 200
    state_body = state.json()
    assert "drug_poisoning" not in state_body
    assert [row["measure_id"] for row in state_body["heart_stroke"]] == [
        "heart_disease_death_rate",
        "stroke_death_rate",
    ]
    assert state_body["heart_stroke"][0]["state"]["value"] is not None
    assert state_body["heart_stroke"][0]["us"]["value"] == pytest.approx(315.3, abs=1e-4)
    assert [row["measure_id"] for row in state_body["cancer"]] == [
        "cancer_death_rate_all",
        "cancer_death_rate_lung",
        "cancer_death_rate_colorectal",
    ]
    assert state_body["cancer"][0]["state"]["value"] is not None
    assert state_body["cancer"][0]["us"]["value"] == pytest.approx(143.2, abs=1e-4)
