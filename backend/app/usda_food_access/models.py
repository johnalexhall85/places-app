from sqlalchemy import Column, DateTime, Float, Index, Integer, SmallInteger, Text, text
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base
from app.db_schemas import USDA_FOOD_ACCESS_SCHEMA


class UsdaFoodAccessTractAtlas(Base):
    __tablename__ = "tract_atlas"

    geoid = Column(Text, primary_key=True)
    state = Column(Text, nullable=True)
    county = Column(Text, nullable=True)
    urban = Column(SmallInteger, nullable=True)
    pop2010 = Column(Integer, nullable=True)

    # Curated map-first numeric subset for fast choropleths.
    low_income_tracts = Column(SmallInteger, nullable=True)
    poverty_rate = Column(Float, nullable=True)
    median_family_income = Column(Float, nullable=True)
    la1and10 = Column(Float, nullable=True)
    lahalfand10 = Column(Float, nullable=True)
    la1and20 = Column(Float, nullable=True)
    lilatracts_1and10 = Column(SmallInteger, nullable=True)
    lilatracts_halfand10 = Column(SmallInteger, nullable=True)
    lilatracts_1and20 = Column(SmallInteger, nullable=True)
    lilatracts_vehicle = Column(SmallInteger, nullable=True)
    lapop1_10 = Column(Float, nullable=True)
    lapop05_10 = Column(Float, nullable=True)
    lapop1_20 = Column(Float, nullable=True)
    lalowi1_10 = Column(Float, nullable=True)
    lalowi05_10 = Column(Float, nullable=True)
    lalowi1_20 = Column(Float, nullable=True)

    raw = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("tract_atlas_state_idx", "state"),
        Index("tract_atlas_county_idx", "county"),
        Index("tract_atlas_raw_gin_idx", "raw", postgresql_using="gin"),
        {"schema": USDA_FOOD_ACCESS_SCHEMA},
    )


class UsdaFoodAccessVariableLookup(Base):
    __tablename__ = "variable_lookup"

    field = Column(Text, primary_key=True)
    long_name = Column(Text, nullable=True)
    description = Column(Text, nullable=True)

    __table_args__ = {"schema": USDA_FOOD_ACCESS_SCHEMA}


class UsdaFoodAccessDatasetMeta(Base):
    __tablename__ = "dataset_meta"

    dataset_key = Column(Text, primary_key=True)
    source_name = Column(Text, nullable=True)
    source_url = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    vintage = Column(Text, nullable=True)
    ingested_at = Column(DateTime(timezone=False), nullable=True)
    row_count = Column(Integer, nullable=True)

    __table_args__ = {"schema": USDA_FOOD_ACCESS_SCHEMA}
