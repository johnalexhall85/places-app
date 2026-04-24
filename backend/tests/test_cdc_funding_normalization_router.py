from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.cdc_funding import intelligence as cdc_intelligence
from app.cdc_funding import budget_grounded
from app.cdc_funding import canonical
from app.cdc_funding import router as cdc_router
from app.cdc_funding import services as cdc_services
from app.funding_models import runtime as funding_model_runtime


def _build_test_client() -> TestClient:
    app = FastAPI()
    app.include_router(cdc_router.router)
    app.dependency_overrides[cdc_router.get_db] = lambda: None
    return TestClient(app)


def test_cdc_methodology_summary_router_returns_service_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        cdc_services,
        "fetch_methodology_display_summary",
        lambda: {"current_frozen_version": "profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics_calibration_v1"},
    )

    payload = cdc_router.get_cdc_funding_methodology_summary()

    assert payload["current_frozen_version"] == "profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics_calibration_v1"


def test_cdc_map_router_forwards_explicit_funding_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_map_geojson(*_args, **kwargs):
        captured.update(kwargs)
        return {"type": "FeatureCollection", "features": [], "meta": {}}

    monkeypatch.setattr(cdc_intelligence, "fetch_map_geojson", fake_fetch_map_geojson)

    payload = cdc_router.get_cdc_funding_map(
        fiscal_year=2025,
        metric="funding_per_capita",
        funding_type="emergency_response",
        funding_mode="raw_total",
        cdc_center="public_health_preparedness_and_response",
        mechanism="cooperative_agreements",
        recipient_type="state_governments",
        geography_level="state",
        time_aggregation="single_fiscal_year",
        db=None,
    )

    assert payload["type"] == "FeatureCollection"
    assert captured["fiscal_year"] == 2025
    assert captured["metric"] == "funding_per_capita"
    assert captured["funding_type"] == "emergency_response"
    assert captured["funding_mode"] == "raw_total"
    assert captured["cdc_center"] == "public_health_preparedness_and_response"
    assert captured["geography_level"] == "state"


def test_cdc_map_router_defaults_to_canonical_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(cdc_router, "is_custom_funding_mode", lambda *_args, **_kwargs: False)

    def fake_fetch_map_geojson(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "type": "FeatureCollection",
            "features": [],
            "meta": {"funding_mode_label": canonical.FUNDING_MODEL_LABEL},
        }

    monkeypatch.setattr(canonical, "fetch_map_geojson", fake_fetch_map_geojson)

    payload = cdc_router.get_cdc_funding_map(
        fiscal_year=2026,
        metric="total_funding",
        funding_type="mandatory_only",
        include_mandatory=True,
        include_emergency=False,
        include_supplemental=False,
        include_pphf=True,
        include_transfers=True,
        review_mode="all_master_universe",
        geography_level="state",
        bbox="-125,24,-66,49",
        db=None,
    )

    assert payload["meta"]["funding_mode_label"] == canonical.FUNDING_MODEL_LABEL
    assert captured["fiscal_year"] == 2026
    assert captured["funding_type"] == "mandatory_only"
    assert captured["include_mandatory"] is True
    assert captured["include_emergency"] is False
    assert captured["include_supplemental"] is False
    assert captured["include_pphf"] is True
    assert captured["include_transfers"] is True
    assert captured["review_mode"] == "all_master_universe"
    assert captured["geography_level"] == "state"
    assert captured["bbox"] == "-125,24,-66,49"


def test_cdc_map_router_dispatches_published_custom_funding_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(cdc_router, "is_custom_funding_mode", lambda *_args, **_kwargs: True)

    def fake_fetch_map_geojson(*_args, **kwargs):
        captured.update(kwargs)
        return {"type": "FeatureCollection", "features": [], "meta": {"funding_mode_label": "Custom"}}

    monkeypatch.setattr(funding_model_runtime, "fetch_map_geojson", fake_fetch_map_geojson)

    payload = cdc_router.get_cdc_funding_map(
        fiscal_year=2025,
        metric="total_funding",
        funding_mode="chip_v1_1_emergency",
        geography_level="state",
        db=None,
    )

    assert payload["meta"]["funding_mode_label"] == "Custom"
    assert captured["funding_mode"] == "chip_v1_1_emergency"
    assert captured["geography_level"] == "state"


def test_cdc_map_router_dispatches_budget_grounded_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_map_geojson(*_args, **kwargs):
        captured.update(kwargs)
        return {"type": "FeatureCollection", "features": [], "meta": {"funding_mode_label": budget_grounded.FUNDING_MODEL_LABEL}}

    monkeypatch.setattr(budget_grounded, "fetch_map_geojson", fake_fetch_map_geojson)

    payload = cdc_router.get_cdc_funding_map(
        fiscal_year=2025,
        metric="total_funding",
        funding_model="budget_grounded_v1",
        include_mandatory=False,
        include_emergency=True,
        include_supplemental=True,
        include_pphf=False,
        include_transfers=False,
        review_mode="analyst_only",
        geography_level="state",
        db=None,
    )

    assert payload["meta"]["funding_mode_label"] == budget_grounded.FUNDING_MODEL_LABEL
    assert captured["fiscal_year"] == 2025
    assert captured["include_mandatory"] is False
    assert captured["include_emergency"] is True
    assert captured["include_supplemental"] is True
    assert captured["include_pphf"] is False
    assert captured["include_transfers"] is False
    assert captured["review_mode"] == "analyst_only"
    assert captured["geography_level"] == "state"


def test_cdc_map_router_accepts_all_master_universe_review_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_map_geojson(*_args, **kwargs):
        captured.update(kwargs)
        return {"type": "FeatureCollection", "features": [], "meta": {}}

    monkeypatch.setattr(budget_grounded, "fetch_map_geojson", fake_fetch_map_geojson)

    payload = cdc_router.get_cdc_funding_map(
        fiscal_year=2024,
        metric="total_funding",
        funding_model="budget_grounded_v1",
        review_mode="all_master_universe",
        geography_level="state",
        db=None,
    )

    assert payload["type"] == "FeatureCollection"
    assert captured["review_mode"] == "all_master_universe"


def test_cdc_legend_router_maps_legacy_appropriation_filter_and_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_legend_stats(*_args, **kwargs):
        captured.update(kwargs)
        return {"bins": [], "note": None}

    monkeypatch.setattr(cdc_intelligence, "fetch_legend_stats", fake_fetch_legend_stats)

    payload = cdc_router.get_cdc_funding_legend(
        geography="county",
        metric="total_funding",
        appropriation_type="regular",
        funding_mode="chip_normalized",
        db=None,
    )

    assert payload["bins"] == []
    assert captured["funding_type"] == "non_emergency_program"
    assert captured["funding_mode"] == "chip_normalized"
    assert captured["geography_level"] == "county"


def test_cdc_legend_router_forwards_bbox_to_canonical_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(cdc_router, "is_custom_funding_mode", lambda *_args, **_kwargs: False)

    def fake_fetch_legend_stats(*_args, **kwargs):
        captured.update(kwargs)
        return {"bins": [], "note": "ok"}

    monkeypatch.setattr(canonical, "fetch_legend_stats", fake_fetch_legend_stats)

    payload = cdc_router.get_cdc_funding_legend(
        geography_level="county",
        fiscal_year=2025,
        funding_model="canonical_v1",
        review_mode="all_master_universe",
        bbox="-180,-24,21,81",
        db=None,
    )

    assert payload["bins"] == []
    assert captured["geography_level"] == "county"
    assert captured["bbox"] == "-180,-24,21,81"
    assert captured["review_mode"] == "all_master_universe"


def test_cdc_public_map_route_exists_and_returns_shape(monkeypatch) -> None:
    monkeypatch.setattr(cdc_router, "is_custom_funding_mode", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        canonical,
        "fetch_map_geojson",
        lambda *_args, **_kwargs: {"type": "FeatureCollection", "features": [], "meta": {"funding_mode_label": canonical.FUNDING_MODEL_LABEL}},
    )

    client = _build_test_client()
    response = client.get("/api/cdc/funding/map?funding_model=canonical_v1")

    assert response.status_code == 200
    assert response.json()["type"] == "FeatureCollection"


def test_cdc_public_legend_route_exists_and_returns_shape(monkeypatch) -> None:
    monkeypatch.setattr(cdc_router, "is_custom_funding_mode", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        canonical,
        "fetch_legend_stats",
        lambda *_args, **_kwargs: {"bins": [], "note": "ok", "mapped_geographies": 0, "noDataCount": 0},
    )

    client = _build_test_client()
    response = client.get("/api/cdc/funding/legend?funding_model=canonical_v1")

    assert response.status_code == 200
    assert response.json()["bins"] == []


def test_cdc_public_filters_route_exists_and_returns_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        cdc_intelligence,
        "list_filter_options",
        lambda *_args, **_kwargs: {
            "metric_options": [],
            "fiscal_year_options": [{"value": "2025", "label": "FY2025"}],
            "default_fiscal_year": 2025,
            "default_funding_mode": canonical.FUNDING_MODEL_KEY,
        },
    )

    client = _build_test_client()
    response = client.get("/api/cdc/funding/filters")

    assert response.status_code == 200
    payload = response.json()
    assert payload["default_fiscal_year"] == 2025
    assert payload["default_funding_mode"] == canonical.FUNDING_MODEL_KEY


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
        funding_mode="chip_normalized",
        cdc_center="public_health_scientific_services",
        mechanism="grants",
        recipient_type="state_governments",
        time_aggregation="single_fiscal_year",
        db=None,
    )

    assert payload["state_code"] == "AL"
    assert captured["state"] == "AL"
    assert captured["fiscal_year"] == 2025
    assert captured["metric"] == "share_national"
    assert captured["funding_type"] == "total_cdc_funding"
    assert captured["funding_mode"] == "chip_normalized"
    assert captured["cdc_center"] == "public_health_scientific_services"
    assert captured["mechanism"] == "grants"
    assert captured["recipient_type"] == "state_governments"


def test_cdc_profile_overview_router_forwards_new_state_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_state_profile_overview(*_args, **kwargs):
        captured.update(kwargs)
        return {"summary": {}, "categories": {}, "subcategories": {}}

    monkeypatch.setattr(cdc_intelligence, "fetch_state_profile_overview", fake_fetch_state_profile_overview)

    payload = cdc_router.get_cdc_state_profile_overview(
        state="AL",
        fiscal_year=2025,
        metric="funding_per_capita",
        funding_type="emergency_response",
        funding_mode="chip_normalized",
        cdc_center="public_health_preparedness_and_response",
        mechanism="cooperative_agreements",
        recipient_type="state_governments",
        time_aggregation="single_fiscal_year",
        db=None,
    )

    assert payload == {"summary": {}, "categories": {}, "subcategories": {}}
    assert captured["state"] == "AL"
    assert captured["fiscal_year"] == 2025
    assert captured["metric"] == "funding_per_capita"
    assert captured["funding_type"] == "emergency_response"
    assert captured["funding_mode"] == "chip_normalized"
    assert captured["cdc_center"] == "public_health_preparedness_and_response"
    assert captured["mechanism"] == "cooperative_agreements"
    assert captured["recipient_type"] == "state_governments"


def test_cdc_profile_details_router_maps_funding_mode_to_normalize(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_state_profile_details(*_args, **kwargs):
        captured.update(kwargs)
        return {"total_rows": 0, "rows": []}

    monkeypatch.setattr(cdc_services, "fetch_state_profile_details", fake_fetch_state_profile_details)

    payload = cdc_router.get_cdc_state_profile_details(
        state="GA",
        funding_mode="raw_total",
        basis="subaward",
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
    assert captured["normalization_funding_mode"] == "raw_total"
    assert captured["q"] == "vaccines"
    assert captured["page"] == 2
    assert captured["page_size"] == 50
    assert captured["sort_by"] == "category"
    assert captured["sort_dir"] == "asc"


def test_cdc_profile_details_router_accepts_fiscal_year_alias(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_state_profile_details(*_args, **kwargs):
        captured.update(kwargs)
        return {"total_rows": 0, "rows": []}

    monkeypatch.setattr(cdc_services, "fetch_state_profile_details", fake_fetch_state_profile_details)

    payload = cdc_router.get_cdc_state_profile_details(
        state="GA",
        funding_mode="chip_normalized",
        fiscal_year=2024,
        db=None,
    )

    assert payload["rows"] == []
    assert captured["fiscal_year"] == 2024
    assert captured["normalize"] is True
    assert captured["normalization_funding_mode"] == "chip_normalized"


def test_cdc_profile_details_router_defaults_to_canonical_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_state_profile_details(*_args, **kwargs):
        captured.update(kwargs)
        return {"total_rows": 0, "rows": []}

    monkeypatch.setattr(cdc_router, "is_custom_funding_mode", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(canonical, "fetch_state_profile_details", fake_fetch_state_profile_details)

    payload = cdc_router.get_cdc_state_profile_details(
        state="GA",
        db=None,
    )

    assert payload["rows"] == []
    assert captured["state"] == "GA"
    assert captured["funding_type"] is None


def test_cdc_profile_details_router_dispatches_custom_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(cdc_router, "is_custom_funding_mode", lambda *_args, **_kwargs: True)

    def fake_fetch_state_profile_details(*_args, **kwargs):
        captured.update(kwargs)
        return {"total_rows": 0, "rows": [], "funding_mode_effective": "chip_v1_1_emergency"}

    monkeypatch.setattr(funding_model_runtime, "fetch_state_profile_details", fake_fetch_state_profile_details)

    payload = cdc_router.get_cdc_state_profile_details(
        state="GA",
        funding_mode="chip_v1_1_emergency",
        fiscal_year=2025,
        db=None,
    )

    assert payload["rows"] == []
    assert captured["state"] == "GA"
    assert captured["fiscal_year"] == 2025
    assert captured["funding_mode"] == "chip_v1_1_emergency"


def test_cdc_profile_details_router_dispatches_budget_grounded_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_state_profile_details(*_args, **kwargs):
        captured.update(kwargs)
        return {"total_rows": 0, "rows": [], "funding_mode_effective": budget_grounded.FUNDING_MODEL_KEY}

    monkeypatch.setattr(budget_grounded, "fetch_state_profile_details", fake_fetch_state_profile_details)

    payload = cdc_router.get_cdc_state_profile_details(
        state="GA",
        funding_model="budget_grounded_v1",
        fiscal_year=2025,
        funding_type="mandatory_only",
        include_mandatory=True,
        include_emergency=False,
        include_supplemental=False,
        include_pphf=True,
        include_transfers=True,
        review_mode="trusted_auto",
        db=None,
    )

    assert payload["rows"] == []
    assert captured["state"] == "GA"
    assert captured["fiscal_year"] == 2025
    assert captured["funding_type"] == "mandatory_only"
    assert captured["include_mandatory"] is True
    assert captured["include_emergency"] is False
    assert captured["include_supplemental"] is False
    assert captured["include_pphf"] is True
    assert captured["include_transfers"] is True
    assert captured["review_mode"] == "trusted_auto"


def test_cdc_mode_diagnostics_router_forwards_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_mode_diagnostics(*_args, **kwargs):
        captured.update(kwargs)
        return {"rows": []}

    monkeypatch.setattr(cdc_intelligence, "fetch_mode_diagnostics", fake_fetch_mode_diagnostics)

    payload = cdc_router.get_cdc_funding_mode_diagnostics(
        fiscal_year=[2022, 2024],
        state=["AL", "CA"],
        db=None,
    )

    assert payload == {"rows": []}
    assert captured["fiscal_years"] == [2022, 2024]
    assert captured["states"] == ["AL", "CA"]
