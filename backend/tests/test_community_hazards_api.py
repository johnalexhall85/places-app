"""Unit and read-only PostGIS staging tests for /community/{county,state}/{geoid}/hazards."""
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
    """Fake SQLAlchemy session serving area_pilot boundary, release, and observation tables."""

    def __init__(self, *, areas=None, svi_rows=None, nri_rows=None, releases=None):
        self.areas = areas or []
        self.tables = {
            "observation_cdc_svi": svi_rows or [],
            "observation_fema_nri": nri_rows or [],
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
                if spec.key in {"cdc_svi", "fema_nri"}
            ])
        if "acs_boundary_2024" in sql and "ST_XMin" in sql:
            level = params.get("level")
            geoids = set(params.get("geoids") or [])
            return FakeResult([
                row for row in self.areas if row["level"] == level and row["geoid"] in geoids
            ])
        for table_name, rows in self.tables.items():
            if f"area_pilot.{table_name} " in sql:
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


def _spec_measures(spec_key: str) -> dict[str, dict]:
    spec = next(s for s in lookup.SPECS if s.key == spec_key)
    config = spec.load()
    return {m["measure_id"]: lookup._measure_meta(spec, config, m) for m in config["measures"]}


def _svi_obs(geoid: str, measure_id: str, value: Decimal | None, status: str = "available",
             source_value: str | None = None) -> dict:
    meta = _spec_measures("cdc_svi")[measure_id]
    return {
        "geo_level": "county",
        "geoid": geoid,
        "measure_id": measure_id,
        "observation_period": meta["period"],
        "population": meta["population"],
        "value_type": meta["value_type"],
        "value": value,
        "status": status,
        "source_value": source_value if source_value is not None else (str(value) if value is not None else "-999"),
    }


def _nri_obs(level: str, geoid: str, measure_id: str, value: Decimal | None, status: str = "available",
             rating: str | None = None, source_value: str | None = None) -> dict:
    meta = _spec_measures("fema_nri")[measure_id]
    return {
        "geo_level": level,
        "geoid": geoid,
        "measure_id": measure_id,
        "observation_period": meta["period"],
        "population": meta["population"],
        "value_type": meta["value_type"],
        "value": value,
        "status": status,
        "rating": rating,
        "source_value": source_value if source_value is not None else (str(value) if value is not None else ""),
    }


def _make_client(db) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_county_hazards_shape_order_and_pairing():
    geoid = "37063"
    svi_rows = [
        _svi_obs(geoid, "rpl_themes", Decimal("0.6860")),
        _svi_obs(geoid, "rpl_theme1", Decimal("0.5120")),
        _svi_obs(geoid, "rpl_theme2", Decimal("0.3310")),
        _svi_obs(geoid, "rpl_theme3", Decimal("0.8920")),
        _svi_obs(geoid, "rpl_theme4", Decimal("0.7440")),
        _svi_obs(geoid, "rpl_themes_state", Decimal("0.5960")),
        _svi_obs(geoid, "rpl_theme1_state", Decimal("0.4200")),
        _svi_obs(geoid, "rpl_theme2_state", Decimal("0.2800")),
        _svi_obs(geoid, "rpl_theme3_state", Decimal("0.9100")),
        _svi_obs(geoid, "rpl_theme4_state", Decimal("0.6500")),
    ]
    nri_rows = [
        _nri_obs("county", geoid, "risk_score", Decimal("81.4000"), rating="Relatively Moderate"),
        _nri_obs("county", geoid, "risk_spctl", Decimal("89.0000")),
        _nri_obs("county", geoid, "eal_score", Decimal("84.2000"), rating="Relatively Moderate"),
        _nri_obs("county", geoid, "eal_spctl", Decimal("86.0000")),
        _nri_obs("county", geoid, "eal_valt", Decimal("38142500.2500")),
        _nri_obs("county", geoid, "sovi_score", Decimal("65.3000"), rating="Relatively High"),
        _nri_obs("county", geoid, "sovi_spctl", Decimal("51.0000")),
        _nri_obs("county", geoid, "resl_score", Decimal("72.1000"), rating="Relatively High"),
        _nri_obs("county", geoid, "resl_spctl", Decimal("84.0000")),
        _nri_obs("county", geoid, "crf_value", Decimal("1.1200")),
    ]
    db = FakeDb(
        areas=[_area_row("county", geoid, "Durham", "North Carolina")],
        svi_rows=svi_rows,
        nri_rows=nri_rows,
    )
    client = _make_client(db)

    response = client.get(f"/community/county/{geoid}/hazards")
    assert response.status_code == 200
    body = response.json()

    assert body["level"] == "county"
    assert body["geoid"] == geoid
    assert body["name"] == "Durham"
    assert body["state"] == {"geoid": "37", "name": "North Carolina"}

    # SVI order matches contract section 1
    assert [row["measure_id"] for row in body["svi"]] == [
        "rpl_themes", "rpl_theme1", "rpl_theme2", "rpl_theme3", "rpl_theme4",
    ]
    assert [row["label"] for row in body["svi"]] == [
        "Overall social vulnerability",
        "Socioeconomic status",
        "Household characteristics",
        "Racial and ethnic minority status",
        "Housing type and transportation",
    ]
    first_svi = body["svi"][0]
    assert first_svi["us"]["measure_id"] == "rpl_themes"
    assert first_svi["us"]["value"] == pytest.approx(0.686)
    assert first_svi["state"]["measure_id"] == "rpl_themes_state"
    assert first_svi["state"]["value"] == pytest.approx(0.596)
    assert first_svi["us"]["citation"].startswith("Source: ")
    assert first_svi["state"]["citation"].startswith("Source: ")
    assert first_svi["status"] == "available"
    assert first_svi["status_text"] == "Published value"

    # NRI order matches contract section 4
    assert [row["measure_id"] for row in body["nri"]] == [
        "risk_score", "eal_score", "eal_valt", "sovi_score", "resl_score", "crf_value",
    ]
    nri_by_id = {row["measure_id"]: row for row in body["nri"]}
    assert nri_by_id["risk_score"]["rating"] == "Relatively Moderate"
    assert nri_by_id["risk_score"]["state_percentile"]["measure_id"] == "risk_spctl"
    assert nri_by_id["risk_score"]["state_percentile"]["value"] == pytest.approx(89.0)
    assert nri_by_id["eal_score"]["state_percentile"]["measure_id"] == "eal_spctl"
    assert nri_by_id["eal_valt"]["rating"] is None
    assert nri_by_id["eal_valt"]["state_percentile"] is None
    assert nri_by_id["sovi_score"]["state_percentile"]["measure_id"] == "sovi_spctl"
    assert nri_by_id["resl_score"]["state_percentile"]["measure_id"] == "resl_spctl"
    assert nri_by_id["resl_score"]["direction"] == "higher_better"
    assert nri_by_id["risk_score"]["direction"] == "higher_worse"
    assert nri_by_id["crf_value"]["rating"] is None
    assert nri_by_id["crf_value"]["state_percentile"] is None
    assert all(row["citation"].startswith("Source: ") for row in body["nri"])

    assert set(body["sources"]) == {"cdc_svi", "fema_nri"}
    assert set(body["limitations"]) == {"cdc_svi", "fema_nri"}
    assert len(body["limitations"]["cdc_svi"]) == 7
    assert len(body["limitations"]["fema_nri"]) == 6

    # 404 / 400 / demo access gate match /charts
    assert client.get("/community/county/99999/hazards").status_code == 404
    assert client.get("/community/county/bad/hazards").status_code == 400
    assert not _is_public_path("/community/county/37063/hazards")
    assert not _is_public_path("/api/community/county/37063/hazards")


def test_county_hazards_svi_not_available_tract_free_county():
    geoid = "15005"  # Kalawao-style unranked / tract-free county simulated via FakeDb
    svi_rows = [
        _svi_obs(geoid, mid, None, status="not_available", source_value="-999")
        for mid in (
            "rpl_themes", "rpl_theme1", "rpl_theme2", "rpl_theme3", "rpl_theme4",
            "rpl_themes_state", "rpl_theme1_state", "rpl_theme2_state", "rpl_theme3_state", "rpl_theme4_state",
        )
    ]
    db = FakeDb(
        areas=[_area_row("county", geoid, "Kalawao", "Hawaii")],
        svi_rows=svi_rows,
        nri_rows=[],
    )
    client = _make_client(db)

    response = client.get(f"/community/county/{geoid}/hazards")
    assert response.status_code == 200
    body = response.json()
    assert len(body["svi"]) == 5
    for row in body["svi"]:
        assert row["us"]["value"] is None
        assert row["us"]["status"] == "not_available"
        assert row["us"]["status_text"] == "Not ranked by CDC (−999 in the source file)"
        assert row["state"]["value"] is None
        assert row["state"]["status"] == "not_available"
        assert row["state"]["status_text"] == "Not ranked by CDC (−999 in the source file)"


def test_county_hazards_nri_blank_score_and_paired_percentile():
    geoid = "72001"
    nri_rows = [
        _nri_obs("county", geoid, "risk_score", None, status="not_available", rating="Data Unavailable", source_value=""),
        _nri_obs("county", geoid, "risk_spctl", None, status="not_available", rating=None, source_value=""),
        _nri_obs("county", geoid, "eal_score", Decimal("41.5000"), rating="Relatively Low"),
        _nri_obs("county", geoid, "eal_spctl", Decimal("32.1000")),
        _nri_obs("county", geoid, "eal_valt", Decimal("1250000.0000")),
        _nri_obs("county", geoid, "sovi_score", None, status="not_available", rating="Data Unavailable", source_value=""),
        _nri_obs("county", geoid, "sovi_spctl", None, status="not_available", rating=None, source_value="0"),
        _nri_obs("county", geoid, "resl_score", None, status="not_available", rating="Data Unavailable", source_value=""),
        _nri_obs("county", geoid, "resl_spctl", None, status="not_available", rating=None, source_value="0"),
        _nri_obs("county", geoid, "crf_value", None, status="not_available", rating=None, source_value=""),
    ]
    db = FakeDb(
        areas=[_area_row("county", geoid, "Adjuntas", "Puerto Rico")],
        svi_rows=[],
        nri_rows=nri_rows,
    )
    client = _make_client(db)

    response = client.get(f"/community/county/{geoid}/hazards")
    assert response.status_code == 200
    body = response.json()
    nri_by_id = {row["measure_id"]: row for row in body["nri"]}

    sovi = nri_by_id["sovi_score"]
    assert sovi["value"] is None
    assert sovi["status"] == "not_available"
    assert sovi["rating"] == "Data Unavailable"
    assert sovi["status_text"] == "Not published by FEMA for this area (Data Unavailable)"

    spctl = sovi["state_percentile"]
    assert spctl is not None
    assert spctl["measure_id"] == "sovi_spctl"
    assert spctl["value"] is None
    assert spctl["status"] == "not_available"
    assert spctl["status_text"] == "Not published by FEMA for this area"
    assert spctl["notes"]["source_value"] == "0"


def test_state_hazards_has_no_svi_and_only_eal_measures():
    geoid = "37"
    nri_rows = [
        _nri_obs("state", geoid, "eal_score", Decimal("89.2857"), rating="Relatively High"),
        _nri_obs("state", geoid, "eal_valt", Decimal("3210450123.5000")),
    ]
    db = FakeDb(
        areas=[_area_row("state", geoid, "North Carolina", "North Carolina")],
        svi_rows=[],
        nri_rows=nri_rows,
    )
    client = _make_client(db)

    response = client.get(f"/community/state/{geoid}/hazards")
    assert response.status_code == 200
    body = response.json()

    assert "svi" not in body
    assert body["level"] == "state"
    assert body["geoid"] == geoid
    assert [row["measure_id"] for row in body["nri"]] == ["eal_score", "eal_valt"]
    assert body["nri"][0]["rating"] == "Relatively High"
    assert body["nri"][0]["state_percentile"] is None
    assert body["nri"][1]["rating"] is None
    assert body["nri"][1]["value"] == pytest.approx(3210450123.5)
    assert set(body["sources"]) == {"fema_nri"}
    assert set(body["limitations"]) == {"fema_nri"}

    assert client.get("/community/state/99/hazards").status_code == 404
    assert client.get("/community/state/bad/hazards").status_code == 400
    assert not _is_public_path("/community/state/37/hazards")


@pytest.fixture(scope="module")
def staging_db():
    try:
        with SessionLocal() as db:
            if db.execute(text("select current_database()")).scalar_one() != "places_staging":
                pytest.skip("hazard staging check requires places_staging")
            yield db
    except OSError as error:
        pytest.skip(f"staging DB unavailable: {error}")


def test_postgis_staging_durham_county_and_north_carolina(staging_db):
    client = _make_client(staging_db)

    county = client.get("/community/county/37063/hazards")
    assert county.status_code == 200
    body = county.json()

    assert [row["measure_id"] for row in body["svi"]] == [
        "rpl_themes", "rpl_theme1", "rpl_theme2", "rpl_theme3", "rpl_theme4",
    ]
    overall = body["svi"][0]
    assert overall["us"]["value"] == pytest.approx(0.686, abs=1e-4)
    assert overall["state"]["value"] == pytest.approx(0.596, abs=1e-4)
    assert overall["us"]["citation"].startswith("Source: ")

    assert [row["measure_id"] for row in body["nri"]] == [
        "risk_score", "eal_score", "eal_valt", "sovi_score", "resl_score", "crf_value",
    ]
    nri_by_id = {row["measure_id"]: row for row in body["nri"]}
    assert nri_by_id["risk_score"]["value"] is not None
    assert nri_by_id["risk_score"]["rating"]
    assert nri_by_id["risk_score"]["state_percentile"]["value"] is not None
    assert nri_by_id["eal_valt"]["value"] > 0
    assert nri_by_id["resl_score"]["direction"] == "higher_better"

    state = client.get("/community/state/37/hazards")
    assert state.status_code == 200
    state_body = state.json()
    assert "svi" not in state_body
    assert [row["measure_id"] for row in state_body["nri"]] == ["eal_score", "eal_valt"]
    assert state_body["nri"][0]["value"] is not None and state_body["nri"][0]["rating"]
    assert state_body["nri"][1]["value"] > 0
