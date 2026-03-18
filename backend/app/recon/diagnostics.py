from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import text

from app.recon.funding_scope import (
    FUNDING_SCOPE_BIOMEDICAL_RESEARCH,
    FUNDING_SCOPE_CORE_PUBLIC_HEALTH,
    FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH,
    FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER,
    FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE,
    FUNDING_SCOPE_OTHER_PUBLIC_HEALTH,
    FUNDING_SCOPE_PROCUREMENT_SUPPORT,
    FUNDING_SCOPE_SPECIAL_TRANSFER,
    FUNDING_SCOPE_UNKNOWN,
)
from app.recon.multi_account import build_component_scope_payload

NULL_TOKENS = {"", "na", "n/a", "none", "null", "nan"}
ACCOUNT_SPLIT_RE = re.compile(r"\s*[;|]\s*")


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


def _split_account_symbols(value: Any) -> list[str]:
    token = _normalize_text(value)
    if token is None:
        return []
    return [piece for piece in ACCOUNT_SPLIT_RE.split(token) if piece]


def _legacy_scope_from_before_row(row: Mapping[str, Any] | None) -> str:
    if not row:
        return FUNDING_SCOPE_UNKNOWN
    stream = _normalize_text(row.get("funding_stream_guess")) or "unknown"
    effective_profile_relevant = row.get("effective_profile_relevant")
    if stream in {"covid_emergency", "arpa", "other_emergency_or_disaster", "non_covid_supplemental"}:
        return FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH
    if stream == "procurement_support":
        return FUNDING_SCOPE_PROCUREMENT_SUPPORT
    if stream == "transfer_or_special":
        return FUNDING_SCOPE_SPECIAL_TRANSFER
    if stream == "regular_appropriation":
        return FUNDING_SCOPE_CORE_PUBLIC_HEALTH if effective_profile_relevant is True else FUNDING_SCOPE_UNKNOWN
    return FUNDING_SCOPE_UNKNOWN


def _approx_before_row(
    account_symbols: list[str],
    before_lookup: Mapping[str, Mapping[str, Any]],
    raw_amount: Decimal,
) -> dict[str, Any]:
    component_items = []
    any_profile_relevant = False
    for symbol in account_symbols:
        before_row = before_lookup.get(symbol)
        legacy_scope = _legacy_scope_from_before_row(before_row)
        if before_row and before_row.get("effective_profile_relevant") is True:
            any_profile_relevant = True
        component_items.append(
            {
                "federal_account_symbol": symbol,
                "account_title": None,
                "effective_funding_scope": legacy_scope,
                "funding_scope_method": "before_snapshot",
                "effective_profile_relevant": before_row.get("effective_profile_relevant") if before_row else None,
            }
        )
    payload = build_component_scope_payload(component_items)
    if payload["mixed_scope_contains_unknown"]:
        before_scope = FUNDING_SCOPE_UNKNOWN
    elif payload["mixed_scope_contains_international"]:
        before_scope = FUNDING_SCOPE_INTERNATIONAL_HEALTH_ASSISTANCE
    elif payload["mixed_scope_contains_research"]:
        before_scope = FUNDING_SCOPE_BIOMEDICAL_RESEARCH
    elif payload["mixed_scope_contains_special_transfer"]:
        before_scope = FUNDING_SCOPE_SPECIAL_TRANSFER
    elif payload["mixed_scope_contains_core"] and payload["mixed_scope_contains_transfer"]:
        before_scope = FUNDING_SCOPE_FEDERAL_HEALTH_TRANSFER
    elif payload["mixed_scope_contains_core"] and payload["mixed_scope_contains_procurement"]:
        before_scope = FUNDING_SCOPE_PROCUREMENT_SUPPORT
    elif payload["mixed_scope_contains_core"] and payload["mixed_scope_contains_emergency"]:
        before_scope = FUNDING_SCOPE_EMERGENCY_PUBLIC_HEALTH
    elif payload["component_scope_count"] == 1 and payload["component_account_scopes"]:
        before_scope = payload["component_account_scopes"][0]["effective_funding_scope"]
    else:
        before_scope = FUNDING_SCOPE_UNKNOWN
    return {
        "before_effective_funding_scope": before_scope,
        "before_account_structure_type": payload["account_structure_type"],
        "before_multi_account_interpretation": payload["multi_account_interpretation"],
        "before_normalized_amount_estimate": raw_amount if any_profile_relevant else Decimal("0.00"),
    }


def _fetch_fy2021_rows(connection: Any, *, state_code_to_name: Mapping[str, str]) -> list[dict[str, Any]]:
    rows = connection.execute(
        text(
            """
            SELECT
                'assistance'::text AS award_type,
                source_system,
                source_transaction_id,
                fiscal_year,
                state_code,
                assistance_listing_number AS aln_or_code,
                assistance_listing_title AS listing_or_award_title,
                NULL::text AS award_description,
                effective_funding_stream,
                funding_scope_method,
                effective_funding_scope,
                include_in_profile_scope,
                inclusion_weight,
                decision_context,
                transaction_obligated_amount,
                federal_account_symbol,
                federal_account_titles_combined,
                federal_account_count,
                federal_account_combination_key,
                component_account_scopes,
                component_scope_count,
                has_mixed_scopes,
                account_structure_type,
                multi_account_interpretation,
                manual_review_recommended,
                likely_emergency_related AS emergency_related,
                mixed_scope_contains_transfer AS transfer_related,
                mixed_scope_contains_procurement AS procurement_related,
                mixed_scope_contains_research AS research_related,
                mixed_scope_contains_international AS international_related,
                mixed_scope_contains_special_transfer AS special_transfer_related,
                mixed_scope_contains_unknown AS unknown_related,
                conservative_inclusion_reason
            FROM recon.assistance_transactions_profile_enriched
            WHERE fiscal_year = 2021

            UNION ALL

            SELECT
                'contracts'::text AS award_type,
                source_system,
                source_transaction_id,
                fiscal_year,
                state_code,
                product_or_service_code AS aln_or_code,
                award_description AS listing_or_award_title,
                award_description,
                effective_funding_stream,
                funding_scope_method,
                effective_funding_scope,
                include_in_profile_scope,
                inclusion_weight,
                decision_context,
                transaction_obligated_amount,
                federal_account_symbol,
                federal_account_titles_combined,
                federal_account_count,
                federal_account_combination_key,
                component_account_scopes,
                component_scope_count,
                has_mixed_scopes,
                account_structure_type,
                multi_account_interpretation,
                manual_review_recommended,
                likely_emergency_related AS emergency_related,
                mixed_scope_contains_transfer AS transfer_related,
                mixed_scope_contains_procurement AS procurement_related,
                mixed_scope_contains_research AS research_related,
                mixed_scope_contains_international AS international_related,
                mixed_scope_contains_special_transfer AS special_transfer_related,
                mixed_scope_contains_unknown AS unknown_related,
                conservative_inclusion_reason
            FROM recon.contract_transactions_profile_enriched
            WHERE fiscal_year = 2021
            """
        )
    ).mappings().all()

    payload_rows = []
    for row in rows:
        raw_amount = _quantize_money(_to_decimal(row.get("transaction_obligated_amount"))) or Decimal("0.00")
        include_in_profile_scope = row.get("include_in_profile_scope")
        inclusion_weight = row.get("inclusion_weight")
        normalized_amount = Decimal("0.00")
        if include_in_profile_scope is True and inclusion_weight is not None:
            normalized_amount = _quantize_money(raw_amount * _to_decimal(inclusion_weight)) or Decimal("0.00")
        state_code = _normalize_text(row.get("state_code"))
        payload_rows.append(
            {
                **dict(row),
                "state_name": state_code_to_name.get(str(state_code or "").upper()),
                "raw_amount": raw_amount,
                "normalized_amount": normalized_amount,
            }
        )
    return payload_rows


def _group_diagnostics(
    rows: Sequence[Mapping[str, Any]],
    *,
    key_field: str,
) -> list[dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _normalize_text(row.get(key_field))
        if key is None:
            continue
        accumulator = totals.setdefault(
            key,
            {
                key_field: key,
                "row_count": 0,
                "raw_amount": Decimal("0.00"),
                "after_normalized_amount": Decimal("0.00"),
                "before_normalized_amount_estimate": Decimal("0.00"),
                "residual_contribution_estimate": Decimal("0.00"),
            },
        )
        accumulator["row_count"] += 1
        accumulator["raw_amount"] += _to_decimal(row.get("raw_amount"))
        accumulator["after_normalized_amount"] += _to_decimal(row.get("normalized_amount"))
        accumulator["before_normalized_amount_estimate"] += _to_decimal(row.get("before_normalized_amount_estimate"))
        accumulator["residual_contribution_estimate"] += _to_decimal(row.get("residual_contribution_estimate"))
    return sorted(
        (
            {
                **value,
                "raw_amount": _quantize_money(value["raw_amount"]),
                "after_normalized_amount": _quantize_money(value["after_normalized_amount"]),
                "before_normalized_amount_estimate": _quantize_money(value["before_normalized_amount_estimate"]),
                "residual_contribution_estimate": _quantize_money(value["residual_contribution_estimate"]),
            }
            for value in totals.values()
        ),
        key=lambda item: (_to_decimal(item["residual_contribution_estimate"]), _to_decimal(item["raw_amount"])),
        reverse=True,
    )


def build_fy2021_residual_diagnostics_payload(
    connection: Any,
    *,
    before_snapshot_path: str | Path,
    state_code_to_name: Mapping[str, str],
) -> dict[str, Any]:
    before_snapshot = json.loads(Path(before_snapshot_path).read_text(encoding="utf-8"))
    before_lookup = {row["federal_account_symbol"]: row for row in before_snapshot.get("lookup_rows", [])}
    current_rows = _fetch_fy2021_rows(connection, state_code_to_name=state_code_to_name)

    diagnostic_rows = []
    for row in current_rows:
        symbols = _split_account_symbols(row.get("federal_account_symbol"))
        before_row = _approx_before_row(symbols, before_lookup, row["raw_amount"])
        residual_contribution_estimate = _quantize_money(
            _to_decimal(before_row["before_normalized_amount_estimate"]) - _to_decimal(row["normalized_amount"])
        ) or Decimal("0.00")
        diagnostic_rows.append(
            {
                **row,
                **before_row,
                "residual_contribution_estimate": residual_contribution_estimate,
            }
        )

    worsening_rows = [
        row
        for row in sorted(
            diagnostic_rows,
            key=lambda item: (
                _to_decimal(item["residual_contribution_estimate"]),
                _to_decimal(item["raw_amount"]),
            ),
            reverse=True,
        )
        if _to_decimal(row["residual_contribution_estimate"]) > 0
    ]
    top_national = worsening_rows[:100]
    top_wa = [row for row in worsening_rows if row.get("state_code") == "WA"][:50]

    before_by_scope: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    after_by_scope: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    before_by_structure: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    after_by_structure: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    scope_delta: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    structure_delta: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
    for row in diagnostic_rows:
        before_scope = _normalize_text(row.get("before_effective_funding_scope")) or FUNDING_SCOPE_UNKNOWN
        after_scope = _normalize_text(row.get("effective_funding_scope")) or FUNDING_SCOPE_UNKNOWN
        before_structure = _normalize_text(row.get("before_account_structure_type")) or "unknown"
        after_structure = _normalize_text(row.get("account_structure_type")) or "unknown"
        before_amount = _to_decimal(row.get("before_normalized_amount_estimate"))
        after_amount = _to_decimal(row.get("normalized_amount"))
        delta = _to_decimal(row.get("residual_contribution_estimate"))
        before_by_scope[before_scope] += before_amount
        after_by_scope[after_scope] += after_amount
        before_by_structure[before_structure] += before_amount
        after_by_structure[after_structure] += after_amount
        scope_delta[after_scope] += delta
        structure_delta[after_structure] += delta

    all_scopes = sorted(set(before_by_scope) | set(after_by_scope))
    all_structures = sorted(set(before_by_structure) | set(after_by_structure))
    before_after_scope = [
        {
            "scope_bucket": scope,
            "before_normalized_amount_estimate": _quantize_money(before_by_scope[scope]),
            "after_normalized_amount": _quantize_money(after_by_scope[scope]),
            "residual_contribution_estimate": _quantize_money(scope_delta[scope]),
        }
        for scope in all_scopes
    ]
    before_after_structure = [
        {
            "account_structure_type": structure,
            "before_normalized_amount_estimate": _quantize_money(before_by_structure[structure]),
            "after_normalized_amount": _quantize_money(after_by_structure[structure]),
            "residual_contribution_estimate": _quantize_money(structure_delta[structure]),
        }
        for structure in all_structures
    ]

    mixed_multi_delta = structure_delta.get("multi_account_mixed_scope", Decimal("0.00"))
    sorted_scope_deltas = sorted(scope_delta.items(), key=lambda item: item[1], reverse=True)
    dominant_scope, dominant_scope_delta = (
        sorted_scope_deltas[0] if sorted_scope_deltas else ("mixed", Decimal("0.00"))
    )
    second_scope_delta = sorted_scope_deltas[1][1] if len(sorted_scope_deltas) > 1 else Decimal("0.00")
    if mixed_multi_delta > dominant_scope_delta * Decimal("1.10") and mixed_multi_delta > 0:
        primary_conclusion = "mixed multi-account attribution"
    elif dominant_scope_delta > 0 and dominant_scope_delta >= second_scope_delta * Decimal("1.10"):
        primary_conclusion = dominant_scope
    else:
        primary_conclusion = "mixed / no single dominant bucket"

    manual_review_combinations = _group_diagnostics(
        [row for row in diagnostic_rows if bool(row.get("manual_review_recommended"))],
        key_field="federal_account_combination_key",
    )[:25]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "comparison_method": "before side is an approximate replay from the preserved account-lookup snapshot rather than a full pre-refinement row rebuild.",
        "top_100_fy2021_residual_contributor_rows_national": top_national,
        "top_50_wa_fy2021_residual_contributor_rows": top_wa,
        "fy2021_summary_by_effective_funding_scope": _group_diagnostics(diagnostic_rows, key_field="effective_funding_scope"),
        "fy2021_summary_by_funding_scope_method": _group_diagnostics(diagnostic_rows, key_field="funding_scope_method"),
        "fy2021_summary_by_federal_account_combination": _group_diagnostics(diagnostic_rows, key_field="federal_account_combination_key")[:100],
        "fy2021_summary_by_aln_or_code": _group_diagnostics(diagnostic_rows, key_field="aln_or_code")[:100],
        "fy2021_summary_by_award_type": _group_diagnostics(diagnostic_rows, key_field="award_type"),
        "fy2021_summary_by_multi_account_interpretation": _group_diagnostics(diagnostic_rows, key_field="multi_account_interpretation"),
        "fy2021_summary_by_account_structure_type": _group_diagnostics(diagnostic_rows, key_field="account_structure_type"),
        "before_vs_after_fy2021_by_scope_bucket": before_after_scope,
        "before_vs_after_fy2021_by_account_structure_type": before_after_structure,
        "manual_review_combinations": manual_review_combinations,
        "conclusion": {
            "primary_worsening_bucket": primary_conclusion,
            "dominant_scope_bucket": dominant_scope,
            "dominant_scope_delta": _quantize_money(dominant_scope_delta),
            "mixed_multi_account_delta": _quantize_money(mixed_multi_delta),
        },
    }


def build_funding_scope_refinement_summary_payload(
    connection: Any,
    *,
    before_snapshot_path: str | Path,
    profile_scope_summary_path: str | Path,
    calibration_summary_path: str | Path,
) -> dict[str, Any]:
    before = json.loads(Path(before_snapshot_path).read_text(encoding="utf-8"))
    profile_scope_summary = json.loads(Path(profile_scope_summary_path).read_text(encoding="utf-8"))
    calibration_summary = json.loads(Path(calibration_summary_path).read_text(encoding="utf-8"))
    before_lookup = {row["federal_account_symbol"]: row for row in before.get("lookup_rows", [])}
    before_residuals = {
        (row["source_system"], row["fiscal_year"], row["state_code"]): row
        for row in before.get("residual_rows", [])
        if row.get("source_system") == "usaspending" and row.get("residual_pct") is not None
    }

    lookup_rows = connection.execute(
        text(
            """
            SELECT
                federal_account_symbol,
                account_title,
                effective_funding_scope,
                funding_scope_guess,
                funding_scope_method,
                effective_profile_relevant,
                effective_funding_stream,
                effective_scope_guess,
                effective_classification_method,
                observed_total_obligations
            FROM recon.federal_account_lookup
            ORDER BY observed_total_obligations DESC NULLS LAST, federal_account_symbol
            """
        )
    ).mappings().all()
    current_residual_rows = connection.execute(
        text(
            """
            SELECT fiscal_year, state_code, source_system, residual_amount, residual_pct, abs_residual_amount
            FROM recon.profile_reconciliation_state_year
            WHERE source_system = 'usaspending' AND fiscal_year BETWEEN 2020 AND 2023
            ORDER BY fiscal_year, state_code
            """
        )
    ).mappings().all()

    top_accounts_by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in lookup_rows:
        scope = _normalize_text(row.get("effective_funding_scope")) or FUNDING_SCOPE_UNKNOWN
        if len(top_accounts_by_scope[scope]) >= 8:
            continue
        top_accounts_by_scope[scope].append(dict(row))

    reclassified = []
    for row in lookup_rows:
        symbol = row["federal_account_symbol"]
        previous = before_lookup.get(symbol)
        if previous is None:
            continue
        previous_scope = _legacy_scope_from_before_row(previous)
        if (
            previous_scope != row["effective_funding_scope"]
            or previous.get("effective_profile_relevant") != row["effective_profile_relevant"]
            or previous.get("funding_stream_guess") != row["effective_funding_stream"]
        ):
            reclassified.append(
                {
                    "federal_account_symbol": symbol,
                    "account_title": row.get("account_title"),
                    "observed_total_obligations": row.get("observed_total_obligations"),
                    "before_funding_stream_guess": previous.get("funding_stream_guess"),
                    "before_scope_approximation": previous_scope,
                    "before_profile_relevant": previous.get("effective_profile_relevant"),
                    "after_funding_scope": row.get("effective_funding_scope"),
                    "after_funding_stream": row.get("effective_funding_stream"),
                    "after_profile_relevant": row.get("effective_profile_relevant"),
                    "funding_scope_method": row.get("funding_scope_method"),
                }
            )
    reclassified.sort(key=lambda item: _to_decimal(item.get("observed_total_obligations")), reverse=True)

    state_improvements = []
    for row in current_residual_rows:
        previous = before_residuals.get((row["source_system"], row["fiscal_year"], row["state_code"]))
        if previous is None:
            continue
        before_pct = abs(_to_decimal(previous["residual_pct"]))
        after_pct = abs(_to_decimal(row["residual_pct"]))
        state_improvements.append(
            {
                "fiscal_year": row["fiscal_year"],
                "state_code": row["state_code"],
                "before_abs_residual_pct": before_pct,
                "after_abs_residual_pct": after_pct,
                "improvement_abs_residual_pct": before_pct - after_pct,
            }
        )
    state_improvements.sort(key=lambda item: item["improvement_abs_residual_pct"], reverse=True)

    example_assistance_rows = {}
    for label, context in [
        ("core_public_health_included", "cdc_domestic_core_public_health"),
        ("emergency_public_health_conditional", "cdc_domestic_emergency_public_health_conditional"),
        ("federal_health_transfer_excluded", "cdc_domestic_federal_health_transfer_excluded"),
        ("mixed_core_emergency_conservative", "cdc_domestic_mixed_core_emergency_conservative"),
        ("international_health_assistance_excluded", "international_health_assistance_excluded"),
    ]:
        row = connection.execute(
            text(
                """
                SELECT
                    source_transaction_id,
                    fiscal_year,
                    state_code,
                    assistance_listing_number,
                    assistance_listing_title,
                    federal_account_symbol,
                    effective_funding_scope,
                    decision_context,
                    include_in_profile_scope,
                    transaction_obligated_amount
                FROM recon.assistance_transactions_profile_enriched
                WHERE decision_context = :context
                ORDER BY transaction_obligated_amount DESC NULLS LAST
                LIMIT 1
                """
            ),
            {"context": context},
        ).mappings().first()
        if row is not None:
            example_assistance_rows[label] = dict(row)

    unknown_rows = connection.execute(
        text(
            """
            SELECT
                federal_account_symbol,
                account_title,
                observed_total_obligations,
                effective_funding_stream,
                effective_profile_relevant,
                funding_scope_method
            FROM recon.federal_account_lookup
            WHERE effective_funding_scope = 'unknown'
            ORDER BY observed_total_obligations DESC NULLS LAST
            LIMIT 15
            """
        )
    ).mappings().all()

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline_snapshot_path": str(before_snapshot_path),
        "methodology_versions": {
            "profile_scope_before": before["profile_scope_build_summary"]["methodology_version"],
            "profile_scope_after": profile_scope_summary["methodology_version"],
            "calibration_before": before["profile_calibration_summary"]["methodology_version"],
            "calibration_after": calibration_summary["methodology_version"],
        },
        "top_accounts_by_funding_scope": top_accounts_by_scope,
        "top_accounts_reclassified": reclassified[:20],
        "before_vs_after_profile_scope_totals": {
            "included_assistance_total_before": before["profile_scope_build_summary"]["included_assistance_total"],
            "included_assistance_total_after": profile_scope_summary["included_assistance_total"],
            "excluded_assistance_total_before": before["profile_scope_build_summary"]["excluded_assistance_total"],
            "excluded_assistance_total_after": profile_scope_summary["excluded_assistance_total"],
            "uncertain_assistance_total_before": before["profile_scope_build_summary"]["uncertain_assistance_total"],
            "uncertain_assistance_total_after": profile_scope_summary["uncertain_assistance_total"],
            "included_contract_total_before": before["profile_scope_build_summary"]["included_contract_total"],
            "included_contract_total_after": profile_scope_summary["included_contract_total"],
            "excluded_contract_total_before": before["profile_scope_build_summary"]["excluded_contract_total"],
            "excluded_contract_total_after": profile_scope_summary["excluded_contract_total"],
            "uncertain_contract_total_before": before["profile_scope_build_summary"]["uncertain_contract_total"],
            "uncertain_contract_total_after": profile_scope_summary["uncertain_contract_total"],
        },
        "before_vs_after_residual_stats_by_year": {
            year: {
                "before_avg_abs_residual_pct": ((before["profile_calibration_summary"].get("residual_stats_by_year") or {}).get(year) or {}).get("usaspending", {}).get("avg_abs_residual_pct"),
                "after_avg_abs_residual_pct": ((calibration_summary.get("residual_stats_by_year") or {}).get(year) or {}).get("usaspending", {}).get("avg_abs_residual_pct"),
            }
            for year in ("2020", "2021", "2022", "2023")
        },
        "states_with_biggest_improvement": state_improvements[:10],
        "states_with_biggest_worsening": sorted(state_improvements, key=lambda item: item["improvement_abs_residual_pct"])[:10],
        "component_totals_by_funding_scope_and_year": calibration_summary.get("funding_scope_component_totals_by_year"),
        "account_structure_summary": {
            "row_count_by_account_structure_type": profile_scope_summary.get("row_count_by_account_structure_type"),
            "raw_amount_by_account_structure_type": profile_scope_summary.get("raw_amount_by_account_structure_type"),
            "row_count_by_multi_account_interpretation": profile_scope_summary.get("row_count_by_multi_account_interpretation"),
            "manual_review_recommended_row_count": profile_scope_summary.get("manual_review_recommended_row_count"),
        },
        "example_assistance_rows": example_assistance_rows,
        "still_unknown_high_dollar_accounts": list(unknown_rows),
    }


def _current_inclusion_treatment(row: Mapping[str, Any]) -> str:
    include_in_profile_scope = row.get("include_in_profile_scope")
    if include_in_profile_scope is True:
        return "included"
    if include_in_profile_scope is False:
        return "excluded"
    return "conditional"


def _program_family_label(row: Mapping[str, Any]) -> str:
    aln_or_code = _normalize_text(row.get("aln_or_code")) or ""
    listing_or_award_title = _normalize_text(row.get("listing_or_award_title")) or ""
    award_description = _normalize_text(row.get("award_description")) or ""
    descriptor_blob = " ".join(part for part in (aln_or_code, listing_or_award_title, award_description) if part).lower()

    if aln_or_code == "93.323" or "epidemiology and laboratory capacity" in descriptor_blob or re.search(r"\belc\b", descriptor_blob):
        return "ELC"
    if (
        aln_or_code in {"93.268", "93.185", "93.083"}
        or "immunization" in descriptor_blob
        or "vaccine" in descriptor_blob
        or "vaccination" in descriptor_blob
    ):
        return "immunization"
    if aln_or_code == "93.069" or "preparedness" in descriptor_blob:
        return "preparedness"
    if aln_or_code in {"93.326", "93.322"} or "epidemiolog" in descriptor_blob:
        return "epidemiology"
    return "other"


def _aggregate_review_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    key_fields: Sequence[str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(_normalize_text(row.get(field)) or "" for field in key_fields)
        accumulator = grouped.setdefault(
            key,
            {
                **{field: (_normalize_text(row.get(field)) or None) for field in key_fields},
                "row_count": 0,
                "raw_amount": Decimal("0.00"),
                "normalized_amount": Decimal("0.00"),
                "residual_contribution_estimate": Decimal("0.00"),
            },
        )
        accumulator["row_count"] += 1
        accumulator["raw_amount"] += _to_decimal(row.get("raw_amount"))
        accumulator["normalized_amount"] += _to_decimal(row.get("normalized_amount"))
        accumulator["residual_contribution_estimate"] += _to_decimal(row.get("residual_contribution_estimate"))

    return sorted(
        (
            {
                **value,
                "raw_amount": _quantize_money(value["raw_amount"]),
                "normalized_amount": _quantize_money(value["normalized_amount"]),
                "residual_contribution_estimate": _quantize_money(value["residual_contribution_estimate"]),
            }
            for value in grouped.values()
        ),
        key=lambda item: (
            _to_decimal(item["residual_contribution_estimate"]),
            _to_decimal(item["raw_amount"]),
            *(_normalize_text(item.get(field)) or "" for field in key_fields),
        ),
        reverse=True,
    )


def build_fy2021_mixed_program_transfer_review_payload(
    connection: Any,
    *,
    before_snapshot_path: str | Path,
    state_code_to_name: Mapping[str, str],
) -> dict[str, Any]:
    before_snapshot = json.loads(Path(before_snapshot_path).read_text(encoding="utf-8"))
    before_lookup = {row["federal_account_symbol"]: row for row in before_snapshot.get("lookup_rows", [])}
    current_rows = _fetch_fy2021_rows(connection, state_code_to_name=state_code_to_name)

    review_rows = []
    for row in current_rows:
        if _normalize_text(row.get("multi_account_interpretation")) != "mixed_program_transfer":
            continue
        symbols = _split_account_symbols(row.get("federal_account_symbol"))
        before_row = _approx_before_row(symbols, before_lookup, row["raw_amount"])
        residual_contribution_estimate = _quantize_money(
            _to_decimal(before_row["before_normalized_amount_estimate"]) - _to_decimal(row["normalized_amount"])
        ) or Decimal("0.00")
        program_family_label = _program_family_label(row)
        review_rows.append(
            {
                **row,
                **before_row,
                "state": _normalize_text(row.get("state_name")) or _normalize_text(row.get("state_code")),
                "award_identifier": _normalize_text(row.get("source_transaction_id")),
                "award_title": _normalize_text(row.get("listing_or_award_title")) or _normalize_text(row.get("award_description")),
                "aln": _normalize_text(row.get("aln_or_code")),
                "assistance_or_contracts_stream": _normalize_text(row.get("award_type")),
                "current_inclusion_treatment": _current_inclusion_treatment(row),
                "residual_contribution_estimate": residual_contribution_estimate,
                "known_cdc_program_family": program_family_label != "other",
                "program_family_label": program_family_label,
                "program_family_heuristic_label": program_family_label,
            }
        )

    ordered_rows = sorted(
        review_rows,
        key=lambda item: (
            _to_decimal(item.get("residual_contribution_estimate")),
            _to_decimal(item.get("raw_amount")),
        ),
        reverse=True,
    )
    washington_rows = [row for row in ordered_rows if row.get("state_code") == "WA"]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(review_rows),
        "national_top_rows": ordered_rows[:250],
        "washington_rows": washington_rows,
        "summary_by_aln": _aggregate_review_rows(
            review_rows,
            key_fields=("aln_or_code", "listing_or_award_title"),
        )[:100],
        "summary_by_program_family": _aggregate_review_rows(
            review_rows,
            key_fields=("program_family_label",),
        ),
        "summary_by_federal_account_combination_key": _aggregate_review_rows(
            review_rows,
            key_fields=("federal_account_combination_key",),
        )[:100],
        "summary_by_state": _aggregate_review_rows(
            review_rows,
            key_fields=("state_code", "state_name"),
        )[:100],
        "summary_by_award_type": _aggregate_review_rows(
            review_rows,
            key_fields=("award_type",),
        ),
        "summary_by_assistance_vs_contracts": _aggregate_review_rows(
            review_rows,
            key_fields=("award_type",),
        ),
    }


def build_mixed_program_transfer_exception_recommendations_payload(
    review_payload: Mapping[str, Any],
) -> dict[str, Any]:
    summary_by_family = list(review_payload.get("summary_by_program_family", []))
    summary_by_aln = list(review_payload.get("summary_by_aln", []))
    summary_by_combination = list(review_payload.get("summary_by_federal_account_combination_key", []))
    washington_rows = list(review_payload.get("washington_rows", []))
    preferred_alns_by_family = {
        "ELC": ["93.323"],
        "immunization": ["93.268", "93.185", "D318"],
    }

    candidate_recommendations = []
    for family_name in ("ELC", "immunization"):
        family_row = next(
            (row for row in summary_by_family if _normalize_text(row.get("program_family_label")) == family_name),
            None,
        )
        if family_row is None:
            continue
        matching_alns = [
            row
            for row in summary_by_aln
            if _program_family_label(row) == family_name
        ]
        preferred_codes = preferred_alns_by_family.get(family_name, [])
        preferred_matching_alns = [
            row
            for code in preferred_codes
            for row in matching_alns
            if _normalize_text(row.get("aln_or_code")) == code
        ]
        selected_alns = []
        seen_aln_codes: set[str] = set()
        for row in preferred_matching_alns or matching_alns:
            aln_code = _normalize_text(row.get("aln_or_code"))
            if aln_code is None or aln_code in seen_aln_codes:
                continue
            seen_aln_codes.add(aln_code)
            selected_alns.append(row)
            if not preferred_matching_alns and len(selected_alns) >= 3:
                break
        top_combinations = [
            row.get("federal_account_combination_key")
            for row in summary_by_combination
            if any(
                _normalize_text(wa_row.get("program_family_label")) == family_name
                and _normalize_text(wa_row.get("federal_account_combination_key")) == _normalize_text(row.get("federal_account_combination_key"))
                for wa_row in washington_rows
            )
        ][:3]
        if not top_combinations:
            top_combinations = [
                row.get("federal_account_combination_key")
                for row in summary_by_combination[:3]
                if _normalize_text(row.get("federal_account_combination_key"))
            ]
        candidate_recommendations.append(
            {
                "status": "manual_review_only",
                "apply_in_production": False,
                "program_family_label": family_name,
                "rationale": (
                    "This family drives a large share of FY2021 mixed core-plus-transfer residuals, but the source "
                    "still does not provide an exact account-level split. A narrower exception may be worth manual "
                    "review, but not an automatic production rule."
                ),
                "proposed_conditions": {
                    "fiscal_year": 2021,
                    "award_type": "assistance",
                    "alns": [row.get("aln_or_code") for row in selected_alns if _normalize_text(row.get("aln_or_code"))],
                    "program_family_label": family_name,
                    "federal_account_combination_keys": [value for value in top_combinations if value],
                },
                "evidence": {
                    "row_count": family_row.get("row_count"),
                    "raw_amount": family_row.get("raw_amount"),
                    "normalized_amount": family_row.get("normalized_amount"),
                    "residual_contribution_estimate": family_row.get("residual_contribution_estimate"),
                },
                "reason_not_auto_applied": (
                    "The combinations still contain explicit federal-health-transfer accounts, and the public source "
                    "does not support defensible within-row dollar splits."
                ),
            }
        )

    production_change_recommended = False
    overall_assessment = (
        "FY2021 mixed_program_transfer residuals are concentrated in a small number of CDC assistance families, "
        "especially ELC and immunization, but the evidence is not strong enough to loosen the frozen production "
        "methodology automatically."
    )
    if not candidate_recommendations:
        overall_assessment = (
            "No narrow mixed_program_transfer family had enough concentrated evidence to justify even a manual-review "
            "candidate exception in this pass."
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "production_change_recommended": production_change_recommended,
        "production_methodology_should_remain_unchanged": True,
        "overall_assessment": overall_assessment,
        "candidate_recommendations": candidate_recommendations,
    }
