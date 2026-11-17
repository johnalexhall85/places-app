"""Unit tests for the pure evaluation check functions in backend/tests/mcp_eval/run_eval.py.

These tests run offline in the sandbox without touching PostgreSQL or a live MCP server.
Covers TOOL_CONTRACT.md and Amendment 1 (M3b).
"""
from __future__ import annotations

import copy
import json
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
        "period": "2023",
        "population": "adults",
        "value_type": "crude_prevalence",
        "boundary_vintage": "TIGER/Line 2023 county",
        "release_id": "7bf96574-ac68-4d2f-9db8-95b07fbbf622",
        "notes": {},
        "source_credit": None,
        "citation": "Source: Centers for Disease Control and Prevention · PLACES 2025 county and tract pilot · 2023 · release 2025-12-12",
    }


def _sample_measure_meta(
    *,
    measure_key: str = "places:diabetes_crudeprev",
    boundary_vintage: str | None = "TIGER/Line 2023 county",
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "measure_key": measure_key,
        "label": "Diagnosed diabetes",
        "unit": "percent",
        "storage_scale": None,
        "period": "2023",
        "population": "adults",
        "value_type": "crude_prevalence",
        "release_id": "7bf96574-ac68-4d2f-9db8-95b07fbbf622",
        "citation": "Source: Centers for Disease Control and Prevention · PLACES 2025 county and tract pilot · 2023 · release 2025-12-12",
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
    uncertainty: dict[str, Any] = {"kind": uncertainty_kind, "label": "95% confidence interval"}
    if uncertainty_kind == "ci95":
        uncertainty |= {"low": 11.1 if value is not None else None, "high": 15.6 if value is not None else None}
    elif uncertainty_kind == "moe90":
        uncertainty = {"kind": "moe90", "moe": 1.2 if value is not None else None, "label": "90% margin of error"}
    else:
        uncertainty = {"kind": "none", "label": "No uncertainty published"}

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
    # Valid measure meta and compact row
    meta = _sample_measure_meta()
    assert run_eval.check_across_areas_measure_meta(meta) == []

    row = _sample_compact_row(position=1, notes={"days_with_aqi": 274})
    assert run_eval.check_compact_value_row_shape(row, product="places", require_position=True) == []

    # Empty notes dict on compact row must fail (Amendment 1 §2: omit notes when empty)
    empty_notes_row = _sample_compact_row(position=1)
    empty_notes_row["notes"] = {}
    errs = run_eval.check_compact_value_row_shape(empty_notes_row, product="places", require_position=True)
    assert any("omit 'notes' when empty" in e for e in errs)

    # Repeating shared fields (e.g. citation or measure_key) on compact row must fail
    bloated_row = _sample_compact_row(position=1)
    bloated_row["citation"] = meta["citation"]
    errs = run_eval.check_compact_value_row_shape(bloated_row, product="places", require_position=True)
    assert any("unexpected extra keys" in e for e in errs)

    # Full row in get_area_values must NOT have position (even null)
    full_row_with_null_pos = _sample_value_row()
    full_row_with_null_pos["position"] = None
    errs = run_eval.check_value_row_shape(full_row_with_null_pos)
    assert any("must not contain 'position'" in e for e in errs)


def test_forbidden_words_scan_in_keys_and_warnings():
    clean = _sample_envelope(
        data={"values": [_sample_value_row()]},
        warnings=[run_eval.ORDERING_WARNING],
    )
    assert run_eval.check_forbidden_words(clean) == []

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

    # 4. get_measure_details items must carry measure_key, product, and measure_id (Amendment 1 §6)
    details_resp = _sample_envelope(
        data={
            "measures": [
                {
                    "measure_key": "places:diabetes_crudeprev",
                    "product": "places",
                    "measure_id": "diabetes_crudeprev",
                    "label": "Diagnosed diabetes",
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
    assert summary["total_questions"] == 44
    assert summary["trap_questions"] == 12
    for tool in run_eval.ALL_TOOLS:
        assert summary["tool_call_counts"][tool] >= 1
    for prod in run_eval.PUBLIC_PRODUCTS + run_eval.FACILITY_BLOCKS:
        assert summary["product_question_counts"][prod] >= 1
    for lvl in run_eval.ALL_LEVELS:
        assert summary["level_counts"][lvl] >= 1
    assert set(run_eval.SHOWCASE_GEOIDS).issubset(set(summary["showcase_geoids_covered"]))
