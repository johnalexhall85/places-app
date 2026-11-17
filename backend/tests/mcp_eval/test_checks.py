"""Unit tests for the pure evaluation check functions in backend/tests/mcp_eval/run_eval.py.

These tests run offline in the sandbox without touching PostgreSQL or a live MCP server.
"""
from __future__ import annotations

import copy
from typing import Any

import pytest

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
    position: int | None = None,
) -> dict[str, Any]:
    uncertainty: dict[str, Any] = {"kind": uncertainty_kind, "label": "95% confidence interval"}
    if uncertainty_kind == "ci95":
        uncertainty |= {"low": 12.7 if value is not None else None, "high": 17.2 if value is not None else None}
    elif uncertainty_kind == "moe90":
        uncertainty = {"kind": "moe90", "moe": 1.2 if value is not None else None, "label": "90% margin of error"}
    else:
        uncertainty = {"kind": "none", "label": "No uncertainty published"}

    row: dict[str, Any] = {
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
    if position is not None:
        row["position"] = position
    return row


def _sample_envelope(data: dict[str, Any], sources: list[dict[str, Any]] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
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


def test_competition_position_numbering_with_ties():
    assert run_eval.compute_competition_positions([18.4, 15.0, 15.0, 12.1]) == [1, 2, 2, 4]
    assert run_eval.compute_competition_positions([10.0, 10.0, 10.0, 9.5, 8.0, 8.0, 7.1]) == [1, 1, 1, 4, 5, 5, 7]
    assert run_eval.compute_competition_positions([]) == []

    rows_desc = [
        _sample_value_row(geoid="01001", value=18.4, position=1),
        _sample_value_row(geoid="01003", value=15.0, position=2),
        _sample_value_row(geoid="01005", value=15.0, position=2),
        _sample_value_row(geoid="01007", value=12.1, position=4),
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

    # Ascending order with ties
    rows_asc = [
        _sample_value_row(geoid="01007", value=12.1, position=1),
        _sample_value_row(geoid="01003", value=15.0, position=2),
        _sample_value_row(geoid="01005", value=15.0, position=2),
        _sample_value_row(geoid="01001", value=18.4, position=4),
    ]
    assert run_eval.check_competition_positions(rows_asc, sort_mode="value_asc") == []


def test_without_value_rows_check():
    valid_without = [
        _sample_value_row(geoid="01001", value=None, status="no_reported_value", status_text="No value reported"),
        _sample_value_row(geoid="01005", value=None, status="no_reported_value", status_text="No value reported"),
    ]
    assert run_eval.check_without_value_rows(valid_without) == []

    # Non-null value (e.g. 0 instead of null) in without_value must fail
    zero_row = [_sample_value_row(geoid="01001", value=0, status="no_reported_value", status_text="No value reported")]
    errs = run_eval.check_without_value_rows(zero_row)
    assert errs and "non-null value" in errs[0]

    # Out of GEOID order must fail
    wrong_order = [valid_without[1], valid_without[0]]
    errs = run_eval.check_without_value_rows(wrong_order)
    assert errs and "not in GEOID order" in errs[0]


def test_forbidden_words_scan_in_keys_and_warnings():
    clean = _sample_envelope(
        data={"values": [_sample_value_row()]},
        warnings=[run_eval.ORDERING_WARNING],
    )
    assert run_eval.check_forbidden_words(clean) == []

    # Forbidden word in dictionary key
    bad_key_1 = _sample_envelope(data={"best_counties": []})
    assert any("best_counties" in e for e in run_eval.check_forbidden_words(bad_key_1))

    bad_key_2 = _sample_envelope(data={"compositeScore": 85})
    assert any("compositeScore" in e for e in run_eval.check_forbidden_words(bad_key_2))

    bad_key_3 = _sample_envelope(data={"worst": "01001"})
    assert any("worst" in e for e in run_eval.check_forbidden_words(bad_key_3))

    # Forbidden word in warnings
    bad_warn_1 = _sample_envelope(data={}, warnings=["Showing the best 10 counties in Alabama."])
    assert any("warnings[0]" in e for e in run_eval.check_forbidden_words(bad_warn_1))

    bad_warn_2 = _sample_envelope(data={}, warnings=["Health score is not available."])
    assert any("warnings[0]" in e for e in run_eval.check_forbidden_words(bad_warn_2))


def test_no_ahrf_scan():
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


def test_response_size_cap():
    small = _sample_envelope(data={"values": [_sample_value_row()]})
    assert run_eval.check_response_size(small) == []

    oversized = _sample_envelope(data={"blob": "x" * (run_eval.MAX_RESPONSE_BYTES + 100)})
    errs = run_eval.check_response_size(oversized)
    assert errs and "exceeds cap of 60000 bytes" in errs[0]


def test_envelope_and_sources_filtering_and_across_areas_warnings():
    # Valid get_area_values response
    valid_area = _sample_envelope(data={"level": "county", "areas": [{"geoid": "37145", "name": "Person"}], "values": [_sample_value_row()]})
    assert run_eval.check_envelope(valid_area, "get_area_values", {"level": "county", "geoids": ["37145"]}) == []

    # Mismatched sources (e.g. extra unvisited product in sources) must fail
    extra_source = copy.deepcopy(valid_area)
    extra_source["sources"].append({"product": "brfss", "dataset_id": "cdc_brfss"})
    errs = run_eval.check_envelope(extra_source, "get_area_values", {"level": "county", "geoids": ["37145"]})
    assert any("sources products" in e for e in errs)

    # Wrong uncertainty.kind for product must fail
    wrong_unc = copy.deepcopy(valid_area)
    wrong_unc["data"]["values"][0]["uncertainty"]["kind"] = "moe90"
    errs = run_eval.check_envelope(wrong_unc, "get_area_values", {"level": "county", "geoids": ["37145"]})
    assert any("uncertainty.kind" in e for e in errs)

    # Valid get_measure_across_areas with value_desc sort and ordering warning
    valid_across = _sample_envelope(
        data={
            "measure": {"measure_key": "places:diabetes_crudeprev"},
            "parent": {"level": "state", "geoid": "01", "name": "Alabama"},
            "total_areas": 3,
            "with_value": [
                _sample_value_row(geoid="01003", value=16.1, position=1),
                _sample_value_row(geoid="01005", value=16.1, position=1),
            ],
            "without_value": [
                _sample_value_row(geoid="01001", value=None, status="not_in_release", status_text="No row for this area in the published release"),
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

    # Missing ordering warning on value_desc sort must fail
    no_warn = copy.deepcopy(valid_across)
    no_warn["warnings"] = []
    errs = run_eval.check_envelope(
        no_warn,
        "get_measure_across_areas",
        {"measure_key": "places:diabetes_crudeprev", "level": "county", "within": "01", "sort": "value_desc"},
    )
    assert any("Missing required ordering warning" in e for e in errs)


def test_questions_yaml_validates_offline():
    ok, summary, errors = run_eval.validate_questions_yaml()
    assert ok, f"questions.yaml validation failed: {errors}"
    assert summary["total_questions"] >= 40
    assert summary["trap_questions"] >= 8
    for tool in run_eval.ALL_TOOLS:
        assert summary["tool_call_counts"][tool] >= 1
    for prod in run_eval.PUBLIC_PRODUCTS + run_eval.FACILITY_BLOCKS:
        assert summary["product_question_counts"][prod] >= 1
    for lvl in run_eval.ALL_LEVELS:
        assert summary["level_counts"][lvl] >= 1
    assert set(run_eval.SHOWCASE_GEOIDS).issubset(set(summary["showcase_geoids_covered"]))
