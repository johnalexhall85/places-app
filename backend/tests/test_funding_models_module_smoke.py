from __future__ import annotations

from app.funding_models import models as funding_models
from app.db_schemas import ANALYTICS_SCHEMA
from app.main import app


def test_funding_models_use_analytics_schema() -> None:
    assert ANALYTICS_SCHEMA == "analytics"
    assert funding_models.FundingProfileModel.__table__.schema == ANALYTICS_SCHEMA
    assert funding_models.FundingProfileVersion.__table__.schema == ANALYTICS_SCHEMA
    assert funding_models.FundingProfileBuildRun.__table__.schema == ANALYTICS_SCHEMA
    assert funding_models.FundingModeRegistryEntry.__table__.schema == ANALYTICS_SCHEMA


def test_funding_model_routes_are_registered() -> None:
    route_paths = {route.path for route in app.routes}
    assert "/api/funding-models" in route_paths
    assert "/api/funding-models/field-catalog" in route_paths
    assert "/api/funding-models/{model_id}" in route_paths
    assert "/api/funding-models/{model_id}/publish" in route_paths
    assert "/api/funding-modes" in route_paths
