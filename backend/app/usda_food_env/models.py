from sqlalchemy import Boolean, Column, DateTime, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base
from app.db_schemas import USDA_FOOD_ENV_SCHEMA


class UsdaFoodEnvVariableLookup(Base):
    __tablename__ = "variable_lookup"

    var_name = Column(Text, primary_key=True)
    display_name = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    category = Column(Text, nullable=True)
    level = Column(Text, nullable=False)
    unit = Column(Text, nullable=True)
    year_start = Column(Integer, nullable=True)
    year_end = Column(Integer, nullable=True)
    is_mapped = Column(Boolean, nullable=False, server_default=text("true"))
    sort_order = Column(Integer, nullable=True)
    raw = Column(JSONB, nullable=False)

    __table_args__ = {"schema": USDA_FOOD_ENV_SCHEMA}


class UsdaFoodEnvCountyValues(Base):
    __tablename__ = "county_values"

    geoid = Column(Text, primary_key=True)
    state_fips = Column(Text, nullable=False)
    county_fips = Column(Text, nullable=False)
    state_abbr = Column(Text, nullable=True)
    county_name = Column(Text, nullable=True)
    state_name = Column(Text, nullable=True)
    raw = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("county_values_state_fips_idx", "state_fips"),
        Index("county_values_raw_gin_idx", "raw", postgresql_using="gin"),
        {"schema": USDA_FOOD_ENV_SCHEMA},
    )


class UsdaFoodEnvStateValues(Base):
    __tablename__ = "state_values"

    state_fips = Column(Text, primary_key=True)
    state_abbr = Column(Text, nullable=True)
    state_name = Column(Text, nullable=True)
    raw = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("state_values_state_fips_idx", "state_fips"),
        Index("state_values_raw_gin_idx", "raw", postgresql_using="gin"),
        {"schema": USDA_FOOD_ENV_SCHEMA},
    )


class UsdaFoodEnvDatasetMeta(Base):
    __tablename__ = "dataset_meta"

    dataset_key = Column(Text, primary_key=True)
    source_name = Column(Text, nullable=True)
    vintage = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    ingested_at = Column(DateTime(timezone=False), nullable=True)
    row_count_county = Column(Integer, nullable=True)
    row_count_state = Column(Integer, nullable=True)

    __table_args__ = {"schema": USDA_FOOD_ENV_SCHEMA}
