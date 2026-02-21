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
]
