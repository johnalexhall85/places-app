from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Index, Integer, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID

from app.db import Base
from app.db_schemas import BUDGET_SCHEMA


class CdcBudgetTrackerRaw(Base):
    __tablename__ = "cdc_budget_tracker_raw"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_file = Column(Text, nullable=False)
    source_sheet = Column(Text, nullable=False)
    ingest_batch_id = Column(UUID(as_uuid=True), nullable=False)
    ingested_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    unique_id = Column(Text, nullable=False)
    record_id = Column(Integer, nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    agency = Column(Text, nullable=True)
    sub_agency = Column(Text, nullable=True)
    program = Column(Text, nullable=True)
    sub_program = Column(Text, nullable=True)
    sub_program_2 = Column(Text, nullable=True)
    sub_program_3 = Column(Text, nullable=True)
    budget_source = Column(Text, nullable=True)
    budget_stage = Column(Text, nullable=True)
    granularity = Column(Text, nullable=True)
    amount_millions = Column(Numeric(18, 6), nullable=True)
    funding_type = Column(Text, nullable=True)
    program_status = Column(Text, nullable=True)
    is_non_add = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    source_id = Column(Text, nullable=True)
    source_page = Column(Integer, nullable=True)
    date_entered = Column(Date, nullable=True)
    entered_by = Column(Text, nullable=True)
    verified = Column(Text, nullable=True)
    crosswalk_note = Column(Text, nullable=True)

    amount_dollars = Column(Numeric(20, 2), nullable=True)
    row_hash = Column(Text, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint(
            "source_file",
            "source_sheet",
            "unique_id",
            name="uq_cdc_budget_tracker_raw_source_sheet_unique_id",
        ),
        Index("cdc_budget_tracker_raw_fiscal_year_idx", "fiscal_year"),
        Index("cdc_budget_tracker_raw_sub_agency_idx", "sub_agency"),
        Index("cdc_budget_tracker_raw_budget_source_idx", "budget_source"),
        Index("cdc_budget_tracker_raw_budget_stage_idx", "budget_stage"),
        Index("cdc_budget_tracker_raw_funding_type_idx", "funding_type"),
        Index("cdc_budget_tracker_raw_granularity_idx", "granularity"),
        Index("cdc_budget_tracker_raw_source_id_idx", "source_id"),
        Index("cdc_budget_tracker_raw_row_hash_idx", "row_hash"),
        {"schema": BUDGET_SCHEMA},
    )


class CdcBudgetSourceRegistryRaw(Base):
    __tablename__ = "cdc_budget_source_registry_raw"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_file = Column(Text, nullable=False)
    source_sheet = Column(Text, nullable=False)
    ingest_batch_id = Column(UUID(as_uuid=True), nullable=False)
    ingested_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    source_id = Column(Text, nullable=False)
    document_name = Column(Text, nullable=True)
    source_type = Column(Text, nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    agency = Column(Text, nullable=True)
    release_date = Column(Date, nullable=True)
    url = Column(Text, nullable=True)
    granularity_available = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    row_hash = Column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source_file",
            "source_sheet",
            "source_id",
            name="uq_cdc_budget_source_registry_raw_source_sheet_source_id",
        ),
        Index("cdc_budget_source_registry_raw_row_hash_idx", "row_hash"),
        {"schema": BUDGET_SCHEMA},
    )
