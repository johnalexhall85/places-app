from __future__ import annotations

from app.cdc_funding import intelligence as cdc_intelligence
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


def test_cdc_map_router_uses_new_filter_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_map_geojson(*_args, **kwargs):
        captured.update(kwargs)
        return {"type": "FeatureCollection", "features": [], "meta": {}}

    monkeypatch.setattr(cdc_intelligence, "fetch_map_geojson", fake_fetch_map_geojson)

    payload = cdc_router.get_cdc_funding_map(
        fiscal_year=2025,
        metric="funding_per_capita",
        funding_type="emergency_response",
        cdc_center="public_health_preparedness_and_response",
        mechanism="cooperative_agreements",
        recipient_type="state_governments",
        geography_level="state",
        time_aggregation="single_fiscal_year",
        normalize=True,
        db=None,
    )

    assert payload["type"] == "FeatureCollection"
    assert captured["fiscal_year"] == 2025
    assert captured["metric"] == "funding_per_capita"
    assert captured["funding_type"] == "emergency_response"
    assert captured["cdc_center"] == "public_health_preparedness_and_response"
    assert captured["geography_level"] == "state"
    assert "normalize" not in captured


def test_cdc_legend_router_maps_legacy_appropriation_filter(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_legend_stats(*_args, **kwargs):
        captured.update(kwargs)
        return {"bins": [], "note": None}

    monkeypatch.setattr(cdc_intelligence, "fetch_legend_stats", fake_fetch_legend_stats)

    payload = cdc_router.get_cdc_funding_legend(
        geography="county",
        metric="total_funding",
        appropriation_type="regular",
        db=None,
    )

    assert payload["bins"] == []
    assert captured["funding_type"] == "non_emergency_program"
    assert captured["geography_level"] == "county"


def test_cdc_profile_summary_router_forwards_new_state_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_state_profile_summary(*_args, **kwargs):
        captured.update(kwargs)
        return {"state_code": "AL", "total_funding": 1000}

    monkeypatch.setattr(cdc_intelligence, "fetch_state_profile_summary", fake_fetch_state_profile_summary)

    payload = cdc_router.get_cdc_state_profile_summary(
        state="AL",
        fiscal_year=2025,
        metric="share_national",
        funding_type="total_cdc_funding",
        cdc_center="public_health_scientific_services",
        mechanism="grants",
        recipient_type="state_governments",
        time_aggregation="single_fiscal_year",
        normalize=True,
        db=None,
    )

    assert payload["state_code"] == "AL"
    assert captured["state"] == "AL"
    assert captured["fiscal_year"] == 2025
    assert captured["metric"] == "share_national"
    assert captured["funding_type"] == "total_cdc_funding"
    assert captured["cdc_center"] == "public_health_scientific_services"
    assert captured["mechanism"] == "grants"
    assert captured["recipient_type"] == "state_governments"


def test_cdc_profile_details_router_keeps_legacy_detail_contract(monkeypatch) -> None:
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
