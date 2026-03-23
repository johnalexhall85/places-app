from __future__ import annotations

import math

from app.services import chip_funding_model
from app.services.chip_funding_model import CHIPFundingCacheContext, CHIPFundingModel


def test_chip_funding_model_calculates_raw_and_normalized_state_metrics(monkeypatch) -> None:
    model = CHIPFundingModel()
    monkeypatch.setattr(
        chip_funding_model,
        "fetch_state_normalization_lookup",
        lambda *_args, **_kwargs: {
            "AL": {
                "normalized_amount": 120.0,
                "normalization_factor": 0.6,
                "normalized_amount_type": "observed_cdc_profile_aligned",
                "normalization_method": "funding_scope_reconstruction_calibration_layer",
                "funding_stream_logic_version": "scope_v5",
                "status_label": "Profile-aligned",
                "methodology_version": "profile_scope_v5",
                "confidence_note": "trusted",
            },
            "CA": {
                "normalized_amount": 70.0,
                "normalization_factor": 0.7,
                "normalized_amount_type": "observed_cdc_profile_aligned",
                "normalization_method": "funding_scope_reconstruction_calibration_layer",
                "funding_stream_logic_version": "scope_v5",
                "status_label": "Profile-aligned",
                "methodology_version": "profile_scope_v5",
                "confidence_note": "trusted",
            },
        },
    )

    cache_context = CHIPFundingCacheContext(
        scope="map",
        geography_level="state",
        fiscal_year=2022,
        time_aggregation="single_fiscal_year",
        funding_type="total_cdc_funding",
        funding_mode="chip_normalized",
        program_area=None,
        mechanism=None,
        recipient_type=None,
    )
    mode_context = model.build_mode_context(None, cache_context=cache_context)

    rows = [
        {"geography_id": "AL", "state_code": "AL", "raw_total_funding_amount": 200.0, "population": 10.0},
        {"geography_id": "CA", "state_code": "CA", "raw_total_funding_amount": 100.0, "population": 20.0},
    ]

    transformed = model.calculate_many(rows, cache_context=cache_context, mode_context=mode_context)

    assert transformed[0]["raw_total_funding"] == 200.0
    assert transformed[0]["chip_normalized_funding"] == 120.0
    assert transformed[0]["total_funding_amount"] == 120.0
    assert transformed[0]["funding_mode_effective"] == "chip_normalized"
    assert math.isclose(transformed[0]["share_national_pct"], (120.0 / 190.0) * 100, rel_tol=1e-9)
    assert transformed[1]["raw_total_funding"] == 100.0
    assert transformed[1]["chip_normalized_funding"] == 70.0
    assert transformed[1]["total_funding_amount"] == 70.0


def test_chip_funding_model_falls_back_to_raw_when_normalized_mode_is_incompatible() -> None:
    model = CHIPFundingModel()
    cache_context = CHIPFundingCacheContext(
        scope="map",
        geography_level="state",
        fiscal_year=2022,
        time_aggregation="single_fiscal_year",
        funding_type="total_cdc_funding",
        funding_mode="chip_normalized",
        program_area="public_health_preparedness_and_response",
        mechanism=None,
        recipient_type=None,
    )
    mode_context = model.build_mode_context(None, cache_context=cache_context)
    rows = [{"geography_id": "AL", "state_code": "AL", "raw_total_funding_amount": 200.0, "population": 10.0}]

    transformed = model.calculate_many(rows, cache_context=cache_context, mode_context=mode_context)

    assert mode_context.effective_mode == "raw_total"
    assert mode_context.normalization_supported is False
    assert "statewide overall CDC totals" in str(mode_context.normalization_note)
    assert transformed[0]["total_funding_amount"] == 200.0
    assert transformed[0]["chip_normalized_funding"] is None
    assert transformed[0]["funding_mode_effective"] == "raw_total"


def test_chip_funding_model_scales_counties_with_state_factor(monkeypatch) -> None:
    model = CHIPFundingModel()
    monkeypatch.setattr(
        chip_funding_model,
        "fetch_state_normalization_lookup",
        lambda *_args, **_kwargs: {
            "AL": {
                "normalized_amount": 120.0,
                "normalization_factor": 0.6,
                "normalized_amount_type": "observed_cdc_profile_aligned",
                "normalization_method": "funding_scope_reconstruction_calibration_layer",
                "funding_stream_logic_version": "scope_v5",
                "status_label": "Profile-aligned",
                "methodology_version": "profile_scope_v5",
                "confidence_note": "trusted",
            }
        },
    )

    cache_context = CHIPFundingCacheContext(
        scope="map",
        geography_level="county",
        fiscal_year=2022,
        time_aggregation="single_fiscal_year",
        funding_type="total_cdc_funding",
        funding_mode="chip_normalized",
        program_area=None,
        mechanism=None,
        recipient_type=None,
    )
    mode_context = model.build_mode_context(None, cache_context=cache_context)
    rows = [
        {"geography_id": "01001", "state_code": "AL", "raw_total_funding_amount": 50.0, "population": 10.0},
        {"geography_id": "01003", "state_code": "AL", "raw_total_funding_amount": 150.0, "population": 30.0},
    ]

    transformed = model.calculate_many(rows, cache_context=cache_context, mode_context=mode_context)

    assert transformed[0]["chip_normalized_funding"] == 30.0
    assert transformed[1]["chip_normalized_funding"] == 90.0
    assert transformed[0]["total_funding_amount"] == 30.0
    assert transformed[1]["total_funding_amount"] == 90.0
    assert math.isclose(transformed[0]["share_national_pct"], 25.0, rel_tol=1e-9)
    assert math.isclose(transformed[1]["share_national_pct"], 75.0, rel_tol=1e-9)


def test_chip_funding_model_supports_v11_normalized_mode(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_lookup(*_args, **kwargs):
        captured.update(kwargs)
        return {
            "AL": {
                "normalized_amount": 180.0,
                "normalization_factor": 0.9,
                "normalized_amount_type": "state_profile_v11_emergency_classification_aligned",
                "normalization_method": "v1_1_emergency_classification_state_profile_alignment",
                "funding_stream_logic_version": "chip_state_profile_v1_1_emergency_classification",
                "status_label": "State-profile aligned v1.1",
                "methodology_version": "v1.1",
                "confidence_note": "v1.1 benchmark",
                "core_public_health_amount": 120.0,
                "emergency_public_health_amount": 60.0,
            }
        }

    monkeypatch.setattr(chip_funding_model, "fetch_state_normalization_lookup", fake_lookup)

    model = CHIPFundingModel()
    cache_context = CHIPFundingCacheContext(
        scope="map",
        geography_level="state",
        fiscal_year=2025,
        time_aggregation="single_fiscal_year",
        funding_type="total_cdc_funding",
        funding_mode="chip_normalized_v1_1",
        program_area=None,
        mechanism=None,
        recipient_type=None,
    )
    mode_context = model.build_mode_context(None, cache_context=cache_context)
    rows = [{"geography_id": "AL", "state_code": "AL", "raw_total_funding_amount": 200.0, "population": 10.0}]

    transformed = model.calculate_many(rows, cache_context=cache_context, mode_context=mode_context)

    assert captured["lookup_variant"] == "v1_1_emergency_classification"
    assert mode_context.effective_mode == "chip_normalized_v1_1"
    assert mode_context.funding_mode_label == "CHIP Normalized Funding v1.1"
    assert transformed[0]["funding_mode_effective"] == "chip_normalized_v1_1"
    assert transformed[0]["chip_normalized_funding"] == 180.0
    assert transformed[0]["total_funding_amount"] == 180.0
    assert transformed[0]["normalization_status_label"] == "State-profile aligned v1.1"
