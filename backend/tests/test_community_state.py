"""State product endpoints preserve the published lookup values and BRFSS pairing."""
import csv
import io
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.community import router as community
from app.db import get_db

EXAMPLES = Path(__file__).resolve().parents[2] / "docs/beta/contract-examples"


def example(name):
    return json.loads((EXAMPLES / name).read_text())


@pytest.fixture
def client(monkeypatch):
    catalog = example("after-c3/catalog.json")
    excerpt = example("after-brfss/catalog_brfss_and_paired_places_excerpt.json")
    catalog["measures"].extend(excerpt["measures"])
    catalog["products"].extend(excerpt["products"])
    acs_cms = example("after-c3/area_values_state_54.json")
    brfss = example("after-brfss/state_values_37_brfss.json")
    known = {(row["product"], row["measure_id"]) for row in catalog["measures"]}
    for row in brfss["values"]:
        key = row["product"], row["measure_id"]
        if key not in known:
            catalog["measures"].append({"product": "brfss", "measure_id": row["measure_id"],
                                        "publisher": "CDC", "product_name": "BRFSS state survey estimates",
                                        "landing_page": "https://data.cdc.gov", "source_credit": None})
    values = {"level": "state", "geoids": ["37"],
              "values": [row | {"geoid": "37"} for row in acs_cms["values"] + brfss["values"]],
              "releases": acs_cms["releases"] | brfss["releases"]}
    area = {"level": "state", "geoid": "37", "name": "North Carolina", "state_geoid": "37",
            "state_name": "North Carolina", "bbox": [-84, 33, -75, 37], "point": [-79, 35],
            "boundary_vintage": "TIGER/Line 2024"}
    states = example("after-brfss/states.json")
    companion = example("after-brfss/state_survey_companions_37.json")
    monkeypatch.setattr(community.lookup, "catalog", lambda db: catalog)
    monkeypatch.setattr(community.lookup, "states", lambda db: states)
    monkeypatch.setattr(community.lookup, "area_info", lambda db, level, geoids: [area] if level == "state" and geoids == ["37"] else [])
    monkeypatch.setattr(community.lookup, "area_values", lambda db, level, geoids: values)
    monkeypatch.setattr(community.lookup, "area_facilities", lambda db, level, geoid: example("after-brfss/state_facilities_37_counts.json"))
    monkeypatch.setattr(community.lookup, "state_counties", lambda db, geoid: [{"geoid": "37145", "name": "Person"}])
    monkeypatch.setattr(community.lookup, "state_districts", lambda db, geoid: [{"geoid": "3701", "name": "Congressional District 1"}])
    monkeypatch.setattr(community.lookup, "state_survey_companions", lambda db, geoid: companion)
    monkeypatch.setattr(community, "search_counties", lambda **kwargs: [])
    app = FastAPI()
    app.include_router(community.router)
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


def test_state_search_and_profile_use_published_state_rows(client):
    matches = client.get("/community/search", params={"q": "North Carolina"}).json()
    assert matches[0]["type"] == "state" and matches[0]["state_geoid"] == "37"
    body = client.get("/community/state/37").json()
    assert len(body["values"]) == 33
    assert {row["product"] for row in body["values"]} == {"acs", "acs_profile", "brfss", "cms_gv"}
    assert len([row for row in body["values"] if row["product"] == "brfss"]) == 20
    assert body["districts"][0]["geoid"] == "3701"
    assert client.get("/community/state/99").status_code == 404


def test_state_csv_and_pdf_keep_release_and_session(client, monkeypatch):
    response = client.get("/community/state/37/csv")
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert response.status_code == 200 and len(rows) == 33
    diabetes = next(row for row in rows if row["product"] == "brfss" and row["measure_id"] == "diabetes")
    assert diabetes["value"] == "12.4" and diabetes["uncertainty_low"] == "11"
    assert diabetes["source_release"].startswith("BRFSS Prevalence Data")
    calls = []
    monkeypatch.setattr(community, "render_route_pdf_via_playwright", lambda **kwargs: calls.append(kwargs) or b"%PDF-1.4\n")
    cookie_name = community.get_demo_access_settings().cookie_name
    client.cookies.set(cookie_name, "state-session")
    pdf = client.get("/community/state/37/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert calls == [{"route_path": "/community/state/37", "session_cookie": (cookie_name, "state-session")}]
    assert client.get("/community/state/99/pdf").status_code == 404
