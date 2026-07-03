from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Connection, Engine

from app.db import DEFAULT_DB_URL
from app.db_fqtn import usaspending_fed_account_table
from app.db_schemas import USASPENDING_FED_ACCOUNT_SCHEMA
from app.usaspending_fed_account.models import ChipAccountClassification, FedAccountDimension

logger = logging.getLogger(__name__)

DEFAULT_CLASSIFICATION_VERSION = "chip_account_classification_v1"
DEFAULT_SOURCE = "rule_based_candidate"
SUPPORTED_YEARS = tuple(range(2020, 2027))
DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[3] / "data" / "usaspending" / "fed_account_data" / "outputs"
).resolve()

CDC_SCOPE_CATEGORY_VALUES = (
    "cdc_core",
    "cdc_transfer",
    "cdc_emergency",
    "cdc_business_support",
    "cdc_atdsr",
    "cdc_niosh",
    "non_cdc_hhs",
    "unknown_review",
)
FUNDING_SCOPE_VALUES = (
    "regular_appropriation",
    "emergency_supplemental",
    "pphf",
    "transfer",
    "mandatory",
    "business_support",
    "reimbursable",
    "unknown",
)
REVIEW_STATUS_VALUES = ("candidate", "needs_review", "reviewed", "rejected")
CONTROLLED_VALUE_SETS = {
    "cdc_scope_category": set(CDC_SCOPE_CATEGORY_VALUES),
    "funding_scope": set(FUNDING_SCOPE_VALUES),
    "review_status": set(REVIEW_STATUS_VALUES),
}

CDC_POSITIVE_SIGNALS = (
    "Centers for Disease Control and Prevention",
    "CDC",
    "Disease Control",
    "Public Health Preparedness",
    "Injury Prevention",
    "Chronic Disease",
    "Environmental Health",
    "Occupational Safety",
    "NIOSH",
    "National Institute for Occupational Safety and Health",
    "Toxic Substances and Disease Registry",
    "ATSDR",
    "Emerging and Zoonotic",
    "Global Health",
    "Immunization",
    "Birth Defects",
    "Developmental Disabilities",
    "Public Health Scientific Services",
)
NON_CDC_HHS_EXCLUSION_SIGNALS = (
    "Centers for Medicare",
    "Centers for Medicare & Medicaid",
    "Medicaid",
    "Medicare",
    "National Institutes of Health",
    "NIH",
    "Health Resources and Services Administration",
    "HRSA",
    "Substance Abuse and Mental Health Services Administration",
    "SAMHSA",
    "Food and Drug Administration",
    "FDA",
    "Administration for Children and Families",
    "ACF",
    "Indian Health Service",
    "IHS",
    "Administration for Strategic Preparedness and Response",
    "ASPR",
    "Public Health and Social Services Emergency Fund",
    "Provider Relief Fund",
    "Low Income Home Energy Assistance",
    "Child Care",
    "Temporary Assistance for Needy Families",
)
EMERGENCY_SIGNALS = (
    "COVID",
    "Coronavirus",
    "CARES",
    "American Rescue Plan",
    "ARP",
    "Emergency",
    "Supplemental",
    "Response Activities",
    "Public Health Emergency",
    "Pandemic",
)
PPHF_SIGNALS = ("Prevention and Public Health Fund", "PPHF")
TRANSFER_SIGNALS = ("transfer", "transfers", "transferred")
BUSINESS_SUPPORT_SIGNALS = (
    "Business Services Support",
    "Program Support Center",
    "Departmental Management",
    "Office of the Secretary",
    "Buildings and Facilities",
    "Rent",
    "Working Capital Fund",
)
NIOSH_SIGNALS = ("NIOSH", "National Institute for Occupational Safety and Health", "Occupational Safety")
ATSDR_SIGNALS = ("ATSDR", "Toxic Substances and Disease Registry")

IDENTITY_TEXT_FIELDS = (
    "federal_account_name",
    "account_title",
    "agency_name",
    "bureau_name",
    "normalized_account_key",
)
CONTEXT_TEXT_FIELDS = (
    "top_program_activities",
    "top_object_classes",
    "top_award_descriptions_sample",
    "top_assistance_listings",
    "top_naics_or_psc",
)
CONTEXT_OUTPUT_LIMITS = {
    "top_award_descriptions_sample": 5,
    "top_assistance_listings": 5,
    "top_naics_or_psc": 5,
}

RECONCILIATION_COLUMNS = (
    "balance_obligations",
    "award_obligations_total",
    "assistance_award_obligations",
    "contracts_award_obligations",
    "unlinked_award_obligations",
    "pa_oc_obligations_total",
    "balance_minus_awards",
    "balance_minus_pa_oc",
    "award_match_percent_of_balance",
    "pa_oc_match_percent_of_balance",
    "record_count_awards",
    "record_count_pa_oc",
)

CANDIDATE_EXPORT_COLUMNS = [
    "fiscal_year",
    "normalized_account_key",
    "federal_account_id",
    "federal_account_name",
    "account_title",
    "agency_name",
    "bureau_name",
    "balance_obligations",
    "award_obligations_total",
    "assistance_award_obligations",
    "contracts_award_obligations",
    "unlinked_award_obligations",
    "pa_oc_obligations_total",
    "balance_minus_awards",
    "balance_minus_pa_oc",
    "award_match_percent_of_balance",
    "pa_oc_match_percent_of_balance",
    "record_count_awards",
    "record_count_pa_oc",
    "top_program_activities",
    "top_object_classes",
    "top_award_descriptions_sample",
    "top_assistance_listings",
    "top_naics_or_psc",
    "is_cdc_related",
    "cdc_scope_category",
    "funding_scope",
    "include_in_chip_baseline",
    "include_in_chip_emergency",
    "include_in_chip_total",
    "include_in_public_map",
    "review_status",
    "confidence",
    "classification_reason",
    "notes",
    "source",
    "classification_version",
]

CLASSIFICATION_VALUE_FIELDS = (
    "is_cdc_related",
    "cdc_scope_category",
    "funding_scope",
    "include_in_chip_baseline",
    "include_in_chip_emergency",
    "include_in_chip_total",
    "include_in_public_map",
    "review_status",
    "confidence",
    "classification_reason",
    "notes",
    "source",
    "classification_version",
)
INGEST_REQUIRED_COLUMNS = (
    "fiscal_year",
    "normalized_account_key",
    "is_cdc_related",
    "cdc_scope_category",
    "funding_scope",
    "include_in_chip_baseline",
    "include_in_chip_emergency",
    "include_in_chip_total",
    "include_in_public_map",
    "review_status",
)

TRUE_TOKENS = {"1", "true", "t", "yes", "y"}
FALSE_TOKENS = {"0", "false", "f", "no", "n"}
NULL_TOKENS = {"", "na", "n/a", "none", "null", "nan"}
CLASSIFICATION_TABLE = ChipAccountClassification.__table__
DIM_ACCOUNT_TABLE = FedAccountDimension.__table__


@dataclass(frozen=True)
class CandidateExportSummary:
    output_path: Path
    rows_written: int


@dataclass(frozen=True)
class IngestClassificationSummary:
    rows_read: int
    rows_inserted: int
    rows_updated: int
    cdc_related_count: int
    baseline_included_count: int
    emergency_included_count: int
    public_map_included_count: int
    rejected_count: int
    needs_review_count: int
    dry_run: bool = False


@dataclass(frozen=True)
class ClassifiedExportSummary:
    detail_output_path: Path
    by_year_output_path: Path
    detail_rows_written: int
    by_year_rows_written: int


class ClassificationValidationError(ValueError):
    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        raw = " ".join(str(item) for item in value if item is not None)
    else:
        raw = str(value)
    raw = raw.replace("\ufeff", " ").replace("&", " and ")
    token = re.sub(r"[^A-Za-z0-9]+", " ", raw.lower())
    token = re.sub(r"\s+", " ", token)
    return token.strip()


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    token = re.sub(r"\s+", " ", str(value).replace("\ufeff", " ")).strip()
    if token.lower() in NULL_TOKENS:
        return None
    return token or None


def _row_text(row: Mapping[str, Any], fields: Iterable[str]) -> str:
    return normalize_text(" fieldbreak ".join(str(row.get(field) or "") for field in fields))


def _term_matches(normalized_haystack: str, signal: str) -> bool:
    normalized_signal = normalize_text(signal)
    if not normalized_signal:
        return False
    if " " not in normalized_signal or len(normalized_signal) <= 4:
        return re.search(rf"\b{re.escape(normalized_signal)}\b", normalized_haystack) is not None
    return normalized_signal in normalized_haystack


def _first_signal(normalized_haystack: str, signals: Iterable[str]) -> str | None:
    for signal in signals:
        if _term_matches(normalized_haystack, signal):
            return signal
    return None


def _has_allocation_transfer_agency(row: Mapping[str, Any]) -> bool:
    for field in ("allocation_transfer_agency_identifier", "allocation_transfer_agency", "ata"):
        value = normalize_text(row.get(field))
        if value and value not in {"0", "00", "000", "0000", "na", "none", "null"}:
            return True
    return False


def _classification_row(
    *,
    is_cdc_related: bool,
    cdc_scope_category: str,
    funding_scope: str,
    include_in_chip_baseline: bool,
    include_in_chip_emergency: bool,
    include_in_chip_total: bool,
    include_in_public_map: bool,
    review_status: str,
    confidence: Decimal,
    classification_reason: str,
    notes: str | None = None,
    source: str = DEFAULT_SOURCE,
    classification_version: str = DEFAULT_CLASSIFICATION_VERSION,
) -> dict[str, Any]:
    row = {
        "is_cdc_related": is_cdc_related,
        "cdc_scope_category": cdc_scope_category,
        "funding_scope": funding_scope,
        "include_in_chip_baseline": include_in_chip_baseline,
        "include_in_chip_emergency": include_in_chip_emergency,
        "include_in_chip_total": include_in_chip_total,
        "include_in_public_map": include_in_public_map,
        "review_status": review_status,
        "confidence": confidence,
        "classification_reason": classification_reason,
        "notes": notes,
        "source": source,
        "classification_version": classification_version,
    }
    validate_classification_controlled_values(row)
    return row


def _non_cdc_funding_scope(
    *,
    emergency_signal: str | None,
    pphf_signal: str | None,
    transfer_signal: str | None,
    business_signal: str | None,
) -> str:
    if emergency_signal:
        return "emergency_supplemental"
    if pphf_signal:
        return "pphf"
    if transfer_signal:
        return "transfer"
    if business_signal:
        return "business_support"
    return "unknown"


def classify_account_candidate(row: Mapping[str, Any]) -> dict[str, Any]:
    identity_text = _row_text(row, IDENTITY_TEXT_FIELDS)
    context_text = _row_text(row, CONTEXT_TEXT_FIELDS)
    full_text = normalize_text(f"{identity_text} {context_text}")

    cdc_signal = _first_signal(full_text, CDC_POSITIVE_SIGNALS)
    non_cdc_signal = _first_signal(identity_text, NON_CDC_HHS_EXCLUSION_SIGNALS)
    emergency_signal = _first_signal(full_text, EMERGENCY_SIGNALS)
    pphf_signal = _first_signal(full_text, PPHF_SIGNALS)
    transfer_signal = _first_signal(full_text, TRANSFER_SIGNALS)
    allocation_transfer_signal = _has_allocation_transfer_agency(row)
    business_signal = _first_signal(full_text, BUSINESS_SUPPORT_SIGNALS)
    niosh_signal = _first_signal(full_text, NIOSH_SIGNALS)
    atdsr_signal = _first_signal(full_text, ATSDR_SIGNALS)

    if non_cdc_signal and not cdc_signal:
        funding_scope = _non_cdc_funding_scope(
            emergency_signal=emergency_signal,
            pphf_signal=pphf_signal,
            transfer_signal=transfer_signal,
            business_signal=business_signal,
        )
        return _classification_row(
            is_cdc_related=False,
            cdc_scope_category="non_cdc_hhs",
            funding_scope=funding_scope,
            include_in_chip_baseline=False,
            include_in_chip_emergency=False,
            include_in_chip_total=False,
            include_in_public_map=False,
            review_status="candidate",
            confidence=Decimal("0.90"),
            classification_reason=(
                f"Matched non-CDC HHS exclusion signal '{non_cdc_signal}'; "
                "kept out of CHIP CDC scope."
            ),
        )

    if cdc_signal:
        if emergency_signal:
            return _classification_row(
                is_cdc_related=True,
                cdc_scope_category="cdc_emergency",
                funding_scope="emergency_supplemental",
                include_in_chip_baseline=False,
                include_in_chip_emergency=True,
                include_in_chip_total=True,
                include_in_public_map=False,
                review_status="candidate",
                confidence=Decimal("0.85"),
                classification_reason=(
                    f"Matched CDC signal '{cdc_signal}' and emergency/supplemental "
                    f"signal '{emergency_signal}'; classified as CDC emergency funding."
                ),
            )

        if pphf_signal:
            return _classification_row(
                is_cdc_related=True,
                cdc_scope_category="cdc_transfer",
                funding_scope="pphf",
                include_in_chip_baseline=False,
                include_in_chip_emergency=False,
                include_in_chip_total=True,
                include_in_public_map=False,
                review_status="candidate",
                confidence=Decimal("0.75"),
                classification_reason=(
                    f"Matched CDC signal '{cdc_signal}' and PPHF signal '{pphf_signal}'; "
                    "classified as CDC transfer/PPHF funding."
                ),
            )

        if transfer_signal or allocation_transfer_signal:
            signal_label = transfer_signal or "allocation transfer agency"
            return _classification_row(
                is_cdc_related=True,
                cdc_scope_category="cdc_transfer",
                funding_scope="transfer",
                include_in_chip_baseline=False,
                include_in_chip_emergency=False,
                include_in_chip_total=True,
                include_in_public_map=False,
                review_status="candidate",
                confidence=Decimal("0.75"),
                classification_reason=(
                    f"Matched CDC signal '{cdc_signal}' and transfer signal '{signal_label}'; "
                    "classified as CDC transfer funding."
                ),
            )

        if business_signal:
            return _classification_row(
                is_cdc_related=True,
                cdc_scope_category="cdc_business_support",
                funding_scope="business_support",
                include_in_chip_baseline=False,
                include_in_chip_emergency=False,
                include_in_chip_total=False,
                include_in_public_map=False,
                review_status="candidate",
                confidence=Decimal("0.75"),
                classification_reason=(
                    f"Matched CDC signal '{cdc_signal}' and business/admin signal "
                    f"'{business_signal}'; classified as CDC business support."
                ),
            )

        if atdsr_signal:
            cdc_scope_category = "cdc_atdsr"
            scope_reason = f"ATSDR signal '{atdsr_signal}'"
        elif niosh_signal:
            cdc_scope_category = "cdc_niosh"
            scope_reason = f"NIOSH signal '{niosh_signal}'"
        else:
            cdc_scope_category = "cdc_core"
            scope_reason = "no NIOSH/ATSDR-specific signal"

        return _classification_row(
            is_cdc_related=True,
            cdc_scope_category=cdc_scope_category,
            funding_scope="regular_appropriation",
            include_in_chip_baseline=True,
            include_in_chip_emergency=False,
            include_in_chip_total=True,
            include_in_public_map=True,
            review_status="candidate",
            confidence=Decimal("0.85"),
            classification_reason=(
                f"Matched CDC signal '{cdc_signal}' and {scope_reason}; "
                "classified as CDC core regular appropriation."
            ),
        )

    if business_signal:
        return _classification_row(
            is_cdc_related=False,
            cdc_scope_category="non_cdc_hhs",
            funding_scope="business_support",
            include_in_chip_baseline=False,
            include_in_chip_emergency=False,
            include_in_chip_total=False,
            include_in_public_map=False,
            review_status="candidate",
            confidence=Decimal("0.75"),
            classification_reason=(
                f"Matched business/admin signal '{business_signal}' without a CDC signal; "
                "classified as non-CDC HHS business support."
            ),
        )

    return _classification_row(
        is_cdc_related=False,
        cdc_scope_category="unknown_review",
        funding_scope="unknown",
        include_in_chip_baseline=False,
        include_in_chip_emergency=False,
        include_in_chip_total=False,
        include_in_public_map=False,
        review_status="needs_review",
        confidence=Decimal("0.35"),
        classification_reason="No clear CDC, non-CDC HHS, emergency, transfer, or admin rule matched.",
    )


def validate_controlled_value(field_name: str, value: Any) -> str:
    if field_name not in CONTROLLED_VALUE_SETS:
        raise ValueError(f"Unknown controlled value field: {field_name}")
    normalized = clean_text(value)
    allowed = CONTROLLED_VALUE_SETS[field_name]
    if normalized not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"Invalid {field_name} value {value!r}; allowed values are: {allowed_text}")
    return normalized


def validate_classification_controlled_values(row: Mapping[str, Any]) -> None:
    validate_controlled_value("cdc_scope_category", row.get("cdc_scope_category"))
    validate_controlled_value("funding_scope", row.get("funding_scope"))
    validate_controlled_value("review_status", row.get("review_status"))


def _years_label(years: Iterable[int]) -> str:
    selected = sorted(set(int(year) for year in years))
    if not selected:
        return "fy_all"
    if len(selected) == 1:
        return f"fy{selected[0]}"
    if selected == list(range(selected[0], selected[-1] + 1)):
        return f"fy{selected[0]}_{selected[-1]}"
    return "fy" + "_".join(str(year) for year in selected)


def _classification_version_suffix(classification_version: str) -> str:
    match = re.search(r"(v\d+)$", classification_version)
    if match:
        return match.group(1)
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", classification_version).strip("_").lower()
    return suffix or "version"


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    token = clean_text(value)
    if token is None:
        return None
    try:
        return Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None


def _format_amount_for_list(value: Any) -> str:
    amount = _decimal_or_none(value)
    if amount is None:
        return "$0.00"
    return f"${amount:,.2f}"


def _format_csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _truncate(value: Any, max_len: int = 180) -> str | None:
    token = clean_text(value)
    if token is None:
        return None
    if len(token) <= max_len:
        return token
    return token[: max_len - 3].rstrip() + "..."


def _format_ranked_item(value: Any, amount: Any = None) -> str | None:
    token = _truncate(value)
    if token is None:
        return None
    if amount is None:
        return token
    return f"{token} ({_format_amount_for_list(amount)})"


def _join_ranked_items(rows: Sequence[Mapping[str, Any]], *, max_items: int | None = None) -> str:
    values: list[str] = []
    seen: set[str] = set()
    for row in rows:
        key = normalize_text(row.get("value"))
        if key in seen:
            continue
        item = _format_ranked_item(row.get("value"), row.get("amount"))
        if item:
            seen.add(key)
            values.append(item)
        if max_items is not None and len(values) >= max_items:
            break
    return " | ".join(values)


def _fetch_grouped_top_values(
    conn: Connection,
    *,
    years: Sequence[int],
    table_name: str,
    value_expression: str,
    amount_expression: str,
    limit: int,
    extra_where: str = "",
) -> dict[tuple[int, int], list[dict[str, Any]]]:
    if limit <= 0:
        return {}
    sql = text(
        f"""
        WITH grouped AS (
            SELECT
                fiscal_year,
                federal_account_id,
                {value_expression} AS value,
                SUM({amount_expression}) AS amount
            FROM {usaspending_fed_account_table(table_name)}
            WHERE fiscal_year = ANY(:years)
              AND federal_account_id IS NOT NULL
              {extra_where}
            GROUP BY fiscal_year, federal_account_id, value
        ),
        ranked AS (
            SELECT
                fiscal_year,
                federal_account_id,
                value,
                amount,
                ROW_NUMBER() OVER (
                    PARTITION BY fiscal_year, federal_account_id
                    ORDER BY ABS(COALESCE(amount, 0)) DESC NULLS LAST, value
                ) AS row_number
            FROM grouped
            WHERE value IS NOT NULL AND BTRIM(value) <> ''
        )
        SELECT fiscal_year, federal_account_id, value, amount
        FROM ranked
        WHERE row_number <= :limit
        ORDER BY fiscal_year, federal_account_id, row_number
        """
    )
    output: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in conn.execute(sql, {"years": list(years), "limit": int(limit)}):
        key = (int(row.fiscal_year), int(row.federal_account_id))
        output.setdefault(key, []).append(dict(row._mapping))
    return output


def _fetch_top_award_values_for_accounts(
    conn: Connection,
    *,
    account_years: Sequence[tuple[int, int]],
    value_expression: str,
    where_sql: str,
    limit: int,
) -> dict[tuple[int, int], list[dict[str, Any]]]:
    pairs = sorted(set((int(fiscal_year), int(account_id)) for fiscal_year, account_id in account_years))
    if not pairs or limit <= 0:
        return {}

    params: dict[str, Any] = {"limit": int(limit)}
    values_sql_parts: list[str] = []
    for index, (fiscal_year, federal_account_id) in enumerate(pairs):
        fy_param = f"fy_{index}"
        account_param = f"account_{index}"
        values_sql_parts.append(f"(CAST(:{fy_param} AS integer), CAST(:{account_param} AS integer))")
        params[fy_param] = fiscal_year
        params[account_param] = federal_account_id

    values_sql = ", ".join(values_sql_parts)
    amount_expression = "COALESCE(award.obligation_amount, award.transaction_obligated_amount, 0)"
    sql = text(
        f"""
        WITH account_years(fiscal_year, federal_account_id) AS (
            VALUES {values_sql}
        )
        SELECT
            account_years.fiscal_year,
            account_years.federal_account_id,
            ranked.value,
            ranked.amount
        FROM account_years
        CROSS JOIN LATERAL (
            SELECT
                {value_expression} AS value,
                {amount_expression} AS amount
            FROM {usaspending_fed_account_table("fact_award_account_breakdown")} AS award
            WHERE award.fiscal_year = account_years.fiscal_year
              AND award.federal_account_id = account_years.federal_account_id
              {where_sql}
            ORDER BY award.id
            LIMIT :limit
        ) AS ranked
        WHERE ranked.value IS NOT NULL
          AND BTRIM(ranked.value) <> ''
        ORDER BY account_years.fiscal_year,
                 account_years.federal_account_id,
                 ABS(COALESCE(ranked.amount, 0)) DESC NULLS LAST,
                 ranked.value
        """
    )
    output: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in conn.execute(sql, params):
        key = (int(row.fiscal_year), int(row.federal_account_id))
        output.setdefault(key, []).append(dict(row._mapping))
    return output


def _fetch_context_maps(
    conn: Connection,
    *,
    years: Sequence[int],
    account_years: Sequence[tuple[int, int]],
    top_n_pa: int,
    top_n_oc: int,
) -> dict[str, dict[tuple[int, int], list[dict[str, Any]]]]:
    return {
        "top_program_activities": _fetch_grouped_top_values(
            conn,
            years=years,
            table_name="fact_account_pa_oc",
            value_expression="NULLIF(BTRIM(program_activity_name), '')",
            amount_expression="COALESCE(obligations_incurred_amount, 0)",
            limit=top_n_pa,
        ),
        "top_object_classes": _fetch_grouped_top_values(
            conn,
            years=years,
            table_name="fact_account_pa_oc",
            value_expression="NULLIF(BTRIM(object_class_name), '')",
            amount_expression="COALESCE(obligations_incurred_amount, 0)",
            limit=top_n_oc,
        ),
        "top_award_descriptions_sample": _fetch_top_award_values_for_accounts(
            conn,
            account_years=account_years,
            value_expression="NULLIF(BTRIM(award.award_description), '')",
            where_sql="AND award.award_description IS NOT NULL AND BTRIM(award.award_description) <> ''",
            limit=25,
        ),
        "top_assistance_listings": _fetch_top_award_values_for_accounts(
            conn,
            account_years=account_years,
            value_expression=(
                "NULLIF(BTRIM(CONCAT_WS(' ', award.assistance_listing_number, award.cfda_title)), '')"
            ),
            where_sql="AND (award.assistance_listing_number IS NOT NULL OR award.cfda_title IS NOT NULL)",
            limit=25,
        ),
        "top_naics_or_psc": _fetch_top_award_values_for_accounts(
            conn,
            account_years=account_years,
            value_expression=(
                "CASE "
                "WHEN award.naics_code IS NOT NULL OR award.naics_description IS NOT NULL "
                "THEN NULLIF(BTRIM(CONCAT_WS(' ', 'NAICS', award.naics_code, award.naics_description)), '') "
                "WHEN award.psc_code IS NOT NULL OR award.psc_description IS NOT NULL "
                "THEN NULLIF(BTRIM(CONCAT_WS(' ', 'PSC', award.psc_code, award.psc_description)), '') "
                "ELSE NULL END"
            ),
            where_sql=(
                "AND (award.naics_code IS NOT NULL OR award.naics_description IS NOT NULL "
                "OR award.psc_code IS NOT NULL OR award.psc_description IS NOT NULL)"
            ),
            limit=25,
        ),
    }


def _fetch_candidate_source_rows(
    conn: Connection,
    *,
    years: Sequence[int],
    classification_version: str,
    min_obligations: Decimal | None,
) -> list[dict[str, Any]]:
    min_sql = ""
    params: dict[str, Any] = {
        "years": list(years),
        "classification_version": classification_version,
    }
    if min_obligations is not None:
        min_sql = "AND ABS(COALESCE(reconciliation.balance_obligations, 0)) >= :min_obligations"
        params["min_obligations"] = min_obligations

    existing_selects = ", ".join(
        f"classification.{field} AS existing_{field}"
        for field in (
            "is_cdc_related",
            "cdc_scope_category",
            "funding_scope",
            "include_in_chip_baseline",
            "include_in_chip_emergency",
            "include_in_chip_total",
            "include_in_public_map",
            "review_status",
            "confidence",
            "classification_reason",
            "notes",
            "source",
            "classification_version",
        )
    )
    sql = text(
        f"""
        SELECT
            reconciliation.fiscal_year,
            reconciliation.normalized_account_key,
            reconciliation.federal_account_id,
            reconciliation.federal_account_name,
            dim.account_title,
            dim.agency_name,
            dim.bureau_name,
            dim.allocation_transfer_agency_identifier,
            reconciliation.balance_obligations,
            reconciliation.award_obligations_total,
            reconciliation.assistance_award_obligations,
            reconciliation.contracts_award_obligations,
            reconciliation.unlinked_award_obligations,
            reconciliation.pa_oc_obligations_total,
            reconciliation.balance_minus_awards,
            reconciliation.balance_minus_pa_oc,
            reconciliation.award_match_percent_of_balance,
            reconciliation.pa_oc_match_percent_of_balance,
            reconciliation.record_count_awards,
            reconciliation.record_count_pa_oc,
            classification.id AS existing_classification_id,
            {existing_selects}
        FROM {usaspending_fed_account_table("v_account_reconciliation")} AS reconciliation
        LEFT JOIN {usaspending_fed_account_table("dim_federal_account")} AS dim
            ON dim.id = reconciliation.federal_account_id
        LEFT JOIN {usaspending_fed_account_table("chip_account_classification")} AS classification
            ON classification.fiscal_year = reconciliation.fiscal_year
           AND classification.normalized_account_key = reconciliation.normalized_account_key
           AND classification.classification_version = :classification_version
        WHERE reconciliation.fiscal_year = ANY(:years)
          {min_sql}
        ORDER BY reconciliation.fiscal_year ASC,
                 reconciliation.balance_obligations DESC NULLS LAST,
                 reconciliation.normalized_account_key
        """
    )
    return [dict(row._mapping) for row in conn.execute(sql, params)]


def _existing_classification_from_row(row: Mapping[str, Any]) -> dict[str, Any] | None:
    if row.get("existing_classification_id") is None:
        return None
    return {
        field: row.get(f"existing_{field}")
        for field in CLASSIFICATION_VALUE_FIELDS
        if f"existing_{field}" in row
    }


def _build_candidate_csv_rows(
    source_rows: Sequence[Mapping[str, Any]],
    *,
    context_maps: Mapping[str, Mapping[tuple[int, int], Sequence[Mapping[str, Any]]]],
    classification_version: str,
    include_reviewed: bool,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for source_row in source_rows:
        row = dict(source_row)
        fiscal_year = int(row["fiscal_year"])
        federal_account_id = row.get("federal_account_id")
        context_key = (fiscal_year, int(federal_account_id)) if federal_account_id is not None else None

        for context_field in CONTEXT_TEXT_FIELDS:
            context_rows = context_maps.get(context_field, {}).get(context_key, []) if context_key else []
            row[context_field] = _join_ranked_items(
                context_rows,
                max_items=CONTEXT_OUTPUT_LIMITS.get(context_field),
            )

        existing = _existing_classification_from_row(row)
        if existing and existing.get("review_status") in {"reviewed", "rejected"} and not include_reviewed:
            continue

        classification = existing or classify_account_candidate(row)
        classification["classification_version"] = classification_version

        csv_row: dict[str, Any] = {
            "fiscal_year": row.get("fiscal_year"),
            "normalized_account_key": row.get("normalized_account_key"),
            "federal_account_id": row.get("federal_account_id"),
            "federal_account_name": row.get("federal_account_name"),
            "account_title": row.get("account_title"),
            "agency_name": row.get("agency_name"),
            "bureau_name": row.get("bureau_name"),
        }
        for column in RECONCILIATION_COLUMNS:
            csv_row[column] = row.get(column)
        for column in CONTEXT_TEXT_FIELDS:
            csv_row[column] = row.get(column)
        for column in CLASSIFICATION_VALUE_FIELDS:
            csv_row[column] = classification.get(column)
        output.append(csv_row)
    return output


def write_candidate_rows_to_csv(rows: Sequence[Mapping[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANDIDATE_EXPORT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _format_csv_value(row.get(column)) for column in CANDIDATE_EXPORT_COLUMNS})


def build_candidate_export(
    engine_or_conn: Engine | Connection,
    *,
    years: Iterable[int],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    classification_version: str = DEFAULT_CLASSIFICATION_VERSION,
    min_obligations: Decimal | None = None,
    include_reviewed: bool = False,
    top_n_pa: int = 5,
    top_n_oc: int = 5,
) -> CandidateExportSummary:
    selected_years = sorted(set(int(year) for year in years))
    if not selected_years:
        raise ValueError("At least one fiscal year is required.")
    output_path = (
        Path(output_dir)
        / f"chip_account_classification_candidates_{_years_label(selected_years)}_"
        f"{_classification_version_suffix(classification_version)}.csv"
    )

    def _build(conn: Connection) -> list[dict[str, Any]]:
        source_rows = _fetch_candidate_source_rows(
            conn,
            years=selected_years,
            classification_version=classification_version,
            min_obligations=min_obligations,
        )
        account_years = [
            (int(row["fiscal_year"]), int(row["federal_account_id"]))
            for row in source_rows
            if row.get("federal_account_id") is not None
        ]
        context_maps = _fetch_context_maps(
            conn,
            years=selected_years,
            account_years=account_years,
            top_n_pa=top_n_pa,
            top_n_oc=top_n_oc,
        )
        return _build_candidate_csv_rows(
            source_rows,
            context_maps=context_maps,
            classification_version=classification_version,
            include_reviewed=include_reviewed,
        )

    if isinstance(engine_or_conn, Engine):
        with engine_or_conn.connect() as conn:
            csv_rows = _build(conn)
    else:
        csv_rows = _build(engine_or_conn)

    write_candidate_rows_to_csv(csv_rows, output_path)
    logger.info("Wrote %s candidate classification rows to %s", len(csv_rows), output_path)
    return CandidateExportSummary(output_path=output_path, rows_written=len(csv_rows))


def _coerce_bool(value: Any, *, field_name: str, row_number: int) -> bool:
    if isinstance(value, bool):
        return value
    token = clean_text(value)
    if token is None:
        raise ValueError(f"row {row_number}: {field_name} is required and must be true/false.")
    normalized = token.lower()
    if normalized in TRUE_TOKENS:
        return True
    if normalized in FALSE_TOKENS:
        return False
    raise ValueError(
        f"row {row_number}: invalid boolean for {field_name}: {value!r}; "
        "use true/false, yes/no, or 1/0."
    )


def _coerce_int(value: Any, *, field_name: str, row_number: int, required: bool) -> int | None:
    token = clean_text(value)
    if token is None:
        if required:
            raise ValueError(f"row {row_number}: {field_name} is required.")
        return None
    try:
        return int(token)
    except ValueError as exc:
        raise ValueError(f"row {row_number}: invalid integer for {field_name}: {value!r}.") from exc


def _coerce_decimal(value: Any, *, field_name: str, row_number: int) -> Decimal | None:
    token = clean_text(value)
    if token is None:
        return None
    try:
        parsed = Decimal(token.replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError(f"row {row_number}: invalid decimal for {field_name}: {value!r}.") from exc
    if parsed < 0 or parsed > 1:
        raise ValueError(f"row {row_number}: {field_name} must be between 0 and 1.")
    return parsed


def _validate_required_columns(fieldnames: Sequence[str] | None) -> None:
    if not fieldnames:
        raise ClassificationValidationError(["Input CSV is missing a header row."])
    normalized = {field.strip() for field in fieldnames if field}
    missing = [field for field in INGEST_REQUIRED_COLUMNS if field not in normalized]
    if missing:
        raise ClassificationValidationError(
            [f"Input CSV is missing required column(s): {', '.join(missing)}"]
        )


def _parse_reviewed_csv_rows(
    input_path: Path,
    *,
    classification_version: str,
    allow_candidates: bool,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    parsed_rows: list[dict[str, Any]] = []
    seen_keys: set[tuple[int, str, str]] = set()
    candidate_status_count = 0
    needs_review_status_count = 0

    with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_required_columns(reader.fieldnames)
        for row_number, row in enumerate(reader, start=2):
            try:
                fiscal_year = _coerce_int(
                    row.get("fiscal_year"),
                    field_name="fiscal_year",
                    row_number=row_number,
                    required=True,
                )
                normalized_account_key = clean_text(row.get("normalized_account_key"))
                if normalized_account_key is None:
                    raise ValueError(f"row {row_number}: normalized_account_key is required.")

                row_version = clean_text(row.get("classification_version")) or classification_version
                if row_version != classification_version:
                    raise ValueError(
                        f"row {row_number}: classification_version {row_version!r} does not match "
                        f"CLI classification version {classification_version!r}."
                    )

                review_status = validate_controlled_value("review_status", row.get("review_status"))
                if review_status == "candidate":
                    candidate_status_count += 1
                elif review_status == "needs_review":
                    needs_review_status_count += 1

                parsed = {
                    "fiscal_year": fiscal_year,
                    "federal_account_id": _coerce_int(
                        row.get("federal_account_id"),
                        field_name="federal_account_id",
                        row_number=row_number,
                        required=False,
                    ),
                    "normalized_account_key": normalized_account_key,
                    "federal_account_name": clean_text(row.get("federal_account_name")),
                    "agency_name": clean_text(row.get("agency_name")),
                    "bureau_name": clean_text(row.get("bureau_name")),
                    "is_cdc_related": _coerce_bool(
                        row.get("is_cdc_related"),
                        field_name="is_cdc_related",
                        row_number=row_number,
                    ),
                    "cdc_scope_category": validate_controlled_value(
                        "cdc_scope_category",
                        row.get("cdc_scope_category"),
                    ),
                    "funding_scope": validate_controlled_value("funding_scope", row.get("funding_scope")),
                    "include_in_chip_baseline": _coerce_bool(
                        row.get("include_in_chip_baseline"),
                        field_name="include_in_chip_baseline",
                        row_number=row_number,
                    ),
                    "include_in_chip_emergency": _coerce_bool(
                        row.get("include_in_chip_emergency"),
                        field_name="include_in_chip_emergency",
                        row_number=row_number,
                    ),
                    "include_in_chip_total": _coerce_bool(
                        row.get("include_in_chip_total"),
                        field_name="include_in_chip_total",
                        row_number=row_number,
                    ),
                    "include_in_public_map": _coerce_bool(
                        row.get("include_in_public_map"),
                        field_name="include_in_public_map",
                        row_number=row_number,
                    ),
                    "review_status": review_status,
                    "confidence": _coerce_decimal(
                        row.get("confidence"),
                        field_name="confidence",
                        row_number=row_number,
                    ),
                    "classification_reason": clean_text(row.get("classification_reason")),
                    "notes": clean_text(row.get("notes")),
                    "source": clean_text(row.get("source")) or DEFAULT_SOURCE,
                    "classification_version": row_version,
                }
                unique_key = (int(fiscal_year), normalized_account_key, row_version)
                if unique_key in seen_keys:
                    raise ValueError(
                        f"row {row_number}: duplicate fiscal_year + normalized_account_key + "
                        "classification_version in input CSV."
                    )
                seen_keys.add(unique_key)
                parsed_rows.append(parsed)
            except ValueError as exc:
                errors.append(str(exc))

    if candidate_status_count:
        warnings.append(f"{candidate_status_count} row(s) still have review_status=candidate.")
        if not allow_candidates:
            errors.append(
                f"{candidate_status_count} row(s) have review_status=candidate; "
                "pass --allow-candidates to ingest candidate rows."
            )
    if needs_review_status_count:
        warnings.append(f"{needs_review_status_count} row(s) still have review_status=needs_review.")

    if errors:
        raise ClassificationValidationError(errors)
    return parsed_rows, warnings


def _attach_federal_account_ids(conn: Connection, rows: list[dict[str, Any]]) -> None:
    missing_keys = sorted(
        {
            row["normalized_account_key"]
            for row in rows
            if row.get("federal_account_id") is None and row.get("normalized_account_key")
        }
    )
    if not missing_keys:
        return
    result = conn.execute(
        select(DIM_ACCOUNT_TABLE.c.normalized_account_key, DIM_ACCOUNT_TABLE.c.id).where(
            DIM_ACCOUNT_TABLE.c.normalized_account_key.in_(missing_keys)
        )
    )
    account_ids = {str(row.normalized_account_key): int(row.id) for row in result}
    for row in rows:
        if row.get("federal_account_id") is None:
            row["federal_account_id"] = account_ids.get(str(row["normalized_account_key"]))


def _existing_classification_keys(
    conn: Connection,
    *,
    rows: Sequence[Mapping[str, Any]],
    classification_version: str,
) -> set[tuple[int, str]]:
    years = sorted({int(row["fiscal_year"]) for row in rows})
    if not years:
        return set()
    result = conn.execute(
        select(CLASSIFICATION_TABLE.c.fiscal_year, CLASSIFICATION_TABLE.c.normalized_account_key)
        .where(CLASSIFICATION_TABLE.c.classification_version == classification_version)
        .where(CLASSIFICATION_TABLE.c.fiscal_year.in_(years))
    )
    return {(int(row.fiscal_year), str(row.normalized_account_key)) for row in result}


def _upsert_classification_rows(
    conn: Connection,
    rows: Sequence[Mapping[str, Any]],
) -> None:
    if not rows:
        return
    insert_stmt = pg_insert(CLASSIFICATION_TABLE).values(list(rows))
    excluded = insert_stmt.excluded
    update_fields = [
        "federal_account_id",
        "federal_account_name",
        "agency_name",
        "bureau_name",
        "is_cdc_related",
        "cdc_scope_category",
        "funding_scope",
        "include_in_chip_baseline",
        "include_in_chip_emergency",
        "include_in_chip_total",
        "include_in_public_map",
        "review_status",
        "confidence",
        "classification_reason",
        "notes",
        "source",
    ]
    set_values = {field: getattr(excluded, field) for field in update_fields}
    set_values["updated_at"] = text("now()")
    stmt = insert_stmt.on_conflict_do_update(
        index_elements=[
            CLASSIFICATION_TABLE.c.fiscal_year,
            CLASSIFICATION_TABLE.c.normalized_account_key,
            CLASSIFICATION_TABLE.c.classification_version,
        ],
        set_=set_values,
    )
    conn.execute(stmt)


def _summarize_ingest(
    rows: Sequence[Mapping[str, Any]],
    *,
    rows_inserted: int,
    rows_updated: int,
    dry_run: bool,
) -> IngestClassificationSummary:
    return IngestClassificationSummary(
        rows_read=len(rows),
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
        cdc_related_count=sum(1 for row in rows if row.get("is_cdc_related")),
        baseline_included_count=sum(1 for row in rows if row.get("include_in_chip_baseline")),
        emergency_included_count=sum(1 for row in rows if row.get("include_in_chip_emergency")),
        public_map_included_count=sum(1 for row in rows if row.get("include_in_public_map")),
        rejected_count=sum(1 for row in rows if row.get("review_status") == "rejected"),
        needs_review_count=sum(1 for row in rows if row.get("review_status") == "needs_review"),
        dry_run=dry_run,
    )


def ingest_reviewed_classification(
    *,
    input_path: Path,
    db_url: str = DEFAULT_DB_URL,
    classification_version: str = DEFAULT_CLASSIFICATION_VERSION,
    dry_run: bool = False,
    replace_version: bool = False,
    allow_candidates: bool = False,
) -> IngestClassificationSummary:
    rows, warnings = _parse_reviewed_csv_rows(
        input_path,
        classification_version=classification_version,
        allow_candidates=allow_candidates,
    )
    for warning in warnings:
        logger.warning(warning)

    if dry_run:
        return _summarize_ingest(rows, rows_inserted=0, rows_updated=0, dry_run=True)

    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        with engine.begin() as conn:
            if replace_version:
                deleted = conn.execute(
                    CLASSIFICATION_TABLE.delete().where(
                        CLASSIFICATION_TABLE.c.classification_version == classification_version
                    )
                ).rowcount
                logger.info("Deleted %s existing classification rows for %s", deleted, classification_version)

            _attach_federal_account_ids(conn, rows)
            existing_keys = (
                set()
                if replace_version
                else _existing_classification_keys(
                    conn,
                    rows=rows,
                    classification_version=classification_version,
                )
            )
            rows_inserted = sum(
                1
                for row in rows
                if (int(row["fiscal_year"]), str(row["normalized_account_key"])) not in existing_keys
            )
            rows_updated = len(rows) - rows_inserted
            _upsert_classification_rows(conn, rows)
    finally:
        engine.dispose()

    return _summarize_ingest(
        rows,
        rows_inserted=rows_inserted,
        rows_updated=rows_updated,
        dry_run=False,
    )


def rebuild_classified_views_or_refresh_materialized_views(
    engine_or_conn: Engine | Connection | None = None,
) -> dict[str, list[str]]:
    if engine_or_conn is None:
        return {"refreshed": []}

    def _refresh(conn: Connection) -> dict[str, list[str]]:
        result = conn.execute(
            text(
                """
                SELECT matviewname
                FROM pg_matviews
                WHERE schemaname = :schema
                  AND matviewname LIKE 'mv_chip_cdc%'
                ORDER BY matviewname
                """
            ),
            {"schema": USASPENDING_FED_ACCOUNT_SCHEMA},
        )
        refreshed: list[str] = []
        for row in result:
            matview_name = str(row.matviewname)
            conn.execute(text(f"REFRESH MATERIALIZED VIEW {usaspending_fed_account_table(matview_name)}"))
            refreshed.append(matview_name)
        return {"refreshed": refreshed}

    if isinstance(engine_or_conn, Engine):
        with engine_or_conn.begin() as conn:
            return _refresh(conn)
    return _refresh(engine_or_conn)


def _write_query_rows_to_csv(
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: _format_csv_value(row.get(column)) for column in columns})


def export_classified_reconciliation(
    engine_or_conn: Engine | Connection,
    *,
    years: Iterable[int],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    classification_version: str = DEFAULT_CLASSIFICATION_VERSION,
) -> ClassifiedExportSummary:
    selected_years = sorted(set(int(year) for year in years))
    if not selected_years:
        raise ValueError("At least one fiscal year is required.")

    years_label = _years_label(selected_years)
    version_suffix = _classification_version_suffix(classification_version)
    detail_output_path = (
        Path(output_dir) / f"chip_classified_reconciliation_{years_label}_{version_suffix}.csv"
    )
    by_year_output_path = (
        Path(output_dir) / f"chip_classified_reconciliation_by_year_{years_label}_{version_suffix}.csv"
    )

    detail_sql = text(
        f"""
        SELECT *
        FROM {usaspending_fed_account_table("v_chip_account_classified_reconciliation")}
        WHERE fiscal_year = ANY(:years)
          AND classification_version = :classification_version
        ORDER BY fiscal_year ASC, balance_obligations DESC NULLS LAST, normalized_account_key
        """
    )
    by_year_sql = text(
        f"""
        SELECT *
        FROM {usaspending_fed_account_table("v_chip_cdc_funding_reconciliation_by_year")}
        WHERE fiscal_year = ANY(:years)
          AND classification_version = :classification_version
        ORDER BY fiscal_year ASC, classification_version
        """
    )

    def _fetch(conn: Connection, sql: Any) -> tuple[list[str], list[dict[str, Any]]]:
        result = conn.execute(
            sql,
            {"years": selected_years, "classification_version": classification_version},
        )
        columns = list(result.keys())
        rows = [dict(row._mapping) for row in result]
        return columns, rows

    if isinstance(engine_or_conn, Engine):
        with engine_or_conn.connect() as conn:
            detail_columns, detail_rows = _fetch(conn, detail_sql)
            by_year_columns, by_year_rows = _fetch(conn, by_year_sql)
    else:
        detail_columns, detail_rows = _fetch(engine_or_conn, detail_sql)
        by_year_columns, by_year_rows = _fetch(engine_or_conn, by_year_sql)

    _write_query_rows_to_csv(detail_rows, detail_columns, detail_output_path)
    _write_query_rows_to_csv(by_year_rows, by_year_columns, by_year_output_path)
    logger.info("Wrote %s classified reconciliation rows to %s", len(detail_rows), detail_output_path)
    logger.info("Wrote %s classified by-year rows to %s", len(by_year_rows), by_year_output_path)
    return ClassifiedExportSummary(
        detail_output_path=detail_output_path,
        by_year_output_path=by_year_output_path,
        detail_rows_written=len(detail_rows),
        by_year_rows_written=len(by_year_rows),
    )


def _print_ingest_summary(summary: IngestClassificationSummary) -> None:
    prefix = "Dry-run " if summary.dry_run else ""
    print(f"{prefix}CHIP account classification ingest summary")
    print(f"rows read: {summary.rows_read}")
    print(f"rows inserted: {summary.rows_inserted}")
    print(f"rows updated: {summary.rows_updated}")
    print(f"CDC-related count: {summary.cdc_related_count}")
    print(f"baseline included count: {summary.baseline_included_count}")
    print(f"emergency included count: {summary.emergency_included_count}")
    print(f"public map included count: {summary.public_map_included_count}")
    print(f"rejected count: {summary.rejected_count}")
    print(f"needs review count: {summary.needs_review_count}")
    if summary.dry_run:
        print("Dry run complete; no database writes performed.")


def parse_export_candidates_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export editable CHIP federal account classification candidates."
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or local development DSN).",
    )
    parser.add_argument("--years", nargs="*", type=int, default=list(SUPPORTED_YEARS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--classification-version", default=DEFAULT_CLASSIFICATION_VERSION)
    parser.add_argument("--min-obligations", default=None)
    parser.add_argument("--include-reviewed", action="store_true", default=False)
    parser.add_argument("--top-n-pa", type=int, default=5)
    parser.add_argument("--top-n-oc", type=int, default=5)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser.parse_args(argv)


def main_export_candidates(argv: list[str] | None = None) -> None:
    args = parse_export_candidates_args(argv)
    configure_logging(args.log_level)
    min_obligations = _decimal_or_none(args.min_obligations)
    if args.min_obligations is not None and min_obligations is None:
        raise SystemExit(f"Invalid --min-obligations value: {args.min_obligations!r}")
    engine = create_engine(args.db_url, pool_pre_ping=True)
    try:
        summary = build_candidate_export(
            engine,
            years=args.years,
            output_dir=Path(args.output_dir).expanduser().resolve(),
            classification_version=args.classification_version,
            min_obligations=min_obligations,
            include_reviewed=args.include_reviewed,
            top_n_pa=args.top_n_pa,
            top_n_oc=args.top_n_oc,
        )
    finally:
        engine.dispose()
    print(f"Wrote {summary.rows_written} candidate row(s) to {summary.output_path}")


def parse_ingest_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest reviewed CHIP account classification CSV.")
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or local development DSN).",
    )
    parser.add_argument("--input", required=True, help="Path to the reviewed classification CSV.")
    parser.add_argument("--classification-version", default=DEFAULT_CLASSIFICATION_VERSION)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace-version", action="store_true")
    parser.add_argument("--allow-candidates", action="store_true")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser.parse_args(argv)


def main_ingest(argv: list[str] | None = None) -> None:
    args = parse_ingest_args(argv)
    configure_logging(args.log_level)
    try:
        summary = ingest_reviewed_classification(
            input_path=Path(args.input).expanduser().resolve(),
            db_url=args.db_url,
            classification_version=args.classification_version,
            dry_run=args.dry_run,
            replace_version=args.replace_version,
            allow_candidates=args.allow_candidates,
        )
    except ClassificationValidationError as exc:
        print("Reviewed classification CSV validation failed:", file=sys.stderr)
        for error in exc.errors:
            print(f"- {error}", file=sys.stderr)
        raise SystemExit(2) from exc
    _print_ingest_summary(summary)


def parse_export_classified_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export classified CHIP reconciliation CSVs.")
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or local development DSN).",
    )
    parser.add_argument("--years", nargs="*", type=int, default=list(SUPPORTED_YEARS))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--classification-version", default=DEFAULT_CLASSIFICATION_VERSION)
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return parser.parse_args(argv)


def main_export_classified(argv: list[str] | None = None) -> None:
    args = parse_export_classified_args(argv)
    configure_logging(args.log_level)
    engine = create_engine(args.db_url, pool_pre_ping=True)
    try:
        summary = export_classified_reconciliation(
            engine,
            years=args.years,
            output_dir=Path(args.output_dir).expanduser().resolve(),
            classification_version=args.classification_version,
        )
    finally:
        engine.dispose()
    print(f"Wrote {summary.detail_rows_written} classified row(s) to {summary.detail_output_path}")
    print(f"Wrote {summary.by_year_rows_written} by-year row(s) to {summary.by_year_output_path}")


def verify_classification_workflow(
    *,
    db_url: str = DEFAULT_DB_URL,
    years: Iterable[int] = SUPPORTED_YEARS,
    classification_version: str = DEFAULT_CLASSIFICATION_VERSION,
    skip_db: bool = False,
) -> None:
    examples = [
        (
            {
                "federal_account_name": "CDC-wide Activities and Program Support",
                "bureau_name": "Centers for Disease Control and Prevention",
            },
            "cdc_core",
        ),
        (
            {
                "federal_account_name": "Centers for Medicare and Medicaid Services",
                "bureau_name": "Centers for Medicare & Medicaid Services",
            },
            "non_cdc_hhs",
        ),
        (
            {
                "federal_account_name": "CDC COVID-19 Response Activities",
                "bureau_name": "Centers for Disease Control and Prevention",
            },
            "cdc_emergency",
        ),
        (
            {
                "federal_account_name": "CDC Prevention and Public Health Fund",
                "bureau_name": "Centers for Disease Control and Prevention",
            },
            "cdc_transfer",
        ),
    ]
    for row, expected_scope in examples:
        classified = classify_account_candidate(row)
        if classified["cdc_scope_category"] != expected_scope:
            raise RuntimeError(
                f"Classifier verification failed for {row}: "
                f"expected {expected_scope}, got {classified['cdc_scope_category']}"
            )
    print("Classifier verification checks passed.")

    if skip_db:
        return

    selected_years = sorted(set(int(year) for year in years))
    engine = create_engine(db_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            detail_count = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*) AS row_count
                    FROM {usaspending_fed_account_table("v_chip_account_classified_reconciliation")}
                    WHERE fiscal_year = ANY(:years)
                      AND classification_version = :classification_version
                    """
                ),
                {"years": selected_years, "classification_version": classification_version},
            ).scalar_one()
            by_year_count = conn.execute(
                text(
                    f"""
                    SELECT COUNT(*) AS row_count
                    FROM {usaspending_fed_account_table("v_chip_cdc_funding_reconciliation_by_year")}
                    WHERE fiscal_year = ANY(:years)
                      AND classification_version = :classification_version
                    """
                ),
                {"years": selected_years, "classification_version": classification_version},
            ).scalar_one()
    finally:
        engine.dispose()
    if detail_count == 0 or by_year_count == 0:
        raise RuntimeError(
            "Classified views returned no rows. Run migration, export candidates, ingest reviewed "
            "classification rows, then verify again."
        )
    print(
        f"Classified views returned {detail_count} detail row(s) and {by_year_count} by-year row(s)."
    )


def parse_verify_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify CHIP account classification workflow.")
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or local development DSN).",
    )
    parser.add_argument("--years", nargs="*", type=int, default=list(SUPPORTED_YEARS))
    parser.add_argument("--classification-version", default=DEFAULT_CLASSIFICATION_VERSION)
    parser.add_argument("--skip-db", action="store_true")
    return parser.parse_args(argv)


def main_verify(argv: list[str] | None = None) -> None:
    args = parse_verify_args(argv)
    verify_classification_workflow(
        db_url=args.db_url,
        years=args.years,
        classification_version=args.classification_version,
        skip_db=args.skip_db,
    )
