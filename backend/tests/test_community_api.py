"""HTTP contract checks for place-first reads; source values stay in lookup."""
import json
import csv
import io
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
    monkeypatch.setattr(community.lookup, "state_survey_companions", lambda db, state: {
        "companions": {}, "note": "State survey estimate (BRFSS) is context, not a benchmark.",
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


def test_paired_brfss_state_survey_is_in_county_csv_and_comparison(client, monkeypatch):
    catalog = example("catalog.json")
    catalog["measures"].append({"product": "brfss", "measure_id": "dental_visit", "publisher": "CDC",
                                "product_name": "BRFSS state survey estimates", "landing_page": "https://data.cdc.gov",
                                "source_credit": None})
    monkeypatch.setattr(community.lookup, "catalog", lambda db: catalog)
    survey = {"product": "brfss", "measure_id": "dental_visit", "value": 61.2, "status": "available",
              "status_text": "Published estimate", "period": "2022", "population": "adults",
              "uncertainty": {"kind": "ci95", "low": 59.8, "high": 62.6},
              "source_release_id": "BRFSS 2022", "release_id": "brfss-release"}
    monkeypatch.setattr(community.lookup, "state_survey_companions", lambda db, state: {
        "companions": {"dental_crudeprev": survey}, "note": "Direct state survey estimate",
    })
    county = client.get("/community/county/01055").json()
    assert county["survey_companions"]["dental_crudeprev"]["source"]["product_name"] == "BRFSS state survey estimates"
    rows = list(csv.DictReader(io.StringIO(client.get("/community/county/01055/csv").text)))
    dental = next(row for row in rows if row["measure_id"] == "dental_crudeprev")
    assert dental["state_survey_label"] == "State survey estimate (BRFSS)"
    assert dental["state_survey_value"] == "61.2" and dental["state_survey_ci_low"] == "59.8"
    assert dental["state_survey_source_release"] == "BRFSS 2022"
    assert not next(row for row in rows if row["product"] == "acs")["state_survey_label"]
    comparison = client.get("/community/compare", params={"geoids": "01055,01073"}).json()
    assert comparison["survey_companions"]["01"]["dental_crudeprev"]["value"] == 61.2


def test_topics_and_tract_route(client):
    topics = client.get("/community/topics").json()
    assert len(topics) == 7
    assert client.get("/community/topics/unknown").status_code == 404
    assert client.get("/community/county/01055/tracts", params={"product": "places", "measure_id": "dental_crudeprev"}).status_code == 200
    assert client.get("/community/county/99999").status_code == 404


def test_pdf_uses_current_session_cookie_and_rejects_unknown_county(client, monkeypatch):
    calls = []
    monkeypatch.setattr(community, "render_route_pdf_via_playwright", lambda **kwargs: calls.append(kwargs) or b"%PDF-1.4\n")
    cookie_name = community.get_demo_access_settings().cookie_name
    client.cookies.set(cookie_name, "session-value")
    response = client.get("/community/county/01055/pdf")
    assert response.status_code == 200 and response.content.startswith(b"%PDF")
    assert calls == [{"route_path": "/community/county/01055", "session_cookie": (cookie_name, "session-value")}]
    assert client.get("/community/county/99999/pdf").status_code == 404


def test_district_briefing_uses_only_published_district_rows(monkeypatch):
    catalog = example("after-c3/catalog.json")
    area = example("after-c3/area_info_cd_5401.json")[0]
    values = example("after-c3/area_values_cd_5401.json")
    facilities = example("after-c3/area_facilities_cd_5401.json")
    counties = example("after-c3/district_counties_5401.json")
    monkeypatch.setattr(community.lookup, "catalog", lambda db: catalog)
    monkeypatch.setattr(community.lookup, "area_info", lambda db, level, geoids: [area] if level == "cd" and geoids == ["5401"] else [])
    monkeypatch.setattr(community.lookup, "area_values", lambda db, level, geoids: values if level == "cd" and geoids == ["5401"] else None)
    monkeypatch.setattr(community.lookup, "area_facilities", lambda db, level, geoid: facilities)
    monkeypatch.setattr(community.lookup, "district_counties", lambda db, geoid: counties)
    app = FastAPI()
    app.include_router(community.router)
    app.dependency_overrides[get_db] = lambda: object()
    client = TestClient(app)
    response = client.get("/community/district/5401")
    assert response.status_code == 200
    body = response.json()
    assert len(body["values"]) == 7
    assert {row["product"] for row in body["values"]} == {"acs_profile"}
    assert all(row["level"] == "cd" and row["source"]["publisher"] for row in body["values"])
    assert len(body["counties"]["counties"]) == 28
    assert body["facilities"]["health_centers"]["count"] == 347
    assert client.get("/community/district/9999").status_code == 404


def test_area_outline_returns_bbox_and_outline_and_rejects_unknowns(client, monkeypatch):
    calls = []

    def area_info(db, level, geoids, geometry=False):
        calls.append((level, geoids, geometry))
        if geoids == ["99999"]:
            return []
        return [{"level": level, "geoid": geoids[0], "name": "Person", "bbox": [-79.2, 36.2, -78.8, 36.5],
                 "point": [-79.0, 36.4], "geometry": {"type": "Polygon", "coordinates": []}}]

    monkeypatch.setattr(community.lookup, "area_info", area_info)
    body = client.get("/community/area/county/37145").json()
    assert body["bbox"] == [-79.2, 36.2, -78.8, 36.5] and body["geometry"]["type"] == "Polygon"
    assert calls == [("county", ["37145"], True)]
    assert client.get("/community/area/county/99999").status_code == 404
    assert client.get("/community/area/zip/27573").status_code == 400
