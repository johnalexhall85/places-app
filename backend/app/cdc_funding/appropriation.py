from __future__ import annotations

import re
from typing import Any

APPROPRIATION_TYPE_REGULAR = "regular"
APPROPRIATION_TYPE_COVID_EMERGENCY = "covid_emergency"
APPROPRIATION_TYPE_OTHER_EMERGENCY = "other_emergency"
APPROPRIATION_TYPE_UNKNOWN = "unknown"

APPROPRIATION_TYPES = {
    APPROPRIATION_TYPE_REGULAR,
    APPROPRIATION_TYPE_COVID_EMERGENCY,
    APPROPRIATION_TYPE_OTHER_EMERGENCY,
    APPROPRIATION_TYPE_UNKNOWN,
}

APPROPRIATION_FILTER_ALL = "all"
APPROPRIATION_FILTER_VALUES = {APPROPRIATION_FILTER_ALL, *APPROPRIATION_TYPES}
APPROPRIATION_FILTER_UI_VALUES = {
    APPROPRIATION_FILTER_ALL,
    APPROPRIATION_TYPE_REGULAR,
    APPROPRIATION_TYPE_COVID_EMERGENCY,
}

APPROPRIATION_CLASSIFICATION_SOURCE_OFFICIAL = "official_field"
APPROPRIATION_CLASSIFIER_VERSION = "v1_official_defc"
APPROPRIATION_SUBTYPE_CARES = "CARES"
APPROPRIATION_SUBTYPE_CRRSA = "CRRSA"
APPROPRIATION_SUBTYPE_ARP = "ARP"
APPROPRIATION_SUBTYPE_OTHER_COVID_EMERGENCY = "OTHER_COVID_EMERGENCY"
APPROPRIATION_SUBTYPE_OTHER_EMERGENCY = "OTHER_EMERGENCY"
APPROPRIATION_SUBTYPE_UNKNOWN = "UNKNOWN"
APPROPRIATION_SUBTYPE_MULTI_COVID = "MULTI_COVID"

_DEFC_ENTRY_RE = re.compile(r"^\s*(?P<code>[^:;]+?)\s*:\s*(?P<description>.+?)\s*$")

# Mapping is intentionally centralized and explicit for maintainability.
# These DEFC codes/public laws represent COVID-era supplemental appropriations.
_COVID_CODE_TO_SUBTYPE = {
    "L": APPROPRIATION_SUBTYPE_OTHER_COVID_EMERGENCY,
    "N": APPROPRIATION_SUBTYPE_CARES,
    "P": APPROPRIATION_SUBTYPE_OTHER_COVID_EMERGENCY,
    "U": APPROPRIATION_SUBTYPE_CRRSA,
    "V": APPROPRIATION_SUBTYPE_ARP,
}

_COVID_PUBLIC_LAW_TO_SUBTYPE = {
    "116-123": APPROPRIATION_SUBTYPE_OTHER_COVID_EMERGENCY,
    "116-136": APPROPRIATION_SUBTYPE_CARES,
    "116-139": APPROPRIATION_SUBTYPE_OTHER_COVID_EMERGENCY,
    "116-260": APPROPRIATION_SUBTYPE_CRRSA,
    "117-2": APPROPRIATION_SUBTYPE_ARP,
}

_REGULAR_CODES = {"Q"}
_OTHER_EMERGENCY_CODES = {"6", "AAB", "C", "E"}
_NOT_DESIGNATED_TOKEN = "not designated nonemergency/emergency/disaster/wildfire suppression"


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    if not token:
        return None
    return token


def _parse_defc_entries(raw_code: str) -> list[dict[str, str | None]]:
    entries: list[dict[str, str | None]] = []
    for chunk in re.split(r"\s*;\s*", raw_code):
        token = _clean_text(chunk)
        if token is None:
            continue
        match = _DEFC_ENTRY_RE.match(token)
        if match:
            code = _clean_text(match.group("code"))
            description = _clean_text(match.group("description"))
            entries.append(
                {
                    "code": code.upper() if code else None,
                    "description": description,
                }
            )
            continue
        entries.append({"code": None, "description": token})
    return entries


def extract_defc_codes(raw_emergency_code: Any) -> tuple[str, ...]:
    raw_code = _clean_text(raw_emergency_code)
    if raw_code is None:
        return ()
    return tuple(
        code
        for code in (
            _clean_text(entry.get("code"))
            for entry in _parse_defc_entries(raw_code)
        )
        if code
    )


def _covid_subtype_for_entry(entry: dict[str, str | None]) -> str | None:
    code = _clean_text(entry.get("code"))
    if code:
        mapped = _COVID_CODE_TO_SUBTYPE.get(code.upper())
        if mapped:
            return mapped

    description = _clean_text(entry.get("description"))
    if not description:
        return None
    for public_law, subtype in _COVID_PUBLIC_LAW_TO_SUBTYPE.items():
        if public_law in description:
            return subtype
    return None


def _extract_public_law(description: str | None) -> str | None:
    if not description:
        return None
    match = re.search(r"p\.l\.\s*(\d+-\d+)", description, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def classify_official_emergency_code(raw_emergency_code: Any) -> dict[str, str | None]:
    raw_code = _clean_text(raw_emergency_code)
    if raw_code is None:
        return {
            "raw_emergency_code": None,
            "appropriation_type": APPROPRIATION_TYPE_REGULAR,
            "appropriation_subtype": None,
            "appropriation_reason_code": "blank_or_null_code",
            "classification_source": APPROPRIATION_CLASSIFICATION_SOURCE_OFFICIAL,
            "classifier_version": APPROPRIATION_CLASSIFIER_VERSION,
        }

    entries = _parse_defc_entries(raw_code)
    if not entries:
        return {
            "raw_emergency_code": raw_code,
            "appropriation_type": APPROPRIATION_TYPE_UNKNOWN,
            "appropriation_subtype": APPROPRIATION_SUBTYPE_UNKNOWN,
            "appropriation_reason_code": "unparseable_code",
            "classification_source": APPROPRIATION_CLASSIFICATION_SOURCE_OFFICIAL,
            "classifier_version": APPROPRIATION_CLASSIFIER_VERSION,
        }

    covid_subtypes: set[str] = set()
    has_other_emergency = False
    has_unknown_tokens = False
    other_emergency_code: str | None = None

    for entry in entries:
        covid_subtype = _covid_subtype_for_entry(entry)
        if covid_subtype:
            covid_subtypes.add(covid_subtype)
            continue

        code = _clean_text(entry.get("code"))
        normalized_code = code.upper() if code else None
        description = _clean_text(entry.get("description"))
        description_lower = (description or "").lower()
        public_law = _extract_public_law(description)

        is_regular_entry = (
            normalized_code in _REGULAR_CODES
            or _NOT_DESIGNATED_TOKEN in description_lower
        )
        if is_regular_entry:
            continue

        is_other_emergency = (
            normalized_code in _OTHER_EMERGENCY_CODES
            or (
                "emergency p.l." in description_lower
                and public_law not in _COVID_PUBLIC_LAW_TO_SUBTYPE
            )
            or "disaster" in description_lower
            or "wildfire" in description_lower
        )
        if is_other_emergency:
            has_other_emergency = True
            if other_emergency_code is None:
                other_emergency_code = normalized_code
            continue

        has_unknown_tokens = True

    if covid_subtypes:
        subtype = (
            next(iter(covid_subtypes))
            if len(covid_subtypes) == 1
            else APPROPRIATION_SUBTYPE_MULTI_COVID
        )
        return {
            "raw_emergency_code": raw_code,
            "appropriation_type": APPROPRIATION_TYPE_COVID_EMERGENCY,
            "appropriation_subtype": subtype,
            "appropriation_reason_code": "covid_code_detected",
            "classification_source": APPROPRIATION_CLASSIFICATION_SOURCE_OFFICIAL,
            "classifier_version": APPROPRIATION_CLASSIFIER_VERSION,
        }

    if has_other_emergency:
        return {
            "raw_emergency_code": raw_code,
            "appropriation_type": APPROPRIATION_TYPE_OTHER_EMERGENCY,
            "appropriation_subtype": APPROPRIATION_SUBTYPE_OTHER_EMERGENCY,
            "appropriation_reason_code": (
                f"other_emergency_code_{other_emergency_code.lower()}"
                if other_emergency_code
                else "other_emergency_detected"
            ),
            "classification_source": APPROPRIATION_CLASSIFICATION_SOURCE_OFFICIAL,
            "classifier_version": APPROPRIATION_CLASSIFIER_VERSION,
        }

    if has_unknown_tokens:
        return {
            "raw_emergency_code": raw_code,
            "appropriation_type": APPROPRIATION_TYPE_UNKNOWN,
            "appropriation_subtype": APPROPRIATION_SUBTYPE_UNKNOWN,
            "appropriation_reason_code": "unmapped_code_value",
            "classification_source": APPROPRIATION_CLASSIFICATION_SOURCE_OFFICIAL,
            "classifier_version": APPROPRIATION_CLASSIFIER_VERSION,
        }

    return {
        "raw_emergency_code": raw_code,
        "appropriation_type": APPROPRIATION_TYPE_REGULAR,
        "appropriation_subtype": None,
        "appropriation_reason_code": "regular_not_designated",
        "classification_source": APPROPRIATION_CLASSIFICATION_SOURCE_OFFICIAL,
        "classifier_version": APPROPRIATION_CLASSIFIER_VERSION,
    }
