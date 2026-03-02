from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    text,
)

from app.db import Base
from app.db_schemas import CMS_SCHEMA


class CmsGeoDim(Base):
    __tablename__ = "geo_dim"

    geo_level = Column(Text, primary_key=True)
    geo_code = Column(Text, primary_key=True)
    geo_name = Column(Text, nullable=False)
    state_fips = Column(CHAR(2), nullable=True)
    county_fips = Column(CHAR(5), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "geo_level IN ('national','state','county')",
            name="geo_dim_geo_level_check",
        ),
        Index("geo_dim_county_fips_idx", "county_fips"),
        Index("geo_dim_state_fips_idx", "state_fips"),
        {"schema": CMS_SCHEMA},
    )


class CmsGvMeasureDim(Base):
    __tablename__ = "gv_measure_dim"

    measure_id = Column(Text, primary_key=True)
    label = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    unit = Column(Text, nullable=True)
    domain = Column(Text, nullable=True)
    source = Column(Text, nullable=False, server_default=text("'CMS FFS GV PUF'"))

    __table_args__ = {"schema": CMS_SCHEMA}


class CmsGvFact(Base):
    __tablename__ = "gv_fact"

    year = Column(SmallInteger, primary_key=True)
    geo_level = Column(Text, primary_key=True)
    geo_code = Column(Text, primary_key=True)
    age_level = Column(Text, primary_key=True)
    measure_id = Column(
        Text,
        ForeignKey(f"{CMS_SCHEMA}.gv_measure_dim.measure_id"),
        primary_key=True,
    )
    value = Column(Float, nullable=True)
    is_suppressed = Column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        ForeignKeyConstraint(
            ["geo_level", "geo_code"],
            [f"{CMS_SCHEMA}.geo_dim.geo_level", f"{CMS_SCHEMA}.geo_dim.geo_code"],
            name="gv_fact_geo_fk",
        ),
        Index(
            "gv_fact_measure_year_geo_idx",
            "measure_id",
            "year",
            "geo_level",
            "geo_code",
        ),
        Index("gv_fact_geo_year_idx", "geo_level", "geo_code", "year"),
        {"schema": CMS_SCHEMA},
    )


class CmsSspMeasureDim(Base):
    __tablename__ = "ssp_measure_dim"

    measure_id = Column(Text, primary_key=True)
    label = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    unit = Column(Text, nullable=True)
    domain = Column(Text, nullable=True)
    source = Column(
        Text,
        nullable=False,
        server_default=text("'CMS SSP County FFS PUF'"),
    )

    __table_args__ = {"schema": CMS_SCHEMA}


class CmsSspFact(Base):
    __tablename__ = "ssp_fact"

    year = Column(SmallInteger, primary_key=True)
    county_fips = Column(CHAR(5), primary_key=True)
    enrollment_type = Column(Text, primary_key=True)
    assign_window = Column(Text, primary_key=True)
    measure_id = Column(
        Text,
        ForeignKey(f"{CMS_SCHEMA}.ssp_measure_dim.measure_id"),
        primary_key=True,
    )
    value = Column(Float, nullable=True)
    is_suppressed = Column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        CheckConstraint(
            "assign_window IN ('calendar','offset')",
            name="ssp_fact_assign_window_check",
        ),
        Index("ssp_fact_county_year_idx", "county_fips", "year"),
        Index("ssp_fact_measure_year_idx", "measure_id", "year"),
        {"schema": CMS_SCHEMA},
    )
