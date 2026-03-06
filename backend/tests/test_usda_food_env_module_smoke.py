from __future__ import annotations

from app.db_schemas import USDA_FOOD_ENV_SCHEMA
from app.main import app
from app.usda_food_env import models as env_models


def test_usda_food_env_schema_default() -> None:
    assert USDA_FOOD_ENV_SCHEMA == "usda_food_env"


def test_usda_food_env_model_tables_use_schema() -> None:
    assert env_models.UsdaFoodEnvVariableLookup.__table__.schema == USDA_FOOD_ENV_SCHEMA
    assert env_models.UsdaFoodEnvCountyValues.__table__.schema == USDA_FOOD_ENV_SCHEMA
    assert env_models.UsdaFoodEnvStateValues.__table__.schema == USDA_FOOD_ENV_SCHEMA
    assert env_models.UsdaFoodEnvDatasetMeta.__table__.schema == USDA_FOOD_ENV_SCHEMA


def test_usda_food_env_router_is_registered() -> None:
    route_paths = {route.path for route in app.routes}
    assert any(path.startswith("/api/usda/food-environment/") for path in route_paths)
