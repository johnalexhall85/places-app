"""Read-only national view of CDC grants by recipient state."""

from app.area_pilot import lookup as area_lookup
from app.funding.state_lookup import STATE_ROWS

from .lookup import NEGATIVE_NOTE, citation, money, run, state_name, where


STATE_FIPS = {row.state_code: row.state_fips for row in STATE_ROWS}
FIPS_STATE = {fips: code for code, fips in STATE_FIPS.items()}
ATTRIBUTION_NOTE = (
    "Grants are counted in the state of the recipient's address. Money a recipient passes on "
    "to sub-recipients in other states is not moved."
)
EXCLUDED_NOTE = (
    "Deobligations (net reductions for an award in this year) are left out, "
    "so totals show new and added obligations only."
)


def state_shapes(db):
    """Return the published 2024 state outlines, keyed by postal code."""
    areas = area_lookup.area_info(db, "state", list(FIPS_STATE), geometry=True)
    return {
        FIPS_STATE[area["geoid"]]: {
            "fips": area["geoid"],
            "name": area["name"],
            "geometry": area["geometry"],
        }
        for area in areas
    }


def state_map(db, fy, filters, build):
    """Aggregate every recipient state and the distinct national grant count in one query."""
    build_id = build["build_id"]
    query_filters = {
        "funding_type": filters["funding_type"],
        "award_type": "grant",
        "recipient_type": "all",
        "category": filters["category"],
        "deobligations": filters["deobligations"],
    }
    clause = where(query_filters).replace("o.state=:code AND ", "")
    params = {
        "build_id": build_id,
        "fy": fy,
        "award_type": "grant",
        "category": filters["category"],
        "supplemental": filters["funding_type"] == "supplemental",
    }
    base = """FROM state_funding.obligation o
        JOIN state_funding.award a USING(build_id,award_unique_key)
        JOIN state_funding.budget_category c USING(federal_account_symbol)"""
    rows = run(
        db,
        f"""SELECT o.state, GROUPING(o.state) AS national,
            coalesce(sum(o.amount),0) AS total,
            coalesce(sum(o.amount) FILTER (WHERE NOT o.is_supplemental),0) AS regular,
            coalesce(sum(o.amount) FILTER (WHERE o.is_supplemental),0) AS supplemental,
            count(DISTINCT o.award_unique_key) AS award_count,
            count(DISTINCT coalesce(nullif(a.recipient_uei,''),a.recipient_name)) AS recipient_count
            {base} WHERE {clause}
            GROUP BY GROUPING SETS ((o.state), ())""",
        params,
    ).mappings().all()
    categories = run(
        db,
        f"""SELECT DISTINCT c.category_code AS code, c.category_name AS name,
            c.basis, c.category_order {base}
            WHERE o.build_id=:build_id AND o.fiscal_year=:fy AND a.award_type='grant'
            {"AND o.amount > 0" if filters["deobligations"] == "exclude" else ""}
            ORDER BY c.category_order,c.category_code,c.category_name,c.basis""",
        params,
    ).mappings().all()
    shapes = state_shapes(db)
    profiles = {row["geoid"] for row in area_lookup.states(db)}
    states = []
    national = {"total": 0.0, "award_count": 0}
    unattributed = {"total": 0.0, "award_count": 0}
    negative_supplemental = False
    for row in rows:
        if row["national"]:
            national = {"total": money(row["total"]), "award_count": row["award_count"]}
            continue
        if row["state"] == "__":
            unattributed = {"total": money(row["total"]), "award_count": row["award_count"]}
            continue
        code = row["state"]
        fips = STATE_FIPS.get(code)
        negative_supplemental |= row["supplemental"] < 0
        states.append({
            "code": code,
            "fips": fips,
            "name": state_name(code),
            "total": money(row["total"]),
            "regular": money(row["regular"]),
            "supplemental": money(row["supplemental"]),
            "award_count": row["award_count"],
            "recipient_count": row["recipient_count"],
            "has_shape": code in shapes,
            "indicators_geoid": fips if fips in profiles else None,
        })
    states.sort(key=lambda state: state["name"])
    period = (build["sources"] or {}).get("periods", {}).get(str(fy), f"FY{fy}")
    return {
        "fiscal_year": fy,
        "period": period,
        "filters": {
            "funding_type": filters["funding_type"], "category": filters["category"],
            "award_type": "grant", "deobligations": filters["deobligations"],
        },
        "categories_available": [{key: row[key] for key in ("code", "name", "basis")} for row in categories],
        "states": states,
        "unattributed": unattributed,
        "national": national,
        "citation": citation(fy, period, build_id),
        "notes": ([NEGATIVE_NOTE] if negative_supplemental else [])
        + ([EXCLUDED_NOTE] if filters["deobligations"] == "exclude" else [])
        + [ATTRIBUTION_NOTE],
    }
