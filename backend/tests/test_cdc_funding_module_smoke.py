from __future__ import annotations

from app.cdc_funding import models as cdc_models
from app.db_schemas import CDC_FUNDING_SCHEMA
from app.main import app


def test_cdc_funding_schema_default() -> None:
    assert CDC_FUNDING_SCHEMA == "cdc_funding"


def test_cdc_funding_model_tables_use_schema() -> None:
    assert cdc_models.CdcPrimeAward.__table__.schema == CDC_FUNDING_SCHEMA
    assert cdc_models.CdcSubaward.__table__.schema == CDC_FUNDING_SCHEMA
    assert cdc_models.CdcPrimeTransaction.__table__.schema == CDC_FUNDING_SCHEMA
    assert cdc_models.CdcPrimeTransactionStateSummary.__table__.schema == CDC_FUNDING_SCHEMA
    assert cdc_models.CdcPrimeTransactionCountySummary.__table__.schema == CDC_FUNDING_SCHEMA
    assert cdc_models.CdcPrimeStateSummary.__table__.schema == CDC_FUNDING_SCHEMA
    assert cdc_models.CdcPrimeCountySummary.__table__.schema == CDC_FUNDING_SCHEMA
    assert cdc_models.CdcSubawardStateSummary.__table__.schema == CDC_FUNDING_SCHEMA
    assert cdc_models.CdcSubawardCountySummary.__table__.schema == CDC_FUNDING_SCHEMA
    assert cdc_models.CdcAppropriationClassification.__table__.schema == CDC_FUNDING_SCHEMA
    assert cdc_models.CdcIntelligenceStateCategorySummary.__table__.schema == CDC_FUNDING_SCHEMA
    assert cdc_models.CdcIntelligenceStateSubcategorySummary.__table__.schema == CDC_FUNDING_SCHEMA


def test_cdc_funding_router_is_registered() -> None:
    route_paths = {route.path for route in app.routes}
    assert any(path.startswith("/api/cdc/funding/") for path in route_paths)
    assert "/api/cdc/funding/trend" in route_paths
    assert "/api/cdc/funding/profile/overview" in route_paths


def test_non_cdc_map_routes_remain_registered() -> None:
    route_paths = {route.path for route in app.routes}
    assert "/api/fema/nri/map" in route_paths
    assert "/api/usda/food-access/map" in route_paths
    assert "/api/taggs/states/map" in route_paths
