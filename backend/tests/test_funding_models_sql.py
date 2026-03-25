from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.funding_models.constants import funding_model_field_catalog
from app.funding_models.schemas import FundingModelDraftPayload
from app.funding_models.sql import generate_visual_sql, validate_advanced_sql
from app.funding_models.summary import build_plain_language_summary


def build_payload() -> FundingModelDraftPayload:
    return FundingModelDraftPayload(
        display_name="CHIP v1.1 Emergency Classification",
        internal_model_id="v1_1_emergency_classification",
        chip_methodology_version="v1.1",
        funding_mode_key="chip_v1_1_emergency",
        slug="chip-v1-1-emergency-classification",
        chip_state_profile_source_version="chip_state_profile_v1_1_emergency_classification",
        chip_normalization_source_version="chip_normalized_v1_1_emergency_classification",
        definition={
            "data_sources": {
                "usaspending_awards": True,
                "usaspending_subawards": False,
                "usaspending_assistance_transactions": True,
                "usaspending_contract_transactions": True,
                "taggs": True,
            },
            "options": {
                "include_finalized_only": True,
                "include_deobligations": False,
                "include_negative_adjustments": False,
                "include_pass_through_records": False,
            },
            "include_group": {
                "id": "include-root",
                "combinator": "ALL",
                "children": [
                    {"id": "rule-1", "field": "recipient_state_code", "operator": "equals", "value": "AL"},
                    {
                        "id": "group-1",
                        "combinator": "ANY",
                        "children": [
                            {"id": "rule-2", "field": "fiscal_year", "operator": "greater_than", "value": 2021},
                            {"id": "rule-3", "field": "is_emergency_funding", "operator": "equals", "value": True},
                        ],
                    },
                ],
            },
            "exclude_group": {
                "id": "exclude-root",
                "combinator": "ANY",
                "children": [
                    {"id": "rule-4", "field": "funding_mechanism", "operator": "contains", "value": "procurement"},
                ],
            },
            "advanced_sql_enabled": False,
            "advanced_sql_override": None,
            "aggregation": {
                "default_metric": "normalized_total",
                "supported_geographies": ["nation", "state", "county"],
                "default_geography": "state",
                "default_fiscal_year": 2025,
            },
        },
    )


def test_funding_model_schema_rejects_invalid_internal_id() -> None:
    with pytest.raises(ValueError):
        FundingModelDraftPayload(
            display_name="Bad",
            internal_model_id="bad-id",
            chip_methodology_version="v1.0",
            definition={},
        )


def test_generate_visual_sql_includes_rule_groups_and_sources() -> None:
    sql = generate_visual_sql(build_payload())

    assert "analytics.funding_model_builder_base_v1" in sql
    assert "dataset_key IN ('usaspending_awards', 'usaspending_assistance_transactions', 'usaspending_contract_transactions', 'taggs')" in sql
    assert "COALESCE(is_finalized, FALSE) = TRUE" in sql
    assert "LOWER(COALESCE(recipient_state_code::text, '')) = 'al'" in sql
    assert "fiscal_year > 2021" in sql
    assert "COALESCE(is_emergency_funding, FALSE) = TRUE" in sql
    assert "NOT (LOWER(COALESCE(funding_mechanism::text, '')) LIKE '%procurement%')" in sql


def test_legacy_transaction_toggle_hydrates_split_sources() -> None:
    payload = FundingModelDraftPayload(
        display_name="Legacy",
        internal_model_id="legacy_model",
        chip_methodology_version="v1.0",
        definition={
            "data_sources": {
                "usaspending_awards": True,
                "usaspending_transactions": True,
                "taggs": False,
            },
        },
    )

    assert payload.definition.data_sources.usaspending_assistance_transactions is True
    assert payload.definition.data_sources.usaspending_contract_transactions is True


def test_source_specific_rules_are_scoped_to_matching_sources() -> None:
    payload = build_payload()
    payload.definition.data_sources.usaspending_contract_transactions = False
    payload.definition.include_group.children = [
        {
            "id": "rule-1",
            "field": "assistance.award_id_fain",
            "operator": "equals",
            "value": "FAIN-123",
        },
    ]
    payload.definition.exclude_group.children = [
        {
            "id": "rule-2",
            "field": "assistance.award_id_fain",
            "operator": "equals",
            "value": "FAIN-999",
        },
    ]

    sql = generate_visual_sql(FundingModelDraftPayload(**payload.model_dump(mode="python")))

    assert "dataset_key NOT IN ('usaspending_assistance_transactions')" in sql
    assert "dataset_key IN ('usaspending_assistance_transactions')" in sql
    assert "assistance_award_id_fain" in sql


def test_source_specific_rules_require_their_matching_source() -> None:
    payload = build_payload()
    payload.definition.data_sources.usaspending_assistance_transactions = False
    payload.definition.include_group.children = [
        {
            "id": "rule-1",
            "field": "assistance.award_id_fain",
            "operator": "equals",
            "value": "FAIN-123",
        },
    ]

    with pytest.raises(HTTPException) as exc_info:
        generate_visual_sql(FundingModelDraftPayload(**payload.model_dump(mode="python")))

    assert exc_info.value.status_code == 400
    assert "requires at least one enabled source" in str(exc_info.value.detail)


def test_advanced_sql_validation_rejects_unsafe_keywords() -> None:
    with pytest.raises(HTTPException):
        validate_advanced_sql("SELECT record_key FROM analytics.funding_model_builder_base_v1; DROP TABLE analytics.x")


def test_advanced_sql_validation_rejects_tab_whitespace_bypass() -> None:
    # Keyword followed by a tab (not a space) must still be rejected.
    with pytest.raises(HTTPException) as exc_info:
        validate_advanced_sql(
            "SELECT record_key FROM analytics.funding_model_builder_base_v1 WHERE DROP\tTABLE analytics.x IS NULL"
        )
    assert exc_info.value.status_code == 400


def test_advanced_sql_validation_rejects_newline_whitespace_bypass() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_advanced_sql(
            "SELECT record_key FROM analytics.funding_model_builder_base_v1\nDELETE\nFROM analytics.x"
        )
    assert exc_info.value.status_code == 400


def test_advanced_sql_validation_rejects_grant_keyword() -> None:
    with pytest.raises(HTTPException):
        validate_advanced_sql(
            "SELECT record_key FROM analytics.funding_model_builder_base_v1 GRANT ALL ON analytics.x TO public"
        )


def test_advanced_sql_validation_allows_column_names_containing_keyword_roots() -> None:
    # Column names like 'created_at' or 'grant_amount' must not be rejected.
    result = validate_advanced_sql(
        "SELECT record_key FROM analytics.funding_model_builder_base_v1 WHERE created_at IS NOT NULL"
    )
    assert result is not None


def test_advanced_sql_validation_requires_select_start() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_advanced_sql("DELETE FROM analytics.funding_model_builder_base_v1 WHERE record_key = 'x'")
    assert exc_info.value.status_code == 400


def test_advanced_sql_validation_requires_record_key() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_advanced_sql("SELECT * FROM analytics.funding_model_builder_base_v1")
    assert exc_info.value.status_code == 400


def test_advanced_sql_validation_rejects_unapproved_relation() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_advanced_sql("SELECT record_key FROM public.dim_county WHERE record_key IS NOT NULL")
    assert exc_info.value.status_code == 400


def test_advanced_sql_validation_allows_valid_sql() -> None:
    result = validate_advanced_sql(
        "SELECT record_key FROM analytics.funding_model_builder_base_v1 WHERE fiscal_year = 2024"
    )
    assert result == "SELECT record_key FROM analytics.funding_model_builder_base_v1 WHERE fiscal_year = 2024"


def test_advanced_sql_validation_strips_trailing_semicolon() -> None:
    result = validate_advanced_sql(
        "SELECT record_key FROM analytics.funding_model_builder_base_v1 WHERE fiscal_year = 2024;"
    )
    assert result is not None


def test_advanced_sql_validation_rejects_multiple_statements() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_advanced_sql(
            "SELECT record_key FROM analytics.funding_model_builder_base_v1; SELECT * FROM analytics.funding_model_builder_base_v1"
        )
    assert exc_info.value.status_code == 400


def test_plain_language_summary_mentions_sources_and_rules() -> None:
    summary = build_plain_language_summary(build_payload())

    assert "USAspending awards, USAspending assistance transactions, USAspending contract transactions, TAGGS" in summary
    assert "include rules" in summary
    assert "exclude rules" in summary


def test_field_catalog_includes_split_transaction_fields() -> None:
    items = funding_model_field_catalog()
    by_key = {item["key"]: item for item in items}

    assert by_key["funding_subagency_name"]["group"] == "common"
    assert by_key["assistance.award_id_fain"]["group"] == "assistance"
    assert by_key["contract.product_or_service_code"]["group"] == "contract"
