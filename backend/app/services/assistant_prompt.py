from __future__ import annotations

import json
from typing import Any

from app.settings import ASSISTANT_SYSTEM_PROMPT

SYSTEM_PROMPT = ASSISTANT_SYSTEM_PROMPT


def build_developer_context(context_dict: dict[str, Any]) -> str:
    serialized = json.dumps(context_dict, ensure_ascii=True, sort_keys=True)
    return (
        "UI context (authoritative defaults unless user explicitly overrides):\n"
        f"{serialized}\n"
        "Return only JSON with keys: actions, answer_markdown, debug."
    )
