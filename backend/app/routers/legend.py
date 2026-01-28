from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db

router = APIRouter(tags=["legend"])


@router.get("/legend")
def get_legend(
    measure_id: str = Query(...),
    year: int = Query(...),
    data_value_type_id: str = Query("CrdPrv"),
    bins: int = Query(5, ge=2, le=9),
    db: Session = Depends(get_db),
):
    """
    Returns legend breaks for the current measure/year/type.
    Uses equal-interval bins between min and max.
    """
    # 1) Find the selected measure dimension id
    measure_dim = db.execute(
        text(
            """
            SELECT id
            FROM dim_measure
            WHERE measure_id = :measure_id
              AND data_value_type_id = :data_value_type_id
            LIMIT 1
            """
        ),
        {"measure_id": measure_id, "data_value_type_id": data_value_type_id},
    ).scalar_one_or_none()

    if measure_dim is None:
        return {"breaks": [], "bins": bins}

    # 2) Get min/max for that measure/year
    row = db.execute(
        text(
            """
            SELECT
              MIN(data_value) AS min_value,
              MAX(data_value) AS max_value
            FROM fact_estimate_county
            WHERE year = :year
              AND measure_dim_id = :measure_dim_id
              AND data_value IS NOT NULL
            """
        ),
        {"year": year, "measure_dim_id": measure_dim},
    ).mappings().one()

    min_value = row["min_value"]
    max_value = row["max_value"]

    if min_value is None or max_value is None:
        return {"breaks": [], "bins": bins}

    # 3) Build breaks (bins+1 values)
    if float(min_value) == float(max_value):
        breaks = [float(min_value), float(max_value)]
    else:
        step = (float(max_value) - float(min_value)) / bins
        breaks = [float(min_value) + step * i for i in range(bins + 1)]
        # avoid tiny float noise in UI
        breaks = [round(x, 6) for x in breaks]

    return {
        "measure_id": measure_id,
        "year": year,
        "data_value_type_id": data_value_type_id,
        "bins": bins,
        "breaks": breaks,
    }
