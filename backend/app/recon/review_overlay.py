from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.db_fqtn import recon_table
from app.recon.models import ManualReviewExceptionOverlay

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_METHODOLOGY_DISPLAY_SUMMARY_PATH = REPO_ROOT / "data" / "recon" / "methodology_display_summary.json"
DEFAULT_MANUAL_REVIEW_EXCEPTION_CANDIDATES_PATH = (
    REPO_ROOT / "data" / "recon" / "manual_review_exception_candidates.json"
)
DEFAULT_MANUAL_REVIEW_EXCEPTION_CANDIDATES_CSV_PATH = (
    REPO_ROOT / "data" / "recon" / "manual_review_exception_candidates.csv"
)
DEFAULT_FY2021_MANUAL_REVIEW_CROSSWALK_PATH = (
    REPO_ROOT / "data" / "recon" / "fy2021_manual_review_crosswalk.json"
)
MANUAL_REVIEW_CANDIDATE_FIELDS = (
    "review_id",
    "active",
    "apply_in_production",
    "fiscal_year",
    "assistance_only",
    "contracts_only",
    "state_code",
    "aln",
    "award_family",
    "federal_account_combination_key",
    "current_multi_account_interpretation",
    "recommended_review_disposition",
    "analyst_notes",
    "evidence_source",
    "created_at",
    "updated_at",
    "methodology_version",
)

MANUAL_REVIEW_TABLE = ManualReviewExceptionOverlay.__table__
MANUAL_REVIEW_TABLE_FQTN = recon_table("manual_review_exception_overlay")

NULL_TOKENS = {"", "na", "n/a", "none", "null", "nan"}
NON_WORD_RE = re.compile(r"[^a-z0-9]+")


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).replace("\ufeff", "").strip()
    token = re.sub(r"\s+", " ", token)
    if token.lower() in NULL_TOKENS:
        return None
    return token or None


def _to_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _quantize_money(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.01"))


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(_serialize(dict(payload)), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: str | Path, rows: Sequence[Mapping[str, Any]], *, fieldnames: Sequence[str]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _serialize(row.get(field)) for field in fieldnames})


def _summary_lookup(rows: Sequence[Mapping[str, Any]], key_field: str) -> dict[str, Mapping[str, Any]]:
    return {
        str(key): row
        for row in rows
        if (key := _normalize_text(row.get(key_field))) is not None
    }


def _structure_counts(profile_scope_summary: Mapping[str, Any]) -> dict[str, int]:
    counts = {
        "single_account": 0,
        "multi_account_same_scope": 0,
        "multi_account_mixed_scope": 0,
    }
    for row in profile_scope_summary.get("row_count_by_account_structure_type", []) or []:
        key = _normalize_text(row.get("account_structure_type"))
        if key in counts:
            counts[key] = int(row.get("row_count") or 0)
    return counts


def build_methodology_display_summary_payload(
    *,
    methodology_version: str,
    verified_summary: Mapping[str, Any] | None,
    profile_scope_summary: Mapping[str, Any] | None,
    review_payload: Mapping[str, Any] | None,
    recommendations_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    verified_summary = verified_summary or {}
    profile_scope_summary = profile_scope_summary or {}
    review_payload = review_payload or {}
    recommendations_payload = recommendations_payload or {}

    structure_counts = _structure_counts(profile_scope_summary)
    family_lookup = _summary_lookup(review_payload.get("summary_by_program_family", []) or [], "program_family_label")

    top_review_families = []
    for family_name in ("immunization", "ELC"):
        row = family_lookup.get(family_name)
        if row is None:
            continue
        top_review_families.append(
            {
                "award_family": family_name,
                "row_count": int(row.get("row_count") or 0),
                "raw_amount": _quantize_money(_to_decimal(row.get("raw_amount"))),
                "residual_contribution_estimate": _quantize_money(
                    _to_decimal(row.get("residual_contribution_estimate"))
                ),
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "current_frozen_version": methodology_version,
        "verified_account_count": int(verified_summary.get("loaded_account_count") or 0),
        "fallback_account_count": int(verified_summary.get("fallback_account_count") or 0),
        "total_single_account_rows": structure_counts["single_account"],
        "total_multi_account_same_scope_rows": structure_counts["multi_account_same_scope"],
        "total_multi_account_mixed_scope_rows": structure_counts["multi_account_mixed_scope"],
        "conservative_mixed_account_handling_explanation": (
            "When a public source row mixes multiple federal accounts and does not provide an exact account-level split, "
            "CHIP leaves the raw dollars unchanged but avoids crediting the full row to core CDC public health funding."
        ),
        "why_fy2021_differs": (
            "FY2021 contains unusually large mixed_program_transfer assistance awards, especially in immunization and ELC, "
            "where core CDC accounts appear alongside federal transfer accounts without a defensible public split."
        ),
        "top_fy2021_review_families": top_review_families,
        "manual_review_exceptions_applied_in_production": False,
        "manual_review_exceptions_production_note": (
            "Manual-review candidates are surfaced for analyst review only. No exception rows are applied to frozen "
            "production normalization outputs in this version."
        ),
        "frontend_summary": {
            "version": methodology_version,
            "counts": {
                "verified_accounts": int(verified_summary.get("loaded_account_count") or 0),
                "fallback_accounts": int(verified_summary.get("fallback_account_count") or 0),
                "single_account_rows": structure_counts["single_account"],
                "multi_account_same_scope_rows": structure_counts["multi_account_same_scope"],
                "multi_account_mixed_scope_rows": structure_counts["multi_account_mixed_scope"],
            },
            "top_review_families": top_review_families,
            "production_exceptions_applied": False,
        },
        "review_overlay_summary": {
            "candidate_recommendation_count": len(recommendations_payload.get("candidate_recommendations", []) or []),
            "production_change_recommended": bool(recommendations_payload.get("production_change_recommended")),
        },
    }


def _slugify(value: Any) -> str:
    token = (_normalize_text(value) or "").lower()
    return NON_WORD_RE.sub("_", token).strip("_") or "any"


def _build_review_id(
    *,
    fiscal_year: int | None,
    award_family: Any,
    aln: Any,
    federal_account_combination_key: Any,
) -> str:
    fy_token = str(fiscal_year or "na")
    family_token = _slugify(award_family)
    aln_token = _slugify(aln)
    combo_token = _normalize_text(federal_account_combination_key) or "any"
    combo_hash = hashlib.sha1(combo_token.encode("utf-8")).hexdigest()[:12]
    return f"fy{fy_token}_{family_token}_{aln_token}_{combo_hash}"


def build_manual_review_exception_candidate_rows(
    *,
    methodology_version: str,
    review_payload: Mapping[str, Any],
    recommendations_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    candidate_rows: list[dict[str, Any]] = []
    seen_review_ids: set[str] = set()
    generated_at = datetime.now(timezone.utc)

    for recommendation in recommendations_payload.get("candidate_recommendations", []) or []:
        proposed = recommendation.get("proposed_conditions") or {}
        fiscal_year = int(proposed.get("fiscal_year") or 0) or None
        award_family = _normalize_text(proposed.get("program_family_label")) or _normalize_text(
            recommendation.get("program_family_label")
        )
        alns = [
            _normalize_text(value)
            for value in proposed.get("alns", []) or [None]
            if _normalize_text(value) is not None
        ] or [None]
        combinations = [
            _normalize_text(value)
            for value in proposed.get("federal_account_combination_keys", []) or [None]
            if _normalize_text(value) is not None
        ] or [None]
        award_type = _normalize_text(proposed.get("award_type"))
        assistance_only = award_type == "assistance"
        contracts_only = award_type == "contracts"

        for aln in alns:
            for combination_key in combinations:
                review_id = _build_review_id(
                    fiscal_year=fiscal_year,
                    award_family=award_family,
                    aln=aln,
                    federal_account_combination_key=combination_key,
                )
                if review_id in seen_review_ids:
                    continue
                seen_review_ids.add(review_id)
                candidate_rows.append(
                    {
                        "review_id": review_id,
                        "active": True,
                        "apply_in_production": False,
                        "fiscal_year": fiscal_year,
                        "assistance_only": assistance_only,
                        "contracts_only": contracts_only,
                        "state_code": None,
                        "aln": aln,
                        "award_family": award_family,
                        "federal_account_combination_key": combination_key,
                        "current_multi_account_interpretation": "mixed_program_transfer",
                        "recommended_review_disposition": _normalize_text(recommendation.get("status"))
                        or "manual_review_only",
                        "analyst_notes": _normalize_text(recommendation.get("reason_not_auto_applied"))
                        or _normalize_text(recommendation.get("rationale")),
                        "evidence_source": (
                            "fy2021_mixed_program_transfer_review.json | "
                            "mixed_program_transfer_exception_recommendations.json"
                        ),
                        "created_at": generated_at,
                        "updated_at": generated_at,
                        "methodology_version": methodology_version,
                    }
                )

    candidate_rows.sort(
        key=lambda row: (
            int(row.get("fiscal_year") or 0),
            _slugify(row.get("award_family")),
            _slugify(row.get("aln")),
            _slugify(row.get("federal_account_combination_key")),
        )
    )
    return candidate_rows


def _candidate_lookup(
    candidate_rows: Sequence[Mapping[str, Any]],
) -> dict[tuple[str | None, str | None, str | None], Mapping[str, Any]]:
    return {
        (
            _normalize_text(row.get("award_family")),
            _normalize_text(row.get("aln")),
            _normalize_text(row.get("federal_account_combination_key")),
        ): row
        for row in candidate_rows
    }


def build_manual_review_crosswalk_payload(
    *,
    review_payload: Mapping[str, Any],
    candidate_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    candidates = _candidate_lookup(candidate_rows)
    seen_awards: set[tuple[str | None, str | None]] = set()
    crosswalk_rows: list[dict[str, Any]] = []

    source_rows = [
        *(review_payload.get("national_top_rows", []) or []),
        *(review_payload.get("washington_rows", []) or []),
    ]
    for row in source_rows:
        key = (
            _normalize_text(row.get("program_family_label")),
            _normalize_text(row.get("aln_or_code")),
            _normalize_text(row.get("federal_account_combination_key")),
        )
        candidate = candidates.get(key)
        if candidate is None:
            continue
        row_key = (_normalize_text(row.get("award_identifier")), _normalize_text(row.get("state_code")))
        if row_key in seen_awards:
            continue
        seen_awards.add(row_key)
        crosswalk_rows.append(
            {
                "review_id": candidate.get("review_id"),
                "aln": _normalize_text(row.get("aln_or_code")),
                "award_family": _normalize_text(row.get("program_family_label")),
                "state_code": _normalize_text(row.get("state_code")),
                "state_name": _normalize_text(row.get("state_name")),
                "state": _normalize_text(row.get("state")) or _normalize_text(row.get("state_name")),
                "award_identifier": _normalize_text(row.get("award_identifier")),
                "award_title": _normalize_text(row.get("award_title")),
                "federal_account_combination_key": _normalize_text(row.get("federal_account_combination_key")),
                "current_treatment": _normalize_text(row.get("current_inclusion_treatment")),
                "current_multi_account_interpretation": _normalize_text(
                    row.get("multi_account_interpretation")
                ),
                "residual_contribution_estimate": _quantize_money(
                    _to_decimal(row.get("residual_contribution_estimate"))
                ),
                "raw_amount": _quantize_money(_to_decimal(row.get("raw_amount"))),
                "normalized_amount": _quantize_money(_to_decimal(row.get("normalized_amount"))),
                "recommendation_status": _normalize_text(candidate.get("recommended_review_disposition")),
            }
        )

    crosswalk_rows.sort(
        key=lambda row: (
            _to_decimal(row.get("residual_contribution_estimate")),
            _to_decimal(row.get("raw_amount")),
        ),
        reverse=True,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(crosswalk_rows),
        "rows": crosswalk_rows,
    }


def _table_exists(connection: Any, table_name: str) -> bool:
    row = connection.execute(
        text("SELECT to_regclass(:table_name) AS exists"),
        {"table_name": table_name},
    ).mappings().one()
    return row["exists"] is not None


def replace_manual_review_exception_overlay_rows(
    connection: Any,
    rows: Sequence[Mapping[str, Any]],
) -> int:
    if not _table_exists(connection, MANUAL_REVIEW_TABLE_FQTN):
        return 0

    connection.execute(MANUAL_REVIEW_TABLE.delete())
    if not rows:
        return 0

    insert_stmt = pg_insert(MANUAL_REVIEW_TABLE).values(list(rows))
    update_columns = {
        column.name: getattr(insert_stmt.excluded, column.name)
        for column in MANUAL_REVIEW_TABLE.columns
        if column.name != "review_id"
    }
    connection.execute(
        insert_stmt.on_conflict_do_update(
            index_elements=[MANUAL_REVIEW_TABLE.c.review_id],
            set_=update_columns,
        )
    )
    return len(rows)
