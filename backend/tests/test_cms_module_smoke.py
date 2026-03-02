from __future__ import annotations

from app.cms import models as cms_models
from app.db_schemas import CMS_SCHEMA
from app.main import app


def test_cms_schema_default_is_cms() -> None:
    assert CMS_SCHEMA == "cms"


def test_cms_model_tables_use_cms_schema() -> None:
    assert cms_models.CmsGeoDim.__table__.schema == CMS_SCHEMA
    assert cms_models.CmsGvMeasureDim.__table__.schema == CMS_SCHEMA
    assert cms_models.CmsGvFact.__table__.schema == CMS_SCHEMA
    assert cms_models.CmsSspMeasureDim.__table__.schema == CMS_SCHEMA
    assert cms_models.CmsSspFact.__table__.schema == CMS_SCHEMA


def test_cms_router_is_registered() -> None:
    route_paths = {route.path for route in app.routes}
    assert any(path.startswith("/cms/") for path in route_paths)
