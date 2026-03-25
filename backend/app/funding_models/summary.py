from __future__ import annotations

from app.funding_models.schemas import FundingModelDraftPayload


def build_plain_language_summary(payload: FundingModelDraftPayload) -> str:
    sources: list[str] = []
    data_sources = payload.definition.data_sources
    if data_sources.usaspending_awards:
        sources.append("USAspending awards")
    if data_sources.usaspending_subawards:
        sources.append("USAspending subawards")
    if data_sources.usaspending_assistance_transactions:
        sources.append("USAspending assistance transactions")
    if data_sources.usaspending_contract_transactions:
        sources.append("USAspending contract transactions")
    if data_sources.taggs:
        sources.append("TAGGS")

    source_text = ", ".join(sources) if sources else "no enabled data sources"
    include_count = _count_rules(payload.definition.include_group)
    exclude_count = _count_rules(payload.definition.exclude_group)
    geography = payload.definition.aggregation.default_geography or "state"
    fiscal_year = payload.definition.aggregation.default_fiscal_year
    fiscal_year_text = f"for FY{fiscal_year}" if fiscal_year else "across the selected fiscal years"
    sql_text = " An advanced SQL narrowing layer is enabled." if payload.definition.advanced_sql_enabled else ""
    return (
        f"This model includes {source_text} {fiscal_year_text}, applies {include_count} include rules "
        f"and {exclude_count} exclude rules, and prepares {geography}-level outputs for preview and map display."
        f"{sql_text}"
    )


def _count_rules(group) -> int:
    count = 0
    for child in group.children:
        if hasattr(child, "children"):
            count += _count_rules(child)
        else:
            count += 1
    return count
