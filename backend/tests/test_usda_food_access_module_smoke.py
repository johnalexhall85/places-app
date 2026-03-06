from __future__ import annotations

from app.db_schemas import USDA_FOOD_ACCESS_SCHEMA
from app.main import app
from app.usda_food_access import models as usda_models


def test_usda_schema_default_is_usda_food_access() -> None:
    assert USDA_FOOD_ACCESS_SCHEMA == "usda_food_access"


def test_usda_model_tables_use_usda_schema() -> None:
    assert usda_models.UsdaFoodAccessTractAtlas.__table__.schema == USDA_FOOD_ACCESS_SCHEMA
    assert usda_models.UsdaFoodAccessVariableLookup.__table__.schema == USDA_FOOD_ACCESS_SCHEMA
    assert usda_models.UsdaFoodAccessDatasetMeta.__table__.schema == USDA_FOOD_ACCESS_SCHEMA


def test_usda_router_is_registered() -> None:
    route_paths = {route.path for route in app.routes}
    assert any(path.startswith("/api/usda/food-access/") for path in route_paths)
