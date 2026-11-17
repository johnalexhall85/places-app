"""Unit tests for the pure evaluation check functions in backend/tests/mcp_eval/run_eval.py.

These tests run offline in the sandbox without touching PostgreSQL or a live MCP server.
Covers TOOL_CONTRACT.md, Amendment 1 (M3b), and Amendment 2 (H6).
"""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace
from typing import Any

from tests.mcp_eval import run_eval


def _sample_value_row(
    *,
    measure_key: str = "places:diabetes_crudeprev",
    geoid: str = "37145",
    name: str = "Person",
    value: float | int | None = 14.9,
    status: str = "available",
    status_text: str = "Published value",
    uncertainty_kind: str = "ci95",
    period: str = "2023",
    boundary_vintage: str = "TIGER/Line 2023 county",
    release_id: str = "7bf96574-ac68-4d2f-9db8-95b07fbbf622",
    note: str | None = None,
    citation: str | None = None,
) -> dict[str, Any]:
    uncertainty: dict[str, Any] = {"kind": uncertainty_kind, "label": "95% confidence interval"}
    if uncertainty_kind == "ci95":
        uncertainty |= {"low": 12.7 if value is not None else None, "high": 17.2 if value is not None else None}
    elif uncertainty_kind == "moe90":
        uncertainty = {"kind": "moe90", "moe": 1.2 if value is not None else None, "label": "90% margin of error"}
    else:
        uncertainty = {"kind": "none", "label": "No uncertainty published"}

    return {
        "measure_key": measure_key,
        "label": "Diagnosed diabetes",
        "area": {"level": "county", "geoid": geoid, "name": name},
        "value": value,
        "unit": "percent",
        "storage_scale": None,
        "status": status,
        "status_text": status_text,
        "uncertainty": uncertainty,
        "period": period,
        "population": "adults",
        "value_type": "crude_prevalence",
        "boundary_vintage": boundary_vintage,
        "release_id": release_id,
        "notes": {},
        "note": note,
        "source_credit": None,
        "citation": citation
        or f"Source: Centers for Disease Control and Prevention · PLACES 2025 county and tract pilot · {period} · release 2025-12-12",
    }


def _sample_measure_meta(
    *,
    measure_key: str = "places:diabetes_crudeprev",
    period: str = "2023",
    note: str | None = None,
    uncertainty_kind: str = "ci95",
    uncertainty_label: str = "95% confidence interval",
    boundary_vintage: str | None = "TIGER/Line 2023 county",
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "measure_key": measure_key,
        "label": "Diagnosed diabetes",
        "unit": "percent",
        "storage_scale": None,
        "period": period,
        "population": "adults",
        "value_type": "crude_prevalence",
        "release_id": "7bf96574-ac68-4d2f-9db8-95b07fbbf622",
        "citation": f"Source: Centers for Disease Control and Prevention · PLACES 2025 county and tract pilot · {period} · release 2025-12-12",
        "note": note,
        "uncertainty_kind": uncertainty_kind,
        "uncertainty_label": uncertainty_label,
    }
    if boundary_vintage is not None:
        meta["boundary_vintage"] = boundary_vintage
    return meta


def _sample_compact_row(
    *,
    geoid: str = "01001",
    name: str = "Autauga",
    value: float | int | None = 13.3,
    status: str = "available",
    status_text: str = "Published value",
    uncertainty_kind: str = "ci95",
    position: int | None = None,
    notes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if uncertainty_kind == "ci95":
        uncertainty: dict[str, Any] = {
            "low": 11.1 if value is not None else None,
            "high": 15.6 if value is not None else None,
        }
    elif uncertainty_kind == "moe90":
        uncertainty = {"moe": 1.2 if value is not None else None}
    else:
        uncertainty = {}

    row: dict[str, Any] = {
        "area": {"level": "county", "geoid": geoid, "name": name},
        "value": value,
        "status": status,
        "status_text": status_text,
        "uncertainty": uncertainty,
    }
    if position is not None:
        row["position"] = position
    if notes is not None:
        row["notes"] = notes
    return row


def _sample_envelope(
    data: dict[str, Any],
    sources: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "data": data,
        "sources": sources if sources is not None else [
            {
                "dataset_id": "cdc_places_county_2025_pilot",
                "product": "places",
                "product_name": "PLACES 2025 county and tract pilot",
                "publisher": "Centers for Disease Control and Prevention",
                "release_id": "7bf96574-ac68-4d2f-9db8-95b07fbbf622",
                "source_release_id": "2025-12-12",
                "published_at": "2026-11-15T01:01:07.000510+00:00",
                "landing_page": "https://data.cdc.gov/...",
            }
        ],
        "interpretation_rules": list(run_eval.GENERAL_INTERPRETATION_RULES),
        "warnings": warnings if warnings is not None else [],
    }


def test_competition_position_numbering_and_geoid_sort():
    assert run_eval.compute_competition_positions([18.4, 15.0, 15.0, 12.1]) == [1, 2, 2, 4]
    assert run_eval.compute_competition_positions([10.0, 10.0, 10.0, 9.5, 8.0, 8.0, 7.1]) == [1, 1, 1, 4, 5, 5, 7]
    assert run_eval.compute_competition_positions([]) == []

    rows_desc = [
        _sample_compact_row(geoid="01001", value=18.4, position=1),
        _sample_compact_row(geoid="01003", value=15.0, position=2),
        _sample_compact_row(geoid="01005", value=15.0, position=2),
        _sample_compact_row(geoid="01007", value=12.1, position=4),
    ]
    assert run_eval.check_competition_positions(rows_desc, sort_mode="value_desc") == []

    # Dense numbering (1, 2, 2, 3) instead of competition numbering (1, 2, 2, 4) must fail
    bad_tie = copy.deepcopy(rows_desc)
    bad_tie[3]["position"] = 3
    errs = run_eval.check_competition_positions(bad_tie, sort_mode="value_desc")
    assert errs and "Competition positions mismatch" in errs[0]

    # Out-of-order values for value_desc must fail
    unsorted = copy.deepcopy(rows_desc)
    unsorted[1]["value"] = 19.2
    errs = run_eval.check_competition_positions(unsorted, sort_mode="value_desc")
    assert errs and "not sorted descending" in errs[0]

    # Ascending order with ties (including open_ended status with non-null value per Amendment 1 §8)
    rows_asc = [
        _sample_compact_row(geoid="01007", value=12.1, position=1),
        _sample_compact_row(geoid="01003", value=15.0, position=2),
        _sample_compact_row(geoid="01005", value=15.0, position=2),
        _sample_compact_row(geoid="01001", value=250000, status="open_ended", status_text="Open-ended estimate (see annotation)", position=4),
    ]
    assert run_eval.check_competition_positions(rows_asc, sort_mode="value_asc") == []

    # Amendment 1 §3: With sort="geoid" there is NO position key
    rows_geoid = [
        _sample_compact_row(geoid="01001", value=18.4, position=None),
        _sample_compact_row(geoid="01003", value=15.0, position=None),
    ]
    assert run_eval.check_competition_positions(rows_geoid, sort_mode="geoid") == []

    # Emitting position (or position=null) under sort="geoid" must fail
    rows_geoid_with_pos = [
        _sample_compact_row(geoid="01001", value=18.4, position=1),
    ]
    errs = run_eval.check_competition_positions(rows_geoid_with_pos, sort_mode="geoid")
    assert errs and "must not have 'position'" in errs[0]

    rows_geoid_null_pos = [copy.deepcopy(rows_geoid[0])]
    rows_geoid_null_pos[0]["position"] = None
    errs = run_eval.check_competition_positions(rows_geoid_null_pos, sort_mode="geoid")
    assert errs and "must not have 'position'" in errs[0]


def test_without_value_rows_check():
    valid_without = [
        _sample_compact_row(geoid="01001", value=None, status="no_reported_value", status_text="No value reported"),
        _sample_compact_row(geoid="01005", value=None, status="no_reported_value", status_text="No value reported"),
    ]
    assert run_eval.check_without_value_rows(valid_without) == []

    # Non-null value (e.g. 0 instead of null) in without_value must fail
    zero_row = [_sample_compact_row(geoid="01001", value=0, status="no_reported_value", status_text="No value reported")]
    errs = run_eval.check_without_value_rows(zero_row)
    assert errs and "non-null value" in errs[0]

    # position key (even null) in without_value must fail (Amendment 1 §3)
    pos_in_without = [copy.deepcopy(valid_without[0])]
    pos_in_without[0]["position"] = None
    errs = run_eval.check_without_value_rows(pos_in_without)
    assert errs and "must not contain 'position'" in errs[0]

    # Out of GEOID order must fail
    wrong_order = [valid_without[1], valid_without[0]]
    errs = run_eval.check_without_value_rows(wrong_order)
    assert errs and "not in GEOID order" in errs[0]


def test_compact_row_and_measure_meta_shapes():
    # Valid measure meta and compact rows for ci95, moe90, and none (Amendment 1 §2, §2a & Amendment 2 §3)
    meta = _sample_measure_meta(note="Earlier period comparability note.")
    assert run_eval.check_across_areas_measure_meta(meta) == []

    # Missing uncertainty_kind, uncertainty_label, or note in data.measure must fail
    for req_key in ("uncertainty_kind", "uncertainty_label", "note"):
        missing_k = copy.deepcopy(meta)
        del missing_k[req_key]
        errs = run_eval.check_across_areas_measure_meta(missing_k)
        assert any(req_key in e for e in errs)

    # ci95 compact row -> {"low", "high"} only
    row_ci95 = _sample_compact_row(uncertainty_kind="ci95", position=1, notes={"days_with_aqi": 274})
    assert run_eval.check_compact_value_row_shape(
        row_ci95, product="places", uncertainty_kind="ci95", require_position=True
    ) == []

    # moe90 compact row -> {"moe"} only
    row_moe90 = _sample_compact_row(uncertainty_kind="moe90", position=1)
    assert run_eval.check_compact_value_row_shape(
        row_moe90, product="acs", uncertainty_kind="moe90", require_position=True
    ) == []

    # none compact row -> {} (no interval keys)
    row_none = _sample_compact_row(uncertainty_kind="none", position=1)
    assert row_none["uncertainty"] == {}
    assert run_eval.check_compact_value_row_shape(
        row_none, product="epa_aqi", uncertainty_kind="none", require_position=True
    ) == []

    # Compact rows repeating kind or label in uncertainty must fail (item 2a)
    repeated_kind = _sample_compact_row(uncertainty_kind="ci95", position=1)
    repeated_kind["uncertainty"]["kind"] = "ci95"
    errs = run_eval.check_compact_value_row_shape(
        repeated_kind, product="places", uncertainty_kind="ci95", require_position=True
    )
    assert any("must not repeat" in e for e in errs)

    repeated_label = _sample_compact_row(uncertainty_kind="moe90", position=1)
    repeated_label["uncertainty"]["label"] = "90% margin of error"
    errs = run_eval.check_compact_value_row_shape(
        repeated_label, product="acs", uncertainty_kind="moe90", require_position=True
    )
    assert any("must not repeat" in e for e in errs)

    # Interval keys mismatching data.measure.uncertainty_kind must fail (item 2a)
    errs = run_eval.check_compact_value_row_shape(
        row_moe90, product="places", uncertainty_kind="ci95", require_position=True
    )
    assert any("uncertainty keys" in e for e in errs)

    errs = run_eval.check_compact_value_row_shape(
        row_ci95, product="epa_aqi", uncertainty_kind="none", require_position=True
    )
    assert any("uncertainty keys" in e for e in errs)

    # Empty notes dict on compact row must fail (Amendment 1 §2: omit notes when empty)
    empty_notes_row = _sample_compact_row(position=1)
    empty_notes_row["notes"] = {}
    errs = run_eval.check_compact_value_row_shape(
        empty_notes_row, product="places", uncertainty_kind="ci95", require_position=True
    )
    assert any("omit 'notes' when empty" in e for e in errs)

    # Repeating shared fields (e.g. citation, note, or measure_key) on compact row must fail
    bloated_row = _sample_compact_row(position=1)
    bloated_row["citation"] = meta["citation"]
    errs = run_eval.check_compact_value_row_shape(
        bloated_row, product="places", uncertainty_kind="ci95", require_position=True
    )
    assert any("unexpected extra keys" in e for e in errs)

    # Full row in get_area_values must NOT have position (even null), and MUST have 'note'
    full_row_with_null_pos = _sample_value_row()
    full_row_with_null_pos["position"] = None
    errs = run_eval.check_value_row_shape(full_row_with_null_pos)
    assert any("must not contain 'position'" in e for e in errs)

    full_row_missing_note = _sample_value_row()
    del full_row_missing_note["note"]
    errs = run_eval.check_value_row_shape(full_row_missing_note)
    assert any("note" in e for e in errs)


def test_forbidden_words_and_no_change_keys():
    clean = _sample_envelope(
        data={"values": [_sample_value_row()]},
        warnings=[run_eval.ORDERING_WARNING],
    )
    assert run_eval.check_forbidden_words(clean) == []
    assert run_eval.check_no_change_keys(clean["data"]) == []

    bad_key_1 = _sample_envelope(data={"best_counties": []})
    assert any("best_counties" in e for e in run_eval.check_forbidden_words(bad_key_1))

    bad_key_2 = _sample_envelope(data={"compositeScore": 85})
    assert any("compositeScore" in e for e in run_eval.check_forbidden_words(bad_key_2))

    bad_key_3 = _sample_envelope(data={"worst": "01001"})
    assert any("worst" in e for e in run_eval.check_forbidden_words(bad_key_3))

    bad_warn_1 = _sample_envelope(data={}, warnings=["Showing the best 10 counties in Alabama."])
    assert any("warnings[0]" in e for e in run_eval.check_forbidden_words(bad_warn_1))

    bad_warn_2 = _sample_envelope(data={}, warnings=["Health score is not available."])
    assert any("warnings[0]" in e for e in run_eval.check_forbidden_words(bad_warn_2))

    for bad_change_key in ("change", "pct_change", "percent_change", "trend", "difference", "annual_change", "valueDiff"):
        errs = run_eval.check_no_change_keys({"series": [{bad_change_key: 1.5}]})
        assert errs and bad_change_key in errs[0]


def test_over_time_response_checks():
    r2019 = _sample_value_row(
        measure_key="cms_gv:std_payment_per_capita",
        geoid="37145",
        value=9800.0,
        uncertainty_kind="none",
        period="2019",
        boundary_vintage="2020 Census county boundaries (former Connecticut counties)",
        release_id="89e8cb19-e78e-4bb9-9ae7-3a4f65cff629",
        note="Same CMS file and column as the current year.",
        citation="Source: Centers for Medicare & Medicaid Services · CMS Original Medicare GV · 2019 · release CMS OM GV 2019-2023",
    )
    r2024 = _sample_value_row(
        measure_key="cms_gv:std_payment_per_capita",
        geoid="37145",
        value=11200.0,
        uncertainty_kind="none",
        period="2024",
        boundary_vintage="TIGER/Line 2024 county",
        release_id="11111111-2222-3333-4444-555555555555",
        note=None,
        citation="Source: Centers for Medicare & Medicaid Services · CMS Original Medicare GV · 2024 · release 2024",
    )
    valid_over_time = _sample_envelope(
        data={
            "area": {"level": "county", "geoid": "37145", "name": "Person County"},
            "measure": {
                "measure_key": "cms_gv:std_payment_per_capita",
                "label": "Standardized per-capita Medicare spending",
                "unit": "USD",
                "storage_scale": None,
                "population": "Original Medicare beneficiaries",
                "value_type": "standardized_per_capita",
            },
            "series": [r2019, r2024],
            "unavailable_periods": [],
        },
        sources=[
            {
                "dataset_id": "cms_mmd_gv:history",
                "product": "cms_gv",
                "product_name": "CMS Original Medicare GV",
                "publisher": "Centers for Medicare & Medicaid Services",
                "release_id": "89e8cb19-e78e-4bb9-9ae7-3a4f65cff629",
                "source_release_id": "CMS OM GV 2019-2023",
                "published_at": "2026-11-17T00:00:00+00:00",
                "landing_page": None,
            },
            {
                "dataset_id": "cms_mmd_gv",
                "product": "cms_gv",
                "product_name": "CMS Original Medicare GV",
                "publisher": "Centers for Medicare & Medicaid Services",
                "release_id": "11111111-2222-3333-4444-555555555555",
                "source_release_id": "2024",
                "published_at": "2026-11-17T00:00:00+00:00",
                "landing_page": None,
            },
        ],
        warnings=[run_eval.OVER_TIME_WARNING, run_eval.BOUNDARY_VINTAGE_WARNING],
    )
    assert run_eval.check_over_time_response(valid_over_time) == []
    assert run_eval.check_envelope(
        valid_over_time,
        "get_measure_over_time",
        {"level": "county", "geoid": "37145", "measure_key": "cms_gv:std_payment_per_capita"},
    ) == []

    # Descending periods must fail
    desc_series = copy.deepcopy(valid_over_time)
    desc_series["data"]["series"] = [r2024, r2019]
    errs = run_eval.check_over_time_response(desc_series)
    assert any("not in ascending order" in e for e in errs)

    # Duplicate period in series must fail
    dup_series = copy.deepcopy(valid_over_time)
    dup_series["data"]["series"] = [r2019, copy.deepcopy(r2019)]
    errs = run_eval.check_over_time_response(dup_series)
    assert any("not unique" in e for e in errs)

    # Missing fixed OVER_TIME_WARNING must fail
    no_fixed_warn = copy.deepcopy(valid_over_time)
    no_fixed_warn["warnings"] = [run_eval.BOUNDARY_VINTAGE_WARNING]
    errs = run_eval.check_over_time_response(no_fixed_warn)
    assert any("missing fixed warning" in e for e in errs)

    # Different boundary vintages without boundary-vintage warning must fail
    no_bv_warn = copy.deepcopy(valid_over_time)
    no_bv_warn["warnings"] = [run_eval.OVER_TIME_WARNING]
    errs = run_eval.check_over_time_response(no_bv_warn)
    assert any("no boundary-vintage caution" in e for e in errs)

    # Any change/trend key in data must fail
    with_pct_change = copy.deepcopy(valid_over_time)
    with_pct_change["data"]["pct_change"] = 14.3
    errs = run_eval.check_over_time_response(with_pct_change)
    assert any("pct_change" in e for e in errs)


def test_search_measures_and_details_periods_and_list_sources_notes():
    # 1. check_search_measures_periods
    valid_search_items = [
        {
            "measure_key": "places:diabetes_crudeprev",
            "label": "Diagnosed diabetes",
            "period": "2023",
            "periods": ["2023", "2022", "2021", "2020", "2019", "2018"],
        }
    ]
    assert run_eval.check_search_measures_periods(valid_search_items) == []

    bad_first = copy.deepcopy(valid_search_items)
    bad_first[0]["periods"] = ["2018", "2023"]
    errs = run_eval.check_search_measures_periods(bad_first)
    assert any("does not equal current period" in e for e in errs)

    missing_periods = [{"measure_key": "places:diabetes_crudeprev", "period": "2023"}]
    assert run_eval.check_search_measures_periods(missing_periods) != []

    # 2. check_measure_details_periods
    valid_details_items = [
        {
            "measure_key": "cms_gv:std_payment_per_capita",
            "product": "cms_gv",
            "measure_id": "std_payment_per_capita",
            "period": "2024",
            "periods": [
                {
                    "period": "2024",
                    "current": True,
                    "available": True,
                    "note": None,
                    "boundary_vintage": {"state": "TIGER/Line 2024 state", "county": "TIGER/Line 2024 county"},
                    "release_id": "11111111-2222-3333-4444-555555555555",
                },
                {
                    "period": "2023",
                    "current": False,
                    "available": True,
                    "note": "Same CMS file and column as the current year.",
                    "boundary_vintage": {"state": "TIGER/Line 2024 state", "county": "TIGER/Line 2024 county"},
                    "release_id": "89e8cb19-e78e-4bb9-9ae7-3a4f65cff629",
                },
            ],
        }
    ]
    assert run_eval.check_measure_details_periods(valid_details_items) == []

    bad_details = copy.deepcopy(valid_details_items)
    del bad_details[0]["periods"][1]["note"]
    errs = run_eval.check_measure_details_periods(bad_details)
    assert any("note" in e for e in errs)

    # 3. check_list_data_sources_notes
    valid_notes = [
        "PLACES 2025 county and tract pilot: 2023",
        "ACS 2020–2024 5-year median household income: 2020–2024",
        "ACS 2020–2024 community profile: 2020–2024",
        "CDC BRFSS state prevalence: 2023",
        "County Level Health (CLH): 2020–2024",
        "CMS Original Medicare GV: 2019–2024",
        "EPA AirData annual county AQI: 2025",
        "USDA Food Environment Atlas: 2020",
        "Area context uses TIGER/Line 2024 boundaries and 119th Congress districts; each value row gives its source boundary_vintage, which may differ.",
    ]
    assert run_eval.check_list_data_sources_notes(valid_notes, ["CMS Original Medicare GV: 2019–2024"]) == []

    old_notes = [*valid_notes, "Each measure has one period per measure; there is no time series."]
    errs = run_eval.check_list_data_sources_notes(old_notes)
    assert any("superseded one-period text" in e for e in errs)

    missing_line = run_eval.check_list_data_sources_notes(valid_notes, ["CMS Original Medicare GV: 1900–2024"])
    assert any("missing expected product period line" in e for e in missing_line)


def test_unpublished_period_handled_and_ct_09001_series_checks():
    # 1. expect_unpublished_period_handled (Q52)
    env = _sample_envelope(
        data={"level": "state", "areas": [{"geoid": "54", "name": "West Virginia"}], "values": []},
        sources=[],
        warnings=["brfss:diabetes is not published for 1999; published periods: 2023"],
    )
    call_res = SimpleNamespace(is_error=False, structured_content=env, content=[])
    exp_lookup = {
        "expect_error": False,
        "skipped_unpublished_periods": [("brfss:diabetes", ["2023"])],
        "rows_by_key_geoid": {},
    }
    spec = {
        "expect_unpublished_period_handled": {
            "skipped_measure_key": "brfss:diabetes",
            "requested_period": "1999",
            "min_published_periods": ["2023"],
        }
    }
    assert run_eval.verify_call_against_lookup_and_checks(
        "get_area_values",
        {"level": "state", "geoids": ["54"], "measure_keys": ["brfss:diabetes"], "period": "1999"},
        call_res,
        exp_lookup,
        spec,
        False,
    ) == []

    # Raising ToolError instead of skipping with warning must fail
    err_res = SimpleNamespace(
        is_error=True,
        structured_content=None,
        content=[SimpleNamespace(text="brfss:diabetes not published for 1999")],
    )
    errs = run_eval.verify_call_against_lookup_and_checks(
        "get_area_values",
        {"level": "state", "geoids": ["54"], "measure_keys": ["brfss:diabetes"], "period": "1999"},
        err_res,
        exp_lookup,
        spec,
        False,
    )
    assert errs and "skip measure" in errs[0]

    # 2. expect_series_has_available_and_unpublished_current (Q49: 09001)
    r2020 = _sample_value_row(
        measure_key="cms_gv:readmission_rate",
        geoid="09001",
        value=0.1813,
        uncertainty_kind="none",
        period="2020",
        boundary_vintage="2020 Census county boundaries (former Connecticut counties)",
        note="Connecticut uses its eight former counties.",
    )
    r2024_unpub = _sample_value_row(
        measure_key="cms_gv:readmission_rate",
        geoid="09001",
        value=None,
        status="not_published",
        status_text="Not published in this release",
        uncertainty_kind="none",
        period="2024",
        boundary_vintage="TIGER/Line 2024 county",
        note=None,
    )
    ct_env = _sample_envelope(
        data={
            "area": {"level": "county", "geoid": "09001", "name": None},
            "measure": {
                "measure_key": "cms_gv:readmission_rate",
                "label": "30-day hospital readmission rate",
                "unit": "proportion",
                "storage_scale": "proportion_0_to_1",
                "population": "Original Medicare beneficiaries",
                "value_type": "risk_standardized_rate",
            },
            "series": [r2020, r2024_unpub],
            "unavailable_periods": [],
        },
        sources=[
            {
                "dataset_id": "cms_mmd_gv:history",
                "product": "cms_gv",
                "product_name": "CMS Original Medicare GV",
                "publisher": "Centers for Medicare & Medicaid Services",
                "release_id": r2020["release_id"],
                "source_release_id": "2019-2023",
                "published_at": None,
                "landing_page": None,
            }
        ],
        warnings=[run_eval.OVER_TIME_WARNING, run_eval.BOUNDARY_VINTAGE_WARNING],
    )
    ct_res = SimpleNamespace(is_error=False, structured_content=ct_env, content=[])
    ct_spec = {
        "expect_over_time_series": True,
        "expect_series_has_available_and_unpublished_current": True,
        "expect_boundary_vintage_warning": True,
    }
    assert run_eval.verify_call_against_lookup_and_checks(
        "get_measure_over_time",
        {"level": "county", "geoid": "09001", "measure_key": "cms_gv:readmission_rate"},
        ct_res,
        {"expect_error": False, "series": [r2020, r2024_unpub], "unavailable_periods": []},
        ct_spec,
        False,
    ) == []


def test_no_ahrf_and_withheld_warnings():
    clean = _sample_envelope(data={"values": [_sample_value_row()]})
    assert run_eval.check_no_ahrf(clean) == []

    leaked = _sample_envelope(
        data={"values": [_sample_value_row(measure_key="ahrf:phys_nf_prim_care_pc_exc_rsdt_23")]}
    )
    errs = run_eval.check_no_ahrf(leaked)
    assert errs and "ahrf" in errs[0].lower()

    # list_data_sources is allowed to name ahrf inside data.excluded only
    sources_resp = _sample_envelope(
        data={
            "products": [{"product": "places"}],
            "excluded": [{"product": "ahrf", "reason": "Pending the source agency's answer on redistribution"}],
        },
        sources=[],
    )
    assert run_eval.check_no_ahrf(sources_resp, allow_excluded_list=True) == []
    assert run_eval.check_no_ahrf(sources_resp, allow_excluded_list=False) != []

    # Amendment 1 §7: search_measures warnings explaining withheld AHRF content are allowed,
    # while AHRF in search_measures.data is still forbidden.
    search_withheld_warn = _sample_envelope(
        data={"measures": [], "topics": [{"slug": "health-conditions"}]},
        sources=[],
        warnings=[run_eval.WITHHELD_TOPIC_EXPLANATION],
    )
    assert run_eval.check_no_ahrf(search_withheld_warn, allow_withheld_warning=True) == []
    assert run_eval.check_no_ahrf(search_withheld_warn, allow_withheld_warning=False) != []

    search_leaked_data = _sample_envelope(
        data={"measures": [{"measure_key": "ahrf:hosp_beds_23"}]},
        sources=[],
        warnings=[run_eval.WITHHELD_TOPIC_EXPLANATION],
    )
    assert run_eval.check_no_ahrf(search_leaked_data, allow_withheld_warning=True) != []

    # Verify error substring checks for topic='health-care-resources' (Amendment 1 §7)
    spec = {
        "expect_error_substrings_all": ["Health care resources", "AHRF", "not available through this public server"],
        "forbid_error_substrings": ["Unknown topic"],
    }
    assert run_eval.verify_error_message_checks(run_eval.WITHHELD_TOPIC_EXPLANATION, spec) == []
    bad_err = run_eval.verify_error_message_checks("Unknown topic 'health-care-resources'", spec)
    assert any("forbidden substring 'Unknown topic'" in e for e in bad_err)


def test_response_size_cap_50000_bytes():
    assert run_eval.MAX_RESPONSE_BYTES == 50_000
    small = _sample_envelope(data={"values": [_sample_value_row()]})
    expected_len = len(json.dumps(small, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    assert run_eval.measure_response_bytes(small) == expected_len
    assert run_eval.check_response_size(small) == []

    # 67 compact Alabama county rows easily fit under the 50,000-byte cap
    al_rows = [
        _sample_compact_row(geoid=f"01{i:03d}", name=f"County {i}", value=14.2, position=i)
        for i in range(1, 68)
    ]
    al_envelope = _sample_envelope(
        data={
            "measure": _sample_measure_meta(),
            "parent": {"level": "state", "geoid": "01", "name": "Alabama"},
            "total_areas": 67,
            "with_value": al_rows,
            "without_value": [],
            "truncated": False,
        },
        warnings=[run_eval.ORDERING_WARNING],
    )
    assert run_eval.measure_response_bytes(al_envelope) < 50_000
    assert run_eval.check_response_size(al_envelope) == []

    oversized = _sample_envelope(data={"blob": "x" * (run_eval.MAX_RESPONSE_BYTES + 100)})
    errs = run_eval.check_response_size(oversized)
    assert errs and "exceeds cap of 50000 bytes" in errs[0]


def test_envelope_checks_across_tools():
    # 1. Valid get_area_values response
    valid_area = _sample_envelope(
        data={"level": "county", "areas": [{"geoid": "37145", "name": "Person"}], "values": [_sample_value_row()]}
    )
    assert run_eval.check_envelope(valid_area, "get_area_values", {"level": "county", "geoids": ["37145"]}) == []

    # Mismatched sources must fail
    extra_source = copy.deepcopy(valid_area)
    extra_source["sources"].append({"product": "brfss", "dataset_id": "cdc_brfss"})
    errs = run_eval.check_envelope(extra_source, "get_area_values", {"level": "county", "geoids": ["37145"]})
    assert any("sources products" in e for e in errs)

    # 2. Valid get_measure_across_areas with compact rows and value_desc sort
    valid_across = _sample_envelope(
        data={
            "measure": _sample_measure_meta(),
            "parent": {"level": "state", "geoid": "01", "name": "Alabama"},
            "total_areas": 3,
            "with_value": [
                _sample_compact_row(geoid="01003", value=16.1, position=1),
                _sample_compact_row(geoid="01005", value=16.1, position=1),
            ],
            "without_value": [
                _sample_compact_row(
                    geoid="01001",
                    value=None,
                    status="not_in_release",
                    status_text="No row for this area in the published release",
                ),
            ],
            "truncated": False,
        },
        warnings=[run_eval.ORDERING_WARNING],
    )
    assert run_eval.check_envelope(
        valid_across,
        "get_measure_across_areas",
        {"measure_key": "places:diabetes_crudeprev", "level": "county", "within": "01", "sort": "value_desc"},
    ) == []

    # 3. find_places must have empty sources [] (Amendment 1 §5)
    find_resp = _sample_envelope(
        data={"matches": [{"level": "county", "geoid": "37145", "name": "Person"}]},
        sources=[],
    )
    assert run_eval.check_envelope(find_resp, "find_places", {"query": "Person"}) == []
    bad_find = copy.deepcopy(find_resp)
    bad_find["sources"] = [{"product": "places"}]
    assert any("find_places sources must be []" in e for e in run_eval.check_envelope(bad_find, "find_places", {"query": "Person"}))

    # 4. get_measure_details items must carry measure_key, product, measure_id, and periods (Amendment 1 §6 & Amendment 2 §6)
    details_resp = _sample_envelope(
        data={
            "measures": [
                {
                    "measure_key": "places:diabetes_crudeprev",
                    "product": "places",
                    "measure_id": "diabetes_crudeprev",
                    "label": "Diagnosed diabetes",
                    "period": "2023",
                    "periods": [
                        {
                            "period": "2023",
                            "current": True,
                            "available": True,
                            "note": None,
                            "boundary_vintage": {"county": "TIGER/Line 2023 county"},
                            "release_id": "7bf96574-ac68-4d2f-9db8-95b07fbbf622",
                        }
                    ],
                }
            ]
        }
    )
    assert run_eval.check_envelope(details_resp, "get_measure_details", {"measure_keys": ["places:diabetes_crudeprev"]}) == []

    missing_prod = copy.deepcopy(details_resp)
    del missing_prod["data"]["measures"][0]["product"]
    errs = run_eval.check_envelope(missing_prod, "get_measure_details", {"measure_keys": ["places:diabetes_crudeprev"]})
    assert any("must carry 'measure_key', 'product', and 'measure_id'" in e for e in errs)


def test_questions_yaml_validates_offline():
    ok, summary, errors = run_eval.validate_questions_yaml()
    assert ok, f"questions.yaml validation failed: {errors}"
    assert summary["total_questions"] == 54
    assert summary["regular_questions"] == 38
    assert summary["trap_questions"] == 16
    for tool in run_eval.ALL_TOOLS:
        assert summary["tool_call_counts"][tool] >= 1
    for prod in run_eval.PUBLIC_PRODUCTS + run_eval.FACILITY_BLOCKS:
        assert summary["product_question_counts"][prod] >= 1
    for lvl in run_eval.ALL_LEVELS:
        assert summary["level_counts"][lvl] >= 1
    assert set(run_eval.SHOWCASE_GEOIDS).issubset(set(summary["showcase_geoids_covered"]))
