"""CDC national state-map API contract checks."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import SessionLocal
from app.state_funding import lookup
from app.state_funding.router import router


app = FastAPI()
app.include_router(router)
client = TestClient(app)
ROOT = "/state-funding/v1"


def test_map_rejects_bad_or_unavailable_filters():
    for query in (
        "funding_type=bad", "fy=2020", "award_type=grant", "account=", "recipient_type=all",
        "category=does-not-exist", "deobligations=bad",
    ):
        assert client.get(f"{ROOT}/map?{query}").status_code == 422


def test_map_matches_state_summary_for_funding_types_and_category():
    default = client.get(f"{ROOT}/map?fy=2026").json()
    assert default["filters"]["award_type"] == "grant"
    category = default["categories_available"][0]["code"]
    for funding_type, selected_category in (
        ("all", None), ("regular", None), ("supplemental", None), ("all", category),
    ):
        filters = {"fy": 2026, "funding_type": funding_type}
        if selected_category:
            filters["category"] = selected_category
        response = client.get(f"{ROOT}/map", params=filters)
        assert response.status_code == 200
        payload = response.json()
        state = next(row for row in payload["states"] if row["code"] == "CA")
        summary = client.get(
            f"{ROOT}/states/CA/summary", params=filters | {"award_type": "grant"},
        ).json()
        for key in ("total", "regular", "supplemental", "award_count", "recipient_count"):
            assert state[key] == summary["totals"][key]
        assert round(sum(row["total"] for row in payload["states"]) + payload["unattributed"]["total"], 2) == (
            payload["national"]["total"]
        )


def test_unattributed_profiles_and_shapes():
    payload = client.get(f"{ROOT}/map?fy=2026").json()
    with SessionLocal() as db:
        build = lookup.build_info(db)
        anonymous = db.execute(text("""SELECT coalesce(sum(o.amount),0), count(DISTINCT o.award_unique_key)
            FROM state_funding.obligation o JOIN state_funding.award a USING(build_id,award_unique_key)
            WHERE o.build_id=:build AND o.fiscal_year=2026 AND o.state='__' AND a.award_type='grant'"""),
            {"build": build["build_id"]}).one()
    assert payload["unattributed"] == {"total": lookup.money(anonymous[0]), "award_count": anonymous[1]}
    assert next(row for row in payload["states"] if row["code"] == "GU")["indicators_geoid"] is None
    shapes = client.get(f"{ROOT}/map/shapes")
    assert shapes.status_code == 200
    assert shapes.headers["cache-control"] == "public, max-age=86400"
    assert shapes.json()["states"]["CA"]["fips"] == "06"
    assert shapes.json()["states"]["CA"]["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert len(shapes.content) < 400_000
    assert len(client.get(f"{ROOT}/map?fy=2026").content) < 60_000


def test_staging_fy2026_total():
    try:
        with SessionLocal() as db:
            if db.execute(text("select current_database()")).scalar() != "places_staging" or not lookup.build_info(db):
                pytest.skip("requires an active places_staging build")
    except Exception as exc:
        pytest.skip(f"staging unavailable: {type(exc).__name__}")
    total = client.get(f"{ROOT}/map?fy=2026").json()["national"]["total"]
    assert abs(total - 2_903_439_520) <= 1


def test_excluding_deobligations_matches_state_summary_and_positive_rows():
    included = client.get(f"{ROOT}/map?fy=2026").json()
    assert included["filters"]["deobligations"] == "include"
    excluded = client.get(f"{ROOT}/map?fy=2026&deobligations=exclude").json()
    assert excluded["filters"]["deobligations"] == "exclude"
    assert any("Deobligations (net reductions" in note for note in excluded["notes"])
    assert excluded["national"]["total"] > included["national"]["total"]
    assert all(row["total"] >= 0 and row["regular"] >= 0 and row["supplemental"] >= 0
               for row in excluded["states"])
    assert excluded["national"]["total"] == round(
        sum(row["total"] for row in excluded["states"]) + excluded["unattributed"]["total"], 2,
    )

    category = excluded["categories_available"][0]["code"]
    for funding_type, selected_category in (("all", None), ("regular", None),
                                            ("supplemental", None), ("all", category)):
        filters = {"fy": 2026, "funding_type": funding_type, "deobligations": "exclude"}
        if selected_category:
            filters["category"] = selected_category
        map_response = client.get(f"{ROOT}/map", params=filters)
        assert map_response.status_code == 200
        state = next(row for row in map_response.json()["states"] if row["code"] == "CA")
        summary = client.get(
            f"{ROOT}/states/CA/summary", params=filters | {"award_type": "grant"},
        ).json()
        for key in ("total", "regular", "supplemental", "award_count", "recipient_count"):
            assert state[key] == summary["totals"][key]
        assert sum(category["total"] for category in summary["by_category"]) == summary["totals"]["total"]


def test_summary_default_response_unchanged_when_deobligations_included():
    default = client.get(f"{ROOT}/states/CA/summary?fy=2026").json()
    explicit = client.get(f"{ROOT}/states/CA/summary?fy=2026&deobligations=include").json()
    assert default == explicit
    assert "deobligations" not in default["filters"]
    assert client.get(f"{ROOT}/states/CA/summary?deobligations=bad").status_code == 422
