from __future__ import annotations

import os


def funding_model_builder_enabled() -> bool:
    raw = os.environ.get("FUNDING_MODEL_BUILDER_ENABLED", "true").strip().lower()
    return raw not in ("false", "0", "no", "off")


def ensure_funding_model_builder_access() -> None:
    if not funding_model_builder_enabled():
        raise PermissionError("Funding Model Builder is currently unavailable.")
