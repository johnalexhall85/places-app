from __future__ import annotations

from collections.abc import Sequence

from app.cdc_funding import services as cdc_services


class _FakeMappingsResult:
    def __init__(self, rows: Sequence[dict[str, object]]) -> None:
        self._rows = list(rows)

    def mappings(self) -> "_FakeMappingsResult":
        return self

    def all(self) -> list[dict[str, object]]:
        return list(self._rows)


class _FakeDb:
    def __init__(self, rows: Sequence[dict[str, object]]) -> None:
        self.rows = list(rows)
        self.statements: list[str] = []

    def execute(self, statement, _params=None) -> _FakeMappingsResult:
        self.statements.append(str(statement))
        return _FakeMappingsResult(self.rows)


def test_fetch_legend_stats_county_normalization_sums_visible_rows(monkeypatch) -> None:
    fake_db = _FakeDb(
        [
            {
                "geography_id": "06001",
                "state_code": "CA",
                "metric_value": 100.0,
                "metric_per_capita": 1.0,
                "population": 100.0,
                "funding_per_capita": 1.0,
                "fy_obligated_amount": 100.0,
                "fy_outlayed_amount_estimated": 0.0,
                "transaction_count": 1,
                "distinct_award_count": 1,
                "total_funding_amount": 100.0,
                "total_obligated_amount": 100.0,
                "total_outlayed_amount": 0.0,
                "award_count": 1,
                "total_subaward_amount": 0.0,
                "subaward_count": 0,
            },
            {
                "geography_id": "06013",
                "state_code": "CA",
                "metric_value": 300.0,
                "metric_per_capita": 3.0,
                "population": 100.0,
                "funding_per_capita": 3.0,
                "fy_obligated_amount": 300.0,
                "fy_outlayed_amount_estimated": 0.0,
                "transaction_count": 2,
                "distinct_award_count": 2,
                "total_funding_amount": 300.0,
                "total_obligated_amount": 300.0,
                "total_outlayed_amount": 0.0,
                "award_count": 2,
                "total_subaward_amount": 0.0,
                "subaward_count": 0,
            },
        ]
    )

    monkeypatch.setattr(cdc_services, "_ensure_required_tables", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cdc_services,
        "usaspending_normalization_compatibility",
        lambda **_kwargs: (True, None),
    )
    monkeypatch.setattr(
        cdc_services,
        "fetch_state_normalization_lookup",
        lambda *_args, **_kwargs: {
            "CA": {
                "normalized_amount": 999.0,
                "normalization_factor": 0.5,
                "normalized_amount_type": "estimated_cdc_profile_aligned",
                "normalization_method": "funding_scope_reconstruction_calibration_layer",
                "funding_stream_logic_version": "logic-test",
                "status_label": "Profile-aligned estimate",
                "methodology_version": "test-version",
            }
        },
    )
    monkeypatch.setattr(cdc_services, "_fetch_national_summary", lambda *_args, **_kwargs: None)

    payload = cdc_services.fetch_legend_stats(
        fake_db,
        basis="prime",
        geography="county",
        funding_geography_mode="recipient_location",
        metric="fy_obligated",
        display_mode="total",
        appropriation_type="all",
        fiscal_year=2024,
        normalize=True,
    )

    assert payload["normalization_applied"] is True
    assert payload["total_visible_dollars"] == 200.0
    assert payload["normalization_method"] == "funding_scope_reconstruction_calibration_layer"
    assert payload["funding_stream_logic_version"] == "logic-test"
    assert "c.state_abbr AS state_code" in fake_db.statements[0]


def test_state_profile_normalization_context_scales_amounts(monkeypatch) -> None:
    monkeypatch.setattr(
        cdc_services,
        "usaspending_normalization_compatibility",
        lambda **_kwargs: (True, None),
    )
    monkeypatch.setattr(
        cdc_services,
        "fetch_state_normalization_lookup",
        lambda *_args, **_kwargs: {
            "AL": {
                "normalized_amount": 180.0,
                "normalization_factor": 1.5,
                "normalized_amount_type": "observed_cdc_profile_aligned",
                "normalization_method": "funding_scope_reconstruction_calibration_layer",
                "funding_stream_logic_version": "logic-test",
                "status_label": "Observed profile-aligned total",
                "methodology_version": "test-version",
            }
        },
    )

    normalization = cdc_services._build_state_profile_normalization_context(  # noqa: SLF001
        None,
        normalize=True,
        state_code="AL",
        basis="prime",
        funding_geography_mode="recipient_location",
        appropriation_type="all",
        assistance_type=None,
        fiscal_year=2025,
        awarding_office=None,
        funding_office=None,
        center=None,
        raw_total_funding=120.0,
    )

    assert normalization["normalization_applied"] is True
    assert normalization["data_mode_label"] == "Normalized data"
    assert normalization["normalized_total_funding"] == 180.0
    assert cdc_services._apply_state_profile_normalized_amount(60.0, normalization) == 90.0  # noqa: SLF001


def test_state_profile_normalization_context_requires_explicit_fiscal_year(monkeypatch) -> None:
    monkeypatch.setattr(
        cdc_services,
        "usaspending_normalization_compatibility",
        lambda **_kwargs: (True, None),
    )

    normalization = cdc_services._build_state_profile_normalization_context(  # noqa: SLF001
        None,
        normalize=True,
        state_code="AL",
        basis="prime",
        funding_geography_mode="recipient_location",
        appropriation_type="all",
        assistance_type=None,
        fiscal_year=None,
        awarding_office=None,
        funding_office=None,
        center=None,
        raw_total_funding=120.0,
    )

    assert normalization["normalization_applied"] is False
    assert normalization["data_mode_label"] == "Raw obligations"
    assert "explicit fiscal year" in str(normalization["normalization_note"]).lower()
