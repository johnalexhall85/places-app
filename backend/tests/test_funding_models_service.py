from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.funding_models import service
from app.funding_models.schemas import FundingModelDraftPayload


def test_list_models_returns_empty_when_tables_are_missing(monkeypatch) -> None:
    monkeypatch.setattr(service, "_storage_ready", lambda _db: False)

    assert service.list_models(None) == []


def test_create_model_raises_clear_error_when_tables_are_missing(monkeypatch) -> None:
    monkeypatch.setattr(service, "_storage_ready", lambda _db: False)

    with pytest.raises(HTTPException) as exc_info:
        service.create_model(
            None,
            FundingModelDraftPayload(
                display_name="Example",
                internal_model_id="example_model",
                chip_methodology_version="v1.0",
                definition={},
            ),
        )

    assert exc_info.value.status_code == 503
    assert "alembic upgrade head" in str(exc_info.value.detail)


def test_list_field_catalog_includes_split_transaction_fields() -> None:
    items = service.list_field_catalog()
    by_key = {item["key"]: item for item in items}

    assert by_key["funding_subagency_name"]["group"] == "common"
    assert by_key["assistance.award_id_fain"]["group"] == "assistance"
    assert by_key["contract.product_or_service_code"]["group"] == "contract"
