from __future__ import annotations

import csv
from pathlib import Path

from app.cdc_funding import intelligence, router, v11_emergency
from app.recon import chip_emergency_classification_export


def test_support_status_only_enables_raw_total_without_subset_filters(monkeypatch) -> None:
    monkeypatch.setenv(v11_emergency.RAW_SOURCE_ENV, "v1_1_emergency_classification")

    enabled = v11_emergency.support_status(
        funding_mode="raw_total",
        funding_type="total_cdc_funding",
        cdc_center=None,
        program_area=None,
        mechanism=None,
        recipient_type=None,
    )
    disabled = v11_emergency.support_status(
        funding_mode="chip_normalized",
        funding_type="total_cdc_funding",
        cdc_center=None,
        program_area=None,
        mechanism=None,
        recipient_type=None,
    )
    filtered = v11_emergency.support_status(
        funding_mode="raw_total",
        funding_type="total_cdc_funding",
        cdc_center="NCIRD",
        program_area=None,
        mechanism=None,
        recipient_type=None,
    )

    assert enabled.enabled is True
    assert disabled.enabled is False
    assert disabled.reason == "non_raw_mode_uses_standard_normalization_path"
    assert filtered.enabled is False
    assert filtered.reason == "subset_filters_not_supported_for_v1_1_raw"


def test_intelligence_state_profile_overview_delegates_to_v11_when_enabled(monkeypatch) -> None:
    expected = {
        "summary": {"state_code": "AL", "funding_model_version": v11_emergency.MODEL_VERSION},
        "categories": {"rows": []},
        "subcategories": {"rows": []},
    }

    monkeypatch.setattr(
        v11_emergency,
        "support_status",
        lambda **_kwargs: v11_emergency.EmergencyStateProfileSupport(enabled=True, reason=None),
    )
    monkeypatch.setattr(v11_emergency, "fetch_state_profile_overview", lambda *_args, **_kwargs: expected)

    payload = intelligence.fetch_state_profile_overview(
        None,
        state="AL",
        fiscal_year=2025,
        metric="total_funding",
        funding_type="total_cdc_funding",
        funding_mode="raw_total",
        time_aggregation="single_fiscal_year",
    )

    assert payload == expected


def test_router_profile_details_uses_v11_export_when_enabled(monkeypatch) -> None:
    expected = {"rows": [{"record_id": "assistance:1"}], "funding_model_version": v11_emergency.MODEL_VERSION}
    monkeypatch.setattr(
        v11_emergency,
        "support_status",
        lambda **_kwargs: v11_emergency.EmergencyStateProfileSupport(enabled=True, reason=None),
    )
    monkeypatch.setattr(v11_emergency, "fetch_state_profile_details", lambda *_args, **_kwargs: expected)

    payload = router.get_cdc_state_profile_details(
        state="AL",
        funding_mode="raw_total",
        fiscal_year=2025,
        db=None,
    )

    assert payload == expected


def test_fetch_geography_rows_uses_v11_state_rollup_when_enabled(monkeypatch) -> None:
    filters = intelligence.FundingFilters(
        fiscal_year=2025,
        metric="total_funding",
        funding_type="total_cdc_funding",
        funding_mode="raw_total",
        program_area=None,
        mechanism=None,
        recipient_type=None,
        geography_level="state",
        time_aggregation="single_fiscal_year",
    )
    expected = [{"geography_id": "AL", "funding_model_version": v11_emergency.MODEL_VERSION}]
    monkeypatch.setattr(
        v11_emergency,
        "support_status",
        lambda **_kwargs: v11_emergency.EmergencyStateProfileSupport(enabled=True, reason=None),
    )
    monkeypatch.setattr(v11_emergency, "fetch_state_geography_rows", lambda *_args, **_kwargs: expected)

    rows = intelligence._fetch_geography_rows(  # noqa: SLF001
        None,
        filters,
        include_geometry=False,
        bbox=None,
        limit=100,
        scope="map",
    )

    assert rows == expected


def test_fetch_national_summary_row_uses_v11_when_enabled(monkeypatch) -> None:
    filters = intelligence.FundingFilters(
        fiscal_year=2025,
        metric="total_funding",
        funding_type="total_cdc_funding",
        funding_mode="raw_total",
        program_area=None,
        mechanism=None,
        recipient_type=None,
        geography_level="national",
        time_aggregation="single_fiscal_year",
    )
    expected = {"geography_id": "US", "funding_model_version": v11_emergency.MODEL_VERSION}
    monkeypatch.setattr(
        v11_emergency,
        "support_status",
        lambda **_kwargs: v11_emergency.EmergencyStateProfileSupport(enabled=True, reason=None),
    )
    monkeypatch.setattr(v11_emergency, "fetch_national_summary_row", lambda *_args, **_kwargs: expected)

    row = intelligence._fetch_national_summary_row(None, filters)  # noqa: SLF001

    assert row == expected


class _FakeResult:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict[str, object]]:
        return self._rows

    def keys(self) -> list[str]:
        if not self._rows:
            return []
        return list(self._rows[0].keys())


class _FakeConnection:
    def execute(self, _statement, _params=None):
        return _FakeResult(
            [
                {
                    "source_system": "assistance",
                    "source_transaction_id": "1",
                    "chip_funding_category": "core_cdc_program",
                    "chip_include_in_state_profile": True,
                }
            ]
        )

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class _FakeEngine:
    def connect(self) -> _FakeConnection:
        return _FakeConnection()


def test_emergency_classification_export_writes_all_three_csvs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(chip_emergency_classification_export, "create_engine", lambda *_args, **_kwargs: _FakeEngine())

    written = chip_emergency_classification_export.export_views(
        db_url="postgresql+psycopg://places:places@localhost:5432/places",
        output_dir=tmp_path,
        fiscal_year=2025,
        state="AL",
    )

    assert set(written) == {"all", "included", "centralized"}
    for export_name, path in written.items():
        assert path.exists(), export_name
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
        assert "chip_funding_category" in header
