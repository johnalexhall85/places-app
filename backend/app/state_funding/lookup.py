"""Read only access to the active CDC state funding build."""

from __future__ import annotations

from sqlalchemy import text
from app.taggs.redo_ingest import STATE_CODE_TO_NAME
from app.funding.state_lookup import BY_CODE, BY_FIPS

NEGATIVE_NOTE = (
    "Supplemental amounts are negative when earlier emergency (for example COVID-19) "
    "obligations were reduced in this year."
)


def run(db, sql, params=None):
    return db.execute(text(sql), params or {})


def money(value):
    return round(float(value or 0), 2)


def build_info(db):
    row = (
        run(
            db,
            """SELECT r.build_id,r.finished_at,r.method_version,r.sources
        FROM state_funding.active_build a JOIN state_funding.build_run r USING(build_id)
        WHERE a.singleton""",
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


def build_fingerprint(db, *, include_profiles=False):
    """Cache key for reads that also use the recipient profile build."""
    state_id = (build_info(db) or {}).get('build_id')
    if not include_profiles:
        return (state_id, None)
    from app.funding_report import lookup as funding_lookup
    return (state_id, (funding_lookup.active_build(db) or {}).get('build_id'))


def fiscal_years(db):
    build = build_info(db)
    if not build:
        return {"fiscal_years": [], "default": None, "periods": {}, "build": None}
    years = (
        run(
            db,
            "SELECT DISTINCT fiscal_year FROM state_funding.obligation WHERE build_id=:id ORDER BY fiscal_year DESC",
            {"id": build["build_id"]},
        )
        .scalars()
        .all()
    )
    periods = (build["sources"] or {}).get("periods", {})
    return {
        "fiscal_years": years,
        "default": years[0] if years else None,
        "periods": periods,
        "build": {k: build[k] for k in ("build_id", "finished_at", "method_version")},
    }


def state_exists(db, code, build_id):
    return bool(
        run(
            db,
            "SELECT 1 FROM state_funding.obligation WHERE build_id=:id AND state=:code LIMIT 1",
            {"id": build_id, "code": code},
        ).first()
    )


def state_name(code):
    return STATE_CODE_TO_NAME.get(code, code).title().replace(" Of ", " of ")


def resolve_state(value):
    """Accept a postal code, state name, or two-digit FIPS for read-only tools."""
    token = str(value or '').strip().upper()
    if token in STATE_CODE_TO_NAME:
        return token
    if token in BY_FIPS:
        return BY_FIPS[token].state_code
    for code, name in STATE_CODE_TO_NAME.items():
        if token == name or token == state_name(code).upper():
            return code
    raise ValueError('Unknown state; use a two-letter code, state name, or two-digit FIPS code.')


def citation(fy, period, build_id):
    return f"Source: USAspending · Award financial (File C), CDC · {period or 'FY'+str(fy)} · CHIP build {build_id}"


def where(filters, *, include_category=True):
    sql = "o.build_id=:build_id AND o.state=:code AND o.fiscal_year=:fy"
    if filters["funding_type"] != "all":
        sql += " AND o.is_supplemental=:supplemental"
    if filters["award_type"] != "all":
        sql += " AND a.award_type=:award_type"
    if filters["recipient_type"] == "state_government":
        sql += " AND a.is_state_government IS TRUE"
    if include_category and filters["category"]:
        sql += " AND c.category_code=:category"
    return sql


def params(code, fy, filters, build_id):
    return dict(
        build_id=build_id,
        code=code,
        fy=fy,
        supplemental=filters["funding_type"] == "supplemental",
        award_type=filters["award_type"],
        category=filters["category"],
    )


def summary(db, code, fy, filters, build):
    p = params(code, fy, filters, build["build_id"])
    clause = where(filters)
    base = """FROM state_funding.obligation o
        JOIN state_funding.award a USING(build_id,award_unique_key)
        JOIN state_funding.budget_category c USING(federal_account_symbol)"""
    rows = (
        run(
            db,
            f"""SELECT c.category_code code, c.category_name category_name,
        c.category_order, c.basis, o.federal_account_symbol symbol,
        max(o.federal_account_name) name,
        coalesce(sum(o.amount) FILTER (WHERE NOT o.is_supplemental),0) regular,
        coalesce(sum(o.amount) FILTER (WHERE o.is_supplemental),0) supplemental,
        sum(o.amount) total {base} WHERE {clause}
        GROUP BY c.category_code,c.category_name,c.category_order,c.basis,o.federal_account_symbol""",
            p,
        )
        .mappings()
        .all()
    )
    available = (
        run(
            db,
            f"""SELECT DISTINCT c.category_code code,c.category_name name,
        c.basis,c.category_order {base}
        WHERE {where(filters,include_category=False)} ORDER BY c.category_order,c.category_code""",
            p,
        )
        .mappings()
        .all()
    )
    overall = (
        run(
            db,
            f"""SELECT sum(o.amount) total,
        sum(o.amount) FILTER (WHERE NOT o.is_supplemental) regular,
        sum(o.amount) FILTER (WHERE o.is_supplemental) supplemental,
        count(DISTINCT o.award_unique_key) award_count,
        count(DISTINCT o.award_unique_key) FILTER (WHERE a.award_type='grant') grant_count,
        count(DISTINCT coalesce(nullif(a.recipient_uei,''),a.recipient_name)) recipient_count
        {base} WHERE {clause}""",
            p,
        )
        .mappings()
        .one()
    )
    categories = {}
    for row in rows:
        group = categories.setdefault(
            row["code"],
            {
                "code": row["code"],
                "name": row["category_name"],
                "basis": row["basis"],
                "regular": 0,
                "supplemental": 0,
                "total": 0,
                "award_count": 0,
                "accounts": [],
                "_order": row["category_order"],
            },
        )
        group["accounts"].append(
            {
                "symbol": row["symbol"],
                "name": row["name"],
                **{key: money(row[key]) for key in ("regular", "supplemental", "total")},
            }
        )
        for key in ("regular", "supplemental", "total"):
            group[key] = money(group[key] + money(row[key]))
    counts = run(
        db,
        f"""SELECT c.category_code code,count(DISTINCT o.award_unique_key) n
        {base} WHERE {clause} GROUP BY c.category_code""",
        p,
    ).mappings()
    for row in counts:
        categories[row["code"]]["award_count"] = row["n"]
    by_category = sorted(categories.values(), key=lambda item: (-abs(item["total"]), item["_order"]))
    for group in by_category:
        del group["_order"]
        group["accounts"].sort(key=lambda account: account["symbol"])
    period = (build["sources"] or {}).get("periods", {}).get(str(fy), f"FY{fy}")
    return {
        "state": {"code": code, "name": state_name(code)},
        "fiscal_year": fy,
        "period": period,
        "filters": filters,
        "totals": {
            k: money(overall[k]) if k in ("total", "regular", "supplemental") else overall[k] for k in overall.keys()
        },
        "by_category": by_category,
        "categories_available": [{k: r[k] for k in ("code", "name", "basis")} for r in available],
        "citation": citation(fy, period, build["build_id"]),
        "notes": [NEGATIVE_NOTE] if (overall["supplemental"] or 0) < 0 else [],
    }


def grants(
    db, code, fy, filters, build, *, q="", sort="amount", direction="desc", page=1, page_size=25,
    all_rows=False, offset=None
):
    p = params(code, fy, filters, build["build_id"])
    terms = [x.lower() for x in q.split()]
    p.update({f"term{i}": f"%{term}%" for i, term in enumerate(terms)})
    search_category = "AND sc.category_code=:category" if filters["category"] else ""
    search_funding = "AND so.is_supplemental=:supplemental" if filters["funding_type"] != "all" else ""
    search = "".join(f""" AND (a.search_text LIKE :term{i} OR EXISTS (
        SELECT 1 FROM state_funding.obligation so
        JOIN state_funding.budget_category sc USING(federal_account_symbol)
        WHERE so.build_id=o.build_id AND so.award_unique_key=o.award_unique_key
          AND so.state=o.state AND so.fiscal_year=o.fiscal_year
          {search_category} {search_funding}
          AND lower(sc.category_name) LIKE :term{i}))""" for i in range(len(terms)))
    order = {
        "amount": "abs(sum(o.amount))",
        "name": "a.grant_name",
        "recipient": "a.recipient_name",
    }.get(sort)
    if sort == "category":
        category_condition = "AND c2.category_code=:category" if filters["category"] else ""
        funding_condition = (
            "AND o2.is_supplemental=:supplemental" if filters["funding_type"] != "all" else ""
        )
        order = f"""(SELECT c2.category_order FROM state_funding.obligation o2
            JOIN state_funding.budget_category c2 USING(federal_account_symbol)
            WHERE o2.build_id=a.build_id AND o2.award_unique_key=a.award_unique_key
              AND o2.state=:code AND o2.fiscal_year=:fy
              {category_condition} {funding_condition}
            GROUP BY c2.category_order
            ORDER BY abs(sum(o2.amount)) DESC,c2.category_order LIMIT 1)"""
    direction_sql = "ASC" if direction == "asc" else "DESC"
    limit = "" if all_rows else " LIMIT :page_size OFFSET :offset"
    p.update(page_size=page_size, offset=(page - 1) * page_size if offset is None else offset)
    base = f"""FROM state_funding.obligation o JOIN state_funding.award a USING(build_id,award_unique_key)
       JOIN state_funding.budget_category c USING(federal_account_symbol)
       WHERE {where(filters)}{search}"""
    totals = (
        run(
            db,
            f"""SELECT count(*) n,coalesce(sum(total),0) sum_total FROM
         (SELECT o.award_unique_key,sum(o.amount) total {base} GROUP BY o.award_unique_key) x""",
            p,
        )
        .mappings()
        .one()
    )
    rows = (
        run(
            db,
            f"""SELECT a.award_unique_key,a.award_id,a.award_type,a.grant_name,a.name_source,
       a.project_title,a.description,a.recipient_name,a.recipient_uei,a.is_state_government,
       a.fon,a.cfda_number,a.cfda_title,a.usaspending_url,
       coalesce(sum(o.amount) FILTER (WHERE NOT o.is_supplemental),0) regular,
       coalesce(sum(o.amount) FILTER (WHERE o.is_supplemental),0) supplemental,
       sum(o.amount) total
       {base} GROUP BY a.build_id,a.award_unique_key ORDER BY {order} {direction_sql},a.award_unique_key {limit}""",
            p,
        )
        .mappings()
        .all()
    )
    result = []
    account_map = {}
    category_map = {}
    if rows:
        keys = [row["award_unique_key"] for row in rows]
        account_rows = run(
            db,
            f"""SELECT o.award_unique_key,o.federal_account_symbol symbol,max(o.federal_account_name) name,
           c.category_code code,c.category_name category_name,c.category_order,
           coalesce(sum(o.amount) FILTER (WHERE NOT o.is_supplemental),0) regular,
           coalesce(sum(o.amount) FILTER (WHERE o.is_supplemental),0) supplemental
           FROM state_funding.obligation o
           JOIN state_funding.budget_category c USING(federal_account_symbol)
           WHERE o.build_id=:build_id AND o.state=:code AND o.fiscal_year=:fy
           AND o.award_unique_key=ANY(:keys)
           {'AND o.is_supplemental=:supplemental' if filters['funding_type']!='all' else ''}
           {'AND c.category_code=:category' if filters['category'] else ''}
           GROUP BY o.award_unique_key,o.federal_account_symbol,c.category_code,c.category_name,c.category_order
           ORDER BY o.award_unique_key,c.category_order,symbol""",
            p | {"keys": keys},
        ).mappings()
        for a in account_rows:
            key = a["award_unique_key"]
            account_map.setdefault(key, []).append(
                {
                    "symbol": a["symbol"],
                    "name": a["name"],
                    "regular": money(a["regular"]),
                    "supplemental": money(a["supplemental"]),
                }
            )
            category = category_map.setdefault(key, {}).setdefault(
                a["code"],
                {
                    "code": a["code"],
                    "name": a["category_name"],
                    "regular": 0,
                    "supplemental": 0,
                    "_order": a["category_order"],
                },
            )
            for field in ("regular", "supplemental"):
                category[field] = money(category[field] + money(a[field]))
    for row in rows:
        item = dict(row)
        item["accounts"] = account_map.get(item["award_unique_key"], [])
        item["categories"] = sorted(
            category_map.get(item["award_unique_key"], {}).values(), key=lambda category: category["_order"]
        )
        for category in item["categories"]:
            del category["_order"]
        for k in ("regular", "supplemental", "total"):
            item[k] = money(item[k])
        result.append(item)
    period = (build["sources"] or {}).get("periods", {}).get(str(fy), f"FY{fy}")
    return {
        "fiscal_year": fy,
        "filters": filters | {"q": q},
        "page": page,
        "page_size": page_size,
        "total_rows": totals["n"],
        "rows": result,
        "sum_total": money(totals["sum_total"]),
        "citation": citation(fy, period, build["build_id"]),
    }


def grant_history(db, nofo):
    from .grant_history import grant_history as read_history
    return read_history(db, nofo)


def grant_award(db, nofo, award_unique_key):
    from .grant_history import grant_award as read_award
    return read_award(db, nofo, award_unique_key)
