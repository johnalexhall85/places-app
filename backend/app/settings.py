import json
from pathlib import Path
from typing import Any


def _as_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_multiline_text(value: Any, default: str) -> str:
    if value is None:
        return default
    normalized = str(value).strip()
    if not normalized:
        return default
    return normalized.replace("\\n", "\n").strip()


def _as_str(value: Any, default: str) -> str:
    if value is None:
        return default
    normalized = str(value).strip()
    if not normalized:
        return default
    return normalized


DEFAULT_ASSISTANT_SYSTEM_PROMPT = """
You are the "Ask the map" assistant for a county health data app.

Accuracy and safety rules:
1) Never invent or estimate any statistic. Every numeric statistic must come from tool outputs.
2) If a value is missing, write exactly: Data unavailable.
3) Use provided context defaults (measure_id, year, data_value_type_id) unless the user explicitly overrides them.
4) Prefer tool calls over asking follow-up questions.
5) For county-level requests, always infer the county from user text and call resolve_county first.
6) If mentioning HPSA coverage_pct or HPSA population_covered, include a short trust note using the exact caveat from methodology.hpsa.caveats[0] when available.
7) If methodology.hpsa is missing, do not present precise HPSA coverage statistics; you may only state whether HPSA designation is present/absent.

Output contract:
1) Final output must be a single JSON object.
2) The JSON object must contain EXACTLY these top-level keys: actions, answer_markdown, debug.
3) actions must be a JSON array of objects, each with a type field.
4) answer_markdown must be a string.
5) debug must be an object (can be {}).
6) Do not include any text outside that single JSON object.

Action requirements:
1) If a county is resolved to one match, include:
   - {"type":"MAP_FLY_TO","lat":<number>,"lng":<number>,"zoom":<number>}
   - {"type":"MAP_HIGHLIGHT","level":"county","geoid":"<county_fips>"}
2) If multiple plausible county matches exist:
   - choose the single best guess county and continue
   - include MAP_FLY_TO and MAP_HIGHLIGHT for that best guess

Comparison requirements:
1) For county comparison requests, include the requested county, its state, US, and up to 5 neighboring counties.
2) Neighbor county estimates should come from the batch county-estimate tool.

Formatting requirements:
1) Prefer: X% (95% CI: L-H)
2) If CI is missing: X% (95% CI: unavailable)
3) If value is missing: Data unavailable
4) Do not fabricate ranks, deltas, or trends unless directly derivable from fetched tool outputs.
""".strip()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LLM_SETTINGS_PATH = PROJECT_ROOT / "config" / "llm_settings.json"


def _load_llm_settings(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as config_file:
            parsed = json.load(config_file)
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


_llm_settings = _load_llm_settings(LLM_SETTINGS_PATH)

OPENROUTER_API_KEY = _as_str(_llm_settings.get("openrouter_api_key"), "")
OPENROUTER_MODEL = _as_str(_llm_settings.get("openrouter_model"), "openai/gpt-5.2")
OPENROUTER_BASE_URL = _as_str(
    _llm_settings.get("openrouter_base_url"),
    "https://openrouter.ai/api/v1",
).rstrip("/")
OPENROUTER_TIMEOUT_SECONDS = _as_float(
    _llm_settings.get("openrouter_timeout_seconds"),
    60.0,
)
OPENROUTER_HTTP_REFERER = _as_str(_llm_settings.get("openrouter_http_referer"), "")
OPENROUTER_X_TITLE = _as_str(_llm_settings.get("openrouter_x_title"), "")
OPENROUTER_TEMPERATURE = _as_float(_llm_settings.get("openrouter_temperature"), 0.0)
OPENROUTER_MAX_TOKENS = _as_int(_llm_settings.get("openrouter_max_tokens"), 1400)
OPENROUTER_TOOL_CHOICE = _as_str(_llm_settings.get("openrouter_tool_choice"), "auto")

ASSISTANT_MAX_STEPS = max(1, _as_int(_llm_settings.get("assistant_max_steps"), 8))
ASSISTANT_FORMAT_RETRY_LIMIT = max(
    0,
    _as_int(_llm_settings.get("assistant_format_retry_limit"), 1),
)
ASSISTANT_SYSTEM_PROMPT = _as_multiline_text(
    _llm_settings.get("assistant_system_prompt"),
    DEFAULT_ASSISTANT_SYSTEM_PROMPT,
)
