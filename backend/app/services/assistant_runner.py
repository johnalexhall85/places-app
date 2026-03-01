from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.assistant_prompt import SYSTEM_PROMPT, build_developer_context
from app.services.assistant_tools import TOOLS
from app.services.assistant_tools_impl import (
    export_profile_pdf,
    generate_full_profile,
    get_estimate_county,
    get_estimate_nation,
    get_hpsa_county_summary,
    get_profile,
    get_estimate_state,
    get_estimates_for_counties,
    get_neighbor_counties,
    resolve_county,
)
from app.services.openrouter import OpenRouterClient
from app.settings import (
    ASSISTANT_FORMAT_RETRY_LIMIT,
    ASSISTANT_MAX_STEPS,
    OPENROUTER_TOOL_CHOICE,
)

MAX_STEPS = ASSISTANT_MAX_STEPS
FORMAT_RETRY_LIMIT = ASSISTANT_FORMAT_RETRY_LIMIT
DEFAULT_NEIGHBOR_COUNT = 5
DEFAULT_FLY_ZOOM = 9
ASSISTANT_ACTION_SET_CONTEXT = "SET_MEASURE_CONTEXT"
ALLOWED_ACTION_TYPES = {
    ASSISTANT_ACTION_SET_CONTEXT,
    "MAP_FLY_TO",
    "MAP_FIT_BOUNDS",
    "MAP_HIGHLIGHT",
}
NUMERIC_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?")
MEASURE_TOKEN_STOPWORDS = {
    "the",
    "and",
    "with",
    "among",
    "adults",
    "adult",
    "aged",
    "years",
    "year",
    "current",
    "prevalence",
    "of",
    "to",
    "for",
    "in",
    "at",
    "is",
}


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def _to_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)


def _extract_json_object(content: str) -> dict[str, Any] | None:
    if not content:
        return None

    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _collect_numeric_values(value: Any, destination: set[float]) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        parsed = _safe_float(value)
        if parsed is not None:
            destination.add(parsed)
        return
    if isinstance(value, str):
        stripped = value.strip()
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", stripped):
            parsed = _safe_float(stripped)
            if parsed is not None:
                destination.add(parsed)
        return
    if isinstance(value, list):
        for item in value:
            _collect_numeric_values(item, destination)
        return
    if isinstance(value, dict):
        for item in value.values():
            _collect_numeric_values(item, destination)


def _find_unverified_numbers(answer_markdown: str, allowed_numbers: set[float]) -> list[str]:
    unknown: list[str] = []
    for match in NUMERIC_TOKEN_PATTERN.finditer(answer_markdown):
        token = match.group(0)
        numeric = _safe_float(token)
        if numeric is None:
            continue
        matched = any(abs(numeric - allowed) <= 0.11 for allowed in allowed_numbers)
        if not matched:
            unknown.append(token)
    return unknown


def _format_estimate(entry: dict[str, Any] | None) -> str:
    if not isinstance(entry, dict):
        return "Data unavailable"
    value = _safe_float(entry.get("value"))
    ci_low = _safe_float(entry.get("ci_low"))
    ci_high = _safe_float(entry.get("ci_high"))
    if value is None:
        return "Data unavailable"
    if ci_low is None or ci_high is None:
        return f"{value:.1f}% (95% CI: unavailable)"
    return f"{value:.1f}% (95% CI: {ci_low:.1f}\u2013{ci_high:.1f})"


def _build_safe_answer(runtime_state: dict[str, Any], context: dict[str, Any]) -> str:
    resolved = runtime_state.get("resolved_county")
    county_estimate = runtime_state.get("county_estimate")
    state_estimate = runtime_state.get("state_estimate")
    nation_estimate = runtime_state.get("nation_estimate")
    neighbor_counties = runtime_state.get("neighbor_counties") or []
    neighbor_estimates = runtime_state.get("neighbor_estimates") or []

    county_label = "Requested county"
    state_label = "State"
    if isinstance(resolved, dict):
        county_name = resolved.get("county_name")
        state_abbr = resolved.get("state_abbr")
        if county_name and state_abbr:
            county_label = f"{county_name}, {state_abbr}"
            state_label = str(state_abbr)

    lines = [
        (
            f"Comparison for `{context['measure_id']}` "
            f"({context['data_value_type_id']}, {context['year']})"
        ),
        "",
        f"- {county_label}: {_format_estimate(county_estimate)}",
        f"- {state_label}: {_format_estimate(state_estimate)}",
        f"- US: {_format_estimate(nation_estimate)}",
        "- Nearby counties:",
    ]

    estimates_by_fips = {
        item.get("county_fips"): item
        for item in neighbor_estimates
        if isinstance(item, dict) and item.get("county_fips")
    }
    if neighbor_counties:
        for county in neighbor_counties[:DEFAULT_NEIGHBOR_COUNT]:
            county_fips = county.get("county_fips")
            county_name = county.get("county_name") or county_fips or "County"
            county_state = county.get("state_abbr")
            label = county_name if not county_state else f"{county_name}, {county_state}"
            estimate = estimates_by_fips.get(county_fips)
            lines.append(f"  - {label}: {_format_estimate(estimate)}")
    else:
        lines.append("  - Data unavailable")

    return "\n".join(lines)


def _normalize_measure_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _detect_data_value_type_override(user_text: str) -> str | None:
    lowered = user_text.lower()
    age_match = re.search(r"\b(age[-\s]?adjusted|ageadjprv)\b", lowered)
    crude_match = re.search(r"\b(crude|crdprv)\b", lowered)

    if age_match and crude_match:
        return "AgeAdjPrv" if age_match.start() < crude_match.start() else "CrdPrv"
    if age_match:
        return "AgeAdjPrv"
    if crude_match:
        return "CrdPrv"
    return None


def _detect_year_override(user_text: str) -> int | None:
    for token in re.findall(r"\b(19\d{2}|20\d{2})\b", user_text):
        try:
            return int(token)
        except ValueError:
            continue
    return None


def _detect_measure_override(
    db: Session,
    *,
    user_text: str,
    current_measure_id: str,
) -> str | None:
    normalized_query = _normalize_measure_text(user_text)
    if not normalized_query:
        return None

    padded_query = f" {normalized_query} "
    rows = db.execute(
        text(
            """
            SELECT DISTINCT ON (measure_id)
                measure_id,
                measure,
                short_question_text
            FROM dim_measure
            ORDER BY measure_id
            """
        )
    ).mappings().all()

    best_measure_id: str | None = None
    best_score = 0

    for row in rows:
        measure_id = str(row.get("measure_id") or "").strip()
        if not measure_id:
            continue

        score = 0
        if re.search(rf"\b{re.escape(measure_id.lower())}\b", user_text.lower()):
            score += 100

        label_parts = [
            str(row.get("measure") or ""),
            str(row.get("short_question_text") or ""),
            measure_id,
        ]
        label_normalized = _normalize_measure_text(" ".join(label_parts))
        if label_normalized and label_normalized in normalized_query:
            score += 8

        tokens = {
            token
            for token in label_normalized.split()
            if len(token) >= 4 and token not in MEASURE_TOKEN_STOPWORDS
        }
        for token in tokens:
            if f" {token} " in padded_query:
                score += 2

        if score > best_score:
            best_score = score
            best_measure_id = measure_id
        elif score == best_score and measure_id == current_measure_id:
            best_measure_id = current_measure_id

    if best_score <= 0:
        return None
    return best_measure_id


def _resolve_context(context: dict[str, Any]) -> dict[str, Any]:
    measure_id = str(context.get("measure_id") or "").strip()
    data_value_type_id = str(context.get("data_value_type_id") or "").strip()
    year = _to_int(context.get("year"), 0)
    return {
        "measure_id": measure_id,
        "year": year,
        "data_value_type_id": data_value_type_id,
        "zoom": context.get("zoom"),
        "bbox": context.get("bbox"),
        "active_layer": context.get("active_layer"),
    }


def _resolve_effective_context(
    db: Session,
    *,
    user_text: str,
    requested_context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    detected_measure_id = _detect_measure_override(
        db,
        user_text=user_text,
        current_measure_id=requested_context["measure_id"],
    )
    detected_year = _detect_year_override(user_text)
    detected_data_type = _detect_data_value_type_override(user_text)

    effective_measure_id = detected_measure_id or requested_context["measure_id"]
    effective_year = detected_year if detected_year is not None else requested_context["year"]
    effective_data_type = detected_data_type or requested_context["data_value_type_id"]

    available_types = db.execute(
        text(
            """
            SELECT DISTINCT data_value_type_id
            FROM dim_measure
            WHERE measure_id = :measure_id
            ORDER BY data_value_type_id
            """
        ),
        {"measure_id": effective_measure_id},
    ).scalars().all()
    available_types = [str(value) for value in available_types if value is not None]
    if available_types and effective_data_type not in available_types:
        if requested_context["data_value_type_id"] in available_types:
            effective_data_type = requested_context["data_value_type_id"]
        else:
            effective_data_type = available_types[0]

    effective_context = {
        "measure_id": effective_measure_id,
        "year": effective_year,
        "data_value_type_id": effective_data_type,
        "zoom": requested_context.get("zoom"),
        "bbox": requested_context.get("bbox"),
        "active_layer": requested_context.get("active_layer"),
    }
    overrides = {
        "measure_id": (
            effective_measure_id
            if effective_measure_id != requested_context["measure_id"]
            else None
        ),
        "year": (
            effective_year if effective_year != requested_context["year"] else None
        ),
        "data_value_type_id": (
            effective_data_type
            if effective_data_type != requested_context["data_value_type_id"]
            else None
        ),
    }
    return effective_context, overrides


def _context_action_from_context(context: dict[str, Any]) -> dict[str, Any] | None:
    measure_id = str(context.get("measure_id") or "").strip()
    data_value_type_id = str(context.get("data_value_type_id") or "").strip()
    year = _to_int(context.get("year"), 0)
    if not measure_id or not data_value_type_id or year <= 0:
        return None
    return {
        "type": ASSISTANT_ACTION_SET_CONTEXT,
        "measure_id": measure_id,
        "year": year,
        "data_value_type_id": data_value_type_id,
    }


def _ensure_context_action(
    actions: list[dict[str, Any]],
    *,
    effective_context: dict[str, Any],
) -> list[dict[str, Any]]:
    context_action = _context_action_from_context(effective_context)
    filtered = [
        action
        for action in actions
        if str(action.get("type") or "").upper() != ASSISTANT_ACTION_SET_CONTEXT
    ]
    if context_action is None:
        return filtered
    return [context_action, *filtered]


def _safe_fallback(
    *,
    reason: str,
    debug: dict[str, Any],
    runtime_state: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    context_action = _context_action_from_context(context)
    fallback_actions = [context_action] if context_action else []
    fallback_actions, _ = _ensure_required_actions(
        actions=fallback_actions,
        runtime_state=runtime_state,
    )
    return {
        "actions": fallback_actions,
        "answer_markdown": _build_safe_answer(runtime_state, context),
        "debug": {
            **debug,
            "fallback_reason": reason,
        },
    }


def _normalize_actions(raw_actions: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_actions, list):
        return []

    normalized: list[dict[str, Any]] = []
    for action in raw_actions:
        if not isinstance(action, dict):
            continue
        action_type = str(action.get("type") or "").strip().upper()
        if action_type not in ALLOWED_ACTION_TYPES:
            continue

        merged = dict(action)
        payload = action.get("payload")
        if isinstance(payload, dict):
            for key, value in payload.items():
                merged.setdefault(key, value)

        if action_type == ASSISTANT_ACTION_SET_CONTEXT:
            measure_id = str(merged.get("measure_id") or "").strip()
            year = _to_int(merged.get("year"), 0)
            data_value_type_id = str(merged.get("data_value_type_id") or "").strip()
            if not measure_id or not data_value_type_id or year <= 0:
                continue
            normalized.append(
                {
                    "type": ASSISTANT_ACTION_SET_CONTEXT,
                    "measure_id": measure_id,
                    "year": year,
                    "data_value_type_id": data_value_type_id,
                }
            )
            continue

        if action_type == "MAP_FLY_TO":
            lat = _safe_float(
                merged.get("lat")
                or merged.get("latitude")
                or merged.get("centroid_lat")
            )
            lng = _safe_float(
                merged.get("lng")
                or merged.get("lon")
                or merged.get("longitude")
                or merged.get("centroid_lng")
            )
            zoom = _safe_float(merged.get("zoom"))
            if lat is None or lng is None:
                continue
            normalized.append(
                {
                    "type": "MAP_FLY_TO",
                    "lat": lat,
                    "lng": lng,
                    "zoom": zoom if zoom is not None else DEFAULT_FLY_ZOOM,
                }
            )
            continue

        if action_type == "MAP_FIT_BOUNDS":
            bounds = merged.get("bounds")
            if bounds is None:
                bounds = merged.get("bbox")
            if bounds is None:
                continue
            normalized.append({"type": "MAP_FIT_BOUNDS", "bounds": bounds})
            continue

        if action_type == "MAP_HIGHLIGHT":
            geoid = str(
                merged.get("geoid")
                or merged.get("county_fips")
                or merged.get("location_id")
                or merged.get("fips")
                or ""
            ).strip()
            if not geoid:
                continue
            level = str(merged.get("level") or "county").strip().lower()
            normalized.append(
                {
                    "type": "MAP_HIGHLIGHT",
                    "level": level or "county",
                    "geoid": geoid,
                }
            )

    return normalized


def _ensure_required_actions(
    *,
    actions: list[dict[str, Any]],
    runtime_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    resolved = runtime_state.get("resolved_county")
    if not isinstance(resolved, dict) or not resolved.get("county_fips"):
        return actions, None

    county_fips = str(resolved["county_fips"])
    lat = _safe_float(resolved.get("lat"))
    lng = _safe_float(resolved.get("lng"))

    has_fly_to = False
    has_highlight = False
    output: list[dict[str, Any]] = []
    for action in actions:
        action_type = str(action.get("type") or "").upper()
        if action_type == ASSISTANT_ACTION_SET_CONTEXT:
            output.append(action)
            continue
        if action_type == "MAP_FLY_TO":
            if _safe_float(action.get("lat")) is None or _safe_float(action.get("lng")) is None:
                continue
            has_fly_to = True
        elif action_type == "MAP_HIGHLIGHT":
            action_level = str(action.get("level") or "").lower()
            action_geoid = str(action.get("geoid") or "").strip()
            if action_level == "county" and action_geoid == county_fips:
                has_highlight = True
        output.append(action)

    if not has_fly_to:
        if lat is None or lng is None:
            return output, "Resolved county is missing centroid coordinates."
        output.insert(
            0,
            {
                "type": "MAP_FLY_TO",
                "lat": lat,
                "lng": lng,
                "zoom": DEFAULT_FLY_ZOOM,
            },
        )
    if not has_highlight:
        output.append(
            {
                "type": "MAP_HIGHLIGHT",
                "level": "county",
                "geoid": county_fips,
            }
        )

    return output, None


def _normalize_county_zoom(
    *,
    actions: list[dict[str, Any]],
    runtime_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    county_highlight = next(
        (
            action
            for action in actions
            if str(action.get("type") or "").upper() == "MAP_HIGHLIGHT"
            and str(action.get("level") or "").strip().lower() == "county"
            and str(action.get("geoid") or "").strip()
        ),
        None,
    )
    if county_highlight is None:
        return (
            actions,
            {
                "zoom_normalized": False,
                "final_zoom": DEFAULT_FLY_ZOOM,
            },
            None,
        )

    normalized_actions = [dict(action) for action in actions]
    debug_updates: dict[str, Any] = {
        "zoom_normalized": False,
        "final_zoom": DEFAULT_FLY_ZOOM,
    }

    fly_to_index = next(
        (
            index
            for index, action in enumerate(normalized_actions)
            if str(action.get("type") or "").upper() == "MAP_FLY_TO"
        ),
        None,
    )

    if fly_to_index is not None:
        original_zoom = _safe_float(normalized_actions[fly_to_index].get("zoom"))
        if original_zoom is not None:
            debug_updates["original_zoom"] = original_zoom
        if original_zoom != float(DEFAULT_FLY_ZOOM):
            normalized_actions[fly_to_index]["zoom"] = DEFAULT_FLY_ZOOM
            debug_updates["zoom_normalized"] = True
        else:
            normalized_actions[fly_to_index]["zoom"] = DEFAULT_FLY_ZOOM
        return normalized_actions, debug_updates, None

    resolved = runtime_state.get("resolved_county")
    lat = _safe_float(resolved.get("lat")) if isinstance(resolved, dict) else None
    lng = _safe_float(resolved.get("lng")) if isinstance(resolved, dict) else None
    if lat is None or lng is None:
        return (
            normalized_actions,
            debug_updates,
            "County highlight requires centroid coordinates to insert MAP_FLY_TO.",
        )

    normalized_actions.insert(
        0,
        {
            "type": "MAP_FLY_TO",
            "lat": lat,
            "lng": lng,
            "zoom": DEFAULT_FLY_ZOOM,
        },
    )
    debug_updates["zoom_normalized"] = True
    return normalized_actions, debug_updates, None


def _assert_county_zoom_invariant(actions: list[dict[str, Any]]) -> None:
    has_county_highlight = any(
        str(action.get("type") or "").upper() == "MAP_HIGHLIGHT"
        and str(action.get("level") or "").strip().lower() == "county"
        and str(action.get("geoid") or "").strip()
        for action in actions
    )
    if not has_county_highlight:
        return

    fly_to_actions = [
        action
        for action in actions
        if str(action.get("type") or "").upper() == "MAP_FLY_TO"
    ]
    if not fly_to_actions:
        raise AssertionError(
            "County highlight requires MAP_FLY_TO in final assistant actions."
        )

    if not any(_safe_float(action.get("zoom")) == float(DEFAULT_FLY_ZOOM) for action in fly_to_actions):
        raise AssertionError(
            f"County highlight requires MAP_FLY_TO zoom={DEFAULT_FLY_ZOOM}."
        )


def _validate_and_normalize_response(
    *,
    parsed: dict[str, Any],
    runtime_state: dict[str, Any],
    effective_context: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    if set(parsed.keys()) != {"actions", "answer_markdown", "debug"}:
        return None, "Top-level JSON keys must be exactly actions, answer_markdown, debug."

    if not isinstance(parsed.get("answer_markdown"), str):
        return None, "answer_markdown must be a string."
    if not isinstance(parsed.get("debug"), dict):
        return None, "debug must be an object."
    if not isinstance(parsed.get("actions"), list):
        return None, "actions must be an array."

    normalized_actions = _normalize_actions(parsed["actions"])
    required_actions, required_error = _ensure_required_actions(
        actions=normalized_actions,
        runtime_state=runtime_state,
    )
    if required_error:
        return None, required_error

    zoom_actions, zoom_debug, zoom_error = _normalize_county_zoom(
        actions=required_actions,
        runtime_state=runtime_state,
    )
    if zoom_error:
        return None, zoom_error

    try:
        _assert_county_zoom_invariant(zoom_actions)
    except AssertionError as exc:
        return None, str(exc)

    answer_markdown = parsed["answer_markdown"].strip()
    if not answer_markdown:
        return None, "answer_markdown must not be empty."

    final_actions = _ensure_context_action(
        zoom_actions,
        effective_context=effective_context,
    )
    return {
        "actions": final_actions,
        "answer_markdown": answer_markdown,
        "debug": {
            **parsed["debug"],
            **zoom_debug,
        },
    }, None


def _run_tool(
    *,
    name: str,
    args: dict[str, Any],
    db: Session,
    context: dict[str, Any],
    runtime_state: dict[str, Any],
) -> dict[str, Any]:
    if name == "resolve_county":
        result = resolve_county(db, query=str(args.get("query") or ""))
        runtime_state["county_resolution"] = result
        if result.get("found") and isinstance(result.get("match"), dict):
            runtime_state["resolved_county"] = result["match"]
        return result

    if name == "get_estimate_county":
        county_fips = str(args.get("county_fips") or "").strip()
        measure_id = str(args.get("measure_id") or context["measure_id"]).strip()
        year = _to_int(args.get("year"), context["year"])
        data_type = str(args.get("data_value_type_id") or context["data_value_type_id"]).strip()
        result = get_estimate_county(
            db,
            county_fips=county_fips,
            measure_id=measure_id,
            year=year,
            data_value_type_id=data_type,
        )
        runtime_state["county_estimate"] = result
        if county_fips and runtime_state.get("resolved_county") is None:
            fallback_resolution = resolve_county(db, query=county_fips)
            if fallback_resolution.get("found") and isinstance(fallback_resolution.get("match"), dict):
                runtime_state["resolved_county"] = fallback_resolution["match"]
        return result

    if name == "get_estimate_state":
        resolved_county = runtime_state.get("resolved_county")
        fallback_state = (
            str(resolved_county.get("state_abbr")).strip()
            if isinstance(resolved_county, dict) and resolved_county.get("state_abbr")
            else ""
        )
        state_abbr = str(args.get("state_abbr") or fallback_state).strip().upper()
        measure_id = str(args.get("measure_id") or context["measure_id"]).strip()
        year = _to_int(args.get("year"), context["year"])
        data_type = str(args.get("data_value_type_id") or context["data_value_type_id"]).strip()
        result = get_estimate_state(
            db,
            state_abbr=state_abbr,
            measure_id=measure_id,
            year=year,
            data_value_type_id=data_type,
        )
        runtime_state["state_estimate"] = result
        return result

    if name == "get_estimate_nation":
        measure_id = str(args.get("measure_id") or context["measure_id"]).strip()
        year = _to_int(args.get("year"), context["year"])
        data_type = str(args.get("data_value_type_id") or context["data_value_type_id"]).strip()
        result = get_estimate_nation(
            db,
            measure_id=measure_id,
            year=year,
            data_value_type_id=data_type,
        )
        runtime_state["nation_estimate"] = result
        return result

    if name == "get_neighbor_counties":
        resolved_county = runtime_state.get("resolved_county")
        fallback_fips = (
            str(resolved_county.get("county_fips")).strip()
            if isinstance(resolved_county, dict) and resolved_county.get("county_fips")
            else ""
        )
        county_fips = str(args.get("county_fips") or fallback_fips).strip()
        k = _to_int(args.get("k"), DEFAULT_NEIGHBOR_COUNT)
        result = get_neighbor_counties(
            db,
            county_fips=county_fips,
            k=k,
        )
        runtime_state["neighbor_counties"] = result.get("neighbors") or []
        return result

    if name == "get_estimates_for_counties":
        raw_counties = args.get("county_fips_list")
        county_fips_list = raw_counties if isinstance(raw_counties, list) else []
        measure_id = str(args.get("measure_id") or context["measure_id"]).strip()
        year = _to_int(args.get("year"), context["year"])
        data_type = str(args.get("data_value_type_id") or context["data_value_type_id"]).strip()
        result = get_estimates_for_counties(
            db,
            county_fips_list=county_fips_list,
            measure_id=measure_id,
            year=year,
            data_value_type_id=data_type,
        )
        runtime_state["neighbor_estimates"] = result.get("counties") or []
        return result

    if name == "get_hpsa_county_summary":
        resolved_county = runtime_state.get("resolved_county")
        fallback_fips = (
            str(resolved_county.get("county_fips")).strip()
            if isinstance(resolved_county, dict) and resolved_county.get("county_fips")
            else ""
        )
        county_fips = str(args.get("county_fips") or fallback_fips).strip()
        result = get_hpsa_county_summary(
            db,
            county_fips=county_fips,
        )
        runtime_state["hpsa_summary"] = result
        return result

    if name == "generate_full_profile":
        resolved_county = runtime_state.get("resolved_county")
        fallback_location_id = (
            str(resolved_county.get("county_fips")).strip()
            if isinstance(resolved_county, dict) and resolved_county.get("county_fips")
            else ""
        )
        location_id = str(args.get("location_id") or fallback_location_id).strip()
        geography_value = str(args.get("geography") or "county").strip().lower()
        if geography_value not in {"county", "tract"}:
            geography_value = "county"
        places_year = _to_int(args.get("places_year"), context["year"])
        places_measure_id = str(args.get("places_measure_id") or context["measure_id"]).strip()
        places_data_type = str(
            args.get("places_data_value_type_id") or context["data_value_type_id"]
        ).strip()
        acs_year_window = args.get("acs_year_window")
        if acs_year_window is not None:
            acs_year_window = str(acs_year_window).strip() or None
        acs_data_type = str(args.get("acs_data_value_type_id") or "Percent").strip() or "Percent"
        include_charts = bool(args.get("include_charts", True))
        include_full_narrative = bool(args.get("include_full_narrative", True))
        include_profile_json = bool(args.get("include_profile_json", False))

        result = generate_full_profile(
            db,
            geography=geography_value,
            location_id=location_id,
            places_year=places_year,
            places_measure_id=places_measure_id,
            places_data_value_type_id=places_data_type,
            acs_year_window=acs_year_window,
            acs_data_value_type_id=acs_data_type,
            include_charts=include_charts,
            include_full_narrative=include_full_narrative,
            include_profile_json=include_profile_json,
        )
        if result.get("found") and result.get("profile_id"):
            runtime_state["generated_profile_id"] = str(result.get("profile_id"))
            runtime_state["generated_profile_summary"] = str(result.get("summary_text") or "")
        return result

    if name == "get_profile":
        fallback_profile_id = str(runtime_state.get("generated_profile_id") or "").strip()
        profile_id = str(args.get("profile_id") or fallback_profile_id).strip()
        result = get_profile(
            db,
            profile_id=profile_id,
        )
        if result.get("found") and result.get("profile_id"):
            runtime_state["generated_profile_id"] = str(result.get("profile_id"))
            runtime_state["generated_profile_summary"] = str(result.get("summary_text") or "")
        return result

    if name == "export_profile_pdf":
        fallback_profile_id = str(runtime_state.get("generated_profile_id") or "").strip()
        profile_id = str(args.get("profile_id") or fallback_profile_id).strip()
        result = export_profile_pdf(
            db,
            profile_id=profile_id,
        )
        if result.get("found") and result.get("profile_id"):
            runtime_state["generated_profile_id"] = str(result.get("profile_id"))
        return result

    return {"found": False, "reason": f"Unknown tool: {name}"}


def run_assistant(
    *,
    user_text: str,
    context: dict[str, Any],
    db: Session,
) -> dict[str, Any]:
    stripped_user_text = (user_text or "").strip()
    requested_context = _resolve_context(context)
    effective_context, context_overrides = _resolve_effective_context(
        db,
        user_text=stripped_user_text,
        requested_context=requested_context,
    )

    runtime_state: dict[str, Any] = {
        "resolved_county": None,
        "county_resolution": None,
        "county_estimate": None,
        "state_estimate": None,
        "nation_estimate": None,
        "neighbor_counties": [],
        "neighbor_estimates": [],
        "hpsa_summary": None,
        "generated_profile_id": None,
        "generated_profile_summary": None,
    }
    debug_summary: dict[str, Any] = {
        "tool_calls": [],
        "requested_context": requested_context,
        "effective_context": effective_context,
        "context_overrides": context_overrides,
    }
    allowed_numbers: set[float] = {float(effective_context["year"]), 95.0}

    initial_resolution = resolve_county(db, query=stripped_user_text)
    runtime_state["county_resolution"] = initial_resolution
    if initial_resolution.get("found") and isinstance(initial_resolution.get("match"), dict):
        resolved_match = initial_resolution["match"]
        runtime_state["resolved_county"] = resolved_match
        debug_summary["initial_county_resolution"] = {
            "found": True,
            "county_fips": resolved_match.get("county_fips"),
            "state_abbr": resolved_match.get("state_abbr"),
            "used_best_guess": bool(initial_resolution.get("alternatives")),
        }
    else:
        debug_summary["initial_county_resolution"] = {"found": False}

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "developer", "content": build_developer_context(effective_context)},
        {"role": "user", "content": stripped_user_text},
    ]
    client = OpenRouterClient()
    format_retry_count = 0

    for _ in range(MAX_STEPS):
        completion = client.chat(
            messages=messages,
            tools=TOOLS,
            tool_choice=OPENROUTER_TOOL_CHOICE,
        )
        choices = completion.get("choices")
        if not isinstance(choices, list) or not choices:
            return _safe_fallback(
                reason="Model provider returned no choices.",
                debug=debug_summary,
                runtime_state=runtime_state,
                context=effective_context,
            )

        message = (choices[0] or {}).get("message") or {}
        tool_calls = message.get("tool_calls")
        assistant_content = _to_text(message.get("content"))

        if isinstance(tool_calls, list) and tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": tool_calls,
                }
            )

            for tool_call in tool_calls:
                tool_call_id = str(
                    tool_call.get("id") or f"tool_{len(debug_summary['tool_calls']) + 1}"
                )
                function_data = tool_call.get("function") or {}
                tool_name = str(function_data.get("name") or "").strip()
                raw_arguments = function_data.get("arguments")

                tool_args: dict[str, Any]
                if isinstance(raw_arguments, str):
                    try:
                        parsed_args = json.loads(raw_arguments)
                    except json.JSONDecodeError:
                        parsed_args = {}
                    tool_args = parsed_args if isinstance(parsed_args, dict) else {}
                elif isinstance(raw_arguments, dict):
                    tool_args = raw_arguments
                else:
                    tool_args = {}

                _collect_numeric_values(tool_args, allowed_numbers)

                try:
                    tool_result = _run_tool(
                        name=tool_name,
                        args=tool_args,
                        db=db,
                        context=effective_context,
                        runtime_state=runtime_state,
                    )
                except Exception:
                    tool_result = {
                        "found": False,
                        "reason": "Tool execution failed.",
                    }

                _collect_numeric_values(tool_result, allowed_numbers)
                debug_summary["tool_calls"].append(
                    {
                        "name": tool_name,
                        "ok": bool(tool_result.get("found", False)),
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "name": tool_name,
                        "content": json.dumps(tool_result, ensure_ascii=True),
                    }
                )
            continue

        parsed = _extract_json_object(assistant_content)
        if parsed is None:
            if format_retry_count < FORMAT_RETRY_LIMIT:
                format_retry_count += 1
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append(
                    {
                        "role": "developer",
                        "content": (
                            "FORMAT CORRECTION: return only a single valid JSON object "
                            "with EXACT keys actions, answer_markdown, debug."
                        ),
                    }
                )
                continue
            return _safe_fallback(
                reason="Model output was not valid JSON.",
                debug=debug_summary,
                runtime_state=runtime_state,
                context=effective_context,
            )

        validated, validation_error = _validate_and_normalize_response(
            parsed=parsed,
            runtime_state=runtime_state,
            effective_context=effective_context,
        )
        if validation_error:
            if format_retry_count < FORMAT_RETRY_LIMIT:
                format_retry_count += 1
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append(
                    {
                        "role": "developer",
                        "content": (
                            "FORMAT CORRECTION: output must be valid JSON with EXACT keys "
                            "actions, answer_markdown, debug. "
                            f"Validation error: {validation_error}"
                        ),
                    }
                )
                continue
            return _safe_fallback(
                reason=validation_error,
                debug=debug_summary,
                runtime_state=runtime_state,
                context=effective_context,
            )

        unknown_numbers = _find_unverified_numbers(
            validated["answer_markdown"], allowed_numbers
        )
        if unknown_numbers:
            validated["answer_markdown"] = _build_safe_answer(runtime_state, effective_context)
            validated["debug"]["guardrail_unverified_numbers"] = unknown_numbers

        model_debug = validated["debug"] if isinstance(validated["debug"], dict) else {}
        sanitized_model_debug = {
            key: value
            for key, value in model_debug.items()
            if key not in {"tool_calls", "messages", "raw_tool_calls"}
        }
        merged_debug = {
            **sanitized_model_debug,
            **debug_summary,
        }

        return {
            "actions": validated["actions"],
            "answer_markdown": validated["answer_markdown"],
            "debug": merged_debug,
        }

    return _safe_fallback(
        reason="Assistant exceeded maximum tool-calling iterations.",
        debug=debug_summary,
        runtime_state=runtime_state,
        context=effective_context,
    )
