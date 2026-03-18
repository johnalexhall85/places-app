from __future__ import annotations

from collections.abc import Sequence

from app.taggs import services as taggs_services


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

    def execute(self, *_args, **_kwargs) -> _FakeMappingsResult:
        return _FakeMappingsResult(self.rows)


def test_fetch_state_legend_exposes_new_normalization_metadata(monkeypatch) -> None:
    fake_db = _FakeDb(
        [
            {
                "state_abbr": "CA",
                "total_funding": 400.0,
                "award_count": 3,
                "unique_recipient_count": 2,
                "population": 100.0,
                "funding_per_capita": 4.0,
            }
        ]
    )

    monkeypatch.setattr(taggs_services, "_resolve_filters", lambda *_args, **_kwargs: taggs_services.TaggsFilters(
        state=None,
        fiscal_year=2025,
        program_office=None,
        aln=None,
        can_code=None,
        funding_stream=None,
        domestic_only=False,
    ))
    monkeypatch.setattr(taggs_services, "_build_query_context", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(taggs_services, "_build_where_sql", lambda *_args, **_kwargs: ("", {}))
    monkeypatch.setattr(taggs_services, "_fetch_mapping_metadata", lambda *_args, **_kwargs: {"can_mapping_version": "taggs-test"})
    monkeypatch.setattr(taggs_services, "taggs_normalization_compatibility", lambda **_kwargs: (True, None))
    monkeypatch.setattr(
        taggs_services,
        "fetch_state_normalization_lookup",
        lambda *_args, **_kwargs: {
            "CA": {
                "normalized_amount": 250.0,
                "normalized_amount_type": "estimated_cdc_profile_aligned",
                "normalization_method": "funding_scope_reconstruction_calibration_layer",
                "funding_stream_logic_version": "logic-test",
                "status_label": "Profile-aligned estimate",
                "methodology_version": "method-test",
            }
        },
    )

    payload = taggs_services.fetch_state_legend(
        fake_db,
        metric="total_funding",
        fiscal_year=2025,
        program_office=None,
        aln=None,
        can_code=None,
        funding_stream=None,
        normalize=True,
    )

    assert payload["normalization_applied"] is True
    assert payload["normalization_method"] == "funding_scope_reconstruction_calibration_layer"
    assert payload["funding_stream_logic_version"] == "logic-test"
    assert payload["total_funding"] == 250.0
