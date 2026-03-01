from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.routers import hpsa as hpsa_router


class _DummySession:
    pass


def test_hpsa_counties_geojson_returns_feature_collection_with_metadata(monkeypatch):
    monkeypatch.setattr(hpsa_router, "_ensure_hpsa_county_geojson_tables", lambda _db: None)
    monkeypatch.setattr(
        hpsa_router,
        "fetch_hpsa_domain_quartiles",
        lambda _db, _domain: {
            "q25": 8,
            "q50": 12,
            "q75": 16,
            "n_counties": 100,
            "as_of_date": date(2026, 3, 1),
        },
    )
    monkeypatch.setattr(
        hpsa_router,
        "fetch_hpsa_county_geojson_rows",
        lambda _db, **kwargs: [
            {
                "location_id": "01001",
                "geoid": "01001",
                "name": "Autauga",
                "statefp": "01",
                "countyfp": "001",
                "state_abbr": "AL",
                "state_desc": "Alabama",
                "county_name": "Autauga",
                "county_fips": "01001",
                "designated": True,
                "value": 6,
                "geometry": {"type": "Polygon", "coordinates": []},
            },
            {
                "location_id": "01003",
                "geoid": "01003",
                "name": "Baldwin",
                "statefp": "01",
                "countyfp": "003",
                "state_abbr": "AL",
                "state_desc": "Alabama",
                "county_name": "Baldwin",
                "county_fips": "01003",
                "designated": True,
                "value": 20,
                "geometry": {"type": "Polygon", "coordinates": []},
            },
            {
                "location_id": "01005",
                "geoid": "01005",
                "name": "Barbour",
                "statefp": "01",
                "countyfp": "005",
                "state_abbr": "AL",
                "state_desc": "Alabama",
                "county_name": "Barbour",
                "county_fips": "01005",
                "designated": False,
                "value": 20,
                "geometry": {"type": "Polygon", "coordinates": []},
            },
        ],
    )

    payload = hpsa_router.get_hpsa_counties_geojson(domain="mh", db=_DummySession())

    assert payload["type"] == "FeatureCollection"
    assert payload["metadata"]["domain"] == "mh"
    assert payload["metadata"]["quartiles"]["n_counties"] == 100
    tiers = {row["properties"]["county_fips"]: row["properties"]["tier"] for row in payload["features"]}
    assert tiers["01001"] == 1
    assert tiers["01003"] == 4
    assert tiers["01005"] is None


def test_hpsa_counties_geojson_forwards_bbox_bounds(monkeypatch):
    monkeypatch.setattr(hpsa_router, "_ensure_hpsa_county_geojson_tables", lambda _db: None)
    monkeypatch.setattr(hpsa_router, "fetch_hpsa_domain_quartiles", lambda _db, _domain: None)

    captured: dict[str, object] = {}

    def _fake_fetch(_db, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(hpsa_router, "fetch_hpsa_county_geojson_rows", _fake_fetch)

    payload = hpsa_router.get_hpsa_counties_geojson(
        domain="pc",
        bbox="-90,30,-89,31",
        db=_DummySession(),
    )

    assert payload["type"] == "FeatureCollection"
    assert captured["bbox_bounds"] == (-90.0, 30.0, -89.0, 31.0)


def test_hpsa_counties_geojson_invalid_bbox_returns_400():
    with pytest.raises(HTTPException) as exc:
        hpsa_router.get_hpsa_counties_geojson(
            domain="pc",
            bbox="bad,bbox",
            db=_DummySession(),
        )
    assert exc.value.status_code == 400
    assert "Invalid bbox format" in str(exc.value.detail)


def test_hpsa_counties_geojson_invalid_domain_returns_400():
    with pytest.raises(HTTPException) as exc:
        hpsa_router.get_hpsa_counties_geojson(
            domain="invalid",  # type: ignore[arg-type]
            db=_DummySession(),
        )
    assert exc.value.status_code == 400
    assert "domain must be one of pc, mh, dh" in str(exc.value.detail)
