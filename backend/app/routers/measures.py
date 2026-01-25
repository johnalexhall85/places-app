from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models
from app.db import get_db

router = APIRouter(tags=["measures"])


@router.get("/measures")
def list_measures(db: Session = Depends(get_db)):
    rows = (
        db.query(models.DimMeasure)
        .order_by(models.DimMeasure.category, models.DimMeasure.measure)
        .all()
    )

    return [
        {
            "id": row.id,
            "category_id": row.category_id,
            "category": row.category,
            "measure_id": row.measure_id,
            "measure": row.measure,
            "data_value_type_id": row.data_value_type_id,
            "data_value_type": row.data_value_type,
            "unit": row.unit,
            "short_question_text": row.short_question_text,
        }
        for row in rows
    ]
