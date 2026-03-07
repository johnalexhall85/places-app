import os

from dotenv import load_dotenv

load_dotenv()


def _schema_from_env(env_var: str, default: str) -> str:
    value = os.getenv(env_var, default)
    if value is None:
        return default
    normalized = value.strip()
    return normalized or default


PLACES_SCHEMA = _schema_from_env("PLACES_SCHEMA", "public")
ACS_SCHEMA = _schema_from_env("ACS_SCHEMA", "public")
SVI_SCHEMA = _schema_from_env("SVI_SCHEMA", "public")
HRSA_SCHEMA = _schema_from_env("HRSA_SCHEMA", "public")
CMS_SCHEMA = _schema_from_env("CMS_SCHEMA", "cms")
USDA_FOOD_ACCESS_SCHEMA = _schema_from_env("USDA_FOOD_ACCESS_SCHEMA", "usda_food_access")
USDA_FOOD_ENV_SCHEMA = _schema_from_env("USDA_FOOD_ENV_SCHEMA", "usda_food_env")
FEMA_NRI_SCHEMA = _schema_from_env("FEMA_NRI_SCHEMA", "fema_nri")
CDC_FUNDING_SCHEMA = _schema_from_env("CDC_FUNDING_SCHEMA", "cdc_funding")

SCHEMA_BY_SOURCE = {
    "places": PLACES_SCHEMA,
    "acs": ACS_SCHEMA,
    "svi": SVI_SCHEMA,
    "hrsa": HRSA_SCHEMA,
    "cms": CMS_SCHEMA,
    "usda": USDA_FOOD_ACCESS_SCHEMA,
    "usda_food_access": USDA_FOOD_ACCESS_SCHEMA,
    "usda_food_environment": USDA_FOOD_ENV_SCHEMA,
    "usda_food_env": USDA_FOOD_ENV_SCHEMA,
    "fema": FEMA_NRI_SCHEMA,
    "fema_nri": FEMA_NRI_SCHEMA,
    "fema_national_risk_index": FEMA_NRI_SCHEMA,
    "cdc": CDC_FUNDING_SCHEMA,
    "cdc_funding": CDC_FUNDING_SCHEMA,
}
