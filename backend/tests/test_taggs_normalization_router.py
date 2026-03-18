from __future__ import annotations

from app.taggs import router as taggs_router
from app.taggs import services as taggs_services


def test_taggs_map_router_forwards_normalize_query(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_state_map_geojson(*_args, **kwargs):
        captured.update(kwargs)
        return {"type": "FeatureCollection", "features": [], "meta": {}}

    monkeypatch.setattr(taggs_services, "fetch_state_map_geojson", fake_fetch_state_map_geojson)

    payload = taggs_router.get_taggs_state_map(metric="total_funding", normalize=True, db=None)

    assert payload["type"] == "FeatureCollection"
    assert captured["normalize"] is True


def test_taggs_legend_router_forwards_normalize_query(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_state_legend(*_args, **kwargs):
        captured.update(kwargs)
        return {"bins": [], "note": None}

    monkeypatch.setattr(taggs_services, "fetch_state_legend", fake_fetch_state_legend)

    payload = taggs_router.get_taggs_state_legend(metric="total_funding", normalize=False, db=None)

    assert payload["bins"] == []
    assert captured["normalize"] is False


def test_taggs_can_mapping_status_router_forwards_to_service(monkeypatch) -> None:
    def fake_fetch_can_mapping_status(*_args, **_kwargs):
        return {"status": "ready", "mapped_can_count": 10}

    monkeypatch.setattr(taggs_services, "fetch_can_mapping_status", fake_fetch_can_mapping_status)

    payload = taggs_router.get_taggs_can_mapping_status(db=None)

    assert payload["status"] == "ready"
    assert payload["mapped_can_count"] == 10
