from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db_fqtn import acs_table, cms_table, hrsa_table, places_table, svi_table  # noqa: E402
from app.db_schemas import (  # noqa: E402
    ACS_SCHEMA,
    CMS_SCHEMA,
    HRSA_SCHEMA,
    PLACES_SCHEMA,
    SCHEMA_BY_SOURCE,
    SVI_SCHEMA,
)

__all__ = [
    "PLACES_SCHEMA",
    "ACS_SCHEMA",
    "SVI_SCHEMA",
    "HRSA_SCHEMA",
    "CMS_SCHEMA",
    "SCHEMA_BY_SOURCE",
    "places_table",
    "acs_table",
    "svi_table",
    "hrsa_table",
    "cms_table",
]
