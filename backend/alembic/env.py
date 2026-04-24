from logging.config import fileConfig
import sys
from pathlib import Path
import geoalchemy2  # noqa: F401

# Ensure "backend/" is on sys.path so "import app.*" works
sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
from app.db import Base
from app import models  # noqa: F401
from app.cms import models as cms_models  # noqa: F401
from app.fema_nri import models as fema_nri_models  # noqa: F401
from app.usda_food_access import models as usda_food_access_models  # noqa: F401
from app.usda_food_env import models as usda_food_env_models  # noqa: F401
from app.cdc_funding import models as cdc_funding_models  # noqa: F401
from app.usaspending import models as usaspending_models  # noqa: F401
from app.usaspending_fed_account import models as usaspending_fed_account_models  # noqa: F401
from app.taggs import models as taggs_models  # noqa: F401
from app.cdc_profiles import models as cdc_profiles_models  # noqa: F401
from app.recon import models as recon_models  # noqa: F401
from app.funding_models import models as funding_models_models  # noqa: F401
from app.budget import models as budget_models  # noqa: F401
from app.demo_access import models as demo_access_models  # noqa: F401
target_metadata = Base.metadata

TARGET_TABLES = {
    "dim_county",
    "dim_county_boundary",
    "dim_measure",
    "fact_estimate_county",
    "tract_shapes",
    "tract_estimates",
    "acs_nmf_county_estimates",
    "acs_nmf_tract_estimates",
    "svi_measures",
    "svi_estimates_county",
    "svi_estimates_tract",
    "hpsa_designations_raw",
    "county_hpsa_summary",
    "profiles",
    "profile_assets",
    "geo_dim",
    "gv_measure_dim",
    "gv_fact",
    "ssp_measure_dim",
    "ssp_fact",
    "tract_atlas",
    "variable_lookup",
    "dataset_meta",
    "county_values",
    "state_values",
    "nri_county",
    "nri_tract",
    "prime_awards",
    "subawards",
    "raw_awards",
    "award_funding_summary",
    "state_funding_summary",
    "can_classification",
    "ingestion_runs",
    "raw_file_registry",
    "dim_federal_account",
    "fact_account_balance",
    "fact_account_pa_oc",
    "fact_award_account_breakdown",
    "prime_state_summary",
    "prime_county_summary",
    "subaward_state_summary",
    "subaward_county_summary",
    "contract_transactions_raw",
    "contract_state_year_summary",
    "contract_federal_account_inventory",
    "contract_category_rules",
    "raw_profile_rows",
    "state_year_totals",
    "methodology_documents",
    "cdc_profile_calibration",
    "normalization_rules_by_year",
    "normalized_state_funding",
    "normalization_methodology_log",
    "federal_account_lookup",
    "federal_account_observations",
    "federal_account_classification_rules",
    "assistance_transaction_accounts",
    "assistance_transaction_account_summary",
    "profile_scope_rules",
    "assistance_transactions_profile_enriched",
    "contract_transactions_profile_enriched",
    "profile_scope_transactions",
    "profile_scope_state_year_summary",
    "funding_profile_models",
    "funding_profile_versions",
    "funding_profile_build_runs",
    "funding_mode_registry",
    "cdc_budget_tracker_raw",
    "cdc_budget_source_registry_raw",
    "cdc_budget_classification_v1",
    "cdc_budget_classification_rule_registry",
    "cdc_budget_spending_bridge_v1",
    "cdc_budget_spending_bridge_rule_registry",
    "cdc_budget_spending_bridge_resolution_v1",
    "cdc_budget_spending_bridge_resolution_rule_registry",
    "cdc_budget_spending_bridge_analyst_action_v1",
    "cdc_budget_spending_bridge_analyst_reason_registry",
    "demo_access_codes",
    "demo_access_events",
    "alembic_version",
}

def include_object(object, name, type_, reflected, compare_to):
    # Only include our app tables in autogenerate.
    if type_ == "table":
        return name in TARGET_TABLES
    # indexes/constraints will be handled for included tables automatically
    return True

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.

def _render_item(type_, obj, autogen_context):
    # Ensure geoalchemy2 is imported in migration scripts when Geometry appears
    if type_ == "type" and obj.__class__.__module__.startswith("geoalchemy2"):
        autogen_context.imports.add("import geoalchemy2")
        return False  # use default rendering
    return False


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
	user_module_prefix="sa.",
	render_item=_render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
           include_object=include_object, connection=connection, target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
