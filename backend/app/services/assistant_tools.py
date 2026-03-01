from __future__ import annotations

from typing import Any

# Tool response shapes (all include deterministic fields and never omit "found"):
# - resolve_county:
#   {
#     "found": bool,
#     "match": {
#       "county_fips": str,
#       "county_name": str,
#       "state_abbr": str,
#       "lat": float | null,
#       "lng": float | null
#     } | null,
#     "alternatives": list[{"county_fips": str, "county_name": str, "state_abbr": str}],
#     "reason": str | null
#   }
# - get_estimate_county / get_estimate_state / get_estimate_nation:
#   {
#     "found": bool,
#     "value": float | null,
#     "ci_low": float | null,
#     "ci_high": float | null,
#     "unit": "%",
#     "reason": str | null,
#     ...scope metadata...
#   }
# - get_neighbor_counties:
#   {
#     "found": bool,
#     "county_fips": str,
#     "neighbors": list[{
#       "county_fips": str,
#       "county_name": str,
#       "state_abbr": str,
#       "lat": float | null,
#       "lng": float | null
#     }],
#     "method": str,
#     "reason": str | null
#   }
# - get_estimates_for_counties:
#   {
#     "found": bool,
#     "counties": list[{
#       "county_fips": str,
#       "county_name": str | null,
#       "state_abbr": str | null,
#       "found": bool,
#       "value": float | null,
#       "ci_low": float | null,
#       "ci_high": float | null,
#       "unit": "%",
#       "reason": str | null
#     }],
#     "reason": str | null
#   }

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "resolve_county",
            "description": (
                "Resolve a county query string to a single US county. "
                "Use before estimate calls when county is not already known. "
                "If multiple candidates match, the response includes the best-guess "
                "match plus alternatives."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "County text like 'Fulton County, GA', "
                            "'Cook IL', or a 5-digit county FIPS."
                        ),
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_estimate_county",
            "description": "Fetch county estimate and confidence interval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "county_fips": {"type": "string"},
                    "measure_id": {"type": "string"},
                    "year": {"type": "integer"},
                    "data_value_type_id": {"type": "string"},
                },
                "required": [
                    "county_fips",
                    "measure_id",
                    "year",
                    "data_value_type_id",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_estimate_state",
            "description": "Fetch state estimate and confidence interval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state_abbr": {"type": "string"},
                    "measure_id": {"type": "string"},
                    "year": {"type": "integer"},
                    "data_value_type_id": {"type": "string"},
                },
                "required": [
                    "state_abbr",
                    "measure_id",
                    "year",
                    "data_value_type_id",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_estimate_nation",
            "description": "Fetch US estimate and confidence interval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "measure_id": {"type": "string"},
                    "year": {"type": "integer"},
                    "data_value_type_id": {"type": "string"},
                },
                "required": ["measure_id", "year", "data_value_type_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_neighbor_counties",
            "description": "Fetch up to k neighboring counties for comparison.",
            "parameters": {
                "type": "object",
                "properties": {
                    "county_fips": {"type": "string"},
                    "k": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 5,
                    },
                },
                "required": ["county_fips"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_estimates_for_counties",
            "description": "Batch fetch county estimates for county_fips_list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "county_fips_list": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "maxItems": 10,
                    },
                    "measure_id": {"type": "string"},
                    "year": {"type": "integer"},
                    "data_value_type_id": {"type": "string"},
                },
                "required": [
                    "county_fips_list",
                    "measure_id",
                    "year",
                    "data_value_type_id",
                ],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_hpsa_county_summary",
            "description": (
                "Fetch county-level HRSA HPSA summary including a structured methodology "
                "trust object sourced from county_hpsa_summary metadata."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "county_fips": {"type": "string"},
                },
                "required": ["county_fips"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_full_profile",
            "description": (
                "Generate or reuse a cached full profile for a county/tract using internal "
                "PLACES and ACS NMF data, plus HPSA methodology context when available. "
                "Returns profile_id and summary text."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "geography": {
                        "type": "string",
                        "enum": ["county", "tract"],
                        "description": "Geography level for profile generation.",
                    },
                    "location_id": {
                        "type": "string",
                        "description": "County FIPS (5 chars) or tract GEOID (11 chars).",
                    },
                    "places_year": {"type": "integer"},
                    "places_measure_id": {"type": "string"},
                    "places_data_value_type_id": {"type": "string"},
                    "acs_year_window": {
                        "type": "string",
                        "description": "ACS year window like '2019-2023'.",
                    },
                    "acs_data_value_type_id": {"type": "string"},
                    "include_charts": {"type": "boolean", "default": True},
                    "include_full_narrative": {"type": "boolean", "default": True},
                    "include_profile_json": {
                        "type": "boolean",
                        "default": False,
                        "description": "Include the full profile_json in tool output.",
                    },
                },
                "required": ["location_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_profile",
            "description": (
                "Fetch stored full profile JSON by profile_id. "
                "profile_json may include methodology.hpsa when available."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "profile_id": {"type": "string"},
                },
                "required": ["profile_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_profile_pdf",
            "description": "Generate/reuse profile PDF for profile_id and return its URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "profile_id": {"type": "string"},
                },
                "required": ["profile_id"],
                "additionalProperties": False,
            },
        },
    },
]
