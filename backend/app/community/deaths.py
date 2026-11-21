"""Read-only mortality section composition (CDC HDS, NCI cancer, NCHS drug poisoning) via app.area_pilot.lookup."""
from __future__ import annotations

from app.area_pilot import lookup
from app.community.hazards import _source_entry, _with_citation

HEART_STROKE_MEASURES: tuple[str, ...] = (
    "heart_disease_death_rate",
    "stroke_death_rate",
)

CANCER_MEASURES: tuple[str, ...] = (
    "cancer_death_rate_all",
    "cancer_death_rate_lung",
    "cancer_death_rate_colorectal",
)

DRUG_POISONING_MEASURES: tuple[str, ...] = (
    "drug_poisoning_death_rate",
)

COUNTY_PRODUCTS: list[str] = [
    "cdc_hds_mortality",
    "nci_cancer_mortality",
    "nchs_drug_poisoning",
]

STATE_PRODUCTS: list[str] = [
    "cdc_hds_mortality",
    "nci_cancer_mortality",
]


def _by_measure(rows: list[dict], product_key: str) -> dict[str, dict]:
    return {row["measure_id"]: row for row in rows if row["product"] == product_key}


def _county_group_rows(
    measure_ids: tuple[str, ...],
    product: dict | None,
    county_by_measure: dict[str, dict],
    state_by_measure: dict[str, dict] | None = None,
    us_by_measure: dict[str, dict] | None = None,
    include_refs: bool = True,
) -> list[dict]:
    if product is None or not county_by_measure:
        return []
    rows = []
    for measure_id in measure_ids:
        county_row = _with_citation(county_by_measure.get(measure_id), product)
        if county_row is None:
            continue
        entry = {
            "measure_id": measure_id,
            "label": county_row["label"],
            "unit": county_row["unit"],
            "period": county_row["period"],
            "population": county_row["population"],
            "county": county_row,
            "status": county_row["status"],
            "status_text": county_row["status_text"],
            "uncertainty": county_row["uncertainty"],
            "citation": county_row["citation"],
        }
        if include_refs:
            entry["state"] = _with_citation((state_by_measure or {}).get(measure_id), product)
            entry["us"] = _with_citation((us_by_measure or {}).get(measure_id), product)
        rows.append(entry)
    return rows


def _state_group_rows(
    measure_ids: tuple[str, ...],
    product: dict | None,
    state_by_measure: dict[str, dict],
    us_by_measure: dict[str, dict],
) -> list[dict]:
    if product is None or not state_by_measure:
        return []
    rows = []
    for measure_id in measure_ids:
        state_row = _with_citation(state_by_measure.get(measure_id), product)
        if state_row is None:
            continue
        rows.append(
            {
                "measure_id": measure_id,
                "label": state_row["label"],
                "unit": state_row["unit"],
                "period": state_row["period"],
                "population": state_row["population"],
                "state": state_row,
                "us": _with_citation(us_by_measure.get(measure_id), product),
                "status": state_row["status"],
                "status_text": state_row["status_text"],
                "uncertainty": state_row["uncertainty"],
                "citation": state_row["citation"],
            }
        )
    return rows


def build_county_deaths(db, info: dict) -> dict:
    """Compose county death rate groups strictly from lookup."""
    geoid = info["geoid"]
    state_geoid = info["state_geoid"]
    county_values = lookup.area_values(db, "county", [geoid], products=COUNTY_PRODUCTS)["values"]
    state_values = lookup.area_values(db, "state", [state_geoid], products=STATE_PRODUCTS)["values"]
    national_values = lookup.national_reference(db)
    products = {item["product"]: item for item in lookup.catalog(db)["products"]}

    hds_product = products.get("cdc_hds_mortality")
    cancer_product = products.get("nci_cancer_mortality")
    drug_product = products.get("nchs_drug_poisoning")

    heart_stroke_rows = _county_group_rows(
        HEART_STROKE_MEASURES,
        hds_product,
        _by_measure(county_values, "cdc_hds_mortality"),
        _by_measure(state_values, "cdc_hds_mortality"),
        _by_measure(national_values, "cdc_hds_mortality"),
        include_refs=True,
    )
    cancer_rows = _county_group_rows(
        CANCER_MEASURES,
        cancer_product,
        _by_measure(county_values, "nci_cancer_mortality"),
        _by_measure(state_values, "nci_cancer_mortality"),
        _by_measure(national_values, "nci_cancer_mortality"),
        include_refs=True,
    )
    drug_rows = _county_group_rows(
        DRUG_POISONING_MEASURES,
        drug_product,
        _by_measure(county_values, "nchs_drug_poisoning"),
        include_refs=False,
    )

    sources = {}
    limitations = {}
    if heart_stroke_rows and hds_product is not None:
        sources["cdc_hds_mortality"] = _source_entry(hds_product, heart_stroke_rows[0]["county"])
        limitations["cdc_hds_mortality"] = list(hds_product.get("limitations") or [])
    if cancer_rows and cancer_product is not None:
        sources["nci_cancer_mortality"] = _source_entry(cancer_product, cancer_rows[0]["county"])
        limitations["nci_cancer_mortality"] = list(cancer_product.get("limitations") or [])
    if drug_rows and drug_product is not None:
        sources["nchs_drug_poisoning"] = _source_entry(drug_product, drug_rows[0]["county"])
        limitations["nchs_drug_poisoning"] = list(drug_product.get("limitations") or [])

    return {
        "level": "county",
        "geoid": geoid,
        "name": info["name"],
        "state": {"geoid": state_geoid, "name": info["state_name"]},
        "heart_stroke": heart_stroke_rows,
        "cancer": cancer_rows,
        "drug_poisoning": drug_rows,
        "sources": sources,
        "limitations": limitations,
    }


def build_state_deaths(db, info: dict) -> dict:
    """Compose state death rate groups strictly from lookup. No drug_poisoning is included."""
    geoid = info["geoid"]
    state_values = lookup.area_values(db, "state", [geoid], products=STATE_PRODUCTS)["values"]
    national_values = lookup.national_reference(db)
    products = {item["product"]: item for item in lookup.catalog(db)["products"]}

    hds_product = products.get("cdc_hds_mortality")
    cancer_product = products.get("nci_cancer_mortality")

    heart_stroke_rows = _state_group_rows(
        HEART_STROKE_MEASURES,
        hds_product,
        _by_measure(state_values, "cdc_hds_mortality"),
        _by_measure(national_values, "cdc_hds_mortality"),
    )
    cancer_rows = _state_group_rows(
        CANCER_MEASURES,
        cancer_product,
        _by_measure(state_values, "nci_cancer_mortality"),
        _by_measure(national_values, "nci_cancer_mortality"),
    )

    sources = {}
    limitations = {}
    if heart_stroke_rows and hds_product is not None:
        sources["cdc_hds_mortality"] = _source_entry(hds_product, heart_stroke_rows[0]["state"])
        limitations["cdc_hds_mortality"] = list(hds_product.get("limitations") or [])
    if cancer_rows and cancer_product is not None:
        sources["nci_cancer_mortality"] = _source_entry(cancer_product, cancer_rows[0]["state"])
        limitations["nci_cancer_mortality"] = list(cancer_product.get("limitations") or [])

    return {
        "level": "state",
        "geoid": geoid,
        "name": info["name"],
        "state": {"geoid": info["state_geoid"], "name": info["state_name"]},
        "heart_stroke": heart_stroke_rows,
        "cancer": cancer_rows,
        "sources": sources,
        "limitations": limitations,
    }
