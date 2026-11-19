"""Read-only profile chart composition from published area lookup functions."""
from __future__ import annotations

import json
from pathlib import Path

from app.area_pilot import lookup

GROUPS = json.loads(Path(__file__).with_name("chart_groups.json").read_text())
SECTIONS = ("people", "health", "prevention", "care", "conditions", "food", "environment", "medicare")
_CACHE: dict[tuple, dict] = {}


def _keys(group: dict, level: str) -> list[str]:
    return group.get("all", []) + group.get(level, [])


def _published(row: dict) -> bool:
    return row.get("value") is not None


def _point(row: dict | None) -> dict | None:
    if not row or not _published(row):
        return None
    return {k: row.get(k) for k in ("geoid", "name", "value", "uncertainty", "period")}


def _series_row(row: dict, product_name: str) -> dict:
    uncertainty = row.get("uncertainty") or {}
    value = row.get("value")
    moe = uncertainty.get("moe")
    return {"period": row["period"], "value": value,
            "low": uncertainty.get("low") if moe is None or value is None else value - moe,
            "high": uncertainty.get("high") if moe is None or value is None else value + moe,
            "status": row.get("status"), "status_text": row.get("status_text"),
            "note": row.get("note"), "boundary_vintage": row.get("boundary_vintage"),
            "release_label": product_name if row.get("current_period") else ((row.get("note") or "").split(".")[0] if "release" in (row.get("note") or "").lower() else row.get("source_release_id")),
            "current_period": row.get("current_period", False)}


def _trend(raw: dict, rule: dict, level: str, state_raw: dict | None, national_raw: dict | None,
           product_name: str) -> dict | None:
    if level == "cd" or level not in rule["trend_levels"]:
        return None
    series = raw.get("series", [])
    if sum(_published(row) for row in series) < 2:
        return None
    style = rule["trend_style"]
    if style == "line" and sum(_published(row) for row in series) <= 2:
        style = "dots"
    notes = [row.get("note") for row in series if row.get("note")]
    note = rule.get("trend_note") or (notes[0] if notes else None)
    if rule.get("currency_note") and series and series[-1].get("kind") == "currency":
        note = f'{note} {rule["currency_note"]}' if note else rule["currency_note"]
    return {"style": style, "note": note,
            "series": [_series_row(row, product_name) for row in series],
            "state_series": [_series_row(row, product_name) for row in state_raw.get("series", [])] if state_raw else None,
            "national_series": [_series_row(row, product_name) for row in national_raw.get("series", [])] if national_raw else None,
            "unavailable_periods": raw.get("unavailable_periods", [])}


def _peers(db, level: str, geoid: str, row: dict, rule: dict) -> dict | None:
    peers_rule = rule.get("peers") or {}
    if level not in peers_rule:
        return None
    parent = geoid[:2] if peers_rule[level] == "state" else None
    result = lookup.measure_values_within(db, row["product"], row["measure_id"], level, parent, row["period"])
    rows = [item for item in result["values"] if _published(item) and item["period"] == row["period"]]
    if not rows:
        return None
    low = min(rows, key=lambda item: (item["value"], item["geoid"]))
    high = max(rows, key=lambda item: (item["value"], item["geoid"]))
    return {"level": level, "parent_geoid": parent, "period": row["period"], "count": len(rows),
            "values": [item["value"] for item in rows],
            "min": {k: low.get(k) for k in ("geoid", "name", "value")},
            "max": {k: high.get(k) for k in ("geoid", "name", "value")},
            "peers_url": f'/community/{level}/{geoid}/peers?measure={row["product"]}:{row["measure_id"]}'}


def _side_note(companion: dict | None, state_name: str) -> dict | None:
    if not companion:
        return None
    return {"label": f'{state_name} state survey estimate (BRFSS {companion["period"]})',
            "value": companion.get("value"), "uncertainty": companion.get("uncertainty"),
            "status_text": companion.get("status_text"),
            "text": "Direct survey estimate; not on this chart's scale of comparison."}


def build_charts(db, level: str, info: dict) -> dict:
    """Compose bands without changing current profile endpoints or making direct area SQL reads."""
    geoid = info["geoid"]
    fingerprint = tuple(sorted((name, str(item["release_id"])) for name, item in lookup.active_releases(db).items()))
    cache_key = (level, geoid, fingerprint)
    if cache_key in _CACHE:
        return _CACHE[cache_key]
    current = lookup.area_values(db, level, [geoid])["values"]
    by_key = {f'{row["product"]}:{row["measure_id"]}': row for row in current}
    keys = list(dict.fromkeys(key for group in GROUPS for key in _keys(group, level) if key in by_key))
    series = lookup.area_series_many(db, level, geoid, [tuple(key.split(":", 1)) for key in keys])
    catalog = lookup.catalog(db)
    meta = {(item["product"], item["measure_id"]): item for item in catalog["measures"]}
    state_geoid = info["state_geoid"]
    state_name = info["state_name"]
    state_rows = {}
    state_series = {}
    if level in ("county", "cd"):
        state_rows = {f'{r["product"]}:{r["measure_id"]}': r
                      for r in lookup.area_values(db, "state", [state_geoid])["values"]}
        if level == "county":
            state_keys = [key for key in keys if level in lookup.comparability(*key.split(":", 1))["state_marker_levels"]]
            if state_keys:
                state_series = lookup.area_series_many(db, "state", state_geoid,
                                                       [tuple(key.split(":", 1)) for key in state_keys])
    companions = lookup.state_survey_companions(db, state_geoid)["companions"] if level == "county" else {}
    national = {}
    sections = []
    for section in SECTIONS:
        groups = []
        for group in GROUPS:
            if group["section"] != section:
                continue
            rows = []
            for key in _keys(group, level):
                row = by_key.get(key)
                if row is None:
                    continue
                product, measure_id = key.split(":", 1)
                rule = lookup.comparability(product, measure_id)
                if level in rule["national_marker_levels"] and key not in national:
                    national[key] = lookup.national_series(db, product, measure_id)
                state = state_rows.get(key) if level in rule["state_marker_levels"] else None
                national_rows = national.get(key, {}).get("series", [])
                national_current = national_rows[-1] if national_rows else None
                if state and state["period"] != row["period"]:
                    state = None
                if national_current and national_current["period"] != row["period"]:
                    national_current = None
                item_meta = meta[(product, measure_id)]
                source = {"publisher": item_meta["publisher"], "product_name": item_meta["product_name"],
                          "credit": item_meta.get("source_credit")}
                rows.append({k: row.get(k) for k in ("product", "measure_id", "label", "unit", "kind", "period",
                                                     "population", "value", "status", "status_text", "uncertainty",
                                                     "storage_scale")} | {
                    "comparisons": {"state": _point(state), "national": _point(national_current),
                                    "side_note": _side_note(companions.get(measure_id), state_name) if level == "county" and companions.get(measure_id) else None},
                    "peers": _peers(db, level, geoid, row, rule),
                    "trend": _trend(series[key], rule, level, state_series.get(key), national.get(key), item_meta["product_name"]),
                    "source": source, "citation": item_meta.get("landing_page") or ""})
            if rows:
                units = {row["unit"] for row in rows}
                groups.append({"key": group["key"], "title": group["title"],
                               "unit": rows[0]["unit"] if len(units) == 1 else None,
                               "shared_axis": len(units) == 1, "rows": rows})
        if groups:
            sections.append({"key": section, "groups": groups})
    display_name = f'{info["name"]} County, {state_name}' if level == "county" else info["name"]
    result = {"level": "district" if level == "cd" else level, "geoid": geoid,
              "name": display_name, "state": {"geoid": state_geoid, "name": state_name},
              "sections": sections}
    if len(_CACHE) >= 32:
        _CACHE.clear()
    _CACHE[cache_key] = result
    return result


def build_peers(db, level: str, info: dict, measure: str) -> dict:
    if ":" not in measure:
        raise lookup.LookupError_("measure must be product:measure_id")
    product, measure_id = measure.split(":", 1)
    rule = lookup.comparability(product, measure_id)
    peers_rule = rule.get("peers") or {}
    if level not in peers_rule:
        raise lookup.LookupError_(f"Peers are not allowed for {product}:{measure_id} at {level}")
    rows = lookup.area_values(db, level, [info["geoid"]], [product], [measure_id])["values"]
    if not rows:
        raise lookup.LookupError_("Measure is not published for this area")
    period = rows[0]["period"]
    parent = info["state_geoid"] if peers_rule[level] == "state" else None
    result = lookup.measure_values_within(db, product, measure_id, level, parent, period)
    return {"measure": result["measure"], "period": period, "area_geoid": info["geoid"],
            "values": [{k: row.get(k) for k in ("geoid", "name", "value", "uncertainty", "status", "status_text")}
                       for row in result["values"]]}
