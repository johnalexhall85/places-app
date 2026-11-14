"""HTTP contract checks for place-first reads; source values stay in lookup."""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.community import router as community
from app.db import get_db


EXAMPLES = Path(__file__).resolve().parents[2] / "docs" / "beta" / "contract-examples"


def example(name):
    return json.loads((EXAMPLES / name).read_text())


@pytest.fixture
def client(monkeypatch):
    catalog = example("catalog.json")
    county_info = example("area_info_county_01055.json")[0]
    county_values = example("area_values_county_01055.json")
    state_values = example("area_values_state_01.json")
    facilities = example("area_facilities_county_01055.json")

    def area_info(db, level, geoids):
        if level != "county":
            return []
        return [county_info | {"geoid": geoid, "county_geoid": geoid} for geoid in geoids if geoid != "99999"]

    def area_values(db, level, geoids):
        if level == "state":
            return state_values
        return county_values | {"geoids": geoids, "values": [row | {"geoid": geoid}
                                                    for geoid in geoids for row in county_values["values"]]}

    monkeypatch.setattr(community.lookup, "catalog", lambda db: catalog)
    monkeypatch.setattr(community.lookup, "area_info", area_info)
    monkeypatch.setattr(community.lookup, "area_values", area_values)
    monkeypatch.setattr(community.lookup, "area_facilities", lambda db, level, geoid: facilities)
    monkeypatch.setattr(community.lookup, "county_tract_values", lambda db, county, product, measure: {
        "county_geoid": county, "measure": measure, "values": [], "release": None,
    })
    app = FastAPI()
    app.include_router(community.router)
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


def test_county_profile_keeps_status_uncertainty_and_source_release(client):
    response = client.get("/community/county/01055")
    assert response.status_code == 200
    body = response.json()
    assert body["area"]["geoid"] == "01055"
    assert len(body["values"]) == 28
    assert {row["product"] for row in body["state_values"]} == {"acs", "cms_gv"}
    places = next(row for row in body["values"] if row["product"] == "places")
    assert places["uncertainty"]["kind"] == "ci95"
    assert places["source_release_id"] and places["source"]["publisher"]
    assert body["facilities"]["health_centers"]["count"] == 10


def test_comparison_keeps_each_county_row_and_rejects_invalid_selection(client):
    response = client.get("/community/compare", params={"geoids": "01055,01073"})
    assert response.status_code == 200
    body = response.json()
    assert [area["geoid"] for area in body["areas"]] == ["01055", "01073"]
    assert {row["geoid"] for row in body["values"]} == {"01055", "01073"}
    assert len(body["values"]) == 56
    assert client.get("/community/compare", params={"geoids": "01055,01073,01075,01077,01079"}).status_code == 400
    assert client.get("/community/compare", params={"geoids": "01055,99999"}).status_code == 404


def test_csv_carries_source_period_release_and_missing_status(client):
    response = client.get("/community/county/01055/csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.splitlines()
    assert len(lines) == 29
    assert "source_release" in lines[0] and "population" in lines[0]
    assert "f735c524" in response.text


def test_topics_and_tract_route(client):
    topics = client.get("/community/topics").json()
    assert len(topics) == 7
    assert client.get("/community/topics/unknown").status_code == 404
    assert client.get("/community/county/01055/tracts", params={"product": "places", "measure_id": "dental_crudeprev"}).status_code == 200
    assert client.get("/community/county/99999").status_code == 404
