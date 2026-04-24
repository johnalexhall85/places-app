from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base
from app.db_schemas import USASPENDING_FED_ACCOUNT_SCHEMA


class FedAccountRawFileRegistry(Base):
    __tablename__ = "raw_file_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fiscal_year = Column(Integer, nullable=False)
    file_path = Column(Text, nullable=False)
    file_name = Column(Text, nullable=False)
    dataset_type = Column(Text, nullable=False)
    source_agency_code = Column(Text, nullable=True)
    period_label = Column(Text, nullable=True)
    downloaded_at_from_filename = Column(DateTime(timezone=True), nullable=True)
    row_count = Column(Integer, nullable=True)
    file_hash = Column(Text, nullable=False)
    ingested_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    notes = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "dataset_type IN ("
            "'assistance_award_breakdown', "
            "'contracts_award_breakdown', "
            "'unlinked_award_breakdown', "
            "'account_balances', "
            "'pa_oc_breakdown', "
            "'unknown'"
            ")",
            name="ck_ufa_raw_file_registry_dataset_type",
        ),
        UniqueConstraint("file_hash", name="uq_ufa_raw_file_registry_file_hash"),
        UniqueConstraint("file_path", name="uq_ufa_raw_file_registry_file_path"),
        Index("ufa_raw_file_registry_fy_idx", "fiscal_year"),
        Index("ufa_raw_file_registry_type_idx", "dataset_type"),
        {"schema": USASPENDING_FED_ACCOUNT_SCHEMA},
    )


class FedAccountDimension(Base):
    __tablename__ = "dim_federal_account"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agency_identifier = Column(Text, nullable=True)
    allocation_transfer_agency_identifier = Column(Text, nullable=True)
    main_account_code = Column(Text, nullable=True)
    sub_account_code = Column(Text, nullable=True)
    treasury_account_symbol = Column(Text, nullable=True)
    federal_account_symbol = Column(Text, nullable=True)
    federal_account_name = Column(Text, nullable=True)
    account_title = Column(Text, nullable=True)
    agency_name = Column(Text, nullable=True)
    bureau_name = Column(Text, nullable=True)
    normalized_account_key = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("normalized_account_key", name="uq_ufa_dim_account_key"),
        Index("ufa_dim_federal_account_symbol_idx", "federal_account_symbol"),
        Index("ufa_dim_federal_account_name_idx", "federal_account_name"),
        {"schema": USASPENDING_FED_ACCOUNT_SCHEMA},
    )


class FedAccountBalance(Base):
    __tablename__ = "fact_account_balance"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    fiscal_year = Column(Integer, nullable=False)
    federal_account_id = Column(
        Integer,
        ForeignKey(
            f"{USASPENDING_FED_ACCOUNT_SCHEMA}.dim_federal_account.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    raw_file_id = Column(
        Integer,
        ForeignKey(f"{USASPENDING_FED_ACCOUNT_SCHEMA}.raw_file_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    budget_authority_amount = Column(Numeric(18, 2), nullable=True)
    obligations_incurred_amount = Column(Numeric(18, 2), nullable=True)
    outlay_amount = Column(Numeric(18, 2), nullable=True)
    unobligated_balance_amount = Column(Numeric(18, 2), nullable=True)
    gross_outlay_amount = Column(Numeric(18, 2), nullable=True)
    total_budgetary_resources_amount = Column(Numeric(18, 2), nullable=True)
    other_amount_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    raw_row_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("ufa_balance_fy_idx", "fiscal_year"),
        Index("ufa_balance_account_idx", "federal_account_id"),
        Index("ufa_balance_raw_file_idx", "raw_file_id"),
        {"schema": USASPENDING_FED_ACCOUNT_SCHEMA},
    )


class FedAccountPaOc(Base):
    __tablename__ = "fact_account_pa_oc"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    fiscal_year = Column(Integer, nullable=False)
    federal_account_id = Column(
        Integer,
        ForeignKey(
            f"{USASPENDING_FED_ACCOUNT_SCHEMA}.dim_federal_account.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    raw_file_id = Column(
        Integer,
        ForeignKey(f"{USASPENDING_FED_ACCOUNT_SCHEMA}.raw_file_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    program_activity_code = Column(Text, nullable=True)
    program_activity_name = Column(Text, nullable=True)
    object_class_code = Column(Text, nullable=True)
    object_class_name = Column(Text, nullable=True)
    direct_or_reimbursable = Column(Text, nullable=True)
    obligations_incurred_amount = Column(Numeric(18, 2), nullable=True)
    outlay_amount = Column(Numeric(18, 2), nullable=True)
    raw_amount_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    raw_row_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("ufa_pa_oc_fy_idx", "fiscal_year"),
        Index("ufa_pa_oc_account_idx", "federal_account_id"),
        Index("ufa_pa_oc_raw_file_idx", "raw_file_id"),
        Index("ufa_pa_oc_program_idx", "program_activity_code"),
        Index("ufa_pa_oc_object_idx", "object_class_code"),
        {"schema": USASPENDING_FED_ACCOUNT_SCHEMA},
    )


class FedAwardAccountBreakdown(Base):
    __tablename__ = "fact_award_account_breakdown"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    fiscal_year = Column(Integer, nullable=False)
    federal_account_id = Column(
        Integer,
        ForeignKey(
            f"{USASPENDING_FED_ACCOUNT_SCHEMA}.dim_federal_account.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    raw_file_id = Column(
        Integer,
        ForeignKey(f"{USASPENDING_FED_ACCOUNT_SCHEMA}.raw_file_registry.id", ondelete="CASCADE"),
        nullable=False,
    )
    award_source_type = Column(Text, nullable=False)
    award_id = Column(Text, nullable=True)
    generated_unique_award_id = Column(Text, nullable=True)
    piid = Column(Text, nullable=True)
    fain = Column(Text, nullable=True)
    uri = Column(Text, nullable=True)
    assistance_listing_number = Column(Text, nullable=True)
    recipient_name = Column(Text, nullable=True)
    recipient_uei = Column(Text, nullable=True)
    recipient_state_code = Column(Text, nullable=True)
    recipient_county_name = Column(Text, nullable=True)
    recipient_county_fips = Column(Text, nullable=True)
    place_of_performance_state_code = Column(Text, nullable=True)
    place_of_performance_county_name = Column(Text, nullable=True)
    place_of_performance_county_fips = Column(Text, nullable=True)
    awarding_agency_code = Column(Text, nullable=True)
    awarding_agency_name = Column(Text, nullable=True)
    funding_agency_code = Column(Text, nullable=True)
    funding_agency_name = Column(Text, nullable=True)
    awarding_subagency_name = Column(Text, nullable=True)
    funding_subagency_name = Column(Text, nullable=True)
    obligation_amount = Column(Numeric(18, 2), nullable=True)
    outlay_amount = Column(Numeric(18, 2), nullable=True)
    transaction_obligated_amount = Column(Numeric(18, 2), nullable=True)
    action_date = Column(Date, nullable=True)
    period_of_performance_start_date = Column(Date, nullable=True)
    period_of_performance_current_end_date = Column(Date, nullable=True)
    cfda_title = Column(Text, nullable=True)
    award_description = Column(Text, nullable=True)
    naics_code = Column(Text, nullable=True)
    naics_description = Column(Text, nullable=True)
    psc_code = Column(Text, nullable=True)
    psc_description = Column(Text, nullable=True)
    raw_amount_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    raw_row_json = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "award_source_type IN ('assistance', 'contracts', 'unlinked')",
            name="ck_ufa_award_account_source_type",
        ),
        Index("ufa_award_fy_idx", "fiscal_year"),
        Index("ufa_award_account_idx", "federal_account_id"),
        Index("ufa_award_guid_idx", "generated_unique_award_id"),
        Index("ufa_award_fain_idx", "fain"),
        Index("ufa_award_piid_idx", "piid"),
        Index("ufa_award_recipient_state_idx", "recipient_state_code"),
        Index("ufa_award_recipient_county_idx", "recipient_county_fips"),
        Index("ufa_award_pop_state_idx", "place_of_performance_state_code"),
        Index("ufa_award_pop_county_idx", "place_of_performance_county_fips"),
        Index("ufa_award_source_type_idx", "award_source_type"),
        Index("ufa_award_raw_file_idx", "raw_file_id"),
        {"schema": USASPENDING_FED_ACCOUNT_SCHEMA},
    )

