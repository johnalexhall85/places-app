"""Funding opportunity identifiers."""
import re


def nofo_key(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    key = re.sub(r'[^A-Z0-9]', '', value.upper())
    if key.startswith('CDCRFA'):
        key = key[6:]
    return key or None
