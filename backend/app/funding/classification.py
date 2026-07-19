from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any


DEFC_Q = "Q"
DEFC_COVID_CODES = {"L", "N", "P", "U"}
DEFC_ARP_CODES = {"V"}
DEFC_OTHER_EMERGENCY_CODES = {"C", "E", "X", "6", "AAB"}
KNOWN_NON_Q_DEFC_CODES = DEFC_COVID_CODES | DEFC_ARP_CODES | DEFC_OTHER_EMERGENCY_CODES

DEFC_CODE_RE = re.compile(r"(?:^|[;,|])\s*([A-Z0-9]{1,3})\s*:")
STRONG_PROFILE_TEXT_RE = re.compile(
    r"\bPHSSEF\b|"
    r"\bCOVID(?:-19)?\b|"
    r"\bCoronavirus\b|"
    r"\bCARES\b|"
    r"\bAmerican Rescue Plan\b|"
    r"\bARP\b|"
    r"\bHurricane Supplemental\b|"
    r"\bsupplemental\b|"
    r"\bpublic health crisis response\b",
    re.IGNORECASE,
)
VFC_RE = re.compile(r"\bVFC\b|Vaccines for Children", re.IGNORECASE)
COVID_ERA_IMMUNIZATION_TEXT_RE = re.compile(
    r"\bCOVID(?:-19)?\b|"
    r"\bCoronavirus\b|"
    r"\bpandemic\b|"
    r"\bvaccine response\b|"
    r"\bvaccine implementation\b|"
    r"\bvaccine preparedness\b|"
    r"\bARP\b|"
    r"\bAmerican Rescue Plan\b|"
    r"\bCARES\b|"
    r"\bsupplemental\b",
    re.IGNORECASE,
)


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_amount(value: Any) -> Decimal:
    token = clean_text(value)
    if not token:
        return Decimal("0")
    negative_parentheses = token.startswith("(") and token.endswith(")")
    token = token.strip("()").replace("$", "").replace(",", "").strip()
    if not token:
        return Decimal("0")
    try:
        amount = Decimal(token)
    except InvalidOperation:
        return Decimal("0")
    return -abs(amount) if negative_parentheses else amount


def parse_defc_codes(raw_value: Any) -> list[str]:
    text = clean_text(raw_value)
    if not text:
        return []
    codes = [match.group(1).upper() for match in DEFC_CODE_RE.finditer(text)]
    if not codes and ":" in text:
        possible_code = text.split(":", 1)[0].strip().upper()
        if re.fullmatch(r"[A-Z0-9]{1,3}", possible_code):
            codes = [possible_code]
    if not codes:
        for token in re.split(r"[;,|\s]+", text):
            token = token.strip().upper()
            if token in ({DEFC_Q} | KNOWN_NON_Q_DEFC_CODES):
                codes.append(token)
    deduped: list[str] = []
    for code in codes:
        if code not in deduped:
            deduped.append(code)
    return deduped


def classify_defc(codes: list[str]) -> str:
    code_set = set(codes)
    has_q = DEFC_Q in code_set
    has_non_q = bool(code_set - {DEFC_Q})
    unknown_codes = code_set - ({DEFC_Q} | KNOWN_NON_Q_DEFC_CODES)
    if not code_set or code_set == {DEFC_Q}:
        return "regular_or_not_designated"
    if unknown_codes:
        return "unknown"
    if has_non_q and not has_q:
        return "clean_supplemental_award"
    if has_q and has_non_q:
        return "mixed_regular_and_supplemental_award"
    return "unknown"


def is_likely_vfc(row: dict[str, Any]) -> bool:
    listing_number = clean_text(
        row.get("assistance_listing_number")
        or row.get("cfda_number")
    )
    listing_title = clean_text(
        row.get("assistance_listing_title")
        or row.get("cfda_title")
    ).casefold()
    description_blob = " ".join(
        clean_text(row.get(field))
        for field in (
            "transaction_description",
            "prime_award_base_transaction_description",
        )
    )
    return (
        listing_number == "93.268"
        or "immunization cooperative agreements" in listing_title
        or VFC_RE.search(description_blob) is not None
    )


def is_immunization_cooperative_agreement(row: dict[str, Any]) -> bool:
    listing_number = clean_text(
        row.get("assistance_listing_number")
        or row.get("cfda_number")
    )
    listing_title = clean_text(
        row.get("assistance_listing_title")
        or row.get("cfda_title")
    ).casefold()
    return (
        listing_number == "93.268"
        or "immunization cooperative agreements" in listing_title
    )


def is_profile_aligned_emergency_supplemental(row: dict[str, Any]) -> bool:
    haystack = " ".join(
        clean_text(row.get(field))
        for field in (
            "assistance_listing_title",
            "cfda_title",
            "transaction_description",
            "prime_award_base_transaction_description",
            "federal_accounts_funding_this_award",
            "treasury_accounts_funding_this_award",
        )
    )
    return STRONG_PROFILE_TEXT_RE.search(haystack) is not None


def is_covid_era_immunization_response(
    row: dict[str, Any],
    *,
    covid_amount: Decimal | None = None,
    defc_codes: list[str] | None = None,
) -> bool:
    try:
        fiscal_year = int(clean_text(row.get("source_fiscal_year")))
    except ValueError:
        return False
    if fiscal_year != 2021:
        return False
    if clean_text(row.get("funding_mechanism")) != "grants_cooperative_agreements":
        return False
    if not is_immunization_cooperative_agreement(row):
        return False

    effective_covid_amount = (
        covid_amount
        if covid_amount is not None
        else parse_amount(
            row.get("covid_supplemental_obligated_amount")
            or row.get("obligated_amount_from_COVID-19_supplementals_for_overall_award")
        )
    )
    effective_defc_codes = (
        defc_codes
        if defc_codes is not None
        else parse_defc_codes(row.get("disaster_emergency_fund_codes_for_overall_award"))
    )
    defc_code_set = set(effective_defc_codes)
    has_covid_era_defc = bool(defc_code_set & (DEFC_COVID_CODES | DEFC_ARP_CODES | DEFC_OTHER_EMERGENCY_CODES))
    description_blob = " ".join(
        clean_text(row.get(field))
        for field in (
            "transaction_description",
            "prime_award_base_transaction_description",
        )
    )
    return (
        effective_covid_amount > 0
        or has_covid_era_defc
        or COVID_ERA_IMMUNIZATION_TEXT_RE.search(description_blob) is not None
    )


def classify_funding_row(row: dict[str, Any]) -> dict[str, Any]:
    defc_codes = parse_defc_codes(row.get("disaster_emergency_fund_codes_for_overall_award"))
    defc_code_set = set(defc_codes)
    defc_classification = classify_defc(defc_codes)
    covid_amount = parse_amount(
        row.get("covid_supplemental_obligated_amount")
        or row.get("obligated_amount_from_COVID-19_supplementals_for_overall_award")
    )
    iija_amount = parse_amount(
        row.get("iija_supplemental_obligated_amount")
        or row.get("obligated_amount_from_IIJA_supplemental_for_overall_award")
    )
    has_defc_non_q = bool(defc_code_set - {DEFC_Q})
    likely_vfc = is_likely_vfc(row)
    profile_aligned = is_profile_aligned_emergency_supplemental(row)
    covid_era_immunization = is_covid_era_immunization_response(
        row,
        covid_amount=covid_amount,
        defc_codes=defc_codes,
    )
    has_overall_history = covid_amount > 0 or iija_amount > 0 or has_defc_non_q

    reasons: list[str] = []
    if covid_era_immunization:
        reasons.append("fy2021_covid_era_immunization_response")
    if covid_amount > 0:
        reasons.append("overall_award_covid_supplemental_amount")
    if iija_amount > 0:
        reasons.append("overall_award_iija_supplemental_amount")
    if profile_aligned:
        reasons.append("profile_aligned_emergency_supplemental")
    if defc_classification == "clean_supplemental_award":
        reasons.append("defc_clean_supplemental_award")
    elif defc_classification == "mixed_regular_and_supplemental_award":
        reasons.append("defc_mixed_supplemental_history")

    return {
        "defc_codes": defc_codes,
        "defc_classification": defc_classification,
        "has_defc_q": DEFC_Q in defc_code_set,
        "has_defc_non_q": has_defc_non_q,
        "has_defc_covid": bool(defc_code_set & DEFC_COVID_CODES),
        "has_defc_arp": bool(defc_code_set & DEFC_ARP_CODES),
        "has_defc_other_emergency": bool(defc_code_set & DEFC_OTHER_EMERGENCY_CODES),
        "has_overall_award_supplemental_history": has_overall_history,
        "is_likely_vfc": likely_vfc,
        "is_covid_era_immunization_response": covid_era_immunization,
        "is_profile_aligned_emergency_supplemental": profile_aligned,
        "funding_profiles_comparison_excluded": (
            covid_era_immunization
            or ((covid_amount > 0 or iija_amount > 0) and not likely_vfc)
        ),
        "funding_profiles_exclusion_reason": ";".join(reasons) or None,
    }
