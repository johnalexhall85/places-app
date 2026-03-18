from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import create_engine, text

from app.db import DEFAULT_DB_URL
from app.db_fqtn import recon_table
from app.recon.diagnostics import (
    build_funding_scope_refinement_summary_payload,
    build_fy2021_mixed_program_transfer_review_payload,
    build_fy2021_residual_diagnostics_payload,
    build_mixed_program_transfer_exception_recommendations_payload,
    write_json as write_diagnostics_json,
)
from app.recon.models import (
    NormalizedStateFunding,
    ProfileReconciliationDriverBreakdown,
    ProfileReconciliationStateYear,
    ProfileReconciliationSummary,
)
from app.recon.profile_scope import METHODOLOGY_VERSION as PROFILE_SCOPE_LOGIC_VERSION
from app.recon.review_overlay import (
    DEFAULT_FY2021_MANUAL_REVIEW_CROSSWALK_PATH,
    DEFAULT_MANUAL_REVIEW_EXCEPTION_CANDIDATES_CSV_PATH,
    DEFAULT_MANUAL_REVIEW_EXCEPTION_CANDIDATES_PATH,
    DEFAULT_METHODOLOGY_DISPLAY_SUMMARY_PATH,
    MANUAL_REVIEW_CANDIDATE_FIELDS,
    build_manual_review_crosswalk_payload,
    build_manual_review_exception_candidate_rows,
    build_methodology_display_summary_payload,
    replace_manual_review_exception_overlay_rows,
    write_csv as write_review_overlay_csv,
    write_json as write_review_overlay_json,
)

METHODOLOGY_VERSION = "profile_scope_v5_verified_csv_multi_account_fy2021_diagnostics_calibration_v1"
NORMALIZATION_METHOD = "funding_scope_reconstruction_calibration_layer"
NORMALIZED_AMOUNT_TYPE_OBSERVED = "observed_cdc_profile_aligned"
NORMALIZED_AMOUNT_TYPE_ESTIMATED = "estimated_cdc_profile_aligned"

SOURCE_USASPENDING = "usaspending"
SOURCE_TAGGS = "taggs"
SOURCE_ALL = "all"

OBSERVED_CALIBRATION_YEARS = (2020, 2021, 2022, 2023)
ESTIMATED_YEARS = (2024, 2025, 2026)
DEFAULT_FISCAL_YEARS = (*OBSERVED_CALIBRATION_YEARS, *ESTIMATED_YEARS)

SUPPORT_VIEW_CDC = recon_table("profile_calibration_cdc_reference")
SUPPORT_VIEW_USASPENDING = recon_table("profile_calibration_usaspending_state_year_support")
SUPPORT_VIEW_TAGGS = recon_table("profile_calibration_taggs_state_year_support")

STATE_YEAR_TABLE = ProfileReconciliationStateYear.__table__
DRIVER_TABLE = ProfileReconciliationDriverBreakdown.__table__
SUMMARY_TABLE = ProfileReconciliationSummary.__table__
NORMALIZED_TABLE = NormalizedStateFunding.__table__

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUMMARY_PATH = REPO_ROOT / "data" / "recon" / "profile_calibration_summary.json"
DEFAULT_FY2021_DIAGNOSTICS_PATH = REPO_ROOT / "data" / "recon" / "fy2021_residual_diagnostics.json"
DEFAULT_FY2021_MIXED_PROGRAM_TRANSFER_REVIEW_PATH = (
    REPO_ROOT / "data" / "recon" / "fy2021_mixed_program_transfer_review.json"
)
DEFAULT_FUNDING_SCOPE_REFINEMENT_SUMMARY_PATH = REPO_ROOT / "data" / "recon" / "funding_scope_refinement_summary.json"
DEFAULT_MIXED_PROGRAM_TRANSFER_EXCEPTION_RECOMMENDATIONS_PATH = (
    REPO_ROOT / "data" / "recon" / "mixed_program_transfer_exception_recommendations.json"
)
DEFAULT_VERIFIED_ACCOUNT_SUMMARY_PATH = REPO_ROOT / "data" / "recon" / "verified_account_mapping_summary.json"
DEFAULT_BEFORE_SNAPSHOT_PATH = REPO_ROOT / "data" / "recon" / "_funding_scope_refinement_before_snapshot.json"
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

STATE_NAME_TO_CODE = {
    "alabama": "AL",
    "alaska": "AK",
    "american samoa": "AS",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "district of columbia": "DC",
    "federated states of micronesia": "FM",
    "florida": "FL",
    "georgia": "GA",
    "guam": "GU",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "marshall islands": "MH",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "northern mariana islands": "MP",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "palau": "PW",
    "pennsylvania": "PA",
    "puerto rico": "PR",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "united states virgin islands": "VI",
    "u.s. virgin islands": "VI",
    "utah": "UT",
    "vermont": "VT",
    "virgin islands": "VI",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}
STATE_CODE_TO_NAME = {code: name.title() for name, code in STATE_NAME_TO_CODE.items()}

DRIVER_FIELDS = (
    ("regular_appropriation", "regular_appropriation_amount", "included"),
    ("covid_emergency", "covid_emergency_amount", "included"),
    ("arpa", "arpa_amount", "included"),
    ("other_emergency_or_disaster", "other_emergency_or_disaster_amount", "included"),
    ("non_covid_supplemental", "non_covid_supplemental_amount", "included"),
    ("transfer_or_special", "transfer_or_special_amount", "included"),
    ("procurement_support_stream", "procurement_support_amount", "included"),
    ("unknown_stream", "unknown_stream_included_amount", "included"),
    ("unknown_stream", "unknown_stream_excluded_amount", "excluded"),
    ("unknown_stream", "unknown_stream_uncertain_amount", "uncertain"),
    ("excluded_non_domestic", "excluded_non_domestic_amount", "excluded"),
    ("excluded_contracts", "excluded_contract_amount", "excluded"),
    ("uncertain_rows", "uncertain_amount", "uncertain"),
    ("core_public_health", "core_public_health_amount", "included"),
    ("core_public_health", "core_public_health_excluded_amount", "excluded"),
    ("core_public_health", "core_public_health_uncertain_amount", "uncertain"),
    ("emergency_public_health", "emergency_public_health_amount", "included"),
    ("emergency_public_health", "emergency_public_health_excluded_amount", "excluded"),
    ("emergency_public_health", "emergency_public_health_uncertain_amount", "uncertain"),
    ("federal_health_transfer", "federal_health_transfer_amount", "included"),
    ("federal_health_transfer", "federal_health_transfer_excluded_amount", "excluded"),
    ("federal_health_transfer", "federal_health_transfer_uncertain_amount", "uncertain"),
    ("procurement_support", "procurement_support_scope_amount", "included"),
    ("procurement_support", "procurement_support_scope_excluded_amount", "excluded"),
    ("procurement_support", "procurement_support_scope_uncertain_amount", "uncertain"),
    ("special_transfer", "special_transfer_amount", "included"),
    ("special_transfer", "special_transfer_excluded_amount", "excluded"),
    ("special_transfer", "special_transfer_uncertain_amount", "uncertain"),
    ("other_public_health", "other_public_health_amount", "included"),
    ("other_public_health", "other_public_health_excluded_amount", "excluded"),
    ("other_public_health", "other_public_health_uncertain_amount", "uncertain"),
    ("biomedical_research", "biomedical_research_amount", "included"),
    ("biomedical_research", "biomedical_research_excluded_amount", "excluded"),
    ("biomedical_research", "biomedical_research_uncertain_amount", "uncertain"),
    ("international_health_assistance", "international_health_assistance_amount", "included"),
    (
        "international_health_assistance",
        "international_health_assistance_excluded_amount",
        "excluded",
    ),
    (
        "international_health_assistance",
        "international_health_assistance_uncertain_amount",
        "uncertain",
    ),
    ("unknown", "unknown_funding_scope_amount", "included"),
    ("unknown", "unknown_funding_scope_excluded_amount", "excluded"),
    ("unknown", "unknown_funding_scope_uncertain_amount", "uncertain"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the CDC Funding Profiles calibration and reconciliation layer for CHIP.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--fiscal-years",
        type=int,
        nargs="+",
        default=list(DEFAULT_FISCAL_YEARS),
        help="Fiscal years to process for normalized output (default: 2020-2026).",
    )
    parser.add_argument(
        "--source-system",
        choices=(SOURCE_USASPENDING, SOURCE_TAGGS, SOURCE_ALL),
        default=SOURCE_USASPENDING,
        help="Primary source system to build (default: usaspending).",
    )
    parser.add_argument(
        "--include-taggs",
        action="store_true",
        help="Also build TAGGS reconciliation and normalized rows when support tables are populated.",
    )
    parser.add_argument(
        "--rebuild-normalized-table",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refresh recon.normalized_state_funding rows for the selected years (default: true).",
    )
    parser.add_argument(
        "--export-summary",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write the JSON build summary to disk (default: true).",
    )
    parser.add_argument(
        "--summary-path",
        default=str(DEFAULT_SUMMARY_PATH),
        help="Output path for the calibration summary JSON.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build payloads without writing database rows.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the summary payload after the build completes.",
    )
    return parser.parse_args()


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    return token or None


def _normalize_state_code(value: Any) -> str | None:
    token = _clean_text(value)
    if token is None:
        return None
    normalized = token.upper()
    if STATE_CODE_RE.fullmatch(normalized):
        return normalized
    return STATE_NAME_TO_CODE.get(token.lower())


def _to_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize_money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _quantize_pct(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def _serialize_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _serialize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_json_value(item) for item in value]
    return value


def _table_or_view_exists(connection: Any, fqtn: str) -> bool:
    row = connection.execute(
        text("SELECT to_regclass(:name) AS exists"),
        {"name": fqtn},
    ).mappings().one()
    return row["exists"] is not None


def _table_columns(connection: Any, fqtn: str) -> set[str]:
    if "." not in fqtn:
        return set()
    schema_name, table_name = fqtn.split(".", 1)
    rows = connection.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema_name
              AND table_name = :table_name
            """
        ),
        {
            "schema_name": schema_name,
            "table_name": table_name,
        },
    ).mappings().all()
    return {str(row["column_name"]).strip() for row in rows if row.get("column_name")}


def _require_objects(connection: Any, object_names: Sequence[str]) -> None:
    missing = [name for name in object_names if not _table_or_view_exists(connection, name)]
    if missing:
        raise RuntimeError(
            "Required calibration objects are missing: "
            + ", ".join(missing)
            + ". Run Alembic migrations and build the profile-scope layer first."
        )


def _require_columns(connection: Any, *, fqtn: str, expected_columns: Sequence[str]) -> None:
    actual_columns = _table_columns(connection, fqtn)
    missing_columns = [column for column in expected_columns if column not in actual_columns]
    if missing_columns:
        raise RuntimeError(
            f"{fqtn} is missing expected columns: {', '.join(missing_columns)}. "
            "The calibration layer migration is not fully applied. Run `alembic upgrade head` before rebuilding."
        )


def _fetch_rows(connection: Any, fqtn: str, fiscal_years: Sequence[int]) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            f"""
            SELECT *
            FROM {fqtn}
            WHERE fiscal_year = ANY(:fiscal_years)
            ORDER BY fiscal_year, state_code
            """
        ),
        {"fiscal_years": list(fiscal_years)},
    ).mappings().all()
    return [dict(row) for row in rows]


def build_cdc_profile_reference_map(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[int, str], dict[str, Any]]:
    reference_map: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        fiscal_year = row.get("fiscal_year")
        state_code = _normalize_state_code(row.get("state_code"))
        if fiscal_year is None or state_code is None:
            continue
        reference_map[(int(fiscal_year), state_code)] = {
            "fiscal_year": int(fiscal_year),
            "state_code": state_code,
            "state_name": _clean_text(row.get("state_name")),
            "cdc_profile_amount": _quantize_money(_to_decimal(row.get("cdc_profile_amount") or row.get("amount"))),
            "row_count": int(row.get("row_count") or 0),
        }
    return reference_map


def build_support_map(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[int, str], dict[str, Any]]:
    support_map: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        fiscal_year = row.get("fiscal_year")
        state_code = _normalize_state_code(row.get("state_code"))
        if fiscal_year is None or state_code is None:
            continue
        normalized_row = {
            "source_system": _clean_text(row.get("source_system")),
            "fiscal_year": int(fiscal_year),
            "state_code": state_code,
            "raw_reconstructed_amount": _quantize_money(_to_decimal(row.get("raw_reconstructed_amount"))),
            "reconstructed_profile_scope_amount": (
                None
                if row.get("reconstructed_profile_scope_amount") is None
                else _quantize_money(_to_decimal(row.get("reconstructed_profile_scope_amount")))
            ),
            "regular_appropriation_amount": _quantize_money(_to_decimal(row.get("regular_appropriation_amount"))),
            "covid_emergency_amount": _quantize_money(_to_decimal(row.get("covid_emergency_amount"))),
            "arpa_amount": _quantize_money(_to_decimal(row.get("arpa_amount"))),
            "other_emergency_or_disaster_amount": _quantize_money(
                _to_decimal(row.get("other_emergency_or_disaster_amount"))
            ),
            "non_covid_supplemental_amount": _quantize_money(_to_decimal(row.get("non_covid_supplemental_amount"))),
            "transfer_or_special_amount": _quantize_money(_to_decimal(row.get("transfer_or_special_amount"))),
            "procurement_support_amount": _quantize_money(_to_decimal(row.get("procurement_support_amount"))),
            "unknown_stream_amount": _quantize_money(_to_decimal(row.get("unknown_stream_amount"))),
            "unknown_stream_included_amount": _quantize_money(_to_decimal(row.get("unknown_stream_included_amount"))),
            "unknown_stream_excluded_amount": _quantize_money(_to_decimal(row.get("unknown_stream_excluded_amount"))),
            "unknown_stream_uncertain_amount": _quantize_money(_to_decimal(row.get("unknown_stream_uncertain_amount"))),
            "core_public_health_amount": _quantize_money(_to_decimal(row.get("core_public_health_amount"))),
            "core_public_health_excluded_amount": _quantize_money(_to_decimal(row.get("core_public_health_excluded_amount"))),
            "core_public_health_uncertain_amount": _quantize_money(_to_decimal(row.get("core_public_health_uncertain_amount"))),
            "emergency_public_health_amount": _quantize_money(_to_decimal(row.get("emergency_public_health_amount"))),
            "emergency_public_health_excluded_amount": _quantize_money(_to_decimal(row.get("emergency_public_health_excluded_amount"))),
            "emergency_public_health_uncertain_amount": _quantize_money(_to_decimal(row.get("emergency_public_health_uncertain_amount"))),
            "federal_health_transfer_amount": _quantize_money(_to_decimal(row.get("federal_health_transfer_amount"))),
            "federal_health_transfer_excluded_amount": _quantize_money(_to_decimal(row.get("federal_health_transfer_excluded_amount"))),
            "federal_health_transfer_uncertain_amount": _quantize_money(_to_decimal(row.get("federal_health_transfer_uncertain_amount"))),
            "procurement_support_scope_amount": _quantize_money(_to_decimal(row.get("procurement_support_scope_amount"))),
            "procurement_support_scope_excluded_amount": _quantize_money(_to_decimal(row.get("procurement_support_scope_excluded_amount"))),
            "procurement_support_scope_uncertain_amount": _quantize_money(_to_decimal(row.get("procurement_support_scope_uncertain_amount"))),
            "special_transfer_amount": _quantize_money(_to_decimal(row.get("special_transfer_amount"))),
            "special_transfer_excluded_amount": _quantize_money(_to_decimal(row.get("special_transfer_excluded_amount"))),
            "special_transfer_uncertain_amount": _quantize_money(_to_decimal(row.get("special_transfer_uncertain_amount"))),
            "other_public_health_amount": _quantize_money(_to_decimal(row.get("other_public_health_amount"))),
            "other_public_health_excluded_amount": _quantize_money(
                _to_decimal(row.get("other_public_health_excluded_amount"))
            ),
            "other_public_health_uncertain_amount": _quantize_money(
                _to_decimal(row.get("other_public_health_uncertain_amount"))
            ),
            "biomedical_research_amount": _quantize_money(_to_decimal(row.get("biomedical_research_amount"))),
            "biomedical_research_excluded_amount": _quantize_money(
                _to_decimal(row.get("biomedical_research_excluded_amount"))
            ),
            "biomedical_research_uncertain_amount": _quantize_money(
                _to_decimal(row.get("biomedical_research_uncertain_amount"))
            ),
            "international_health_assistance_amount": _quantize_money(
                _to_decimal(row.get("international_health_assistance_amount"))
            ),
            "international_health_assistance_excluded_amount": _quantize_money(
                _to_decimal(row.get("international_health_assistance_excluded_amount"))
            ),
            "international_health_assistance_uncertain_amount": _quantize_money(
                _to_decimal(row.get("international_health_assistance_uncertain_amount"))
            ),
            "unknown_funding_scope_amount": _quantize_money(_to_decimal(row.get("unknown_funding_scope_amount"))),
            "unknown_funding_scope_excluded_amount": _quantize_money(_to_decimal(row.get("unknown_funding_scope_excluded_amount"))),
            "unknown_funding_scope_uncertain_amount": _quantize_money(_to_decimal(row.get("unknown_funding_scope_uncertain_amount"))),
            "transaction_count": int(row.get("transaction_count") or 0),
            "included_transaction_count": int(row.get("included_transaction_count") or 0),
            "excluded_transaction_count": int(row.get("excluded_transaction_count") or 0),
            "uncertain_transaction_count": int(row.get("uncertain_transaction_count") or 0),
            "uncertain_amount": _quantize_money(_to_decimal(row.get("uncertain_amount"))),
            "excluded_non_domestic_amount": _quantize_money(_to_decimal(row.get("excluded_non_domestic_amount"))),
            "excluded_contract_amount": _quantize_money(_to_decimal(row.get("excluded_contract_amount"))),
            "methodology_version": _clean_text(row.get("methodology_version")),
            "refreshed_at": row.get("refreshed_at"),
        }
        support_map[(int(fiscal_year), state_code)] = normalized_row
    return support_map


def _residual_pct(cdc_profile_amount: Decimal | None, residual_amount: Decimal | None) -> Decimal | None:
    if cdc_profile_amount is None or residual_amount is None or cdc_profile_amount == 0:
        return None
    return _quantize_pct(residual_amount / cdc_profile_amount)


def determine_calibration_status(
    *,
    cdc_profile_amount: Decimal | None,
    reconstructed_profile_scope_amount: Decimal | None,
    raw_reconstructed_amount: Decimal | None,
    residual_pct: Decimal | None,
) -> str:
    if cdc_profile_amount is None or reconstructed_profile_scope_amount is None:
        return "sparse"
    if max(abs(cdc_profile_amount), abs(reconstructed_profile_scope_amount), abs(raw_reconstructed_amount or Decimal("0"))) < Decimal("100"):
        return "sparse"
    if residual_pct is None:
        return "sparse"
    if abs(residual_pct) <= Decimal("0.020000"):
        return "exact_window"
    if abs(residual_pct) <= Decimal("0.100000"):
        return "calibrated"
    return "needs_review"


def determine_confidence_label(
    *,
    calibration_status: str,
    raw_reconstructed_amount: Decimal | None,
    unknown_stream_amount: Decimal | None,
    uncertain_amount: Decimal | None,
    transaction_count: int,
    included_transaction_count: int,
) -> str:
    if calibration_status == "sparse" or transaction_count <= 0:
        return "low"

    raw_total = raw_reconstructed_amount or Decimal("0")
    unknown_share = (unknown_stream_amount or Decimal("0")) / raw_total if raw_total > 0 else Decimal("1")
    uncertain_share = (uncertain_amount or Decimal("0")) / raw_total if raw_total > 0 else Decimal("1")
    included_share = (
        Decimal(included_transaction_count) / Decimal(transaction_count)
        if transaction_count > 0
        else Decimal("0")
    )

    score = 0
    if calibration_status == "exact_window":
        score += 2
    elif calibration_status == "calibrated":
        score += 1

    if unknown_share <= Decimal("0.05"):
        score += 1
    elif unknown_share > Decimal("0.15"):
        score -= 1

    if uncertain_share <= Decimal("0.05"):
        score += 1
    elif uncertain_share > Decimal("0.15"):
        score -= 1

    if included_share >= Decimal("0.80"):
        score += 1
    elif included_share < Decimal("0.50"):
        score -= 1

    if score >= 4:
        return "high"
    if score >= 2:
        return "medium"
    return "low"


def build_state_year_notes(
    *,
    source_system: str,
    calibration_status: str,
    residual_pct: Decimal | None,
    unknown_stream_amount: Decimal | None,
    uncertain_amount: Decimal | None,
    raw_reconstructed_amount: Decimal | None,
    reconstructed_profile_scope_amount: Decimal | None,
) -> str | None:
    if reconstructed_profile_scope_amount is None:
        if source_system == SOURCE_TAGGS:
            return (
                "TAGGS raw statewide totals are present, but a compatible TAGGS profile-scope rollup is not available in this build."
            )
        return "Observed CDC profile reference exists, but no reconstructed profile-scope total was available for comparison."

    parts: list[str] = []
    if calibration_status == "needs_review" and residual_pct is not None:
        parts.append(f"Residual exceeds the default review window at {format(abs(residual_pct), '.2%')}.")
    raw_total = raw_reconstructed_amount or Decimal("0")
    if raw_total > 0 and (unknown_stream_amount or Decimal("0")) / raw_total > Decimal("0.15"):
        parts.append("Unknown-stream exposure is large relative to the reconstructed total.")
    if raw_total > 0 and (uncertain_amount or Decimal("0")) / raw_total > Decimal("0.15"):
        parts.append("A meaningful share of rows remain uncertain under the profile-scope rules.")
    return " ".join(parts) or None


def build_reconciliation_rows(
    *,
    source_system: str,
    fiscal_years: Sequence[int],
    cdc_reference_map: Mapping[tuple[int, str], Mapping[str, Any]],
    support_map: Mapping[tuple[int, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    observed_years = {year for year in fiscal_years if year in OBSERVED_CALIBRATION_YEARS}
    keys = {
        key
        for key in set(cdc_reference_map) | set(support_map)
        if key[0] in observed_years
    }
    rows: list[dict[str, Any]] = []
    refreshed_at = datetime.now(timezone.utc)
    for fiscal_year, state_code in sorted(keys):
        reference = cdc_reference_map.get((fiscal_year, state_code), {})
        support = support_map.get((fiscal_year, state_code), {})

        cdc_profile_amount = reference.get("cdc_profile_amount")
        reconstructed_profile_scope_amount = support.get("reconstructed_profile_scope_amount")
        raw_reconstructed_amount = support.get("raw_reconstructed_amount")
        residual_amount = (
            None
            if cdc_profile_amount is None or reconstructed_profile_scope_amount is None
            else _quantize_money(cdc_profile_amount - reconstructed_profile_scope_amount)
        )
        residual_pct = _residual_pct(cdc_profile_amount, residual_amount)
        abs_residual_amount = None if residual_amount is None else _quantize_money(abs(residual_amount))
        calibration_status = determine_calibration_status(
            cdc_profile_amount=cdc_profile_amount,
            reconstructed_profile_scope_amount=reconstructed_profile_scope_amount,
            raw_reconstructed_amount=raw_reconstructed_amount,
            residual_pct=residual_pct,
        )
        confidence_label = determine_confidence_label(
            calibration_status=calibration_status,
            raw_reconstructed_amount=raw_reconstructed_amount,
            unknown_stream_amount=support.get("unknown_stream_amount"),
            uncertain_amount=support.get("uncertain_amount"),
            transaction_count=int(support.get("transaction_count") or 0),
            included_transaction_count=int(support.get("included_transaction_count") or 0),
        )

        rows.append(
            {
                "fiscal_year": fiscal_year,
                "state_code": state_code,
                "source_system": source_system,
                "cdc_profile_amount": cdc_profile_amount,
                "reconstructed_profile_scope_amount": reconstructed_profile_scope_amount,
                "raw_reconstructed_amount": raw_reconstructed_amount,
                "residual_amount": residual_amount,
                "residual_pct": residual_pct,
                "abs_residual_amount": abs_residual_amount,
                "regular_appropriation_amount": support.get("regular_appropriation_amount"),
                "covid_emergency_amount": support.get("covid_emergency_amount"),
                "arpa_amount": support.get("arpa_amount"),
                "other_emergency_or_disaster_amount": support.get("other_emergency_or_disaster_amount"),
                "non_covid_supplemental_amount": support.get("non_covid_supplemental_amount"),
                "transfer_or_special_amount": support.get("transfer_or_special_amount"),
                "procurement_support_amount": support.get("procurement_support_amount"),
                "unknown_stream_amount": support.get("unknown_stream_amount"),
                "unknown_stream_included_amount": support.get("unknown_stream_included_amount"),
                "core_public_health_amount": support.get("core_public_health_amount"),
                "emergency_public_health_amount": support.get("emergency_public_health_amount"),
                "federal_health_transfer_amount": support.get("federal_health_transfer_amount"),
                "procurement_support_scope_amount": support.get("procurement_support_scope_amount"),
                "special_transfer_amount": support.get("special_transfer_amount"),
                "other_public_health_amount": support.get("other_public_health_amount"),
                "biomedical_research_amount": support.get("biomedical_research_amount"),
                "international_health_assistance_amount": support.get("international_health_assistance_amount"),
                "unknown_funding_scope_amount": support.get("unknown_funding_scope_amount"),
                "excluded_non_domestic_amount": support.get("excluded_non_domestic_amount"),
                "excluded_contract_amount": support.get("excluded_contract_amount"),
                "uncertain_amount": support.get("uncertain_amount"),
                "included_transaction_count": int(support.get("included_transaction_count") or 0),
                "excluded_transaction_count": int(support.get("excluded_transaction_count") or 0),
                "uncertain_transaction_count": int(support.get("uncertain_transaction_count") or 0),
                "calibration_status": calibration_status,
                "confidence_label": confidence_label,
                "methodology_version": METHODOLOGY_VERSION,
                "notes": build_state_year_notes(
                    source_system=source_system,
                    calibration_status=calibration_status,
                    residual_pct=residual_pct,
                    unknown_stream_amount=support.get("unknown_stream_amount"),
                    uncertain_amount=support.get("uncertain_amount"),
                    raw_reconstructed_amount=raw_reconstructed_amount,
                    reconstructed_profile_scope_amount=reconstructed_profile_scope_amount,
                ),
                "refreshed_at": refreshed_at,
            }
        )
    return rows


def build_driver_breakdown_rows(
    *,
    source_system: str,
    fiscal_years: Sequence[int],
    support_map: Mapping[tuple[int, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    observed_years = {year for year in fiscal_years if year in OBSERVED_CALIBRATION_YEARS}
    refreshed_at = datetime.now(timezone.utc)
    for fiscal_year, state_code in sorted(key for key in support_map if key[0] in observed_years):
        support = support_map[(fiscal_year, state_code)]
        for driver_name, field_name, inclusion_status in DRIVER_FIELDS:
            amount = support.get(field_name)
            if amount is None or amount == 0:
                continue
            rows.append(
                {
                    "fiscal_year": fiscal_year,
                    "state_code": state_code,
                    "source_system": source_system,
                    "driver_name": driver_name,
                    "inclusion_status": inclusion_status,
                    "driver_amount": amount,
                    "methodology_version": METHODOLOGY_VERSION,
                    "refreshed_at": refreshed_at,
                }
            )
    return rows


def build_normalized_state_funding_rows(
    *,
    source_system: str,
    fiscal_years: Sequence[int],
    cdc_reference_map: Mapping[tuple[int, str], Mapping[str, Any]],
    support_map: Mapping[tuple[int, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    keys = {
        key
        for key in set(support_map) | {
            reference_key
            for reference_key in cdc_reference_map
            if reference_key[0] in fiscal_years
        }
        if key[0] in fiscal_years
    }
    rows: list[dict[str, Any]] = []
    refreshed_at = datetime.now(timezone.utc)
    for fiscal_year, state_code in sorted(keys):
        support = support_map.get((fiscal_year, state_code), {})
        reference = cdc_reference_map.get((fiscal_year, state_code), {})
        normalized_amount = support.get("reconstructed_profile_scope_amount")
        if source_system == SOURCE_TAGGS and normalized_amount is None:
            continue

        raw_amount = support.get("raw_reconstructed_amount") or Decimal("0.00")
        cdc_profile_reference_amount = reference.get("cdc_profile_amount")
        residual_amount = (
            None
            if cdc_profile_reference_amount is None or normalized_amount is None
            else _quantize_money(cdc_profile_reference_amount - normalized_amount)
        )
        residual_pct = _residual_pct(cdc_profile_reference_amount, residual_amount)

        if fiscal_year in OBSERVED_CALIBRATION_YEARS:
            normalized_amount_type = NORMALIZED_AMOUNT_TYPE_OBSERVED
            if source_system == SOURCE_USASPENDING:
                confidence_note = (
                    "Observed CDC Funding Profiles FY2020-FY2023 are used as calibration references. "
                    "The normalized amount remains the reconstructed profile-scope total, not a copied CDC profile total."
                )
                calibration_basis = (
                    "Observed CDC Funding Profiles FY2020-FY2023 are used only to benchmark the reconstructed public-data total."
                )
            else:
                confidence_note = (
                    "TAGGS profile-scope values are derived from existing TAGGS funding-stream scope rules and benchmarked against observed CDC Funding Profiles when both are available."
                )
                calibration_basis = (
                    "Observed CDC Funding Profiles FY2020-FY2023 are benchmark references; TAGGS normalized totals remain derived TAGGS profile-scope rollups."
                )
        else:
            normalized_amount_type = NORMALIZED_AMOUNT_TYPE_ESTIMATED
            confidence_note = (
                "No official CDC Funding Profiles state total exists for this year. The normalized amount is a funding-scope-aware profile-scope estimate using the same reconstruction framework."
            )
            calibration_basis = (
                "No observed CDC Funding Profiles total is available for this year; later-year values remain profile-aligned estimates."
            )

        rows.append(
            {
                "source_system": source_system,
                "fiscal_year": fiscal_year,
                "state_code": state_code,
                "raw_amount": raw_amount,
                "normalized_amount": normalized_amount or Decimal("0.00"),
                "normalized_amount_type": normalized_amount_type,
                "normalization_method": NORMALIZATION_METHOD,
                "funding_stream_logic_version": PROFILE_SCOPE_LOGIC_VERSION,
                "cdc_profile_reference_amount": cdc_profile_reference_amount,
                "residual_amount": residual_amount,
                "residual_pct": residual_pct,
                "core_public_health_amount": support.get("core_public_health_amount"),
                "emergency_public_health_amount": support.get("emergency_public_health_amount"),
                "federal_health_transfer_amount": support.get("federal_health_transfer_amount"),
                "procurement_support_scope_amount": support.get("procurement_support_scope_amount"),
                "special_transfer_amount": support.get("special_transfer_amount"),
                "other_public_health_amount": support.get("other_public_health_amount"),
                "biomedical_research_amount": support.get("biomedical_research_amount"),
                "international_health_assistance_amount": support.get("international_health_assistance_amount"),
                "unknown_funding_scope_amount": support.get("unknown_funding_scope_amount"),
                "funding_scope_components_json": _serialize_json_value(
                    {
                        "core_public_health": support.get("core_public_health_amount"),
                        "emergency_public_health": support.get("emergency_public_health_amount"),
                        "federal_health_transfer": support.get("federal_health_transfer_amount"),
                        "procurement_support": support.get("procurement_support_scope_amount"),
                        "special_transfer": support.get("special_transfer_amount"),
                        "other_public_health": support.get("other_public_health_amount"),
                        "biomedical_research": support.get("biomedical_research_amount"),
                        "international_health_assistance": support.get("international_health_assistance_amount"),
                        "unknown": support.get("unknown_funding_scope_amount"),
                    }
                ),
                "methodology_version": METHODOLOGY_VERSION,
                "confidence_note": confidence_note,
                "calibration_basis": calibration_basis,
                "refreshed_at": refreshed_at,
            }
        )
    return rows


def _median(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal("2")


def build_reconciliation_summary_rows(
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        fiscal_year = row.get("fiscal_year")
        source_system = _clean_text(row.get("source_system"))
        if fiscal_year is None or source_system is None:
            continue
        grouped[(int(fiscal_year), source_system)].append(row)

    summary_rows: list[dict[str, Any]] = []
    refreshed_at = datetime.now(timezone.utc)
    for (fiscal_year, source_system), group_rows in sorted(grouped.items()):
        abs_pct_values = [
            abs(_to_decimal(row.get("residual_pct")))
            for row in group_rows
            if row.get("residual_pct") is not None
        ]
        avg_abs = (
            _quantize_pct(sum(abs_pct_values, Decimal("0")) / Decimal(len(abs_pct_values)))
            if abs_pct_values
            else None
        )
        median_abs = _quantize_pct(_median(abs_pct_values)) if abs_pct_values else None
        max_abs = _quantize_pct(max(abs_pct_values)) if abs_pct_values else None
        summary_rows.append(
            {
                "fiscal_year": fiscal_year,
                "source_system": source_system,
                "state_count": len(group_rows),
                "avg_abs_residual_pct": avg_abs,
                "median_abs_residual_pct": median_abs,
                "max_abs_residual_pct": max_abs,
                "exact_window_state_count": sum(1 for row in group_rows if row.get("calibration_status") == "exact_window"),
                "calibrated_state_count": sum(1 for row in group_rows if row.get("calibration_status") == "calibrated"),
                "needs_review_state_count": sum(1 for row in group_rows if row.get("calibration_status") == "needs_review"),
                "sparse_state_count": sum(1 for row in group_rows if row.get("calibration_status") == "sparse"),
                "total_unknown_stream_amount": _quantize_money(
                    sum((_to_decimal(row.get("unknown_stream_amount")) for row in group_rows), Decimal("0"))
                ),
                "total_uncertain_amount": _quantize_money(
                    sum((_to_decimal(row.get("uncertain_amount")) for row in group_rows), Decimal("0"))
                ),
                "methodology_version": METHODOLOGY_VERSION,
                "refreshed_at": refreshed_at,
            }
        )
    return summary_rows


def build_export_summary(
    *,
    fiscal_years: Sequence[int],
    source_systems: Sequence[str],
    reconciliation_rows: Sequence[Mapping[str, Any]],
    summary_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    summary_lookup = {
        (int(row["fiscal_year"]), str(row["source_system"])): row
        for row in summary_rows
    }
    needs_review_rows = sorted(
        (
            row
            for row in reconciliation_rows
            if row.get("calibration_status") == "needs_review"
        ),
        key=lambda item: abs(_to_decimal(item.get("residual_amount"))),
        reverse=True,
    )
    over_rows = sorted(
        (
            row
            for row in reconciliation_rows
            if row.get("residual_amount") is not None and _to_decimal(row.get("residual_amount")) > 0
        ),
        key=lambda item: _to_decimal(item.get("residual_amount")),
        reverse=True,
    )
    under_rows = sorted(
        (
            row
            for row in reconciliation_rows
            if row.get("residual_amount") is not None and _to_decimal(row.get("residual_amount")) < 0
        ),
        key=lambda item: _to_decimal(item.get("residual_amount")),
    )

    residual_stats_by_year: dict[str, dict[str, Any]] = {}
    unknown_by_year: dict[str, dict[str, Any]] = {}
    funding_scope_component_totals_by_year: dict[str, dict[str, Any]] = {}
    for fiscal_year in sorted({row.get("fiscal_year") for row in summary_rows if row.get("fiscal_year") is not None}):
        per_source: dict[str, Any] = {}
        per_source_unknown: dict[str, Any] = {}
        per_source_components: dict[str, Any] = {}
        for source_system in sorted({str(row.get("source_system")) for row in summary_rows if row.get("source_system")}):
            summary_row = summary_lookup.get((int(fiscal_year), source_system))
            if summary_row is None:
                continue
            per_source[source_system] = {
                "avg_abs_residual_pct": summary_row.get("avg_abs_residual_pct"),
                "median_abs_residual_pct": summary_row.get("median_abs_residual_pct"),
                "max_abs_residual_pct": summary_row.get("max_abs_residual_pct"),
                "state_count": summary_row.get("state_count"),
                "needs_review_state_count": summary_row.get("needs_review_state_count"),
            }
            per_source_unknown[source_system] = summary_row.get("total_unknown_stream_amount")
            component_rows = [
                row
                for row in reconciliation_rows
                if int(row.get("fiscal_year") or 0) == int(fiscal_year)
                and str(row.get("source_system") or "") == source_system
            ]
            per_source_components[source_system] = {
                "core_public_health": _quantize_money(
                    sum((_to_decimal(row.get("core_public_health_amount")) for row in component_rows), Decimal("0"))
                ),
                "emergency_public_health": _quantize_money(
                    sum((_to_decimal(row.get("emergency_public_health_amount")) for row in component_rows), Decimal("0"))
                ),
                "federal_health_transfer": _quantize_money(
                    sum((_to_decimal(row.get("federal_health_transfer_amount")) for row in component_rows), Decimal("0"))
                ),
                "procurement_support": _quantize_money(
                    sum((_to_decimal(row.get("procurement_support_scope_amount")) for row in component_rows), Decimal("0"))
                ),
                "special_transfer": _quantize_money(
                    sum((_to_decimal(row.get("special_transfer_amount")) for row in component_rows), Decimal("0"))
                ),
                "other_public_health": _quantize_money(
                    sum((_to_decimal(row.get("other_public_health_amount")) for row in component_rows), Decimal("0"))
                ),
                "biomedical_research": _quantize_money(
                    sum((_to_decimal(row.get("biomedical_research_amount")) for row in component_rows), Decimal("0"))
                ),
                "international_health_assistance": _quantize_money(
                    sum(
                        (_to_decimal(row.get("international_health_assistance_amount")) for row in component_rows),
                        Decimal("0"),
                    )
                ),
                "unknown": _quantize_money(
                    sum((_to_decimal(row.get("unknown_funding_scope_amount")) for row in component_rows), Decimal("0"))
                ),
            }
        residual_stats_by_year[str(fiscal_year)] = per_source
        unknown_by_year[str(fiscal_year)] = per_source_unknown
        funding_scope_component_totals_by_year[str(fiscal_year)] = per_source_components

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "fiscal_years_processed": sorted({int(year) for year in fiscal_years}),
        "source_systems_processed": list(source_systems),
        "state_count": len(reconciliation_rows),
        "residual_stats_by_year": residual_stats_by_year,
        "states_needing_review": [
            {
                "source_system": row.get("source_system"),
                "fiscal_year": row.get("fiscal_year"),
                "state_code": row.get("state_code"),
                "residual_amount": row.get("residual_amount"),
                "residual_pct": row.get("residual_pct"),
                "confidence_label": row.get("confidence_label"),
            }
            for row in needs_review_rows[:20]
        ],
        "biggest_over_states": [
            {
                "source_system": row.get("source_system"),
                "fiscal_year": row.get("fiscal_year"),
                "state_code": row.get("state_code"),
                "residual_amount": row.get("residual_amount"),
                "residual_pct": row.get("residual_pct"),
            }
            for row in over_rows[:10]
        ],
        "biggest_under_states": [
            {
                "source_system": row.get("source_system"),
                "fiscal_year": row.get("fiscal_year"),
                "state_code": row.get("state_code"),
                "residual_amount": row.get("residual_amount"),
                "residual_pct": row.get("residual_pct"),
            }
            for row in under_rows[:10]
        ],
        "total_unknown_stream_amounts": unknown_by_year,
        "funding_scope_component_totals_by_year": funding_scope_component_totals_by_year,
        "methodology_version": METHODOLOGY_VERSION,
    }


def _insert_rows(connection: Any, table: Any, rows: Sequence[Mapping[str, Any]], *, chunk_size: int = 2000) -> None:
    if not rows:
        return
    for start in range(0, len(rows), chunk_size):
        connection.execute(table.insert(), list(rows[start : start + chunk_size]))


def _validate_state_codes(rows: Sequence[Mapping[str, Any]], *, label: str) -> None:
    invalid_rows = []
    for row in rows:
        state_code = _clean_text(row.get("state_code"))
        if state_code is None:
            invalid_rows.append((row.get("fiscal_year"), state_code, row.get("source_system")))
            continue
        if not STATE_CODE_RE.fullmatch(state_code):
            invalid_rows.append((row.get("fiscal_year"), state_code, row.get("source_system")))
    if invalid_rows:
        sample = ", ".join(
            f"{source_system or 'unknown'} FY{fiscal_year}:{state_code!r}"
            for fiscal_year, state_code, source_system in invalid_rows[:10]
        )
        raise RuntimeError(
            f"{label} contains invalid state_code values that are not two-letter postal codes. Sample: {sample}"
        )


def _delete_selected_rows(
    connection: Any,
    *,
    table_name: str,
    fiscal_years: Sequence[int],
    source_systems: Sequence[str] | None = None,
) -> None:
    if not fiscal_years:
        return
    params: dict[str, Any] = {"fiscal_years": list(fiscal_years)}
    where_sql = "fiscal_year = ANY(:fiscal_years)"
    if source_systems is not None:
        params["source_systems"] = list(source_systems)
        where_sql += " AND source_system = ANY(:source_systems)"
    connection.execute(text(f"DELETE FROM {table_name} WHERE {where_sql}"), params)


def write_summary_file(path: str | Path, payload: Mapping[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_serialize_json_value(dict(payload)), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _resolve_requested_sources(
    *,
    source_system: str,
    include_taggs: bool,
) -> list[str]:
    if source_system == SOURCE_ALL:
        return [SOURCE_USASPENDING, SOURCE_TAGGS]
    if source_system == SOURCE_TAGGS:
        return [SOURCE_TAGGS]
    if include_taggs:
        return [SOURCE_USASPENDING, SOURCE_TAGGS]
    return [SOURCE_USASPENDING]


def rebuild(
    *,
    db_url: str,
    fiscal_years: Sequence[int] = DEFAULT_FISCAL_YEARS,
    source_system: str = SOURCE_USASPENDING,
    include_taggs: bool = False,
    rebuild_normalized_table: bool = True,
    export_summary: bool = True,
    summary_path: str | Path = DEFAULT_SUMMARY_PATH,
    dry_run: bool = False,
) -> dict[str, Any]:
    selected_fiscal_years = sorted({int(year) for year in fiscal_years})
    requested_sources = _resolve_requested_sources(source_system=source_system, include_taggs=include_taggs)
    observed_fiscal_years = [year for year in selected_fiscal_years if year in OBSERVED_CALIBRATION_YEARS]

    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.begin() as connection:
        _require_objects(
            connection,
            [
                SUPPORT_VIEW_CDC,
                SUPPORT_VIEW_USASPENDING,
                recon_table("profile_reconciliation_state_year"),
                recon_table("profile_reconciliation_driver_breakdown"),
                recon_table("profile_reconciliation_summary"),
                recon_table("normalized_state_funding"),
            ],
        )
        _require_columns(
            connection,
            fqtn=recon_table("profile_reconciliation_state_year"),
            expected_columns=(
                "fiscal_year",
                "state_code",
                "source_system",
                "cdc_profile_amount",
                "reconstructed_profile_scope_amount",
                "raw_reconstructed_amount",
                "residual_amount",
                "residual_pct",
                "abs_residual_amount",
                "regular_appropriation_amount",
                "covid_emergency_amount",
                "arpa_amount",
                "other_emergency_or_disaster_amount",
                "non_covid_supplemental_amount",
                "transfer_or_special_amount",
                "procurement_support_amount",
                "unknown_stream_amount",
                "unknown_stream_included_amount",
                "core_public_health_amount",
                "emergency_public_health_amount",
                "federal_health_transfer_amount",
                "procurement_support_scope_amount",
                "special_transfer_amount",
                "other_public_health_amount",
                "biomedical_research_amount",
                "international_health_assistance_amount",
                "unknown_funding_scope_amount",
                "excluded_non_domestic_amount",
                "excluded_contract_amount",
                "uncertain_amount",
                "included_transaction_count",
                "excluded_transaction_count",
                "uncertain_transaction_count",
                "calibration_status",
                "confidence_label",
                "methodology_version",
                "notes",
                "refreshed_at",
            ),
        )
        _require_columns(
            connection,
            fqtn=recon_table("profile_reconciliation_driver_breakdown"),
            expected_columns=(
                "fiscal_year",
                "state_code",
                "source_system",
                "driver_name",
                "inclusion_status",
                "driver_amount",
                "methodology_version",
                "refreshed_at",
            ),
        )
        _require_columns(
            connection,
            fqtn=recon_table("profile_reconciliation_summary"),
            expected_columns=(
                "fiscal_year",
                "source_system",
                "state_count",
                "avg_abs_residual_pct",
                "median_abs_residual_pct",
                "max_abs_residual_pct",
                "exact_window_state_count",
                "calibrated_state_count",
                "needs_review_state_count",
                "sparse_state_count",
                "total_unknown_stream_amount",
                "total_uncertain_amount",
                "methodology_version",
                "refreshed_at",
            ),
        )
        _require_columns(
            connection,
            fqtn=recon_table("normalized_state_funding"),
            expected_columns=(
                "source_system",
                "fiscal_year",
                "state_code",
                "raw_amount",
                "normalized_amount",
                "normalized_amount_type",
                "normalization_method",
                "funding_stream_logic_version",
                "cdc_profile_reference_amount",
                "residual_amount",
                "residual_pct",
                "core_public_health_amount",
                "emergency_public_health_amount",
                "federal_health_transfer_amount",
                "procurement_support_scope_amount",
                "special_transfer_amount",
                "other_public_health_amount",
                "biomedical_research_amount",
                "international_health_assistance_amount",
                "unknown_funding_scope_amount",
                "funding_scope_components_json",
                "methodology_version",
                "confidence_note",
                "calibration_basis",
                "refreshed_at",
            ),
        )

        cdc_reference_rows = _fetch_rows(connection, SUPPORT_VIEW_CDC, observed_fiscal_years or OBSERVED_CALIBRATION_YEARS)
        cdc_reference_map = build_cdc_profile_reference_map(cdc_reference_rows)

        reconciliation_rows: list[dict[str, Any]] = []
        driver_rows: list[dict[str, Any]] = []
        normalized_rows: list[dict[str, Any]] = []

        if SOURCE_USASPENDING in requested_sources:
            usaspending_support_map = build_support_map(
                _fetch_rows(connection, SUPPORT_VIEW_USASPENDING, selected_fiscal_years)
            )
            reconciliation_rows.extend(
                build_reconciliation_rows(
                    source_system=SOURCE_USASPENDING,
                    fiscal_years=selected_fiscal_years,
                    cdc_reference_map=cdc_reference_map,
                    support_map=usaspending_support_map,
                )
            )
            driver_rows.extend(
                build_driver_breakdown_rows(
                    source_system=SOURCE_USASPENDING,
                    fiscal_years=selected_fiscal_years,
                    support_map=usaspending_support_map,
                )
            )
            normalized_rows.extend(
                build_normalized_state_funding_rows(
                    source_system=SOURCE_USASPENDING,
                    fiscal_years=selected_fiscal_years,
                    cdc_reference_map=cdc_reference_map,
                    support_map=usaspending_support_map,
                )
            )

        if SOURCE_TAGGS in requested_sources:
            _require_objects(connection, [SUPPORT_VIEW_TAGGS])
            taggs_support_map = build_support_map(
                _fetch_rows(connection, SUPPORT_VIEW_TAGGS, selected_fiscal_years)
            )
            reconciliation_rows.extend(
                build_reconciliation_rows(
                    source_system=SOURCE_TAGGS,
                    fiscal_years=selected_fiscal_years,
                    cdc_reference_map=cdc_reference_map,
                    support_map=taggs_support_map,
                )
            )
            driver_rows.extend(
                build_driver_breakdown_rows(
                    source_system=SOURCE_TAGGS,
                    fiscal_years=selected_fiscal_years,
                    support_map=taggs_support_map,
                )
            )
            normalized_rows.extend(
                build_normalized_state_funding_rows(
                    source_system=SOURCE_TAGGS,
                    fiscal_years=selected_fiscal_years,
                    cdc_reference_map=cdc_reference_map,
                    support_map=taggs_support_map,
                )
            )

        summary_rows = build_reconciliation_summary_rows(reconciliation_rows)
        export_payload = build_export_summary(
            fiscal_years=selected_fiscal_years,
            source_systems=requested_sources,
            reconciliation_rows=reconciliation_rows,
            summary_rows=summary_rows,
        )
        _validate_state_codes(reconciliation_rows, label="profile_reconciliation_state_year payload")
        _validate_state_codes(driver_rows, label="profile_reconciliation_driver_breakdown payload")
        _validate_state_codes(normalized_rows, label="normalized_state_funding payload")

        if not dry_run:
            _delete_selected_rows(
                connection,
                table_name=recon_table("profile_reconciliation_driver_breakdown"),
                fiscal_years=observed_fiscal_years,
                source_systems=requested_sources,
            )
            _delete_selected_rows(
                connection,
                table_name=recon_table("profile_reconciliation_state_year"),
                fiscal_years=observed_fiscal_years,
                source_systems=requested_sources,
            )
            _delete_selected_rows(
                connection,
                table_name=recon_table("profile_reconciliation_summary"),
                fiscal_years=observed_fiscal_years,
                source_systems=requested_sources,
            )
            if rebuild_normalized_table:
                _delete_selected_rows(
                    connection,
                    table_name=recon_table("normalized_state_funding"),
                    fiscal_years=selected_fiscal_years,
                    source_systems=requested_sources,
                )

            _insert_rows(connection, STATE_YEAR_TABLE, reconciliation_rows)
            _insert_rows(connection, DRIVER_TABLE, driver_rows)
            _insert_rows(connection, SUMMARY_TABLE, summary_rows)
            if rebuild_normalized_table:
                _insert_rows(connection, NORMALIZED_TABLE, normalized_rows)

        if export_summary:
            write_summary_file(summary_path, export_payload)

            diagnostics_written: dict[str, Any] = {}
            before_snapshot_path = DEFAULT_BEFORE_SNAPSHOT_PATH
            profile_scope_summary_path = REPO_ROOT / "data" / "recon" / "profile_scope_build_summary.json"
            if SOURCE_USASPENDING in requested_sources and before_snapshot_path.exists():
                fy2021_payload = build_fy2021_residual_diagnostics_payload(
                    connection,
                    before_snapshot_path=before_snapshot_path,
                    state_code_to_name=STATE_CODE_TO_NAME,
                )
                write_diagnostics_json(DEFAULT_FY2021_DIAGNOSTICS_PATH, fy2021_payload)
                diagnostics_written["fy2021_residual_diagnostics_path"] = str(DEFAULT_FY2021_DIAGNOSTICS_PATH)

                mixed_program_transfer_payload = build_fy2021_mixed_program_transfer_review_payload(
                    connection,
                    before_snapshot_path=before_snapshot_path,
                    state_code_to_name=STATE_CODE_TO_NAME,
                )
                write_diagnostics_json(
                    DEFAULT_FY2021_MIXED_PROGRAM_TRANSFER_REVIEW_PATH,
                    mixed_program_transfer_payload,
                )
                diagnostics_written["fy2021_mixed_program_transfer_review_path"] = str(
                    DEFAULT_FY2021_MIXED_PROGRAM_TRANSFER_REVIEW_PATH
                )

                mixed_program_transfer_recommendations_payload = build_mixed_program_transfer_exception_recommendations_payload(
                    mixed_program_transfer_payload
                )
                write_diagnostics_json(
                    DEFAULT_MIXED_PROGRAM_TRANSFER_EXCEPTION_RECOMMENDATIONS_PATH,
                    mixed_program_transfer_recommendations_payload,
                )
                diagnostics_written["mixed_program_transfer_exception_recommendations_path"] = str(
                    DEFAULT_MIXED_PROGRAM_TRANSFER_EXCEPTION_RECOMMENDATIONS_PATH
                )

                verified_summary_payload = (
                    json.loads(DEFAULT_VERIFIED_ACCOUNT_SUMMARY_PATH.read_text(encoding="utf-8"))
                    if DEFAULT_VERIFIED_ACCOUNT_SUMMARY_PATH.exists()
                    else {}
                )
                methodology_display_payload = build_methodology_display_summary_payload(
                    methodology_version=METHODOLOGY_VERSION,
                    verified_summary=verified_summary_payload,
                    profile_scope_summary=(
                        json.loads(profile_scope_summary_path.read_text(encoding="utf-8"))
                        if profile_scope_summary_path.exists()
                        else {}
                    ),
                    review_payload=mixed_program_transfer_payload,
                    recommendations_payload=mixed_program_transfer_recommendations_payload,
                )
                write_review_overlay_json(
                    DEFAULT_METHODOLOGY_DISPLAY_SUMMARY_PATH,
                    methodology_display_payload,
                )
                diagnostics_written["methodology_display_summary_path"] = str(
                    DEFAULT_METHODOLOGY_DISPLAY_SUMMARY_PATH
                )

                manual_review_candidate_rows = build_manual_review_exception_candidate_rows(
                    methodology_version=METHODOLOGY_VERSION,
                    review_payload=mixed_program_transfer_payload,
                    recommendations_payload=mixed_program_transfer_recommendations_payload,
                )
                write_review_overlay_json(
                    DEFAULT_MANUAL_REVIEW_EXCEPTION_CANDIDATES_PATH,
                    {
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "methodology_version": METHODOLOGY_VERSION,
                        "candidate_count": len(manual_review_candidate_rows),
                        "rows": manual_review_candidate_rows,
                    },
                )
                write_review_overlay_csv(
                    DEFAULT_MANUAL_REVIEW_EXCEPTION_CANDIDATES_CSV_PATH,
                    manual_review_candidate_rows,
                    fieldnames=MANUAL_REVIEW_CANDIDATE_FIELDS,
                )
                diagnostics_written["manual_review_exception_candidates_path"] = str(
                    DEFAULT_MANUAL_REVIEW_EXCEPTION_CANDIDATES_PATH
                )
                diagnostics_written["manual_review_exception_candidates_csv_path"] = str(
                    DEFAULT_MANUAL_REVIEW_EXCEPTION_CANDIDATES_CSV_PATH
                )
                diagnostics_written["manual_review_exception_overlay_rows_written"] = (
                    replace_manual_review_exception_overlay_rows(
                        connection,
                        manual_review_candidate_rows,
                    )
                )

                write_review_overlay_json(
                    DEFAULT_FY2021_MANUAL_REVIEW_CROSSWALK_PATH,
                    build_manual_review_crosswalk_payload(
                        review_payload=mixed_program_transfer_payload,
                        candidate_rows=manual_review_candidate_rows,
                    ),
                )
                diagnostics_written["fy2021_manual_review_crosswalk_path"] = str(
                    DEFAULT_FY2021_MANUAL_REVIEW_CROSSWALK_PATH
                )

                if profile_scope_summary_path.exists():
                    refinement_payload = build_funding_scope_refinement_summary_payload(
                        connection,
                        before_snapshot_path=before_snapshot_path,
                        profile_scope_summary_path=profile_scope_summary_path,
                        calibration_summary_path=summary_path,
                    )
                    write_diagnostics_json(
                        DEFAULT_FUNDING_SCOPE_REFINEMENT_SUMMARY_PATH,
                        refinement_payload,
                    )
                    diagnostics_written["funding_scope_refinement_summary_path"] = str(
                        DEFAULT_FUNDING_SCOPE_REFINEMENT_SUMMARY_PATH
                    )
                else:
                    diagnostics_written["funding_scope_refinement_summary_path"] = None
            else:
                diagnostics_written["fy2021_residual_diagnostics_path"] = None
                diagnostics_written["fy2021_mixed_program_transfer_review_path"] = None
                diagnostics_written["mixed_program_transfer_exception_recommendations_path"] = None
                diagnostics_written["methodology_display_summary_path"] = None
                diagnostics_written["manual_review_exception_candidates_path"] = None
                diagnostics_written["manual_review_exception_candidates_csv_path"] = None
                diagnostics_written["manual_review_exception_overlay_rows_written"] = 0
                diagnostics_written["fy2021_manual_review_crosswalk_path"] = None
                diagnostics_written["funding_scope_refinement_summary_path"] = None
        else:
            diagnostics_written = {
                "fy2021_residual_diagnostics_path": None,
                "fy2021_mixed_program_transfer_review_path": None,
                "mixed_program_transfer_exception_recommendations_path": None,
                "methodology_display_summary_path": None,
                "manual_review_exception_candidates_path": None,
                "manual_review_exception_candidates_csv_path": None,
                "manual_review_exception_overlay_rows_written": 0,
                "fy2021_manual_review_crosswalk_path": None,
                "funding_scope_refinement_summary_path": None,
            }

        return {
            "methodology_version": METHODOLOGY_VERSION,
            "profile_scope_logic_version": PROFILE_SCOPE_LOGIC_VERSION,
            "fiscal_years_processed": selected_fiscal_years,
            "source_systems_processed": requested_sources,
            "cdc_reference_rows": len(cdc_reference_map),
            "reconciliation_rows_written": len(reconciliation_rows),
            "driver_rows_written": len(driver_rows),
            "normalized_rows_written": len(normalized_rows) if rebuild_normalized_table else 0,
            "summary_rows_written": len(summary_rows),
            "summary_path": str(summary_path) if export_summary else None,
            **diagnostics_written,
            "dry_run": dry_run,
            "export_payload": export_payload,
        }


def main() -> None:
    args = parse_args()
    summary = rebuild(
        db_url=args.db_url,
        fiscal_years=args.fiscal_years,
        source_system=args.source_system,
        include_taggs=bool(args.include_taggs),
        rebuild_normalized_table=bool(args.rebuild_normalized_table),
        export_summary=bool(args.export_summary),
        summary_path=args.summary_path,
        dry_run=bool(args.dry_run),
    )
    if args.verbose or args.dry_run:
        print(json.dumps(_serialize_json_value(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
