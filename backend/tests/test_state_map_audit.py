"""Independent reconciliation audit for the CDC state funding national map.

Implements State Funding Map Contract §5 invariants 1–5 plus Amendment 1
(`deobligations=exclude`) and Amendment 2 (Freely Associated States `FM`, `MH`, `PW`
in Invariant 4) against the active `state_funding` build on `places_staging`.

Calls `/state-funding/v1/map`, `/state-funding/v1/map/shapes`, and
`/state-funding/v1/states/{code}/summary` in-process via FastAPI's `TestClient`
with the demo-access middleware bypassed in-memory, and queries `state_funding`
directly (read-only) for the obligation sums. Writes no database rows and makes
no external network calls.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.area_pilot import lookup as area_lookup
from app.db import SessionLocal
from app.demo_access import middleware as demo_middleware
from app.demo_access.settings import get_demo_access_settings
from app.main import app
from app.state_funding import lookup

pytestmark = pytest.mark.integration

TOLERANCE_DECIMAL = Decimal("0.01")
TOLERANCE_FLOAT = 0.01
MAX_MAP_BYTES = 60 * 1024
MAX_SHAPES_BYTES = 400 * 1024

FUNDING_TYPES = ("all", "regular", "supplemental")
FY2026_AUDIT_CATEGORIES = ("HIV", "CROSS", "PHPR")
SAMPLED_STATES = ("CA", "TX", "NY", "GA", "WY", "VT", "DC", "PR", "AK", "GU")
ALLOWED_NO_SHAPE_CODES = frozenset({"GU", "VI", "AS", "MP", "FM", "MH", "PW"})

EXCLUDED_NOTE = (
    "Deobligations (net reductions for an award in this year) are left out, "
    "so totals show new and added obligations only."
)
ATTRIBUTION_NOTE = (
    "Grants are counted in the state of the recipient's address. Money a recipient passes on "
    "to sub-recipients in other states is not moved."
)


def _format_slice(fy: int, funding_type: str, category: str | None, deobligations: str) -> str:
    return (
        f"fy={fy} funding_type={funding_type!r} category={category!r} "
        f"deobligations={deobligations!r}"
    )


def _sql_grant_obligation_totals(
    db,
    build_id: int,
    fy: int,
    funding_type: str,
    category: str | None,
    deobligations: str,
) -> dict[str, Any]:
    """Query `state_funding` directly for national and unattributed grant sums and counts."""
    clauses = [
        "o.build_id = :build_id",
        "o.fiscal_year = :fy",
        "a.award_type = 'grant'",
    ]
    params: dict[str, Any] = {"build_id": build_id, "fy": fy}

    if funding_type == "regular":
        clauses.append("o.is_supplemental IS FALSE")
    elif funding_type == "supplemental":
        clauses.append("o.is_supplemental IS TRUE")

    if category is not None:
        clauses.append("c.category_code = :category")
        params["category"] = category

    if deobligations == "exclude":
        amount_expr = "coalesce(sum(o.amount) FILTER (WHERE o.amount > 0), 0)"
        unattr_expr = "coalesce(sum(o.amount) FILTER (WHERE o.state = '__' AND o.amount > 0), 0)"
        award_count_expr = "count(DISTINCT o.award_unique_key) FILTER (WHERE o.amount > 0)"
        unattr_award_expr = (
            "count(DISTINCT o.award_unique_key) FILTER (WHERE o.state = '__' AND o.amount > 0)"
        )
    else:
        amount_expr = "coalesce(sum(o.amount), 0)"
        unattr_expr = "coalesce(sum(o.amount) FILTER (WHERE o.state = '__'), 0)"
        award_count_expr = "count(DISTINCT o.award_unique_key)"
        unattr_award_expr = "count(DISTINCT o.award_unique_key) FILTER (WHERE o.state = '__')"

    sql = f"""
        SELECT
            {amount_expr} AS national_total,
            {award_count_expr} AS national_award_count,
            {unattr_expr} AS unattributed_total,
            {unattr_award_expr} AS unattributed_award_count
        FROM state_funding.obligation o
        JOIN state_funding.award a USING (build_id, award_unique_key)
        JOIN state_funding.budget_category c USING (federal_account_symbol)
        WHERE {' AND '.join(clauses)}
    """
    row = db.execute(text(sql), params).mappings().one()
    return {
        "national_total": Decimal(row["national_total"]),
        "national_award_count": int(row["national_award_count"]),
        "unattributed_total": Decimal(row["unattributed_total"]),
        "unattributed_award_count": int(row["unattributed_award_count"]),
    }


@pytest.fixture(scope="module")
def audit_context():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1")).scalar()
        build = lookup.build_info(db)
    except SQLAlchemyError as exc:
        db.close()
        pytest.skip(f"Database unreachable or state_funding schema unavailable: {exc}")

    if not build:
        db.close()
        pytest.skip("No active state_funding build available")

    try:
        fy_info = lookup.fiscal_years(db)
        fiscal_years = tuple(sorted(fy_info["fiscal_years"]))
        if not fiscal_years:
            pytest.skip("Active state_funding build contains no fiscal years")
        if 2026 not in fiscal_years:
            pytest.skip("Active state_funding build does not include FY2026")

        disabled_demo_settings = replace(get_demo_access_settings(), enabled=False)
        with patch.object(
            demo_middleware,
            "get_demo_access_settings",
            return_value=disabled_demo_settings,
        ):
            with TestClient(app) as client:
                shapes_resp = client.get("/state-funding/v1/map/shapes")
                assert shapes_resp.status_code == 200, (
                    f"Setup failed: GET /state-funding/v1/map/shapes returned {shapes_resp.status_code}"
                )

                standard_slices: list[tuple[int, str, str | None, str]] = [
                    (fy, ft, None, "include")
                    for fy in fiscal_years
                    for ft in FUNDING_TYPES
                ] + [
                    (2026, ft, cat, "include")
                    for cat in FY2026_AUDIT_CATEGORIES
                    for ft in FUNDING_TYPES
                ]

                exclude_slices: list[tuple[int, str, str | None, str]] = [
                    (fy, ft, None, "exclude")
                    for fy in fiscal_years
                    for ft in FUNDING_TYPES
                ] + [
                    (2026, "all", cat, "exclude")
                    for cat in FY2026_AUDIT_CATEGORIES
                ]

                map_responses: dict[tuple[int, str, str | None, str], tuple[int, bytes, dict[str, Any]]] = {}
                for key in (*standard_slices, *exclude_slices):
                    fy, ft, cat, deob = key
                    params: dict[str, Any] = {
                        "fy": fy,
                        "funding_type": ft,
                        "deobligations": deob,
                    }
                    if cat is not None:
                        params["category"] = cat
                    resp = client.get("/state-funding/v1/map", params=params)
                    assert resp.status_code == 200, (
                        f"GET /state-funding/v1/map failed for {_format_slice(*key)}: "
                        f"status={resp.status_code} body={resp.text[:300]}"
                    )
                    map_responses[key] = (resp.status_code, resp.content, resp.json())

                profile_geoids = frozenset(row["geoid"] for row in area_lookup.states(db))

                yield {
                    "db": db,
                    "client": client,
                    "build": build,
                    "build_id": build["build_id"],
                    "fiscal_years": fiscal_years,
                    "standard_slices": tuple(standard_slices),
                    "exclude_slices": tuple(exclude_slices),
                    "all_slices": tuple((*standard_slices, *exclude_slices)),
                    "map_responses": map_responses,
                    "shapes_response": shapes_resp,
                    "shapes_json": shapes_resp.json(),
                    "profile_geoids": profile_geoids,
                }
    finally:
        db.rollback()
        db.close()


def test_map_shapes_contract(audit_context):
    """Contract §2: `/map/shapes` returns TIGER/Line 2024 outlines under 400 KB with Cache-Control."""
    resp = audit_context["shapes_response"]
    body = audit_context["shapes_json"]

    assert resp.headers.get("cache-control") == "public, max-age=86400", (
        f"Unexpected Cache-Control header: {resp.headers.get('cache-control')!r}"
    )
    assert len(resp.content) < MAX_SHAPES_BYTES, (
        f"/map/shapes uncompressed payload too large: {len(resp.content)} bytes >= {MAX_SHAPES_BYTES}"
    )
    assert body.get("boundary_vintage") == "TIGER/Line 2024"
    states = body.get("states") or {}
    assert len(states) == 52, f"Expected 52 state-level shapes (50 states + DC + PR), got {len(states)}"
    for code, entry in states.items():
        assert entry.get("fips") and entry.get("name") and entry.get("geometry"), (
            f"Incomplete shape entry for {code!r}: keys={sorted(entry.keys())}"
        )


def test_invariant_1_totals_reconcile_to_national_and_sql(audit_context):
    """Contract §5 Invariant 1 + Amendment 1: sum(states.total) + unattributed.total == national.total == SQL sum."""
    db = audit_context["db"]
    build_id = audit_context["build_id"]

    for key in audit_context["all_slices"]:
        fy, ft, cat, deob = key
        label = _format_slice(*key)
        _, raw_bytes, body = audit_context["map_responses"][key]

        assert len(raw_bytes) < MAX_MAP_BYTES, (
            f"Contract §2 payload limit exceeded ({label}): {len(raw_bytes)} bytes >= {MAX_MAP_BYTES}"
        )
        assert body["filters"] == {
            "funding_type": ft,
            "category": cat,
            "award_type": "grant",
            "deobligations": deob,
        }, f"Unexpected echoed filters ({label}): {body['filters']}"

        states_sum = sum((Decimal(str(s["total"])) for s in body["states"]), Decimal("0"))
        unattr_total = Decimal(str(body["unattributed"]["total"]))
        national_total = Decimal(str(body["national"]["total"]))
        combined_total = states_sum + unattr_total

        diff_internal = abs(combined_total - national_total)
        assert diff_internal <= TOLERANCE_DECIMAL, (
            f"Invariant 1 (states + unattributed vs national) failed: {label} "
            f"states_plus_unattributed={combined_total:.2f} national={national_total:.2f} "
            f"diff={diff_internal:.2f}"
        )

        sql_totals = _sql_grant_obligation_totals(db, build_id, fy, ft, cat, deob)
        sql_national = sql_totals["national_total"].quantize(Decimal("0.01"))
        sql_unattr = sql_totals["unattributed_total"].quantize(Decimal("0.01"))

        diff_sql_national = abs(national_total - sql_national)
        assert diff_sql_national <= TOLERANCE_DECIMAL, (
            f"Invariant 1 (national vs SQL) failed: {label} "
            f"api_national={national_total:.2f} sql_national={sql_national:.2f} "
            f"diff={diff_sql_national:.2f}"
        )

        diff_sql_combined = abs(combined_total - sql_national)
        assert diff_sql_combined <= TOLERANCE_DECIMAL, (
            f"Invariant 1 (states + unattributed vs SQL) failed: {label} "
            f"api_combined={combined_total:.2f} sql_national={sql_national:.2f} "
            f"diff={diff_sql_combined:.2f}"
        )

        diff_sql_unattr = abs(unattr_total - sql_unattr)
        assert diff_sql_unattr <= TOLERANCE_DECIMAL, (
            f"Invariant 1 (unattributed vs SQL) failed: {label} "
            f"api_unattributed={unattr_total:.2f} sql_unattributed={sql_unattr:.2f} "
            f"diff={diff_sql_unattr:.2f}"
        )

        assert body["national"]["award_count"] == sql_totals["national_award_count"], (
            f"Invariant 1 (national award_count vs SQL) failed: {label} "
            f"api={body['national']['award_count']} sql={sql_totals['national_award_count']}"
        )
        assert body["unattributed"]["award_count"] == sql_totals["unattributed_award_count"], (
            f"Invariant 1 (unattributed award_count vs SQL) failed: {label} "
            f"api={body['unattributed']['award_count']} sql={sql_totals['unattributed_award_count']}"
        )

        assert ATTRIBUTION_NOTE in body["notes"], f"Missing attribution note ({label})"
        if deob == "exclude":
            assert EXCLUDED_NOTE in body["notes"], f"Missing deobligations-excluded note ({label})"
            assert national_total >= Decimal("0"), (
                f"Amendment 1 failed: negative national total under exclude ({label}): {national_total}"
            )
            assert unattr_total >= Decimal("0"), (
                f"Amendment 1 failed: negative unattributed total under exclude ({label}): {unattr_total}"
            )
        else:
            assert EXCLUDED_NOTE not in body["notes"], f"Unexpected excluded note under include ({label})"


def test_invariant_2_sampled_states_match_summary_endpoint(audit_context):
    """Contract §5 Invariant 2 + Amendment 1: 10 sampled states equal `/states/{code}/summary`."""
    client = audit_context["client"]

    for key in audit_context["all_slices"]:
        fy, ft, cat, deob = key
        label = _format_slice(*key)
        _, _, body = audit_context["map_responses"][key]
        by_code = {row["code"]: row for row in body["states"]}

        # Always include our 10 fixed states; if some are absent in a sparse slice
        # (for example supplemental + exclude), top up from present states so up to
        # min(10, len(states)) present map rows are reconciled against `/summary`.
        present_targets = [code for code in SAMPLED_STATES if code in by_code]
        if len(present_targets) < min(10, len(by_code)):
            for code in sorted(by_code):
                if code not in present_targets:
                    present_targets.append(code)
                if len(present_targets) >= min(10, len(by_code)):
                    break

        for code in present_targets:
            row = by_code[code]
            params: dict[str, Any] = {
                "fy": fy,
                "funding_type": ft,
                "award_type": "grant",
                "deobligations": deob,
            }
            if cat is not None:
                params["category"] = cat
            resp = client.get(f"/state-funding/v1/states/{code}/summary", params=params)
            assert resp.status_code == 200, (
                f"Invariant 2 failed: /states/{code}/summary returned {resp.status_code} "
                f"for present map state ({label})"
            )
            totals = resp.json()["totals"]
            for field in ("total", "regular", "supplemental"):
                diff = abs(Decimal(str(row[field])) - Decimal(str(totals[field])))
                assert diff <= TOLERANCE_DECIMAL, (
                    f"Invariant 2 ({field}) failed: {label} state={code!r} "
                    f"map={row[field]:.2f} summary={totals[field]:.2f} diff={diff:.2f}"
                )
            assert row["award_count"] == totals["award_count"], (
                f"Invariant 2 (award_count) failed: {label} state={code!r} "
                f"map={row['award_count']} summary={totals['award_count']}"
            )
            assert row["recipient_count"] == totals["recipient_count"], (
                f"Invariant 2 (recipient_count) failed: {label} state={code!r} "
                f"map={row['recipient_count']} summary={totals['recipient_count']}"
            )

        # Also verify that any fixed sampled state omitted from `states[]` truly has 0 matching grants.
        absent_fixed = [code for code in SAMPLED_STATES if code not in by_code]
        for code in absent_fixed:
            params = {
                "fy": fy,
                "funding_type": ft,
                "award_type": "grant",
                "deobligations": deob,
            }
            if cat is not None:
                params["category"] = cat
            resp = client.get(f"/state-funding/v1/states/{code}/summary", params=params)
            if resp.status_code == 422 and cat is not None:
                continue
            assert resp.status_code == 200, (
                f"Invariant 2 (absent state check) unexpected status {resp.status_code} "
                f"for state={code!r} ({label})"
            )
            totals = resp.json()["totals"]
            assert totals["award_count"] == 0 and abs(totals["total"]) <= TOLERANCE_FLOAT, (
                f"Invariant 2 (absent state had grants) failed: {label} state={code!r} "
                f"summary_totals={totals}"
            )


def test_invariant_3_regular_plus_supplemental_equals_total_and_non_negative_exclude(audit_context):
    """Contract §5 Invariant 3 + Amendment 1: regular + supplemental == total; non-negative under exclude."""
    for key in audit_context["all_slices"]:
        fy, ft, cat, deob = key
        label = _format_slice(*key)
        _, _, body = audit_context["map_responses"][key]

        for row in body["states"]:
            code = row["code"]
            reg = Decimal(str(row["regular"]))
            sup = Decimal(str(row["supplemental"]))
            tot = Decimal(str(row["total"]))
            diff = abs((reg + sup) - tot)
            assert diff <= TOLERANCE_DECIMAL, (
                f"Invariant 3 (regular + supplemental != total) failed: {label} state={code!r} "
                f"regular={reg:.2f} supplemental={sup:.2f} total={tot:.2f} diff={diff:.2f}"
            )

            if ft == "regular":
                assert sup == Decimal("0"), (
                    f"Invariant 3 (non-zero supplemental in regular filter) failed: {label} "
                    f"state={code!r} supplemental={sup:.2f}"
                )
            elif ft == "supplemental":
                assert reg == Decimal("0"), (
                    f"Invariant 3 (non-zero regular in supplemental filter) failed: {label} "
                    f"state={code!r} regular={reg:.2f}"
                )

            if deob == "exclude":
                assert tot >= Decimal("0") and reg >= Decimal("0") and sup >= Decimal("0"), (
                    f"Amendment 1 (negative value under deobligations=exclude) failed: {label} "
                    f"state={code!r} total={tot:.2f} regular={reg:.2f} supplemental={sup:.2f}"
                )


def test_invariant_4_shapes_and_non_shape_territory_codes(audit_context):
    """Contract §5 Invariant 4 + Amendment 2: has_shape=false only in {GU, VI, AS, MP, FM, MH, PW}; has_shape=true in /map/shapes."""
    shape_codes = frozenset(audit_context["shapes_json"]["states"].keys())
    profile_geoids = audit_context["profile_geoids"]

    missing_from_shapes: list[str] = []
    unexpected_no_shape: list[str] = []
    bad_indicators: list[str] = []

    for key in audit_context["standard_slices"]:
        label = _format_slice(*key)
        _, _, body = audit_context["map_responses"][key]

        for row in body["states"]:
            code = row["code"]
            if row["has_shape"]:
                if code not in shape_codes:
                    missing_from_shapes.append(f"{label} state={code!r}")
            else:
                if code not in ALLOWED_NO_SHAPE_CODES:
                    unexpected_no_shape.append(
                        f"{label} state={code!r} name={row['name']!r} fips={row['fips']!r} "
                        f"total={row['total']:.2f} award_count={row['award_count']}"
                    )

            expected_geoid = row["fips"] if row["fips"] in profile_geoids else None
            if row["indicators_geoid"] != expected_geoid:
                bad_indicators.append(
                    f"{label} state={code!r} expected_indicators_geoid={expected_geoid!r} "
                    f"actual={row['indicators_geoid']!r}"
                )

    assert not missing_from_shapes, (
        f"Invariant 4 failed: has_shape=True codes missing from /map/shapes: "
        f"{missing_from_shapes[:15]} (total={len(missing_from_shapes)})"
    )
    assert not bad_indicators, (
        f"Contract §2 indicators_geoid mismatch: {bad_indicators[:15]} (total={len(bad_indicators)})"
    )
    assert not unexpected_no_shape, (
        f"Invariant 4 failed: has_shape=False codes outside {sorted(ALLOWED_NO_SHAPE_CODES)} "
        f"({len(unexpected_no_shape)} occurrences across standard slices):\n  "
        + "\n  ".join(unexpected_no_shape)
    )


def test_invariant_5_no_zero_award_count_state_rows(audit_context):
    """Contract §5 Invariant 5 + Amendment 1: no state row has award_count == 0; sorted by name; no '__'."""
    for key in audit_context["all_slices"]:
        label = _format_slice(*key)
        _, _, body = audit_context["map_responses"][key]
        states = body["states"]

        names = [row["name"] for row in states]
        assert names == sorted(names), (
            f"Contract §2 sort order failed ({label}): states[] is not sorted by name"
        )

        for row in states:
            code = row["code"]
            assert code != "__", f"Unattributed code '__' leaked into states[] ({label})"
            assert row["award_count"] > 0, (
                f"Invariant 5 failed: zero award_count row ({label}) state={code!r} row={row}"
            )
            assert row["recipient_count"] > 0, (
                f"Invariant 5 failed: zero recipient_count row ({label}) state={code!r} row={row}"
            )
