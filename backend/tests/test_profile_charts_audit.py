"""Independent contract audit for CHIP profile /charts and /peers endpoints.

Audits live HTTP responses against docs/profile-viz/CHART_CONTRACT.md and cross-checks
sampled rows directly against app.area_pilot.lookup via a read-only SessionLocal session.

Skips cleanly when CHIP_AUDIT_BASE or CHIP_AUDIT_COOKIE is unset.
"""
from __future__ import annotations

import json
import os
import random
import urllib.error
import urllib.request
from typing import Any

import pytest

AUDIT_SEED = 20261119
MAX_COUNTY_BYTES = 400 * 1024
COUNT_UNITS = frozenset({
    "people",
    "beneficiaries",
    "physicians",
    "dentists",
    "hospitals",
    "beds",
    "days",
})
COUNT_MEASURE_IDS = frozenset({
    "total_population",
    "om_beneficiaries",
    "days_with_aqi",
    "good_days",
})
FORBIDDEN_KEYS = frozenset({
    "rank",
    "ranks",
    "change",
    "pct_change",
    "percent_change",
    "delta",
    "composite",
    "average",
    "mean",
})
LINE_OR_DOTS_PRODUCTS = frozenset({"ahrf", "clh", "epa_aqi", "usda_fea"})
# Connecticut's 2024 TIGER planning-region equivalent covering legacy Hartford County (09003).
CT_CAPITOL_GEOID = "09110"
CT_FORMER_HARTFORD_GEOID = "09003"


def _audit_env() -> tuple[str, str]:
    base = (os.environ.get("CHIP_AUDIT_BASE") or "").strip().rstrip("/")
    cookie = (os.environ.get("CHIP_AUDIT_COOKIE") or "").strip()
    if not base or not cookie:
        pytest.skip("CHIP_AUDIT_BASE and CHIP_AUDIT_COOKIE must be set to run the profile chart audit")
    return base, cookie


def _http_get(base: str, cookie: str, path: str) -> tuple[int, bytes, Any]:
    url = f"{base}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Cookie": cookie,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, raw, json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = raw.decode("utf-8", errors="replace")
        return exc.code, raw, body


def _is_count_measure(row: dict[str, Any]) -> bool:
    unit = (row.get("unit") or "").strip().lower()
    return (
        row.get("kind") == "count"
        or unit in COUNT_UNITS
        or row.get("product") == "ahrf"
        or row.get("measure_id") in COUNT_MEASURE_IDS
    )


def _iter_rows(payload: dict[str, Any]):
    for section in payload.get("sections", []):
        for group in section.get("groups", []):
            for row in group.get("rows", []):
                yield section, group, row


def _find_forbidden_keys(obj: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_path = f"{path}.{key}" if path else str(key)
            if str(key).lower() in FORBIDDEN_KEYS:
                found.append(key_path)
            found.extend(_find_forbidden_keys(value, key_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            found.extend(_find_forbidden_keys(item, f"{path}[{idx}]"))
    return found


def _expected_series_bounds(lookup_pt: dict[str, Any]) -> tuple[Any, Any]:
    unc = lookup_pt.get("uncertainty") or {}
    kind = unc.get("kind")
    if kind == "ci95":
        return unc.get("low"), unc.get("high")
    if kind == "moe90":
        val = lookup_pt.get("value")
        moe = unc.get("moe")
        if val is not None and moe is not None:
            return val - moe, val + moe
    return None, None


@pytest.fixture(scope="module")
def audit_context():
    base, cookie = _audit_env()

    from app.area_pilot import lookup
    from app.db import SessionLocal

    with SessionLocal() as db:
        all_states = sorted(s["geoid"] for s in lookup.states(db))
        rng = random.Random(AUDIT_SEED)

        # 5 states, always including 01 (Alabama) and 11 (District of Columbia).
        states = ["01", "11"] + rng.sample([s for s in all_states if s not in ("01", "11")], 3)

        # 10 counties from at least 5 states, always including 01063, 01055, and CT 09110
        # (2024 TIGER Capitol Planning Region; legacy Hartford County 09003 is verified separately as 404).
        county_states = rng.sample([s for s in all_states if s not in ("01", "09", "11")], 7)
        counties = ["01063", "01055", CT_CAPITOL_GEOID]
        for st in county_states:
            state_counties = sorted(c["geoid"] for c in lookup.state_counties(db, st))
            counties.append(rng.choice(state_counties))

        # 3 congressional districts, always including 5401.
        all_districts = sorted(
            d["geoid"]
            for st in all_states
            for d in lookup.state_districts(db, st)
        )
        districts = ["5401"] + rng.sample([d for d in all_districts if d != "5401"], 2)

    assert len(counties) == 10
    assert len({c[:2] for c in counties}) >= 5
    assert len(states) == 5
    assert {"01", "11"}.issubset(states)
    assert len(districts) == 3
    assert "5401" in districts

    responses: dict[tuple[str, str], dict[str, Any]] = {}
    raw_sizes: dict[tuple[str, str], int] = {}
    all_rows: list[tuple[str, str, dict[str, Any] | None, dict[str, Any]]] = []

    for api_level, lookup_level, geoids in (
        ("county", "county", counties),
        ("state", "state", states),
        ("district", "cd", districts),
    ):
        for geoid in geoids:
            status, raw, payload = _http_get(base, cookie, f"/community/{api_level}/{geoid}/charts")
            assert status == 200, (
                f"GEOID={geoid} level={api_level} field=http_status "
                f"expected=200 actual={status}"
            )
            responses[(lookup_level, geoid)] = payload
            raw_sizes[(lookup_level, geoid)] = len(raw)
            for _section, _group, row in _iter_rows(payload):
                all_rows.append((lookup_level, geoid, payload.get("state"), row))

    return {
        "base": base,
        "cookie": cookie,
        "counties": counties,
        "states": states,
        "districts": districts,
        "responses": responses,
        "raw_sizes": raw_sizes,
        "all_rows": all_rows,
        "lookup": lookup,
        "SessionLocal": SessionLocal,
    }


def test_county_payload_sizes_under_400kb(audit_context):
    failures: list[str] = []
    for geoid in audit_context["counties"]:
        size = audit_context["raw_sizes"][("county", geoid)]
        if size > MAX_COUNTY_BYTES:
            failures.append(
                f"GEOID={geoid} measure=* field=payload_bytes expected=<={MAX_COUNTY_BYTES} actual={size}"
            )
    assert not failures, "\n".join(failures)


def test_former_ct_county_09003_returns_404_matching_profile(audit_context):
    """Legacy CT county 09003 is absent from CHIP's 2024 TIGER boundary table (replaced by 09110-09190)."""
    base, cookie = audit_context["base"], audit_context["cookie"]
    charts_status, _, _ = _http_get(base, cookie, f"/community/county/{CT_FORMER_HARTFORD_GEOID}/charts")
    profile_status, _, _ = _http_get(base, cookie, f"/community/county/{CT_FORMER_HARTFORD_GEOID}")
    assert profile_status == 404, (
        f"GEOID={CT_FORMER_HARTFORD_GEOID} measure=* field=profile_http_status "
        f"expected=404 actual={profile_status}"
    )
    assert charts_status == 404, (
        f"GEOID={CT_FORMER_HARTFORD_GEOID} measure=* field=charts_http_status "
        f"expected=404 actual={charts_status}"
    )


def test_contract_section_1_and_2_rules_for_all_rows(audit_context):
    lookup = audit_context["lookup"]
    failures: list[str] = []

    for (lookup_level, geoid), payload in audit_context["responses"].items():
        forbidden = _find_forbidden_keys(payload)
        if forbidden:
            failures.append(
                f"GEOID={geoid} measure=* field=forbidden_keys expected=[] actual={forbidden[:10]}"
            )

        for _section, group, row in _iter_rows(payload):
            product = row["product"]
            measure_id = row["measure_id"]
            mkey = f"{product}:{measure_id}"
            comp = row.get("comparisons") or {}
            trend = row.get("trend")
            peers = row.get("peers")
            reg = lookup.comparability(product, measure_id)
            is_count = _is_count_measure(row)

            # Group shared_axis rule (Contract §4)
            if group.get("shared_axis"):
                units = {r.get("unit") for r in group.get("rows", [])}
                if len(units) > 1:
                    failures.append(
                        f"GEOID={geoid} measure={group.get('key')} field=shared_axis_units "
                        f"expected=single_unit actual={sorted(str(u) for u in units)}"
                    )

            # Rule: no places or brfss row has a state or national marker
            if product in ("places", "brfss"):
                if comp.get("state") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=comparisons.state expected=None actual={comp['state']}"
                    )
                if comp.get("national") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=comparisons.national expected=None actual={comp['national']}"
                    )
                if trend is not None and trend.get("state_series") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=trend.state_series expected=None actual=non-null"
                    )
                if trend is not None and trend.get("national_series") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=trend.national_series expected=None actual=non-null"
                    )

            # Rule: count measures have no markers
            if is_count:
                if comp.get("state") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=count.comparisons.state expected=None actual={comp['state']}"
                    )
                if comp.get("national") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=count.comparisons.national expected=None actual={comp['national']}"
                    )
                if trend is not None and trend.get("state_series") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=count.trend.state_series expected=None actual=non-null"
                    )
                if trend is not None and trend.get("national_series") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=count.trend.national_series expected=None actual=non-null"
                    )

            # Registry comparability rules for markers and peers
            if lookup_level not in reg["state_marker_levels"]:
                if comp.get("state") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=comparisons.state expected=None actual={comp['state']}"
                    )
                if trend is not None and trend.get("state_series") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=trend.state_series expected=None actual=non-null"
                    )
            if lookup_level not in reg["national_marker_levels"]:
                if comp.get("national") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=comparisons.national expected=None actual={comp['national']}"
                    )
                if trend is not None and trend.get("national_series") is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=trend.national_series expected=None actual=non-null"
                    )
            if lookup_level not in (reg.get("peers") or {}):
                if peers is not None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=peers expected=None actual=non-null"
                    )

            # Rule: district trends are null
            if lookup_level == "cd" and trend is not None:
                failures.append(
                    f"GEOID={geoid} measure={mkey} field=trend expected=None actual={trend.get('style')}"
                )

            # Rule: places trend style is dots_ci; other trend styles & fixed notes match registry
            if trend is not None:
                if lookup_level not in reg["trend_levels"]:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=trend expected=None actual={trend.get('style')}"
                    )
                if product == "places" and trend.get("style") != "dots_ci":
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=trend.style expected=dots_ci actual={trend.get('style')}"
                    )
                published_pts = [pt for pt in (trend.get("series") or []) if pt.get("value") is not None]
                expected_style = reg["trend_style"]
                if product in LINE_OR_DOTS_PRODUCTS and len(published_pts) <= 2:
                    expected_style = "dots"
                if trend.get("style") != expected_style:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=trend.style "
                        f"expected={expected_style} actual={trend.get('style')}"
                    )
                allowed_notes = {reg["trend_note"]}
                if reg.get("currency_note") and row.get("kind") == "currency":
                    allowed_notes = {f'{reg["trend_note"]} {reg["currency_note"]}'}
                if reg["trend_note"] is not None and trend.get("note") not in allowed_notes:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=trend.note "
                        f"expected={reg['trend_note']!r} actual={trend.get('note')!r}"
                    )

                # Rule: periods in each series strictly ascend; null values carry non-empty status_text
                for series_key in ("series", "state_series", "national_series"):
                    series = trend.get(series_key)
                    if series is None:
                        continue
                    periods = [pt.get("period") for pt in series]
                    if any(periods[i] >= periods[i + 1] for i in range(len(periods) - 1)):
                        failures.append(
                            f"GEOID={geoid} measure={mkey} field=trend.{series_key}.periods "
                            f"expected=strictly_ascending actual={periods}"
                        )
                    for pt in series:
                        if pt.get("value") is None:
                            st = pt.get("status_text")
                            if not isinstance(st, str) or not st.strip():
                                failures.append(
                                    f"GEOID={geoid} measure={mkey} field=trend.{series_key}[{pt.get('period')}].status_text "
                                    f"expected=non_empty actual={st!r}"
                                )

            # Rule: a null value always carries a non-empty status_text
            if row.get("value") is None:
                st = row.get("status_text")
                if not isinstance(st, str) or not st.strip():
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=status_text expected=non_empty actual={st!r}"
                    )
            side_note = comp.get("side_note")
            if side_note is not None and side_note.get("value") is None:
                st = side_note.get("status_text")
                if not isinstance(st, str) or not st.strip():
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=comparisons.side_note.status_text "
                        f"expected=non_empty actual={st!r}"
                    )

            # Rule: peers.count >= len(peers.values), min <= every value <= max, period matches row
            if peers is not None:
                values = peers.get("values") or []
                count = peers.get("count")
                if not isinstance(count, int) or count < len(values):
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=peers.count "
                        f"expected>={len(values)} actual={count}"
                    )
                if peers.get("period") != row.get("period"):
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=peers.period "
                        f"expected={row.get('period')!r} actual={peers.get('period')!r}"
                    )
                if values:
                    pmin = (peers.get("min") or {}).get("value")
                    pmax = (peers.get("max") or {}).get("value")
                    if pmin is None or pmax is None:
                        failures.append(
                            f"GEOID={geoid} measure={mkey} field=peers.min_max "
                            f"expected=non_null actual=({pmin}, {pmax})"
                        )
                    else:
                        for val in values:
                            if not (pmin <= val <= pmax):
                                failures.append(
                                    f"GEOID={geoid} measure={mkey} field=peers.values "
                                    f"expected=[{pmin}, {pmax}] actual={val}"
                                )
                                break
                        if row.get("value") is not None and not (pmin <= row["value"] <= pmax):
                            failures.append(
                                f"GEOID={geoid} measure={mkey} field=peers_contains_row_value "
                                f"expected=[{pmin}, {pmax}] actual={row['value']}"
                            )

            # Rule: marker period equals row period
            for marker_key in ("state", "national"):
                marker = comp.get(marker_key)
                if marker is not None and marker.get("period") != row.get("period"):
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=comparisons.{marker_key}.period "
                        f"expected={row.get('period')!r} actual={marker.get('period')!r}"
                    )

    assert not failures, f"{len(failures)} rule failure(s):\n" + "\n".join(failures[:50])


def test_50_sampled_rows_match_direct_lookup_exactly(audit_context):
    lookup = audit_context["lookup"]
    SessionLocal = audit_context["SessionLocal"]
    all_rows = audit_context["all_rows"]
    assert len(all_rows) >= 50, f"Expected at least 50 rows to sample, got {len(all_rows)}"

    rng = random.Random(AUDIT_SEED)
    sampled = rng.sample(all_rows, 50)
    failures: list[str] = []

    with SessionLocal() as db:
        for lookup_level, geoid, state_info, row in sampled:
            product = row["product"]
            measure_id = row["measure_id"]
            mkey = f"{product}:{measure_id}"

            av_rows = lookup.area_values(
                db, lookup_level, [geoid], products=[product], measure_ids=[measure_id]
            )["values"]
            if len(av_rows) != 1:
                failures.append(
                    f"GEOID={geoid} measure={mkey} field=area_values_count expected=1 actual={len(av_rows)}"
                )
                continue
            expected = av_rows[0]

            if row["value"] != expected["value"]:
                failures.append(
                    f"GEOID={geoid} measure={mkey} field=value "
                    f"expected={expected['value']!r} actual={row['value']!r}"
                )
            if row["uncertainty"] != expected["uncertainty"]:
                failures.append(
                    f"GEOID={geoid} measure={mkey} field=uncertainty "
                    f"expected={expected['uncertainty']!r} actual={row['uncertainty']!r}"
                )
            if row["period"] != expected["period"]:
                failures.append(
                    f"GEOID={geoid} measure={mkey} field=period "
                    f"expected={expected['period']!r} actual={row['period']!r}"
                )

            comp = row.get("comparisons") or {}
            state_marker = comp.get("state")
            if state_marker is not None:
                state_geoid = (state_info or {}).get("geoid") or geoid[:2]
                st_rows = lookup.area_values(
                    db, "state", [state_geoid], products=[product], measure_ids=[measure_id]
                )["values"]
                if len(st_rows) != 1:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=comparisons.state.lookup expected=1 actual={len(st_rows)}"
                    )
                else:
                    st_exp = st_rows[0]
                    if state_marker["value"] != st_exp["value"]:
                        failures.append(
                            f"GEOID={geoid} measure={mkey} field=comparisons.state.value "
                            f"expected={st_exp['value']!r} actual={state_marker['value']!r}"
                        )
                    if state_marker["uncertainty"] != st_exp["uncertainty"]:
                        failures.append(
                            f"GEOID={geoid} measure={mkey} field=comparisons.state.uncertainty "
                            f"expected={st_exp['uncertainty']!r} actual={state_marker['uncertainty']!r}"
                        )

            nat_marker = comp.get("national")
            nat_series_cache = None
            if nat_marker is not None or ((row.get("trend") or {}).get("national_series") is not None):
                nat_series_cache = lookup.national_series(db, product, measure_id)["series"]

            if nat_marker is not None:
                nat_cur = next((pt for pt in nat_series_cache if pt["period"] == row["period"]), None)
                if nat_cur is None:
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=comparisons.national "
                        f"expected=None actual={nat_marker!r}"
                    )
                else:
                    if nat_marker["value"] != nat_cur["value"]:
                        failures.append(
                            f"GEOID={geoid} measure={mkey} field=comparisons.national.value "
                            f"expected={nat_cur['value']!r} actual={nat_marker['value']!r}"
                        )
                    if nat_marker["uncertainty"] != nat_cur["uncertainty"]:
                        failures.append(
                            f"GEOID={geoid} measure={mkey} field=comparisons.national.uncertainty "
                            f"expected={nat_cur['uncertainty']!r} actual={nat_marker['uncertainty']!r}"
                        )

            trend = row.get("trend")
            if trend is not None:
                ams = lookup.area_measure_series(db, lookup_level, geoid, product, measure_id)["series"]
                api_series = trend.get("series") or []
                if len(api_series) != len(ams):
                    failures.append(
                        f"GEOID={geoid} measure={mkey} field=trend.series.len "
                        f"expected={len(ams)} actual={len(api_series)}"
                    )
                else:
                    for api_pt, db_pt in zip(api_series, ams):
                        if api_pt["period"] != db_pt["period"]:
                            failures.append(
                                f"GEOID={geoid} measure={mkey} field=trend.series.period "
                                f"expected={db_pt['period']!r} actual={api_pt['period']!r}"
                            )
                        if api_pt["value"] != db_pt["value"]:
                            failures.append(
                                f"GEOID={geoid} measure={mkey} field=trend.series[{api_pt['period']}].value "
                                f"expected={db_pt['value']!r} actual={api_pt['value']!r}"
                            )
                        exp_low, exp_high = _expected_series_bounds(db_pt)
                        if api_pt["low"] != exp_low or api_pt["high"] != exp_high:
                            failures.append(
                                f"GEOID={geoid} measure={mkey} field=trend.series[{api_pt['period']}].bounds "
                                f"expected=({exp_low!r}, {exp_high!r}) actual=({api_pt['low']!r}, {api_pt['high']!r})"
                            )

                if trend.get("state_series") is not None:
                    state_geoid = (state_info or {}).get("geoid") or geoid[:2]
                    st_ams = lookup.area_measure_series(db, "state", state_geoid, product, measure_id)["series"]
                    api_st = trend["state_series"]
                    if len(api_st) != len(st_ams):
                        failures.append(
                            f"GEOID={geoid} measure={mkey} field=trend.state_series.len "
                            f"expected={len(st_ams)} actual={len(api_st)}"
                        )
                    else:
                        for api_pt, db_pt in zip(api_st, st_ams):
                            exp_low, exp_high = _expected_series_bounds(db_pt)
                            if (
                                api_pt["period"] != db_pt["period"]
                                or api_pt["value"] != db_pt["value"]
                                or api_pt["low"] != exp_low
                                or api_pt["high"] != exp_high
                            ):
                                failures.append(
                                    f"GEOID={geoid} measure={mkey} field=trend.state_series[{api_pt['period']}] "
                                    f"expected=({db_pt['period']!r}, {db_pt['value']!r}, {exp_low!r}, {exp_high!r}) "
                                    f"actual=({api_pt['period']!r}, {api_pt['value']!r}, {api_pt['low']!r}, {api_pt['high']!r})"
                                )

                if trend.get("national_series") is not None:
                    api_nat = trend["national_series"]
                    if len(api_nat) != len(nat_series_cache):
                        failures.append(
                            f"GEOID={geoid} measure={mkey} field=trend.national_series.len "
                            f"expected={len(nat_series_cache)} actual={len(api_nat)}"
                        )
                    else:
                        for api_pt, db_pt in zip(api_nat, nat_series_cache):
                            exp_low, exp_high = _expected_series_bounds(db_pt)
                            if (
                                api_pt["period"] != db_pt["period"]
                                or api_pt["value"] != db_pt["value"]
                                or api_pt["low"] != exp_low
                                or api_pt["high"] != exp_high
                            ):
                                failures.append(
                                    f"GEOID={geoid} measure={mkey} field=trend.national_series[{api_pt['period']}] "
                                    f"expected=({db_pt['period']!r}, {db_pt['value']!r}, {exp_low!r}, {exp_high!r}) "
                                    f"actual=({api_pt['period']!r}, {api_pt['value']!r}, {api_pt['low']!r}, {api_pt['high']!r})"
                                )

    assert not failures, f"{len(failures)} direct-lookup mismatch(es):\n" + "\n".join(failures[:50])


def test_peers_endpoint_matches_lookup_and_rejects_disallowed_products(audit_context):
    base = audit_context["base"]
    cookie = audit_context["cookie"]
    lookup = audit_context["lookup"]
    SessionLocal = audit_context["SessionLocal"]

    with SessionLocal() as db:
        # Allowed: county PLACES
        st_c, _, body_c = _http_get(base, cookie, "/community/county/01063/peers?measure=places:diabetes_crudeprev")
        assert st_c == 200, f"GEOID=01063 measure=places:diabetes_crudeprev field=peers_status expected=200 actual={st_c}"
        mvw_c = lookup.measure_values_within(db, "places", "diabetes_crudeprev", "county", "01")
        assert len(body_c["values"]) == len(mvw_c["values"])
        for api_row, db_row in zip(body_c["values"], mvw_c["values"]):
            assert api_row["geoid"] == db_row["geoid"]
            assert api_row["value"] == db_row["value"]
            assert api_row["uncertainty"] == db_row["uncertainty"]

        # Allowed: state BRFSS
        st_s, _, body_s = _http_get(base, cookie, "/community/state/01/peers?measure=brfss:diabetes")
        assert st_s == 200, f"GEOID=01 measure=brfss:diabetes field=peers_status expected=200 actual={st_s}"
        mvw_s = lookup.measure_values_within(db, "brfss", "diabetes", "state", None)
        assert len(body_s["values"]) == len(mvw_s["values"])
        for api_row, db_row in zip(body_s["values"], mvw_s["values"]):
            assert api_row["geoid"] == db_row["geoid"]
            assert api_row["value"] == db_row["value"]
            assert api_row["uncertainty"] == db_row["uncertainty"]

    # Disallowed products must return 400 per Contract §2
    for path in (
        "/community/county/01063/peers?measure=acs:B19013_001E",
        "/community/state/01/peers?measure=cms_gv:std_payment_per_capita",
    ):
        status, _, _ = _http_get(base, cookie, path)
        assert status == 400, f"path={path} field=peers_status expected=400 actual={status}"
