from __future__ import annotations


def funding_model_builder_enabled() -> bool:
    return True


def ensure_funding_model_builder_access() -> None:
    if not funding_model_builder_enabled():
        raise PermissionError("Funding Model Builder is currently unavailable.")
