from __future__ import annotations

from app.cdc_funding import router as cdc_router
from app.cdc_funding import services as cdc_services


def test_cdc_methodology_summary_router_returns_service_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        cdc_services,
        "fetch_methodology_display_summary",
        lambda: {"current_frozen_version": "profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics_calibration_v1"},
    )

    payload = cdc_router.get_cdc_funding_methodology_summary()

    assert payload["current_frozen_version"] == "profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics_calibration_v1"


def test_cdc_map_router_forwards_normalize_query(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_map_geojson(*_args, **kwargs):
        captured.update(kwargs)
        return {"type": "FeatureCollection", "features": [], "meta": {}}

    monkeypatch.setattr(cdc_services, "fetch_map_geojson", fake_fetch_map_geojson)

    payload = cdc_router.get_cdc_funding_map(
        basis="prime",
        geography="state",
        metric="fy_obligated",
        normalize=True,
        db=None,
    )

    assert payload["type"] == "FeatureCollection"
    assert captured["normalize"] is True


def test_cdc_legend_router_forwards_normalize_query(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_legend_stats(*_args, **kwargs):
        captured.update(kwargs)
        return {"bins": [], "note": None}

    monkeypatch.setattr(cdc_services, "fetch_legend_stats", fake_fetch_legend_stats)

    payload = cdc_router.get_cdc_funding_legend(
        basis="prime",
        geography="state",
        metric="fy_obligated",
        normalize=False,
        db=None,
    )

    assert payload["bins"] == []
    assert captured["normalize"] is False


def test_cdc_profile_summary_router_forwards_state_and_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_state_profile_summary(*_args, **kwargs):
        captured.update(kwargs)
        return {"state_code": "AL", "total_funding": 1000}

    monkeypatch.setattr(cdc_services, "fetch_state_profile_summary", fake_fetch_state_profile_summary)

    payload = cdc_router.get_cdc_state_profile_summary(
        state="AL",
        basis="prime",
        funding_geography_mode="recipient_location",
        appropriation_type="regular",
        assistance_type="Project Grants",
        fy=2025,
        normalize=True,
        funding_office="Office B",
        db=None,
    )

    assert payload["state_code"] == "AL"
    assert captured["state"] == "AL"
    assert captured["basis"] == "prime"
    assert captured["appropriation_type"] == "regular"
    assert captured["fiscal_year"] == 2025
    assert captured["normalize"] is True
    assert captured["funding_office"] == "Office B"


def test_cdc_profile_details_router_forwards_search_and_sort(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_state_profile_details(*_args, **kwargs):
        captured.update(kwargs)
        return {"total_rows": 0, "rows": []}

    monkeypatch.setattr(cdc_services, "fetch_state_profile_details", fake_fetch_state_profile_details)

    payload = cdc_router.get_cdc_state_profile_details(
        state="GA",
        basis="subaward",
        normalize=False,
        q="vaccines",
        page=2,
        page_size=50,
        sort_by="category",
        sort_dir="asc",
        db=None,
    )

    assert payload["rows"] == []
    assert captured["state"] == "GA"
    assert captured["basis"] == "subaward"
    assert captured["normalize"] is False
    assert captured["q"] == "vaccines"
    assert captured["page"] == 2
    assert captured["page_size"] == 50
    assert captured["sort_by"] == "category"
    assert captured["sort_dir"] == "asc"
