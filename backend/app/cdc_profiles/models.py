from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base
from app.db_schemas import CDC_PROFILES_SCHEMA


class CdcProfileRawRow(Base):
    __tablename__ = "raw_profile_rows"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    fiscal_year = Column(Integer, nullable=False)
    source_file_name = Column(Text, nullable=False)
    source_row_number = Column(Integer, nullable=False)
    project_number = Column(Text, nullable=True)
    reference_number = Column(Text, nullable=True)
    nofo_number = Column(Text, nullable=True)
    nofo_title = Column(Text, nullable=True)
    funding_opportunity_title = Column(Text, nullable=True)
    project_title = Column(Text, nullable=True)
    amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    category = Column(Text, nullable=True)
    subcategory = Column(Text, nullable=True)
    grantee_name = Column(Text, nullable=True)
    address = Column(Text, nullable=True)
    city = Column(Text, nullable=True)
    county = Column(Text, nullable=True)
    state_name = Column(Text, nullable=True)
    state_code = Column(String(2), nullable=True)
    zipcode = Column(Text, nullable=True)
    congressional_district = Column(Text, nullable=True)
    geography = Column(Text, nullable=True)
    grantee_type = Column(Text, nullable=True)
    covid_flag = Column(Text, nullable=True)
    raw = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "fiscal_year",
            "source_file_name",
            "source_row_number",
            name="uq_cdc_profile_raw_row_source",
        ),
        Index("cdc_profile_raw_rows_fy_idx", "fiscal_year"),
        Index("cdc_profile_raw_rows_state_code_idx", "state_code"),
        Index("cdc_profile_raw_rows_project_number_idx", "project_number"),
        Index("cdc_profile_raw_rows_category_idx", "category"),
        Index("cdc_profile_raw_rows_subcategory_idx", "subcategory"),
        {"schema": CDC_PROFILES_SCHEMA},
    )


class CdcProfileStateYearTotal(Base):
    __tablename__ = "state_year_totals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fiscal_year = Column(Integer, nullable=False)
    state_code = Column(String(2), nullable=False)
    state_name = Column(Text, nullable=True)
    amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    row_count = Column(Integer, nullable=False, server_default=text("0"))
    methodology_version = Column(Text, nullable=False)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "fiscal_year",
            "state_code",
            name="uq_cdc_profile_state_year_total",
        ),
        Index("cdc_profile_state_year_totals_fy_idx", "fiscal_year"),
        Index("cdc_profile_state_year_totals_state_code_idx", "state_code"),
        {"schema": CDC_PROFILES_SCHEMA},
    )


class CdcProfileMethodologyDocument(Base):
    __tablename__ = "methodology_documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fiscal_year = Column(Integer, nullable=False)
    document_type = Column(Text, nullable=False)
    source_file_name = Column(Text, nullable=False)
    source_path = Column(Text, nullable=False)
    sha256 = Column(Text, nullable=False)
    file_size_bytes = Column(BigInteger, nullable=False, server_default=text("0"))
    methodology_version = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "fiscal_year",
            "document_type",
            "source_file_name",
            name="uq_cdc_profile_methodology_doc",
        ),
        Index("cdc_profile_methodology_docs_fy_idx", "fiscal_year"),
        Index("cdc_profile_methodology_docs_type_idx", "document_type"),
        {"schema": CDC_PROFILES_SCHEMA},
    )
