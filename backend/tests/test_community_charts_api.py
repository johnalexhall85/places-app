"""Staging checks for profile chart contract and published read parity."""
import hashlib
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.area_pilot import lookup
from app.community.router import router
from app.db import SessionLocal, get_db


@pytest.fixture(scope="module")
def staging():
    try:
        with SessionLocal() as db:
            if db.execute(text("select current_database()")).scalar_one() != "places_staging":
                pytest.skip("profile chart integration checks require places_staging")
            yield db
    except OSError as error:
        pytest.skip(f"staging DB unavailable: {error}")


@pytest.fixture(scope="module")
def client(staging):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: staging
    with TestClient(app) as result:
        yield result


@pytest.fixture(scope="module")
def payloads(client):
    return {key: client.get(path).json() for key, path in {
        "01063": "/community/county/01063/charts", "01055": "/community/county/01055/charts",
        "01": "/community/state/01/charts", "5401": "/community/district/5401/charts"}.items()}


def all_rows(payload):
    return [row for section in payload["sections"] for group in section["groups"] for row in group["rows"]]


def test_shapes_and_all_current_measures(payloads, staging):
    for geoid, payload in payloads.items():
        level = {"01": "state", "5401": "cd"}.get(geoid, "county")
        assert {"level", "geoid", "name", "state", "sections"} <= payload.keys()
        # SVI and NRI are served by /hazards, not /charts (docs/vulnerability/CONTRACT.md section 4).
        current = [row for row in lookup.area_values(staging, level, [geoid])["values"]
                   if row["product"] not in {"cdc_svi", "fema_nri"}]
        rows = all_rows(payload)
        assert {(row["product"], row["measure_id"]) for row in rows} == {
            (row["product"], row["measure_id"]) for row in current}
        for section in payload["sections"]:
            assert {"key", "groups"} <= section.keys()
            for group in section["groups"]:
                assert {"key", "title", "unit", "shared_axis", "rows"} <= group.keys()
                if group["shared_axis"]:
                    assert len({row["unit"] for row in group["rows"]}) == 1
        for row in rows:
            assert {"product", "measure_id", "label", "unit", "kind", "period", "population", "value",
                    "status", "status_text", "uncertainty", "comparisons", "peers", "trend", "source", "citation"} <= row.keys()
            assert {"state", "national", "side_note"} <= row["comparisons"].keys()
            assert {"publisher", "product_name", "credit"} <= row["source"].keys()
            if row["trend"]:
                assert {"style", "note", "series", "state_series", "national_series", "unavailable_periods"} <= row["trend"].keys()
                for point in row["trend"]["series"]:
                    assert {"period", "value", "low", "high", "status", "status_text", "note",
                            "boundary_vintage", "release_label", "current_period"} <= point.keys()


def test_comparability_and_current_values(payloads, staging):
    count_units = {"people", "beneficiaries", "physicians", "dentists", "hospitals", "beds", "days"}
    for geoid, payload in payloads.items():
        level = {"01": "state", "5401": "cd"}.get(geoid, "county")
        current = {(row["product"], row["measure_id"]): row
                   for row in lookup.area_values(staging, level, [geoid])["values"]}
        for row in all_rows(payload):
            assert row["value"] == current[(row["product"], row["measure_id"])]["value"]
            if row["product"] in {"places", "brfss"} or row["kind"] == "count" or row["unit"] in count_units:
                assert row["comparisons"]["state"] is None
                assert row["comparisons"]["national"] is None
            if level == "cd":
                assert row["trend"] is None
            if row["product"] == "places" and row["trend"]:
                assert row["trend"]["style"] == "dots_ci"
            if row["value"] is None:
                assert row["status_text"] == current[(row["product"], row["measure_id"])]["status_text"]
                assert row["value"] != 0


def test_peers(client, payloads):
    state = next(row for row in all_rows(payloads["01"]) if row["product"] == "brfss" and row["peers"])
    assert state["peers"]["count"] >= 50
    county = client.get("/community/county/01063/peers", params={"measure": "places:diabetes_crudeprev"})
    assert county.status_code == 200
    values = county.json()["values"]
    assert len(values) == 67
    assert [row["geoid"] for row in values] == sorted(row["geoid"] for row in values)
    assert client.get("/community/county/01063/peers", params={"measure": "acs:B19013_001E"}).status_code == 400


def test_current_release_labels_use_product_names(payloads):
    checked = 0
    for payload in payloads.values():
        for row in all_rows(payload):
            if not row["trend"]:
                continue
            for point in row["trend"]["series"]:
                if point["current_period"]:
                    checked += 1
                    assert point["release_label"] == row["source"]["product_name"]
                    assert not re.fullmatch(r"\d{4}-\d{2}-\d{2}", point["release_label"])
    assert checked > 0


def test_contract_snapshots_stay_byte_identical():
    root = Path(__file__).resolve().parents[2] / "docs/beta/contract-examples"
    expected = {
        "catalog.json": "c9a7dafd54ef81a4e675da76db99bb298425e1fd3e52e7acba30465b667c7842",
        "area_values_county_01055.json": "e6c9238f14af22ff5591bf886ba3302887ae8fc2c2118fb022e315e573f2706b",
        "area_values_state_01.json": "691fcd6073ea9a97efe3ed6955ce60d3b6651f42c89e3f1f337f8eb64ab8ccdc",
    }
    for filename, digest in expected.items():
        assert hashlib.sha256((root / filename).read_bytes()).hexdigest() == digest
