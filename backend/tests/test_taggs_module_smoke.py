from __future__ import annotations

from app.db_schemas import TAGGS_SCHEMA
from app.main import app
from app.taggs import models as taggs_models
from app.taggs import services as taggs_services


def test_taggs_schema_default_is_taggs() -> None:
    assert TAGGS_SCHEMA == "taggs"


def test_taggs_model_tables_use_taggs_schema() -> None:
    assert taggs_models.TaggsRawAward.__table__.schema == TAGGS_SCHEMA
    assert taggs_models.TaggsAwardFundingSummary.__table__.schema == TAGGS_SCHEMA
    assert taggs_models.TaggsStateFundingSummary.__table__.schema == TAGGS_SCHEMA
    assert taggs_models.TaggsCanClassification.__table__.schema == TAGGS_SCHEMA
    assert taggs_models.TaggsCanProfileMatchAudit.__table__.schema == TAGGS_SCHEMA
    assert taggs_models.TaggsIngestionRun.__table__.schema == TAGGS_SCHEMA


def test_taggs_router_is_registered() -> None:
    route_paths = {route.path for route in app.routes}
    assert any(path.startswith("/api/taggs/") for path in route_paths)
    assert "/api/taggs/states/map" in route_paths
    assert "/api/taggs/can-mapping/status" in route_paths
    assert "/api/taggs/funding-profile/summary" in route_paths
    assert "/api/taggs/funding-profile/can-breakdown" in route_paths


def test_taggs_service_sql_falls_back_to_can_classification_columns() -> None:
    context = taggs_services.TaggsQueryContext(
        summary_has_effective_program_name=False,
        summary_has_effective_category=False,
        summary_has_effective_subcategory=False,
        summary_has_effective_mapping_method=False,
        summary_has_funding_stream=False,
        summary_has_appropriation_type=False,
        summary_has_profile_assisted_mapping=False,
        summary_has_fallback_inference=False,
        summary_has_can_mapping_version=False,
        classification_has_effective_program_name=False,
        classification_has_effective_category=False,
        classification_has_effective_subcategory=False,
        classification_has_effective_mapping_method=False,
        classification_has_can_mapping_version=False,
    )

    assert "c.category_override" in taggs_services._category_expr(context)  # noqa: SLF001
    assert "c.subcategory_override" in taggs_services._subcategory_expr(context)  # noqa: SLF001
    assert "c.funding_stream" in taggs_services._funding_stream_expr(context)  # noqa: SLF001
    assert "c.appropriation_type" in taggs_services._appropriation_type_expr(context)  # noqa: SLF001
    assert "LEFT JOIN" in taggs_services._base_from_clause()  # noqa: SLF001


def test_display_label_from_row_prefers_interpreted_mapping_fields() -> None:
    assert (
        taggs_services._display_label_from_row(  # noqa: SLF001
            {
                "effective_program_name": "Vaccines for Children Program",
                "funding_stream": "Vaccines for Children",
                "effective_subcategory": "Vaccines for Children",
                "effective_category": "Immunization",
            }
        )
        == "Vaccines for Children Program"
    )
    assert (
        taggs_services._display_label_from_row(  # noqa: SLF001
            {
                "effective_program_name": "",
                "funding_stream": "Drug Free Communities",
                "effective_subcategory": "Drug-Free Communities Support Program",
                "effective_category": "NCIPC",
            }
        )
        == "Drug Free Communities"
    )
    assert (
        taggs_services._display_label_from_row(  # noqa: SLF001
            {
                "effective_program_name": None,
                "funding_stream": None,
                "effective_subcategory": None,
                "effective_category": None,
            }
        )
        == "Unknown / Unclassified"
    )
