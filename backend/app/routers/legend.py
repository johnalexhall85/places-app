from fastapi import APIRouter, Depends, Query
from sqlalchemy import Float, bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["legend"])

# curl "http://localhost:8000/legend?measure_id=CASTHMA&year=2022&data_value_type_id=1&bins=5"
# curl "http://localhost:8000/legend?measure_id=CASTHMA&year=2022&state_abbr=CA&bins=7"
@router.get("/legend")
def get_legend(
    measure_id: str = Query(...),
    year: int = Query(...),
    data_value_type_id: str | None = Query(default=None),
    state_abbr: str | None = Query(default=None, min_length=2, max_length=2),
    bins: int = Query(default=5, ge=2, le=9),
    db: Session = Depends(get_db),
):
    state_abbr_upper = state_abbr.upper() if state_abbr else None
    quantile_fractions = [i / bins for i in range(1, bins)]

    sql = text(
        """
        SELECT
            COUNT(*) FILTER (WHERE f.data_value IS NOT NULL) AS n,
            COUNT(*) FILTER (WHERE f.data_value IS NULL) AS nulls,
            MIN(f.data_value) AS min,
            MAX(f.data_value) AS max,
            COALESCE(
                percentile_cont(%(quantiles)s)
                  WITHIN GROUP (ORDER BY f.data_value)
                  FILTER (WHERE f.data_value IS NOT NULL),
                ARRAY[]::float8[]
            ) AS quantiles
        FROM fact_estimate_county AS f
        JOIN dim_measure AS m ON f.measure_dim_id = m.id
        JOIN dim_county AS c ON f.location_id = c.location_id
        WHERE f.year = %(year)s
          AND m.measure_id = %(measure_id)s
          AND ((%(data_value_type_id)s)::text IS NULL OR m.data_value_type_id = (%(data_value_type_id)s)::text)
          AND ((%(state_abbr)s)::text IS NULL OR c.state_abbr = (%(state_abbr)s)::text)
        """
    ).bindparams(bindparam("quantiles", type_=ARRAY(Float)))

    row = db.execute(
        sql,
        {
            "year": year,
            "measure_id": measure_id,
            "data_value_type_id": data_value_type_id,
            "state_abbr": state_abbr_upper,
            "quantiles": quantile_fractions,
        },
    ).mappings().one()

    if row["n"] == 0:
        return {
            "measure_id": measure_id,
            "year": year,
            "data_value_type_id": data_value_type_id,
            "state_abbr": state_abbr_upper,
            "bins": bins,
            "n": int(row["n"]),
            "nulls": int(row["nulls"]),
            "min": None,
            "max": None,
            "quantiles": [],
            "breaks": [],
        }

    min_value = row["min"]
    max_value = row["max"]
    if min_value is None or max_value is None:
        quantiles = []
        breaks = []
    else:
        raw_quantiles = row["quantiles"] or []
        quantiles = [float(value) for value in raw_quantiles]
        breaks = [float(min_value), *quantiles, float(max_value)]

    return {
        "measure_id": measure_id,
        "year": year,
        "data_value_type_id": data_value_type_id,
        "state_abbr": state_abbr_upper,
        "bins": bins,
        "n": int(row["n"]),
        "nulls": int(row["nulls"]),
        "min": float(min_value) if min_value is not None else None,
        "max": float(max_value) if max_value is not None else None,
        "quantiles": quantiles,
        "breaks": breaks,
    }
