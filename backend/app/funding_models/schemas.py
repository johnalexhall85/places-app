from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.funding_models.constants import (
    ALLOWED_OPERATORS,
    ALLOWED_RULE_FIELDS,
    ASSET_NAME_RE,
    FUNDING_MODE_KEY_RE,
    INTERNAL_ID_RE,
    MODEL_STATUSES,
    NO_VALUE_OPERATORS,
    SEQUENCE_OPERATORS,
    SLUG_RE,
)


class RuleCondition(BaseModel):
    id: str | None = None
    field: str = Field(min_length=1)
    operator: str = Field(min_length=1)
    value: Any = None

    model_config = ConfigDict(extra="ignore")

    @field_validator("field")
    @classmethod
    def validate_field_name(cls, value: str) -> str:
        token = str(value or "").strip()
        if token not in ALLOWED_RULE_FIELDS:
            allowed = ", ".join(sorted(ALLOWED_RULE_FIELDS))
            raise ValueError(f"field must be one of {allowed}")
        return token

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, value: str) -> str:
        token = str(value or "").strip().lower()
        if token not in ALLOWED_OPERATORS:
            allowed = ", ".join(sorted(ALLOWED_OPERATORS))
            raise ValueError(f"operator must be one of {allowed}")
        return token

    @model_validator(mode="after")
    def validate_value_shape(self) -> "RuleCondition":
        field_meta = ALLOWED_RULE_FIELDS[self.field]
        supported_operators = set(field_meta.get("operators") or ())
        if supported_operators and self.operator not in supported_operators:
            allowed = ", ".join(sorted(supported_operators))
            raise ValueError(f"{self.field} only supports operators: {allowed}")
        if self.operator in NO_VALUE_OPERATORS:
            self.value = None
            return self
        if self.operator in SEQUENCE_OPERATORS and not isinstance(self.value, list):
            raise ValueError(f"{self.operator} requires an array value")
        if self.operator not in SEQUENCE_OPERATORS and self.value is None:
            raise ValueError(f"{self.operator} requires a value")
        return self


class RuleGroup(BaseModel):
    id: str | None = None
    combinator: Literal["ALL", "ANY"] = "ALL"
    children: list["RuleNode"] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


RuleNode = RuleCondition | RuleGroup
RuleGroup.model_rebuild()


class FundingModelDataSources(BaseModel):
    usaspending_awards: bool = True
    usaspending_subawards: bool = False
    usaspending_assistance_transactions: bool = True
    usaspending_contract_transactions: bool = True
    taggs: bool = True

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def hydrate_legacy_transaction_toggle(cls, value):
        data = dict(value or {})
        if "usaspending_transactions" not in data:
            return data
        legacy_enabled = bool(data.pop("usaspending_transactions"))
        data.setdefault("usaspending_assistance_transactions", legacy_enabled)
        data.setdefault("usaspending_contract_transactions", legacy_enabled)
        return data


class FundingModelOptions(BaseModel):
    include_finalized_only: bool = True
    include_deobligations: bool = False
    include_negative_adjustments: bool = False
    include_pass_through_records: bool = False


class FundingModelAggregation(BaseModel):
    default_metric: str = "normalized_total"
    supported_geographies: list[str] = Field(default_factory=lambda: ["nation", "state", "county"])
    default_geography: str = "state"
    default_fiscal_year: int | None = None


class FundingModelDefinition(BaseModel):
    data_sources: FundingModelDataSources = Field(default_factory=FundingModelDataSources)
    options: FundingModelOptions = Field(default_factory=FundingModelOptions)
    include_group: RuleGroup = Field(default_factory=RuleGroup)
    exclude_group: RuleGroup = Field(default_factory=lambda: RuleGroup(combinator="ANY"))
    advanced_sql_enabled: bool = False
    advanced_sql_override: str | None = None
    aggregation: FundingModelAggregation = Field(default_factory=FundingModelAggregation)


class FundingModelDraftPayload(BaseModel):
    display_name: str = Field(min_length=1)
    internal_model_id: str = Field(min_length=1)
    chip_methodology_version: str = Field(min_length=1)
    funding_mode_key: str | None = None
    slug: str | None = None
    description: str | None = None
    chip_state_profile_source_version: str | None = None
    chip_normalization_source_version: str | None = None
    status: str = "draft"
    version_label: str | None = None
    notes: str | None = None
    definition: FundingModelDefinition = Field(default_factory=FundingModelDefinition)

    model_config = ConfigDict(extra="ignore")

    @field_validator("display_name", "chip_methodology_version")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        token = str(value or "").strip()
        if not token:
            raise ValueError("value is required")
        return token

    @field_validator("internal_model_id")
    @classmethod
    def validate_internal_model_id(cls, value: str) -> str:
        token = str(value or "").strip().lower()
        if not INTERNAL_ID_RE.fullmatch(token):
            raise ValueError("internal_model_id must be machine-safe snake_case")
        return token

    @field_validator("funding_mode_key")
    @classmethod
    def validate_funding_mode_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = str(value).strip().lower()
        if not FUNDING_MODE_KEY_RE.fullmatch(token):
            raise ValueError("funding_mode_key must be machine-safe snake_case")
        return token

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = str(value).strip().lower()
        if not SLUG_RE.fullmatch(token):
            raise ValueError("slug must be URL-safe kebab-case")
        return token

    @field_validator("chip_state_profile_source_version", "chip_normalization_source_version")
    @classmethod
    def validate_asset_names(cls, value: str | None) -> str | None:
        if value is None:
            return None
        token = str(value).strip().lower()
        if not ASSET_NAME_RE.fullmatch(token):
            raise ValueError("source version names must be lowercase SQL-safe identifiers")
        return token

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        token = str(value or "draft").strip().lower()
        if token not in MODEL_STATUSES:
            allowed = ", ".join(sorted(MODEL_STATUSES))
            raise ValueError(f"status must be one of {allowed}")
        return token


class FundingModelPreviewRequest(FundingModelDraftPayload):
    preview_fiscal_year: int | None = None
    preview_geography_level: Literal["nation", "state", "county"] = "state"


class FundingModelVersionRequest(FundingModelDraftPayload):
    pass


class FundingModelActionRequest(BaseModel):
    version_number: int | None = None
    notes: str | None = None


class FundingModelCloneRequest(BaseModel):
    version_number: int | None = None
    version_label: str | None = None


class FundingModelSavedPreviewRequest(BaseModel):
    version_number: int | None = None
    preview_fiscal_year: int | None = None
    preview_geography_level: Literal["nation", "state", "county"] = "state"


class FundingModelPublishRequest(BaseModel):
    version_number: int | None = None
    label: str | None = None
    sort_order: int | None = None
    map_default: bool = False


class FundingModeOption(BaseModel):
    value: str
    label: str
    system: bool = False
    is_active: bool = True
    sort_order: int | None = None


class FundingModelFieldCatalogItem(BaseModel):
    key: str
    label: str
    raw_key: str
    type: Literal["text", "number", "boolean", "date", "datetime"]
    group: Literal["common", "assistance", "contract", "legacy_curated"]
    applies_to_sources: list[str] = Field(default_factory=list)
    operators: list[str] = Field(default_factory=list)


class FundingModelVersionSummary(BaseModel):
    id: int
    version_number: int
    version_label: str | None = None
    status: str
    build_status: str | None = None
    validation_status: str | None = None
    plain_language_summary: str | None = None
    chip_state_profile_source_version: str | None = None
    chip_normalization_source_version: str | None = None
    created_by: str | None = None
    created_at: str | None = None


class FundingModelVersionDetail(FundingModelVersionSummary):
    definition_json: dict[str, Any]
    generated_sql: str | None = None
    advanced_sql_override: str | None = None
    notes: str | None = None


class FundingModelResponse(BaseModel):
    id: int
    display_name: str
    internal_model_id: str
    slug: str
    description: str | None = None
    chip_methodology_version: str
    funding_mode_key: str
    status: str
    is_system: bool
    is_user_editable: bool
    is_visible_in_funding_mode: bool
    toolbar_page_enabled: bool
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    current_version_id: int | None = None
    current_version: FundingModelVersionDetail | None = None
    versions: list[FundingModelVersionSummary] = Field(default_factory=list)


class PreviewSeriesRow(BaseModel):
    fiscal_year: int
    total_amount: float
    row_count: int


class PreviewStateRow(BaseModel):
    state_code: str
    state_name: str | None = None
    total_amount: float
    row_count: int


class FundingModelPreviewResponse(BaseModel):
    generated_sql: str
    plain_language_summary: str
    warnings: list[str] = Field(default_factory=list)
    row_count: int = 0
    included_record_count: int = 0
    excluded_record_count: int = 0
    national_totals_by_fiscal_year: list[PreviewSeriesRow] = Field(default_factory=list)
    state_totals_for_fiscal_year: list[PreviewStateRow] = Field(default_factory=list)


class FundingModelBuildRunResponse(BaseModel):
    id: int
    status: str
    run_type: str
    script_name: str
    output_table_name: str | None = None
    output_view_name: str | None = None
    log_excerpt: str | None = None
