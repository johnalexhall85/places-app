from __future__ import annotations

from geoalchemy2 import Geometry
from sqlalchemy import Column, DateTime, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base
from app.db_schemas import FEMA_NRI_SCHEMA


class FemaNriCounty(Base):
    __tablename__ = "nri_county"

    county_geoid = Column(Text, primary_key=True)
    nri_id = Column(Text, nullable=True)

    state_fips = Column(Text, nullable=False)
    county_fips = Column(Text, nullable=False)
    state_abbr = Column(Text, nullable=True)
    state_name = Column(Text, nullable=True)
    county_name = Column(Text, nullable=True)

    geom = Column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    raw = Column(JSONB, nullable=False)

    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("nri_county_state_fips_idx", "state_fips"),
        Index("nri_county_county_fips_idx", "county_fips"),
        Index("nri_county_geom_gist_idx", "geom", postgresql_using="gist"),
        Index("nri_county_raw_gin_idx", "raw", postgresql_using="gin"),
        {"schema": FEMA_NRI_SCHEMA},
    )


class FemaNriTract(Base):
    __tablename__ = "nri_tract"

    tract_geoid = Column(Text, primary_key=True)
    nri_id = Column(Text, nullable=True)

    state_fips = Column(Text, nullable=False)
    county_fips = Column(Text, nullable=False)
    county_geoid = Column(Text, nullable=False)
    tract_code = Column(Text, nullable=True)

    state_abbr = Column(Text, nullable=True)
    state_name = Column(Text, nullable=True)
    county_name = Column(Text, nullable=True)
    tract_name = Column(Text, nullable=True)

    geom = Column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    raw = Column(JSONB, nullable=False)

    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("nri_tract_state_fips_idx", "state_fips"),
        Index("nri_tract_county_fips_idx", "county_fips"),
        Index("nri_tract_county_geoid_idx", "county_geoid"),
        Index("nri_tract_geom_gist_idx", "geom", postgresql_using="gist"),
        Index("nri_tract_raw_gin_idx", "raw", postgresql_using="gin"),
        {"schema": FEMA_NRI_SCHEMA},
    )


class FemaNriDatasetMeta(Base):
    __tablename__ = "dataset_meta"

    dataset_key = Column(Text, primary_key=True)
    source_name = Column(Text, nullable=True)
    vintage = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    county_feature_count = Column(Integer, nullable=True)
    tract_feature_count = Column(Integer, nullable=True)
    county_row_count = Column(Integer, nullable=True)
    tract_row_count = Column(Integer, nullable=True)
    ingested_at = Column(DateTime(timezone=False), nullable=True)

    __table_args__ = {"schema": FEMA_NRI_SCHEMA}
