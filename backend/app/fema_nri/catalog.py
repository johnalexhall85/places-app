from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parent / "measure_catalog.json"


@lru_cache(maxsize=1)
def load_measure_catalog() -> dict[str, Any]:
    with CATALOG_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Invalid FEMA measure catalog format: {CATALOG_PATH}")
    return payload


def get_catalog_measures() -> list[dict[str, Any]]:
    payload = load_measure_catalog()
    measures = payload.get("measures")
    if not isinstance(measures, list):
        return []
    return [item for item in measures if isinstance(item, dict)]


def find_measure(measure_id: str) -> dict[str, Any] | None:
    token = str(measure_id or "").strip().upper()
    if not token:
        return None

    for item in get_catalog_measures():
        candidate = str(item.get("measure_id") or "").strip().upper()
        if candidate == token:
            return item
    return None


def catalog_for_level(level: str | None) -> dict[str, Any]:
    token = str(level or "all").strip().lower()
    allow_all = token in {"", "all"}

    catalog = load_measure_catalog()
    source_measures = get_catalog_measures()
    filtered_measures: list[dict[str, Any]] = []

    for measure in source_measures:
        supported_levels = measure.get("supported_levels")
        if not isinstance(supported_levels, list):
            supported_levels = []
        normalized_levels = {str(item).strip().lower() for item in supported_levels if str(item).strip()}

        if allow_all or not normalized_levels or token in normalized_levels:
            filtered_measures.append(measure)

    sorted_measures = sorted(
        filtered_measures,
        key=lambda item: (
            int(item.get("sort_order") or 1_000_000),
            str(item.get("display_label") or item.get("measure_id") or "").lower(),
        ),
    )

    grouped: dict[str, dict[str, Any]] = {}
    for measure in sorted_measures:
        group_name = str(measure.get("group") or "Other").strip() or "Other"
        subgroup_name = str(measure.get("subgroup") or "General").strip() or "General"

        group_bucket = grouped.setdefault(
            group_name,
            {
                "group": group_name,
                "subgroups": {},
            },
        )
        subgroup_bucket = group_bucket["subgroups"].setdefault(
            subgroup_name,
            {
                "subgroup": subgroup_name,
                "measures": [],
            },
        )
        subgroup_bucket["measures"].append(measure)

    groups_payload: list[dict[str, Any]] = []
    for group_name in sorted(grouped.keys(), key=str.lower):
        group_bucket = grouped[group_name]
        subgroup_map: dict[str, dict[str, Any]] = group_bucket["subgroups"]
        subgroups_payload: list[dict[str, Any]] = []
        for subgroup_name in sorted(subgroup_map.keys(), key=str.lower):
            subgroups_payload.append(subgroup_map[subgroup_name])
        groups_payload.append({"group": group_name, "subgroups": subgroups_payload})

    return {
        "dataset_key": catalog.get("dataset_key"),
        "dataset_name": catalog.get("dataset_name"),
        "dataset_vintage": catalog.get("dataset_vintage"),
        "notes": catalog.get("notes"),
        "default_measure_id": catalog.get("default_measure_id"),
        "measure_count": len(sorted_measures),
        "groups": groups_payload,
        "measures": sorted_measures,
    }
