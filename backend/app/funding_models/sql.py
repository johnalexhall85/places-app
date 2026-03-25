from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException

from app.funding_models.constants import (
    ALLOWED_RULE_FIELDS,
    APPROVED_SQL_RELATIONS,
    ASSET_NAME_RE,
    DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS,
    DEFAULT_DEFINITION,
    DATA_SOURCE_USASPENDING_AWARDS,
    DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS,
    DATA_SOURCE_USASPENDING_SUBAWARDS,
    DATA_SOURCE_TAGGS,
    FUNDING_MODEL_BUILDER_BASE_VIEW,
    FUNDING_MODE_KEY_RE,
    INTERNAL_ID_RE,
    NO_VALUE_OPERATORS,
    SEQUENCE_OPERATORS,
    SLUG_RE,
    STRING_MATCH_OPERATORS,
)
from app.funding_models.schemas import FundingModelDraftPayload, RuleCondition, RuleGroup

RELATION_PATTERN = re.compile(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_\.]*)", re.IGNORECASE)

# Matches disallowed DDL/DML keywords followed by any whitespace character.
# Using \s (not just space) prevents tab/newline bypass (e.g. DROP\tTABLE).
# Word boundary \b avoids false positives on column names like grant_amount or created_at.
_DISALLOWED_SQL_KEYWORDS_RE = re.compile(
    r"\b(insert|update|delete|alter|drop|truncate|grant|revoke|create|comment|vacuum)\s",
    re.IGNORECASE,
)


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or "funding-model"


def machine_id(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    if not text:
        return "funding_model"
    if not text[0].isalpha():
        text = f"m_{text}"
    return text


def default_funding_mode_key(internal_model_id: str) -> str:
    token = machine_id(internal_model_id)
    return token if FUNDING_MODE_KEY_RE.fullmatch(token) else "funding_model"


def validate_metadata_identifiers(payload: FundingModelDraftPayload, *, require_assets: bool = False) -> None:
    if not INTERNAL_ID_RE.fullmatch(payload.internal_model_id):
        raise HTTPException(status_code=400, detail="internal_model_id must be machine-safe snake_case")
    if payload.slug and not SLUG_RE.fullmatch(payload.slug):
        raise HTTPException(status_code=400, detail="slug must be URL-safe kebab-case")
    if payload.funding_mode_key and not FUNDING_MODE_KEY_RE.fullmatch(payload.funding_mode_key):
        raise HTTPException(status_code=400, detail="funding_mode_key must be machine-safe snake_case")
    if require_assets:
        if not payload.chip_state_profile_source_version or not ASSET_NAME_RE.fullmatch(payload.chip_state_profile_source_version):
            raise HTTPException(status_code=400, detail="chip_state_profile_source_version is required before locking")
        if not payload.chip_normalization_source_version or not ASSET_NAME_RE.fullmatch(payload.chip_normalization_source_version):
            raise HTTPException(status_code=400, detail="chip_normalization_source_version is required before locking")


def with_generated_defaults(payload: FundingModelDraftPayload) -> FundingModelDraftPayload:
    data = payload.model_dump(mode="python")
    if not str(data.get("slug") or "").strip():
        data["slug"] = slugify(payload.display_name)
    if not str(data.get("funding_mode_key") or "").strip():
        data["funding_mode_key"] = default_funding_mode_key(payload.internal_model_id)
    return FundingModelDraftPayload(**data)


def compose_definition_json(payload: FundingModelDraftPayload) -> dict[str, Any]:
    merged_definition = DEFAULT_DEFINITION | {}
    data = payload.definition.model_dump(mode="python")
    merged_definition.update(data)
    return {
        "display_name": payload.display_name,
        "internal_model_id": payload.internal_model_id,
        "chip_methodology_version": payload.chip_methodology_version,
        "funding_mode_key": payload.funding_mode_key,
        "slug": payload.slug,
        "description": payload.description,
        "chip_state_profile_source_version": payload.chip_state_profile_source_version,
        "chip_normalization_source_version": payload.chip_normalization_source_version,
        "status": payload.status,
        "definition": merged_definition,
    }


def validate_advanced_sql(sql: str | None) -> str | None:
    token = str(sql or "").strip()
    if not token:
        return None
    lowered = token.lower()
    if ";" in lowered.strip().rstrip(";"):
        raise HTTPException(status_code=400, detail="Advanced SQL must be a single statement.")
    if not lowered.startswith("select"):
        raise HTTPException(status_code=400, detail="Advanced SQL must begin with SELECT.")
    if "record_key" not in lowered:
        raise HTTPException(status_code=400, detail="Advanced SQL must select record_key.")
    if _DISALLOWED_SQL_KEYWORDS_RE.search(lowered):
        raise HTTPException(status_code=400, detail="Advanced SQL contains disallowed write or DDL keywords.")
    relations = {match.group(1).strip() for match in RELATION_PATTERN.finditer(token)}
    unapproved = {relation for relation in relations if relation.lower() not in APPROVED_SQL_RELATIONS}
    if unapproved:
        detail = ", ".join(sorted(unapproved))
        raise HTTPException(status_code=400, detail=f"Advanced SQL references unapproved relations: {detail}")
    return token


def generate_visual_sql(payload: FundingModelDraftPayload) -> str:
    where_clauses: list[str] = []
    dataset_keys = _selected_dataset_keys(payload)
    if not dataset_keys:
        raise HTTPException(status_code=400, detail="At least one data source must be selected.")
    _validate_rule_group_sources(payload.definition.include_group, selected_sources=set(dataset_keys))
    _validate_rule_group_sources(payload.definition.exclude_group, selected_sources=set(dataset_keys))
    where_clauses.append(f"dataset_key IN ({', '.join(_sql_literal(item) for item in dataset_keys)})")

    options = payload.definition.options
    if options.include_finalized_only:
        where_clauses.append("COALESCE(is_finalized, FALSE) = TRUE")
    if not options.include_deobligations:
        where_clauses.append("COALESCE(is_deobligation, FALSE) = FALSE")
    if not options.include_negative_adjustments:
        where_clauses.append("COALESCE(obligation_amount, 0) >= 0")
    if not options.include_pass_through_records:
        where_clauses.append("COALESCE(is_pass_through, FALSE) = FALSE")

    include_sql = _compile_rule_group(
        payload.definition.include_group,
        selected_sources=set(dataset_keys),
        context="include",
    )
    exclude_sql = _compile_rule_group(
        payload.definition.exclude_group,
        selected_sources=set(dataset_keys),
        context="exclude",
    )
    if include_sql:
        where_clauses.append(include_sql)
    if exclude_sql:
        where_clauses.append(f"NOT ({exclude_sql})")

    where_sql = " AND ".join(where_clauses) if where_clauses else "TRUE"
    return (
        f"SELECT *\n"
        f"FROM {FUNDING_MODEL_BUILDER_BASE_VIEW}\n"
        f"WHERE {where_sql}"
    )


def generate_scoped_records_sql(payload: FundingModelDraftPayload) -> str:
    generated_sql = generate_visual_sql(payload)
    advanced_sql = None
    if payload.definition.advanced_sql_enabled:
        advanced_sql = validate_advanced_sql(payload.definition.advanced_sql_override)
    if not advanced_sql:
        return generated_sql
    return (
        "WITH base_records AS (\n"
        f"{_indent_sql(generated_sql)}\n"
        "), advanced_keys AS (\n"
        f"{_indent_sql(advanced_sql)}\n"
        ")\n"
        "SELECT base_records.*\n"
        "FROM base_records\n"
        "WHERE base_records.record_key IN (\n"
        "    SELECT record_key FROM advanced_keys\n"
        ")"
    )


def preview_warning_messages(payload: FundingModelDraftPayload, *, row_count: int) -> list[str]:
    warnings: list[str] = []
    if payload.definition.aggregation.default_fiscal_year is None:
        warnings.append("No default fiscal year is selected.")
    if payload.definition.options.include_negative_adjustments:
        warnings.append("Negative adjustments are included.")
    if not _has_rules(payload.definition.include_group) and not _has_rules(payload.definition.exclude_group):
        warnings.append("Include and exclude rules are both empty.")
    if payload.definition.advanced_sql_enabled and payload.definition.advanced_sql_override:
        warnings.append("Advanced SQL override is enabled.")
    if row_count and row_count < 10:
        warnings.append("Preview returned an unusually low record count.")
    if row_count > 1_000_000:
        warnings.append("Preview returned an unusually high record count.")
    return warnings


def _selected_dataset_keys(payload: FundingModelDraftPayload) -> list[str]:
    dataset_keys: list[str] = []
    data_sources = payload.definition.data_sources
    if data_sources.usaspending_awards:
        dataset_keys.append(DATA_SOURCE_USASPENDING_AWARDS)
    if data_sources.usaspending_subawards:
        dataset_keys.append(DATA_SOURCE_USASPENDING_SUBAWARDS)
    if data_sources.usaspending_assistance_transactions:
        dataset_keys.append(DATA_SOURCE_USASPENDING_ASSISTANCE_TRANSACTIONS)
    if data_sources.usaspending_contract_transactions:
        dataset_keys.append(DATA_SOURCE_USASPENDING_CONTRACT_TRANSACTIONS)
    if data_sources.taggs:
        dataset_keys.append(DATA_SOURCE_TAGGS)
    return dataset_keys


def _validate_rule_group_sources(group: RuleGroup, *, selected_sources: set[str]) -> None:
    for child in group.children:
        if isinstance(child, RuleGroup):
            _validate_rule_group_sources(child, selected_sources=selected_sources)
            continue
        field_meta = ALLOWED_RULE_FIELDS[child.field]
        applies_to_sources = set(field_meta.get("applies_to_sources") or ())
        if selected_sources.isdisjoint(applies_to_sources):
            required = ", ".join(sorted(applies_to_sources))
            raise HTTPException(
                status_code=400,
                detail=f"Field {child.field} requires at least one enabled source from: {required}",
            )


def _compile_rule_group(group: RuleGroup, *, selected_sources: set[str], context: str) -> str | None:
    fragments: list[str] = []
    for child in group.children:
        if isinstance(child, RuleGroup):
            compiled = _compile_rule_group(child, selected_sources=selected_sources, context=context)
            if compiled:
                fragments.append(f"({compiled})")
        else:
            fragments.append(_compile_rule(child, selected_sources=selected_sources, context=context))
    if not fragments:
        return None
    glue = " AND " if group.combinator == "ALL" else " OR "
    return glue.join(fragments)


def _compile_rule(rule: RuleCondition, *, selected_sources: set[str], context: str) -> str:
    field_meta = ALLOWED_RULE_FIELDS[rule.field]
    column = str(field_meta["column"])
    field_type = str(field_meta["type"])
    operator = rule.operator
    predicate = ""

    if operator in NO_VALUE_OPERATORS:
        predicate = f"{column} IS {'NOT ' if operator == 'is_not_null' else ''}NULL"
    elif field_type == "number":
        predicate = _compile_numeric_rule(column, operator, rule.value)
    elif field_type in {"date", "datetime"}:
        predicate = _compile_comparable_rule(column, operator, rule.value)
    elif field_type == "boolean":
        predicate = _compile_boolean_rule(column, operator, rule.value)
    else:
        predicate = _compile_text_rule(column, operator, rule.value)

    target_sources = set(field_meta.get("applies_to_sources") or ()) & selected_sources
    if not target_sources or target_sources == selected_sources:
        return predicate
    target_sql = ", ".join(_sql_literal(item) for item in sorted(target_sources))
    if context == "include":
        return f"(dataset_key NOT IN ({target_sql}) OR {predicate})"
    if context == "exclude":
        return f"(dataset_key IN ({target_sql}) AND {predicate})"
    raise HTTPException(status_code=400, detail=f"Unsupported rule compilation context: {context}")


def _compile_comparable_rule(column: str, operator: str, value: Any) -> str:
    if operator in SEQUENCE_OPERATORS:
        values = _coerce_sequence(value)
        rendered = ", ".join(_sql_literal(item) for item in values)
        comparator = "NOT IN" if operator == "not_in" else "IN"
        return f"{column} {comparator} ({rendered})"
    if operator == "equals":
        return f"{column} = {_sql_literal(value)}"
    if operator == "not_equals":
        return f"{column} <> {_sql_literal(value)}"
    if operator == "greater_than":
        return f"{column} > {_sql_literal(value)}"
    if operator == "less_than":
        return f"{column} < {_sql_literal(value)}"
    raise HTTPException(status_code=400, detail=f"Operator {operator} is not supported for comparable fields.")


def _compile_numeric_rule(column: str, operator: str, value: Any) -> str:
    return _compile_comparable_rule(column, operator, value)


def _compile_boolean_rule(column: str, operator: str, value: Any) -> str:
    if operator == "equals":
        return f"COALESCE({column}, FALSE) = {_sql_literal(bool(value))}"
    if operator == "not_equals":
        return f"COALESCE({column}, FALSE) <> {_sql_literal(bool(value))}"
    raise HTTPException(status_code=400, detail=f"Operator {operator} is not supported for boolean fields.")


def _compile_text_rule(column: str, operator: str, value: Any) -> str:
    normalized_column = f"LOWER(COALESCE({column}::text, ''))"
    if operator in SEQUENCE_OPERATORS:
        values = [str(item).strip().lower() for item in _coerce_sequence(value)]
        rendered = ", ".join(_sql_literal(item) for item in values)
        comparator = "NOT IN" if operator == "not_in" else "IN"
        return f"{normalized_column} {comparator} ({rendered})"
    if operator == "equals":
        return f"{normalized_column} = {_sql_literal(str(value).strip().lower())}"
    if operator == "not_equals":
        return f"{normalized_column} <> {_sql_literal(str(value).strip().lower())}"
    if operator in STRING_MATCH_OPERATORS:
        token = str(value).strip().lower()
        if operator == "contains":
            return f"{normalized_column} LIKE {_sql_literal(f'%{token}%')}"
        if operator == "not_contains":
            return f"{normalized_column} NOT LIKE {_sql_literal(f'%{token}%')}"
        if operator == "starts_with":
            return f"{normalized_column} LIKE {_sql_literal(f'{token}%')}"
        if operator == "ends_with":
            return f"{normalized_column} LIKE {_sql_literal(f'%{token}')}"
    raise HTTPException(status_code=400, detail=f"Operator {operator} is not supported for text fields.")


def _coerce_sequence(value: Any) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise HTTPException(status_code=400, detail="Sequence operators require a non-empty array value.")
    return value


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    text = str(value).replace("'", "''")
    return f"'{text}'"


def _has_rules(group: RuleGroup) -> bool:
    for child in group.children:
        if isinstance(child, RuleGroup) and _has_rules(child):
            return True
        if isinstance(child, RuleCondition):
            return True
    return False


def _indent_sql(sql: str) -> str:
    return "\n".join(f"    {line}" if line else "" for line in sql.splitlines())
