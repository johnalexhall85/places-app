from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Text,
    ForeignKey,
    UniqueConstraint,
    BigInteger,
)
from sqlalchemy.orm import relationship
from geoalchemy2 import Geometry

from .db import Base


class DimCounty(Base):
    __tablename__ = "dim_county"

    location_id = Column(String, primary_key=True)  # e.g., "01001"
    state_abbr = Column(String(2), nullable=False)
    state_desc = Column(String, nullable=False)
    county_name = Column(String, nullable=False)

    total_population = Column(BigInteger, nullable=True)
    total_pop_18_plus = Column(BigInteger, nullable=True)

    # centroid from CSV Geolocation POINT(lon lat)
    geom = Column(Geometry("POINT", srid=4326), nullable=True)

    estimates = relationship("FactEstimateCounty", back_populates="county")


class DimMeasure(Base):
    __tablename__ = "dim_measure"

    id = Column(Integer, primary_key=True, autoincrement=True)

    category_id = Column(String, nullable=False)
    category = Column(String, nullable=False)

    measure_id = Column(String, nullable=False)  # MeasureId in CSV
    measure = Column(String, nullable=False)

    data_value_type_id = Column(String, nullable=False)  # DataValueTypeID
    data_value_type = Column(String, nullable=False)

    unit = Column(String, nullable=True)
    short_question_text = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("measure_id", "data_value_type_id", name="uq_measure_type"),
    )

    estimates = relationship("FactEstimateCounty", back_populates="measure")


class FactEstimateCounty(Base):
    __tablename__ = "fact_estimate_county"

    id = Column(Integer, primary_key=True, autoincrement=True)

    year = Column(Integer, nullable=False)

    location_id = Column(String, ForeignKey("dim_county.location_id"), nullable=False)
    measure_dim_id = Column(Integer, ForeignKey("dim_measure.id"), nullable=False)

    data_value = Column(Float, nullable=True)
    low_confidence_limit = Column(Float, nullable=True)
    high_confidence_limit = Column(Float, nullable=True)

    footnote_symbol = Column(String, nullable=True)
    footnote = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("year", "location_id", "measure_dim_id", name="uq_year_county_measure"),
    )

    county = relationship("DimCounty", back_populates="estimates")
    measure = relationship("DimMeasure", back_populates="estimates")
