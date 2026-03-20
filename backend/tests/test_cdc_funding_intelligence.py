from __future__ import annotations

from app.cdc_funding import intelligence


def _build_row(
    *,
    geography_id: str,
    geography_name: str,
    state_code: str,
    state_name: str,
    raw_total_funding: float,
    chip_normalized_funding: float | None,
    total_funding: float,
    raw_per_capita: float,
    chip_normalized_per_capita: float | None,
    funding_per_capita: float,
    raw_per_100k: float,
    chip_normalized_per_100k: float | None,
    funding_per_100k: float,
    raw_share_of_national: float,
    chip_normalized_share_of_national: float | None,
    share_national_pct: float,
    funding_mode_requested: str,
    funding_mode_effective: str,
    funding_mode_label: str,
    population: float,
    awards_amount: float = 0.0,
    subawards_amount: float = 0.0,
    contracts_amount: float = 0.0,
    award_count: int = 0,
    subaward_count: int = 0,
    contract_award_count: int = 0,
    geometry: dict | None = None,
    normalization_note: str | None = None,
) -> dict[str, object]:
    return {
        "geography_id": geography_id,
        "geography_name": geography_name,
        "state_code": state_code,
        "state_name": state_name,
        "raw_total_funding": raw_total_funding,
        "chip_normalized_funding": chip_normalized_funding,
        "raw_funding_per_capita": raw_per_capita,
        "chip_normalized_funding_per_capita": chip_normalized_per_capita,
        "raw_funding_per_100k": raw_per_100k,
        "chip_normalized_funding_per_100k": chip_normalized_per_100k,
        "raw_share_of_national": raw_share_of_national,
        "chip_normalized_share_of_national": chip_normalized_share_of_national,
        "chip_total_funding": chip_normalized_funding,
        "chip_per_capita_funding": chip_normalized_per_capita,
        "chip_per_100k_funding": chip_normalized_per_100k,
        "chip_share_of_national": chip_normalized_share_of_national,
        "chip_equity_adjusted_metrics": {},
        "total_funding_amount": total_funding,
        "funding_per_capita": funding_per_capita,
        "funding_per_100k": funding_per_100k,
        "share_national_pct": share_national_pct,
        "funding_mode_requested": funding_mode_requested,
        "funding_mode_effective": funding_mode_effective,
        "funding_mode_label": funding_mode_label,
        "normalization_supported": funding_mode_requested == "chip_normalized",
        "normalization_applied": funding_mode_effective == "chip_normalized",
        "normalization_note": normalization_note,
        "normalization_factor": 0.6 if funding_mode_effective == "chip_normalized" else None,
        "normalized_amount_type": "observed_cdc_profile_aligned" if funding_mode_effective == "chip_normalized" else None,
        "normalization_status_label": "Profile-aligned" if funding_mode_effective == "chip_normalized" else None,
        "normalization_method": "funding_scope_reconstruction_calibration_layer" if funding_mode_effective == "chip_normalized" else None,
        "funding_stream_logic_version": "scope_v5" if funding_mode_effective == "chip_normalized" else None,
        "methodology_version": "profile_scope_v5" if funding_mode_effective == "chip_normalized" else "raw_pipeline_v1",
        "funding_model_version": "cdc_funding_mode_v1",
        "population": population,
        "award_count": award_count,
        "subaward_count": subaward_count,
        "contract_award_count": contract_award_count,
        "awards_amount": awards_amount,
        "subawards_amount": subawards_amount,
        "contracts_amount": contracts_amount,
        "min_fiscal_year": 2022,
        "max_fiscal_year": 2022,
        "geometry": geometry,
    }


def _build_profile(row: dict[str, object], *, geography_level: str = "state", funding_mode: str = "chip_normalized") -> intelligence.FundingProfileResult:
    return intelligence._funding_profile_result_from_row(
        row,
        intelligence.FundingFilters(
            fiscal_year=2022,
            metric="total_funding",
            funding_type="total_cdc_funding",
            funding_mode=funding_mode,
            program_area=None,
            mechanism=None,
            recipient_type=None,
            geography_level=geography_level,
            time_aggregation="single_fiscal_year",
        ),
    )


def test_fetch_geography_rows_prefers_state_summary_path(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_fetch_state_summary_rows(_db, filters, **kwargs):
        captured["filters"] = filters
        captured.update(kwargs)
        return [{"geography_id": "AL"}]

    monkeypatch.setattr(intelligence, "_intelligence_summary_tables_available", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(intelligence, "_fetch_state_summary_rows", fake_fetch_state_summary_rows)
    monkeypatch.setattr(
        intelligence,
        "_summary_query",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("raw summary query should not run")),
    )

    filters = intelligence.FundingFilters(
        fiscal_year=2022,
        metric="total_funding",
        funding_type="total_cdc_funding",
        funding_mode="chip_normalized",
        program_area=None,
        mechanism=None,
        recipient_type=None,
        geography_level="state",
        time_aggregation="single_fiscal_year",
    )

    rows = intelligence._fetch_geography_rows(
        None,
        filters,
        include_geometry=True,
        bbox=None,
        limit=200,
        scope="map",
    )

    assert rows == [{"geography_id": "AL"}]
    assert captured["include_geometry"] is True
    assert captured["scope"] == "map"
    assert captured["filters"].geography_level == "state"


def test_fetch_map_geojson_uses_requested_funding_mode_for_feature_values(monkeypatch) -> None:
    county_row = _build_row(
        geography_id="01001",
        geography_name="Autauga",
        state_code="AL",
        state_name="Alabama",
        raw_total_funding=200.0,
        chip_normalized_funding=120.0,
        total_funding=120.0,
        raw_per_capita=20.0,
        chip_normalized_per_capita=12.0,
        funding_per_capita=12.0,
        raw_per_100k=2000000.0,
        chip_normalized_per_100k=1200000.0,
        funding_per_100k=1200000.0,
        raw_share_of_national=10.0,
        chip_normalized_share_of_national=12.0,
        share_national_pct=12.0,
        funding_mode_requested="chip_normalized",
        funding_mode_effective="chip_normalized",
        funding_mode_label="CHIP normalized funding",
        population=10.0,
        geometry={"type": "Polygon", "coordinates": []},
        normalization_note="Normalized from the funding-scope layer.",
    )
    national_row = _build_row(
        geography_id="US",
        geography_name="United States",
        state_code="US",
        state_name="United States",
        raw_total_funding=3000.0,
        chip_normalized_funding=1000.0,
        total_funding=1000.0,
        raw_per_capita=30.0,
        chip_normalized_per_capita=10.0,
        funding_per_capita=10.0,
        raw_per_100k=3000000.0,
        chip_normalized_per_100k=1000000.0,
        funding_per_100k=1000000.0,
        raw_share_of_national=100.0,
        chip_normalized_share_of_national=100.0,
        share_national_pct=100.0,
        funding_mode_requested="chip_normalized",
        funding_mode_effective="chip_normalized",
        funding_mode_label="CHIP normalized funding",
        population=100.0,
    )

    monkeypatch.setattr(intelligence, "_ensure_required_tables", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(intelligence, "_fetch_geography_rows", lambda *_args, **_kwargs: [county_row])
    monkeypatch.setattr(intelligence, "_fetch_national_summary_row", lambda *_args, **_kwargs: national_row)

    payload = intelligence.fetch_map_geojson(
        None,
        fiscal_year=2022,
        metric="total_funding",
        geography_level="county",
        funding_mode="chip_normalized",
        time_aggregation="single_fiscal_year",
    )

    feature = payload["features"][0]["properties"]
    funding_profile = feature["funding_profile"]

    assert feature["value"] == 120.0
    assert feature["funding_mode_effective"] == "chip_normalized"
    assert feature["raw_total_funding"] == 200.0
    assert feature["chip_normalized_funding"] == 120.0
    assert feature["total_funding_amount"] == 120.0
    assert funding_profile["funding_mode_effective"] == "chip_normalized"
    assert payload["meta"]["funding_mode_requested"] == "chip_normalized"
    assert payload["meta"]["national_summary"]["funding_profile"]["total_funding"] == 1000.0


def test_fetch_legend_stats_and_map_share_same_mode(monkeypatch) -> None:
    state_row = _build_row(
        geography_id="AL",
        geography_name="Alabama",
        state_code="AL",
        state_name="Alabama",
        raw_total_funding=200.0,
        chip_normalized_funding=120.0,
        total_funding=200.0,
        raw_per_capita=20.0,
        chip_normalized_per_capita=12.0,
        funding_per_capita=20.0,
        raw_per_100k=2000000.0,
        chip_normalized_per_100k=1200000.0,
        funding_per_100k=2000000.0,
        raw_share_of_national=10.0,
        chip_normalized_share_of_national=12.0,
        share_national_pct=10.0,
        funding_mode_requested="raw_total",
        funding_mode_effective="raw_total",
        funding_mode_label="Raw total funding",
        population=10.0,
        geometry={"type": "Polygon", "coordinates": []},
    )
    national_row = _build_row(
        geography_id="US",
        geography_name="United States",
        state_code="US",
        state_name="United States",
        raw_total_funding=3000.0,
        chip_normalized_funding=1000.0,
        total_funding=3000.0,
        raw_per_capita=30.0,
        chip_normalized_per_capita=10.0,
        funding_per_capita=30.0,
        raw_per_100k=3000000.0,
        chip_normalized_per_100k=1000000.0,
        funding_per_100k=3000000.0,
        raw_share_of_national=100.0,
        chip_normalized_share_of_national=100.0,
        share_national_pct=100.0,
        funding_mode_requested="raw_total",
        funding_mode_effective="raw_total",
        funding_mode_label="Raw total funding",
        population=100.0,
    )
    state_profile = _build_profile(state_row, geography_level="state", funding_mode="raw_total")

    monkeypatch.setattr(intelligence, "_ensure_required_tables", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(intelligence, "_build_funding_profiles", lambda *_args, **_kwargs: ([state_row], [state_profile]))
    monkeypatch.setattr(intelligence, "_fetch_national_summary_row", lambda *_args, **_kwargs: national_row)

    map_payload = intelligence.fetch_map_geojson(
        None,
        fiscal_year=2022,
        metric="total_funding",
        geography_level="state",
        funding_mode="raw_total",
        time_aggregation="single_fiscal_year",
    )
    legend_payload = intelligence.fetch_legend_stats(
        None,
        fiscal_year=2022,
        metric="total_funding",
        geography_level="state",
        funding_mode="raw_total",
        time_aggregation="single_fiscal_year",
    )

    assert map_payload["features"][0]["properties"]["funding_mode_effective"] == "raw_total"
    assert map_payload["features"][0]["properties"]["total_funding_amount"] == 200.0
    assert legend_payload["funding_mode_effective"] == "raw_total"
    assert legend_payload["national_summary"]["funding_mode_effective"] == "raw_total"
    assert legend_payload["total_visible_dollars"] == 200.0


def test_fetch_map_geojson_uses_lightweight_state_feature_payload(monkeypatch) -> None:
    state_row = _build_row(
        geography_id="AL",
        geography_name="Alabama",
        state_code="AL",
        state_name="Alabama",
        raw_total_funding=200.0,
        chip_normalized_funding=120.0,
        total_funding=120.0,
        raw_per_capita=20.0,
        chip_normalized_per_capita=12.0,
        funding_per_capita=12.0,
        raw_per_100k=2000000.0,
        chip_normalized_per_100k=1200000.0,
        funding_per_100k=1200000.0,
        raw_share_of_national=10.0,
        chip_normalized_share_of_national=12.0,
        share_national_pct=12.0,
        funding_mode_requested="chip_normalized",
        funding_mode_effective="chip_normalized",
        funding_mode_label="CHIP normalized funding",
        population=10.0,
        geometry={"type": "Polygon", "coordinates": []},
        normalization_note="Normalized from the funding-scope layer.",
    )
    state_profile = _build_profile(state_row, geography_level="state")
    national_row = _build_row(
        geography_id="US",
        geography_name="United States",
        state_code="US",
        state_name="United States",
        raw_total_funding=3000.0,
        chip_normalized_funding=1000.0,
        total_funding=1000.0,
        raw_per_capita=30.0,
        chip_normalized_per_capita=10.0,
        funding_per_capita=10.0,
        raw_per_100k=3000000.0,
        chip_normalized_per_100k=1000000.0,
        funding_per_100k=1000000.0,
        raw_share_of_national=100.0,
        chip_normalized_share_of_national=100.0,
        share_national_pct=100.0,
        funding_mode_requested="chip_normalized",
        funding_mode_effective="chip_normalized",
        funding_mode_label="CHIP normalized funding",
        population=100.0,
    )

    monkeypatch.setattr(intelligence, "_ensure_required_tables", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(intelligence, "_build_funding_profiles", lambda *_args, **_kwargs: ([state_row], [state_profile]))
    monkeypatch.setattr(intelligence, "_fetch_national_summary_row", lambda *_args, **_kwargs: national_row)

    payload = intelligence.fetch_map_geojson(
        None,
        fiscal_year=2022,
        metric="total_funding",
        geography_level="state",
        funding_mode="chip_normalized",
        time_aggregation="single_fiscal_year",
    )

    properties = payload["features"][0]["properties"]

    assert properties["value"] == 120.0
    assert properties["total_funding_amount"] == 120.0
    assert properties["funding_per_capita"] == 12.0
    assert properties["share_national_pct"] == 12.0
    assert properties["metric_context"]["funding_mode"] == "chip_normalized"
    assert "funding_profile" not in properties
    assert "raw_total_funding" not in properties


def test_state_map_and_profile_share_identical_canonical_outputs(monkeypatch) -> None:
    state_row = _build_row(
        geography_id="AL",
        geography_name="Alabama",
        state_code="AL",
        state_name="Alabama",
        raw_total_funding=200.0,
        chip_normalized_funding=120.0,
        total_funding=120.0,
        raw_per_capita=20.0,
        chip_normalized_per_capita=12.0,
        funding_per_capita=12.0,
        raw_per_100k=2000000.0,
        chip_normalized_per_100k=1200000.0,
        funding_per_100k=1200000.0,
        raw_share_of_national=10.0,
        chip_normalized_share_of_national=12.0,
        share_national_pct=12.0,
        funding_mode_requested="chip_normalized",
        funding_mode_effective="chip_normalized",
        funding_mode_label="CHIP normalized funding",
        population=10.0,
        geometry={"type": "Polygon", "coordinates": []},
        normalization_note="Normalized from the funding-scope layer.",
    )
    state_profile = _build_profile(state_row, geography_level="state")
    national_row = _build_row(
        geography_id="US",
        geography_name="United States",
        state_code="US",
        state_name="United States",
        raw_total_funding=3000.0,
        chip_normalized_funding=1000.0,
        total_funding=1000.0,
        raw_per_capita=30.0,
        chip_normalized_per_capita=10.0,
        funding_per_capita=10.0,
        raw_per_100k=3000000.0,
        chip_normalized_per_100k=1000000.0,
        funding_per_100k=1000000.0,
        raw_share_of_national=100.0,
        chip_normalized_share_of_national=100.0,
        share_national_pct=100.0,
        funding_mode_requested="chip_normalized",
        funding_mode_effective="chip_normalized",
        funding_mode_label="CHIP normalized funding",
        population=100.0,
    )

    monkeypatch.setattr(intelligence, "_ensure_required_tables", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(intelligence, "_build_funding_profiles", lambda *_args, **_kwargs: ([state_row], [state_profile]))
    monkeypatch.setattr(intelligence, "_fetch_national_summary_row", lambda *_args, **_kwargs: national_row)
    monkeypatch.setattr(intelligence, "_summary_refresh_signature", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        intelligence,
        "_profile_state_rows",
        lambda *_args, **_kwargs: (
            [{"program_area": "chronic_disease_prevention", "amount": 60.0}],
            {
                "state_total_amount": 100.0,
                "awards_amount": 0.0,
                "subawards_amount": 0.0,
                "contracts_amount": 0.0,
                "award_count": 0,
                "subaward_count": 0,
                "contract_award_count": 0,
                "national_total_amount": 1000.0,
            },
            {"min_fiscal_year": 2022, "max_fiscal_year": 2022},
        ),
    )
    monkeypatch.setattr(intelligence, "_state_name", lambda *_args, **_kwargs: "Alabama")

    map_payload = intelligence.fetch_map_geojson(
        None,
        fiscal_year=2022,
        metric="total_funding",
        geography_level="state",
        funding_mode="chip_normalized",
        time_aggregation="single_fiscal_year",
    )
    summary_payload = intelligence.fetch_state_profile_summary(
        None,
        state="AL",
        fiscal_year=2022,
        metric="total_funding",
        funding_mode="chip_normalized",
        time_aggregation="single_fiscal_year",
    )

    map_properties = map_payload["features"][0]["properties"]
    summary_profile = summary_payload["profile"]

    assert "funding_profile" not in map_properties
    assert map_properties["funding_mode_effective"] == summary_profile["funding_mode_effective"] == "chip_normalized"
    assert map_properties["total_funding_amount"] == summary_profile["total_funding"] == 120.0
    assert map_payload["features"][0]["properties"]["value"] == summary_payload["selected_metric_value"] == 120.0
    assert summary_payload["top_program_area"]["amount"] == 72.0


def test_profile_state_rows_aggregates_year_count_inside_state_and_national_totals(monkeypatch) -> None:
    class _FakeResult:
        def mappings(self):
            return self

        def all(self):
            return []

    class _FakeDb:
        def __init__(self) -> None:
            self.last_sql = ""
            self.last_params = None

        def execute(self, statement, params):
            self.last_sql = str(statement)
            self.last_params = params
            return _FakeResult()

    monkeypatch.setattr(
        intelligence,
        "_integrated_rows_cte",
        lambda: (
            "WITH integrated_rows AS ("
            "SELECT 'row-1'::text AS row_key, 'award-1'::text AS award_key, 'award'::text AS component, "
            "2022::integer AS fiscal_year, 'AL'::text AS state_code, NULL::text AS county_fips, "
            "'Preparedness Recipient'::text AS recipient_name, 10::numeric AS amount, 'regular'::text AS appropriation_type, "
            "'grants'::text AS mechanism, 'state_governments'::text AS recipient_type, "
            "'public_health_preparedness_and_response'::text AS program_area, "
            "'Public Health Emergency Preparedness'::text AS program_name, true AS chip_default_include, false AS is_emergency)"
        ),
    )
    monkeypatch.setattr(
        intelligence,
        "_filter_conditions",
        lambda filters, state=None: (
            "WHERE state_code IS NOT NULL" + (" AND state_code = :state_code_filter" if state else ""),
            {
                "time_aggregation": filters.time_aggregation,
                **({"state_code_filter": state} if state else {}),
            },
        ),
    )
    monkeypatch.setattr(intelligence, "_intelligence_summary_tables_available", lambda *_args, **_kwargs: False)

    fake_db = _FakeDb()
    filters = intelligence.FundingFilters(
        fiscal_year=2022,
        metric="total_funding",
        funding_type="total_cdc_funding",
        funding_mode="raw_total",
        program_area=None,
        mechanism=None,
        recipient_type=None,
        geography_level="state",
        time_aggregation="single_fiscal_year",
    )

    intelligence._profile_state_rows(fake_db, filters, state="AL")

    assert "COALESCE(MAX(year_stats.year_count), 0) > 0" in fake_db.last_sql
    assert "/ MAX(year_stats.year_count)" in fake_db.last_sql
