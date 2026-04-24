from __future__ import annotations

from decimal import Decimal
from typing import Any

ALLOCATION_TOLERANCE = Decimal("0.000001")
TRUTHY_TEXT = {"1", "true", "t", "yes", "y"}
INVALID_ACCEPTED_CATEGORIES = {"NON_ADD", "REQUEST_ONLY", "TOTAL_OR_SUBTOTAL", "UNKNOWN"}
EMERGENCY_APPROPRIATION_TYPES = {"covid_emergency", "other_emergency", "emergency"}
REVIEW_MODES = {"analyst_only", "trusted_auto", "all_master_universe"}


def quantize_decimal(value: Decimal | float | int | str | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def text_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in TRUTHY_TEXT


def effective_allocation_pct(value: Decimal | float | int | str | None) -> Decimal:
    return quantize_decimal(value) or Decimal("1.000000")


def allocated_amount(
    *,
    amount: Decimal | float | int | str | None,
    allocation_pct: Decimal | float | int | str | None,
) -> Decimal | None:
    amount_decimal = quantize_decimal(amount)
    if amount_decimal is None:
        return None
    return amount_decimal * effective_allocation_pct(allocation_pct)


def resolve_discretionary_mandatory_type(
    *,
    appropriation_category: str | None,
    signal_funding_type_mandatory: bool = False,
) -> str:
    category = str(appropriation_category or "").strip().upper()
    if category in INVALID_ACCEPTED_CATEGORIES or not category:
        return "unknown"
    if category == "MANDATORY" or signal_funding_type_mandatory:
        return "mandatory"
    return "discretionary"


def resolve_pphf_flag(*, appropriation_category: str | None, appropriation_subtype: str | None = None) -> bool:
    return (
        str(appropriation_category or "").strip().upper() == "PPHF"
        or "prevention" in str(appropriation_subtype or "").strip().lower()
    )


def resolve_transfer_flag(*, appropriation_category: str | None, appropriation_subtype: str | None = None) -> bool:
    subtype = str(appropriation_subtype or "").strip().lower()
    return str(appropriation_category or "").strip().upper() == "TRANSFER" or "transfer" in subtype


def resolve_non_add_flag(
    *,
    appropriation_category: str | None,
    signal_non_add: bool = False,
    raw_is_non_add: Any = None,
) -> bool:
    return (
        str(appropriation_category or "").strip().upper() == "NON_ADD"
        or signal_non_add
        or text_bool(raw_is_non_add)
    )


def resolve_emergency_flag(
    *,
    appropriation_category: str | None,
    appropriation_subtype: str | None = None,
    signal_keyword_emergency: bool = False,
    signal_keyword_covid: bool = False,
    signal_keyword_arp: bool = False,
    signal_keyword_cares: bool = False,
    signal_keyword_rescue_plan: bool = False,
    spending_appropriation_type: str | None = None,
    spending_is_covid_related: bool = False,
    spending_is_arpa_related: bool = False,
) -> bool:
    if str(appropriation_category or "").strip().upper() != "SUPPLEMENTAL":
        return False
    subtype = str(appropriation_subtype or "").strip().lower()
    spending_type = str(spending_appropriation_type or "").strip().lower()
    return any(
        (
            "emergency" in subtype,
            "covid" in subtype,
            signal_keyword_emergency,
            signal_keyword_covid,
            signal_keyword_arp,
            signal_keyword_cares,
            signal_keyword_rescue_plan,
            spending_is_covid_related,
            spending_is_arpa_related,
            spending_type in EMERGENCY_APPROPRIATION_TYPES,
        )
    )


def resolve_supplemental_flag(*, appropriation_category: str | None, emergency_flag: bool) -> bool:
    return str(appropriation_category or "").strip().upper() == "SUPPLEMENTAL" and not emergency_flag


def resolve_category_display_label(
    *,
    discretionary_mandatory_type: str,
    emergency_flag: bool,
    supplemental_flag: bool,
    pphf_flag: bool,
    transfer_flag: bool,
) -> str:
    if pphf_flag:
        return "PPHF"
    if transfer_flag:
        return "Transfers"
    if emergency_flag:
        return "Emergency supplemental"
    if supplemental_flag:
        return "Other supplemental"
    if discretionary_mandatory_type == "mandatory":
        return "Mandatory"
    if discretionary_mandatory_type == "discretionary":
        return "Regular discretionary"
    return "Unknown"


def resolve_filter_bucket(
    *,
    discretionary_mandatory_type: str,
    emergency_flag: bool,
    supplemental_flag: bool,
    pphf_flag: bool,
    transfer_flag: bool,
) -> str:
    if pphf_flag:
        return "pphf"
    if transfer_flag:
        return "transfer"
    if emergency_flag:
        return "emergency_supplemental"
    if supplemental_flag:
        return "other_supplemental"
    if discretionary_mandatory_type == "mandatory":
        return "mandatory"
    if discretionary_mandatory_type == "discretionary":
        return "regular_discretionary"
    return "unknown"


def trusted_auto_seed_candidate(
    *,
    resolution_status: str | None,
    auto_seeded: bool,
    analyst_reviewed: bool,
    match_tier: str | None,
    confidence_band: str | None,
    anchor_has_analyst_review_conflict: bool,
) -> bool:
    return (
        str(resolution_status or "").strip().lower() == "accepted"
        and auto_seeded
        and not analyst_reviewed
        and str(match_tier or "").strip() == "TIER_A_DETERMINISTIC"
        and str(confidence_band or "").strip().upper() == "HIGH"
        and not anchor_has_analyst_review_conflict
    )


def allocation_balance_is_balanced(status: str | None) -> bool:
    return str(status or "").strip().lower() == "balanced"


def duplicate_anchor_source_exclusion_reason(
    *,
    duplicate_source_record_count: int | None,
    duplicate_source_record_rank: int | None,
) -> str | None:
    if int(duplicate_source_record_count or 0) <= 1:
        return None
    if int(duplicate_source_record_rank or 1) <= 1:
        return None
    return "duplicate_anchor_source_noncanonical"


def invalid_accepted_category_reason(
    *,
    appropriation_category: str | None,
    non_add_flag: bool,
) -> str | None:
    category = str(appropriation_category or "").strip().upper()
    if non_add_flag or category == "NON_ADD":
        return "invalid_non_add_category"
    if category == "REQUEST_ONLY":
        return "invalid_request_only_category"
    if category == "TOTAL_OR_SUBTOTAL":
        return "invalid_total_or_subtotal_category"
    if category == "UNKNOWN" or not category:
        return "invalid_unknown_category"
    return None


def resolve_master_universe_inclusion(
    *,
    resolution_status: str | None,
    scope_include_flag: bool,
    allocation_balance_status: str | None,
    duplicate_source_record_count: int | None,
    duplicate_source_record_rank: int | None,
    appropriation_category: str | None,
    non_add_flag: bool,
    analyst_reviewed: bool,
    auto_seeded: bool,
    trusted_auto_seed_flag: bool,
) -> tuple[bool, bool, str | None, str]:
    status = str(resolution_status or "").strip().lower()
    if status not in {"accepted", "accepted_partial"} or not scope_include_flag:
        return (
            False,
            False,
            None,
            "Excluded because the row is not a current accepted or accepted_partial scope row.",
        )

    if not allocation_balance_is_balanced(allocation_balance_status):
        return (
            False,
            True,
            "unbalanced_allocation",
            "Excluded because current accepted in-scope allocations for the anchor are not balanced.",
        )

    duplicate_reason = duplicate_anchor_source_exclusion_reason(
        duplicate_source_record_count=duplicate_source_record_count,
        duplicate_source_record_rank=duplicate_source_record_rank,
    )
    if duplicate_reason is not None:
        return (
            False,
            True,
            duplicate_reason,
            "Excluded duplicate anchor/source representation to avoid double counting; only the canonical row is eligible.",
        )

    invalid_reason = invalid_accepted_category_reason(
        appropriation_category=appropriation_category,
        non_add_flag=non_add_flag,
    )
    if invalid_reason is not None:
        label = invalid_reason.removeprefix("invalid_").replace("_", " ")
        return False, False, None, f"Excluded because accepted scope rows should not carry {label}."

    if auto_seeded and not trusted_auto_seed_flag:
        return (
            False,
            False,
            None,
            "Excluded auto-seeded row because it does not meet the trusted deterministic auto-seed rules.",
        )

    if analyst_reviewed:
        if status == "accepted_partial":
            return (
                True,
                False,
                None,
                "Included analyst-reviewed accepted_partial row with allocation_pct applied to budget-grounded dollars.",
            )
        return True, False, None, "Included analyst-reviewed accepted row in the budget-grounded master universe."

    if trusted_auto_seed_flag:
        return (
            True,
            False,
            None,
            "Included trusted deterministic auto-seeded accepted row in the budget-grounded master universe.",
        )

    return True, False, None, "Included curated non-auto accepted scope row in the budget-grounded master universe."


def review_mode_allows_row(
    *,
    review_mode: str,
    include_in_master_universe: bool,
    analyst_reviewed: bool,
    trusted_auto_seed_flag: bool,
) -> bool:
    token = str(review_mode or "").strip().lower()
    if token not in REVIEW_MODES:
        raise ValueError(f"review_mode must be one of {', '.join(sorted(REVIEW_MODES))}")
    if not include_in_master_universe:
        return False
    if token == "analyst_only":
        return analyst_reviewed
    if token == "trusted_auto":
        return analyst_reviewed or trusted_auto_seed_flag
    return True


def scope_filters_allow_row(
    *,
    discretionary_mandatory_type: str,
    emergency_flag: bool,
    supplemental_flag: bool,
    pphf_flag: bool,
    transfer_flag: bool,
    include_mandatory: bool,
    include_emergency: bool,
    include_supplemental: bool,
    include_pphf: bool,
    include_transfers: bool,
) -> bool:
    if discretionary_mandatory_type == "mandatory" and not include_mandatory:
        return False
    if emergency_flag and not include_emergency:
        return False
    if supplemental_flag and not include_supplemental:
        return False
    if pphf_flag and not include_pphf:
        return False
    if transfer_flag and not include_transfers:
        return False
    return True
