"""Read-only hazard section composition (CDC SVI and FEMA NRI) via app.area_pilot.lookup."""
from __future__ import annotations

from app.area_pilot import lookup

SVI_THEMES: tuple[tuple[str, str, str], ...] = (
    ("rpl_themes", "rpl_themes_state", "Overall social vulnerability"),
    ("rpl_theme1", "rpl_theme1_state", "Socioeconomic status"),
    ("rpl_theme2", "rpl_theme2_state", "Household characteristics"),
    ("rpl_theme3", "rpl_theme3_state", "Racial and ethnic minority status"),
    ("rpl_theme4", "rpl_theme4_state", "Housing type and transportation"),
)

COUNTY_NRI_MEASURES: tuple[tuple[str, str | None], ...] = (
    ("risk_score", None),
    ("eal_score", "eal_spctl"),
    ("eal_valt", None),
    ("sovi_score", "sovi_spctl"),
    ("resl_score", "resl_spctl"),
    ("crf_value", None),
)

STATE_NRI_MEASURES: tuple[tuple[str, str | None], ...] = (
    ("eal_score", None),
    ("eal_valt", None),
)

HIGHER_BETTER_NRI = frozenset({"resl_score", "resl_spctl"})


def _citation(product: dict, row: dict) -> str:
    period = row.get("period") or ""
    release = row.get("source_release_id") or ""
    parts = [product["publisher"], product["name"]]
    if period:
        parts.append(period)
    if release and release != period:
        parts.append(release)
    return "Source: " + " · ".join(parts)


def _with_citation(row: dict | None, product: dict | None) -> dict | None:
    if row is None or product is None:
        return None
    return row | {"citation": _citation(product, row)}


def _source_entry(product: dict, row: dict) -> dict:
    release = product.get("release") or {}
    return {
        "product": product["product"],
        "dataset_id": product["dataset_id"],
        "name": product["name"],
        "publisher": product["publisher"],
        "landing_page": product.get("landing_page"),
        "period": row.get("period"),
        "release_id": row.get("release_id"),
        "source_release_id": row.get("source_release_id"),
        "published_at": release.get("published_at"),
        "boundary_vintage": row.get("boundary_vintage"),
        "citation": _citation(product, row),
    }


def _nri_rows(
    by_measure: dict[str, dict],
    product: dict | None,
    pairs: tuple[tuple[str, str | None], ...],
) -> list[dict]:
    if product is None:
        return []
    rows = []
    for measure_id, spctl_id in pairs:
        row = by_measure.get(measure_id)
        if row is None:
            continue
        spctl = _with_citation(by_measure.get(spctl_id), product) if spctl_id else None
        notes = row.get("notes") or {}
        entry = (
            _with_citation(row, product)
            | {
                "rating": notes.get("rating"),
                "direction": "higher_better" if measure_id in HIGHER_BETTER_NRI else "higher_worse",
            }
        )
        if spctl is not None:
            entry["state_percentile"] = spctl
        rows.append(entry)
    return rows


def build_county_hazards(db, info: dict) -> dict:
    """Compose county SVI and NRI hazard sections strictly from lookup."""
    geoid = info["geoid"]
    values = lookup.area_values(db, "county", [geoid], products=["cdc_svi", "fema_nri"])["values"]
    products = {item["product"]: item for item in lookup.catalog(db)["products"]}

    svi_by_measure = {row["measure_id"]: row for row in values if row["product"] == "cdc_svi"}
    nri_by_measure = {row["measure_id"]: row for row in values if row["product"] == "fema_nri"}

    svi_product = products.get("cdc_svi")
    nri_product = products.get("fema_nri")

    svi_rows = []
    if svi_product is not None and svi_by_measure:
        for us_id, state_id, theme_label in SVI_THEMES:
            us_row = _with_citation(svi_by_measure.get(us_id), svi_product)
            if us_row is None:
                continue
            state_row = _with_citation(svi_by_measure.get(state_id), svi_product)
            svi_rows.append(
                {
                    "measure_id": us_id,
                    "label": theme_label,
                    "us": us_row,
                    "state": state_row,
                    "status": us_row["status"],
                    "status_text": us_row["status_text"],
                    "citation": us_row["citation"],
                }
            )

    nri_rows = _nri_rows(nri_by_measure, nri_product, COUNTY_NRI_MEASURES)

    sources = {}
    limitations = {}
    if svi_rows and svi_product is not None:
        sources["cdc_svi"] = _source_entry(svi_product, svi_rows[0]["us"])
        limitations["cdc_svi"] = list(svi_product.get("limitations") or [])
    if nri_rows and nri_product is not None:
        sources["fema_nri"] = _source_entry(nri_product, nri_rows[0])
        limitations["fema_nri"] = list(nri_product.get("limitations") or [])

    return {
        "level": "county",
        "geoid": geoid,
        "name": info["name"],
        "state": {"geoid": info["state_geoid"], "name": info["state_name"]},
        "svi": svi_rows,
        "nri": nri_rows,
        "sources": sources,
        "limitations": limitations,
    }


def build_state_hazards(db, info: dict) -> dict:
    """Compose state NRI hazard section strictly from lookup. No SVI is included."""
    geoid = info["geoid"]
    values = lookup.area_values(db, "state", [geoid], products=["fema_nri"])["values"]
    products = {item["product"]: item for item in lookup.catalog(db)["products"]}

    nri_by_measure = {row["measure_id"]: row for row in values if row["product"] == "fema_nri"}
    nri_product = products.get("fema_nri")
    nri_rows = _nri_rows(nri_by_measure, nri_product, STATE_NRI_MEASURES)

    sources = {}
    limitations = {}
    if nri_rows and nri_product is not None:
        sources["fema_nri"] = _source_entry(nri_product, nri_rows[0])
        limitations["fema_nri"] = list(nri_product.get("limitations") or [])

    return {
        "level": "state",
        "geoid": geoid,
        "name": info["name"],
        "state": {"geoid": info["state_geoid"], "name": info["state_name"]},
        "nri": nri_rows,
        "sources": sources,
        "limitations": limitations,
    }
