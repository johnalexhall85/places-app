from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db_fqtn import (  # noqa: E402
    acs_table,
    cms_table,
    fema_nri_table,
    hrsa_table,
    places_table,
    svi_table,
    usda_food_access_table,
    usda_food_env_table,
)
from app.db_schemas import (  # noqa: E402
    ACS_SCHEMA,
    CMS_SCHEMA,
    FEMA_NRI_SCHEMA,
    HRSA_SCHEMA,
    PLACES_SCHEMA,
    SCHEMA_BY_SOURCE,
    SVI_SCHEMA,
    USDA_FOOD_ACCESS_SCHEMA,
    USDA_FOOD_ENV_SCHEMA,
)

__all__ = [
    "PLACES_SCHEMA",
    "ACS_SCHEMA",
    "SVI_SCHEMA",
    "HRSA_SCHEMA",
    "CMS_SCHEMA",
    "FEMA_NRI_SCHEMA",
    "USDA_FOOD_ACCESS_SCHEMA",
    "USDA_FOOD_ENV_SCHEMA",
    "SCHEMA_BY_SOURCE",
    "places_table",
    "acs_table",
    "svi_table",
    "hrsa_table",
    "cms_table",
    "fema_nri_table",
    "usda_food_access_table",
    "usda_food_env_table",
]
