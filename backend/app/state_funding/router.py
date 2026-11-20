"""HTTP endpoints for CDC state funding profiles."""

import csv
import io
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session
from app.db import get_db
from . import lookup, state_map as map_lookup
from .grant_history import GrantNotFound

router = APIRouter(prefix="/state-funding/v1", tags=["state-funding"])


@router.get("/map/shapes")
def map_shapes(db: Session = Depends(get_db)):
    return JSONResponse(
        {"states": map_lookup.state_shapes(db), "boundary_vintage": "TIGER/Line 2024"},
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/map")
def state_map(
    fy: int | None = Query(None, ge=2021, le=2026),
    funding_type: str = Query("all", pattern="^(all|regular|supplemental)$"),
    deobligations: str = Query("include", pattern="^(include|exclude)$"),
    category: str | None = None,
    award_type: str | None = None,
    account: str | None = None,
    recipient_type: str | None = None,
    db: Session = Depends(get_db),
):
    if any(value is not None for value in (award_type, account, recipient_type)):
        raise HTTPException(422, "The map accepts only fy, funding_type, category, and deobligations")
    years = lookup.fiscal_years(db)
    selected_fy = fy if fy is not None else years["default"]
    if selected_fy not in years["fiscal_years"]:
        raise HTTPException(422, "Fiscal year is not in this build")
    build = lookup.build_info(db)
    filters = {"funding_type": funding_type, "category": category or None, "deobligations": deobligations}
    result = map_lookup.state_map(db, selected_fy, filters, build)
    if category and not any(item["code"] == category for item in result["categories_available"]):
        raise HTTPException(422, "Budget category is not available for grants in this fiscal year")
    return result


@router.get("/grants/{nofo}.csv")
def grant_history_csv(nofo: str, db: Session = Depends(get_db)):
    try:
        data = lookup.grant_history(db, nofo)
    except GrantNotFound as exc:
        return JSONResponse({"detail": str(exc), "suggestions": exc.suggestions}, status_code=404)
    output = io.StringIO()
    output.write("# " + data["citation"] + "\n")
    latest = data['latest_fy']
    fields = (['state', 'split_state', 'is_current', 'recipient_name', 'recipient_uei', 'city',
               'recipient_type', 'recipient_type_source', 'project_title', 'award_id',
               f'FY{latest}_regular', f'FY{latest}_supplemental', f'FY{latest}_total']
              + [f'FY{year}_total' for year in range(2021, 2027)]
              + ['all_years_total', 'subawardee_count', 'subaward_reported_amount', 'usaspending_url'])
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for award in data['awards']:
        amount = award['latest_fy_amount'] or {}
        history = {r['fiscal_year']: r['total'] for r in award['history']}
        writer.writerow({**{key: award.get(key) for key in fields},
                         **{f'FY{latest}_{key}': amount.get(key) for key in ('regular', 'supplemental', 'total')},
                         **{f'FY{year}_total': history.get(year, 0) for year in range(2021, 2027)},
                         'subawardee_count': (award['subawards'] or {}).get('subawardee_count'),
                         'subaward_reported_amount': (award['subawards'] or {}).get('reported_amount')})
    filename = f"chip-cdc-grant-{data['nofo']['fon_display']}.csv"
    return Response(output.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/grants/{nofo}/awards/{award_unique_key}")
def grant_award(nofo: str, award_unique_key: str, db: Session = Depends(get_db)):
    try:
        return lookup.grant_award(db, nofo, award_unique_key)
    except GrantNotFound as exc:
        return JSONResponse({"detail": str(exc), "suggestions": exc.suggestions}, status_code=404)


@router.get("/grants/{nofo}")
def grant_history(nofo: str, db: Session = Depends(get_db)):
    try:
        return lookup.grant_history(db, nofo)
    except GrantNotFound as exc:
        return JSONResponse({"detail": str(exc), "suggestions": exc.suggestions}, status_code=404)


def context(db, code, fy, funding_type, award_type, category, recipient_type, account):
    if account is not None:
        raise HTTPException(422, "account is no longer supported; use category")
    code = code.upper()
    build = lookup.build_info(db)
    if (
        not re.fullmatch(r"[A-Z]{2}", code)
        or code == "__"
        or not build
        or not lookup.state_exists(db, code, build["build_id"])
    ):
        raise HTTPException(404, "State not found")
    years = lookup.fiscal_years(db)
    fy = fy if fy is not None else years["default"]
    if fy not in years["fiscal_years"]:
        raise HTTPException(422, "Fiscal year is not in this build")
    if (
        category
        and not lookup.run(
            db,
            """SELECT 1 FROM state_funding.obligation o
        JOIN state_funding.budget_category c USING(federal_account_symbol)
        WHERE o.build_id=:id AND o.state=:code AND o.fiscal_year=:fy
          AND c.category_code=:category LIMIT 1""",
            {"id": build["build_id"], "code": code, "fy": fy, "category": category},
        ).first()
    ):
        raise HTTPException(422, "Budget category is not available for this state and fiscal year")
    filters = {
        "funding_type": funding_type,
        "award_type": award_type,
        "category": category,
        "recipient_type": recipient_type,
    }
    return code, fy, filters, build


@router.get("/fiscal-years")
def fiscal_years(db: Session = Depends(get_db)):
    return lookup.fiscal_years(db)


@router.get("/states/{code}/summary")
def summary(
    code: str,
    fy: int | None = Query(None, ge=2021, le=2026),
    funding_type: str = Query("all", pattern="^(all|regular|supplemental)$"),
    deobligations: str = Query("include", pattern="^(include|exclude)$"),
    award_type: str = Query("grant", pattern="^(all|grant|contract)$"),
    category: str | None = None,
    account: str | None = None,
    recipient_type: str = Query("all", pattern="^(all|state_government)$"),
    db: Session = Depends(get_db),
):
    code, fy, filters, build = context(db, code, fy, funding_type, award_type, category, recipient_type, account)
    if deobligations == "exclude":
        filters["deobligations"] = deobligations
    return lookup.summary(db, code, fy, filters, build)


@router.get("/states/{code}/grants")
def grants(
    code: str,
    fy: int | None = Query(None, ge=2021, le=2026),
    funding_type: str = Query("all", pattern="^(all|regular|supplemental)$"),
    award_type: str = Query("grant", pattern="^(all|grant|contract)$"),
    category: str | None = None,
    account: str | None = None,
    recipient_type: str = Query("all", pattern="^(all|state_government)$"),
    q: str = "",
    sort: str = Query("amount", pattern="^(amount|name|recipient|category)$"),
    dir: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25),
    db: Session = Depends(get_db),
):
    if page_size not in (25, 50, 100):
        raise HTTPException(422, "page_size must be 25, 50, or 100")
    code, fy, filters, build = context(db, code, fy, funding_type, award_type, category, recipient_type, account)
    return lookup.grants(db, code, fy, filters, build, q=q, sort=sort, direction=dir, page=page, page_size=page_size)


@router.get("/states/{code}/grants.csv")
def grants_csv(
    code: str,
    fy: int | None = Query(None, ge=2021, le=2026),
    funding_type: str = Query("all", pattern="^(all|regular|supplemental)$"),
    award_type: str = Query("grant", pattern="^(all|grant|contract)$"),
    category: str | None = None,
    account: str | None = None,
    recipient_type: str = Query("all", pattern="^(all|state_government)$"),
    q: str = "",
    sort: str = Query("amount", pattern="^(amount|name|recipient|category)$"),
    dir: str = Query("desc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    code, fy, filters, build = context(db, code, fy, funding_type, award_type, category, recipient_type, account)
    data = lookup.grants(db, code, fy, filters, build, q=q, sort=sort, direction=dir, all_rows=True)
    output = io.StringIO()
    output.write("# " + data["citation"] + "\n")
    fields = [
        "award_unique_key",
        "award_id",
        "award_type",
        "grant_name",
        "name_source",
        "project_title",
        "description",
        "recipient_name",
        "recipient_uei",
        "is_state_government",
        "fon",
        "cfda_number",
        "cfda_title",
        "categories",
        "accounts",
        "regular",
        "supplemental",
        "total",
        "usaspending_url",
    ]
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in data["rows"]:
        writer.writerow(
            row
            | {
                "categories": "; ".join(c["name"] for c in row["categories"]),
                "accounts": "; ".join(a["symbol"] + " " + a["name"] for a in row["accounts"]),
            }
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="chip-cdc-funding-{code}-FY{fy}.csv"'},
    )
