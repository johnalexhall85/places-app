from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    Date,
    Numeric,
    Text,
    ForeignKey,
    UniqueConstraint,
    BigInteger,
    DateTime,
    Index,
    text,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
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


class DimCountyBoundary(Base):
    __tablename__ = "dim_county_boundary"

    location_id = Column(String, primary_key=True)  # e.g., "01001"
    geoid = Column(String, nullable=False)
    name = Column(String, nullable=False)
    statefp = Column(String, nullable=False)
    countyfp = Column(String, nullable=False)

    geom = Column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)


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


class TractShape(Base):
    __tablename__ = "tract_shapes"

    geoid11 = Column(String(11), primary_key=True)
    statefp = Column(String(2), nullable=False)
    countyfp = Column(String(3), nullable=False)
    tractce = Column(String(6), nullable=False)
    name = Column(String, nullable=True)

    geom = Column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)


class TractEstimate(Base):
    __tablename__ = "tract_estimates"

    year = Column(Integer, primary_key=True)
    locationid = Column(String(11), primary_key=True)
    measure_id = Column(String, primary_key=True)
    data_value_type_id = Column(String, primary_key=True)

    state_abbr = Column(String(2), nullable=True)
    state_desc = Column(String, nullable=True)
    county_name = Column(String, nullable=True)
    county_fips = Column(String(5), nullable=True)
    location_name = Column(String(11), nullable=True)
    data_source = Column(String, nullable=True)
    category = Column(String, nullable=True)
    category_id = Column(String, nullable=True)
    measure = Column(String, nullable=True)
    data_value_unit = Column(String, nullable=True)
    data_value_type = Column(String, nullable=True)
    data_value = Column(Float, nullable=True)
    low_confidence_limit = Column(Float, nullable=True)
    high_confidence_limit = Column(Float, nullable=True)
    total_population = Column(BigInteger, nullable=True)
    total_pop_18_plus = Column(BigInteger, nullable=True)
    short_question_text = Column(String, nullable=True)
    geolocation = Column(Geometry("POINT", srid=4326), nullable=True)


class AcsNmfCountyEstimate(Base):
    __tablename__ = "acs_nmf_county_estimates"

    id = Column(Integer, primary_key=True, autoincrement=True)

    year_window = Column(String, nullable=False)
    state_abbr = Column(String(2), nullable=False)
    location_id = Column(String, nullable=False)
    location_name = Column(String, nullable=False)
    category_id = Column(String, nullable=False)
    category = Column(String, nullable=False)
    measure_id = Column(String, nullable=False)
    measure = Column(String, nullable=False)
    data_value_type_id = Column(String, nullable=False)
    data_value_type = Column(String, nullable=False)
    data_value_unit = Column(String, nullable=True)
    data_value = Column(Float, nullable=True)
    moe = Column(Float, nullable=True)
    total_population = Column(Integer, nullable=True)
    geolocation = Column(Geometry("POINT", srid=4326), nullable=True)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "year_window",
            "location_id",
            "measure_id",
            "data_value_type_id",
            name="uq_acs_nmf_county_estimate",
        ),
        Index(
            "idx_acs_nmf_year_measure_type",
            "year_window",
            "measure_id",
            "data_value_type_id",
        ),
        Index("idx_acs_nmf_location_id", "location_id"),
        Index("idx_acs_nmf_measure_location", "measure_id", "location_id"),
    )


class AcsNmfTractEstimate(Base):
    __tablename__ = "acs_nmf_tract_estimates"

    id = Column(Integer, primary_key=True, autoincrement=True)

    year_window = Column(String, nullable=False)
    state_abbr = Column(String(2), nullable=False)
    location_id = Column(String(11), nullable=False)
    location_name = Column(String, nullable=False)
    category_id = Column(String, nullable=False)
    category = Column(String, nullable=False)
    measure_id = Column(String, nullable=False)
    measure = Column(String, nullable=False)
    data_value_type_id = Column(String, nullable=False)
    data_value_type = Column(String, nullable=False)
    data_value_unit = Column(String, nullable=True)
    data_value = Column(Float, nullable=True)
    moe = Column(Float, nullable=True)
    total_population = Column(Integer, nullable=True)
    geolocation = Column(Geometry("POINT", srid=4326), nullable=True)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "year_window",
            "location_id",
            "measure_id",
            "data_value_type_id",
            name="uq_acs_nmf_tract_estimate",
        ),
        Index(
            "idx_acs_nmf_tract_year_measure_type",
            "year_window",
            "measure_id",
            "data_value_type_id",
        ),
        Index("idx_acs_nmf_tract_location_id", "location_id"),
        Index("idx_acs_nmf_tract_measure_location", "measure_id", "location_id"),
    )


class SviMeasure(Base):
    __tablename__ = "svi_measures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    measure_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    theme = Column(String, nullable=True)
    value_type = Column(String, nullable=False)
    year = Column(Integer, nullable=False)
    geography_level = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "measure_id",
            "year",
            "geography_level",
            name="uq_svi_measure",
        ),
        Index("idx_svi_measures_year_geo", "year", "geography_level"),
    )


class SviEstimateCounty(Base):
    __tablename__ = "svi_estimates_county"

    id = Column(Integer, primary_key=True, autoincrement=True)
    geoid = Column(String(5), nullable=False)
    measure_id = Column(String, nullable=False)
    year = Column(Integer, nullable=False)
    value = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("geoid", "measure_id", "year", name="uq_svi_county_estimate"),
        Index("idx_svi_county_year_measure", "year", "measure_id"),
        Index("idx_svi_county_geoid", "geoid"),
        Index("idx_svi_county_year_geoid", "year", "geoid"),
    )


class SviEstimateTract(Base):
    __tablename__ = "svi_estimates_tract"

    id = Column(Integer, primary_key=True, autoincrement=True)
    geoid = Column(String(11), nullable=False)
    measure_id = Column(String, nullable=False)
    year = Column(Integer, nullable=False)
    value = Column(Float, nullable=True)

    __table_args__ = (
        UniqueConstraint("geoid", "measure_id", "year", name="uq_svi_tract_estimate"),
        Index("idx_svi_tract_year_measure", "year", "measure_id"),
        Index("idx_svi_tract_geoid", "geoid"),
        Index("idx_svi_tract_year_geoid", "year", "geoid"),
    )


class HpsaDesignationRaw(Base):
    __tablename__ = "hpsa_designations_raw"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    designation_type = Column(String, nullable=False)  # pc | mh | dh
    load_batch_id = Column(UUID(as_uuid=False), nullable=False)
    source_file = Column(Text, nullable=True)
    row_hash = Column(String, nullable=False)
    county_fips = Column(String(5), nullable=True)
    state_fips = Column(String(2), nullable=True)
    hpsa_score = Column(Integer, nullable=True)
    designation_status = Column(Text, nullable=True)
    designated_population = Column(Integer, nullable=True)
    geo_description = Column(Text, nullable=True)
    data = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("load_batch_id", "row_hash", name="uq_hpsa_raw_batch_rowhash"),
        Index("idx_hpsa_raw_county_type", "county_fips", "designation_type"),
        Index("idx_hpsa_raw_status", "designation_status"),
    )


class CountyHpsaSummary(Base):
    __tablename__ = "county_hpsa_summary"

    county_fips = Column(String(5), primary_key=True)
    state_fips = Column(String(2), nullable=True)

    pc_designated = Column(Boolean, nullable=False, server_default=text("false"))
    pc_hpsa_score_max = Column(Integer, nullable=True)
    pc_population_covered = Column(Integer, nullable=True)
    pc_coverage_pct = Column(Numeric(6, 3), nullable=True)

    mh_designated = Column(Boolean, nullable=False, server_default=text("false"))
    mh_hpsa_score_max = Column(Integer, nullable=True)
    mh_population_covered = Column(Integer, nullable=True)
    mh_coverage_pct = Column(Numeric(6, 3), nullable=True)

    dh_designated = Column(Boolean, nullable=False, server_default=text("false"))
    dh_hpsa_score_max = Column(Integer, nullable=True)
    dh_population_covered = Column(Integer, nullable=True)
    dh_coverage_pct = Column(Numeric(6, 3), nullable=True)

    population_denominator_type = Column(String(16), nullable=True)  # adult_18p | total
    population_denominator = Column(Integer, nullable=True)
    population_denominator_source = Column(Text, nullable=True)
    coverage_population_aggregation_method = Column(
        String(16),
        nullable=False,
        server_default=text("'MAX'"),
    )
    coverage_overlap_caveat = Column(
        Text,
        nullable=False,
        server_default=text(
            "'HPSA designated populations may overlap across partial-county, population-group, and facility designations. Population covered is aggregated conservatively using MAX to reduce double counting; coverage_pct should be interpreted as an approximate upper-bound proxy for coverage within the county.'"
        ),
    )
    coverage_pct_definition = Column(
        Text,
        nullable=False,
        server_default=text(
            "'coverage_pct = (population_covered / population_denominator) * 100, clamped to 0-100; population_denominator uses adult 18+ when available, otherwise total population.'"
        ),
    )
    pc_coverage_method = Column(
        Text,
        nullable=False,
        server_default=text(
            "'MAX designated population among active designations in county (conservative; overlaps possible)'"
        ),
    )
    mh_coverage_method = Column(
        Text,
        nullable=False,
        server_default=text(
            "'MAX designated population among active designations in county (conservative; overlaps possible)'"
        ),
    )
    dh_coverage_method = Column(
        Text,
        nullable=False,
        server_default=text(
            "'MAX designated population among active designations in county (conservative; overlaps possible)'"
        ),
    )
    raw_rows_in_county_pc = Column(Integer, nullable=True)
    raw_rows_in_county_mh = Column(Integer, nullable=True)
    raw_rows_in_county_dh = Column(Integer, nullable=True)

    as_of_date = Column(Date, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("idx_county_hpsa_summary_state_fips", "state_fips"),
    )


class HpsaDomainQuartile(Base):
    __tablename__ = "hpsa_domain_quartiles"

    domain = Column(String(2), primary_key=True)  # pc | mh | dh
    q25 = Column(Numeric(8, 3), nullable=True)
    q50 = Column(Numeric(8, 3), nullable=True)
    q75 = Column(Numeric(8, 3), nullable=True)
    n_counties = Column(Integer, nullable=False)
    as_of_date = Column(Date, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(UUID(as_uuid=False), primary_key=True)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))
    geography = Column(String(16), nullable=False)
    location_id = Column(String(16), nullable=False)
    request_signature = Column(String(64), nullable=False)
    payload_json = Column(JSONB, nullable=False)

    __table_args__ = (
        UniqueConstraint("request_signature", name="uq_profiles_request_signature"),
        Index("idx_profiles_lookup", "geography", "location_id", "created_at"),
    )

    assets = relationship(
        "ProfileAsset",
        back_populates="profile",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ProfileAsset(Base):
    __tablename__ = "profile_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(
        UUID(as_uuid=False),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_name = Column(String(160), nullable=False)
    mime_type = Column(String(120), nullable=False)
    asset_path = Column(String(512), nullable=False)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("profile_id", "asset_name", name="uq_profile_assets_name"),
        Index("idx_profile_assets_profile_id", "profile_id"),
    )

    profile = relationship("Profile", back_populates="assets")
