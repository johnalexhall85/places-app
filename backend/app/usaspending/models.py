from sqlalchemy import Boolean, Column, Date, DateTime, Index, Integer, Numeric, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base
from app.db_schemas import USASPENDING_SCHEMA


class UsaspendingContractTransactionRaw(Base):
    __tablename__ = "contract_transactions_raw"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_file = Column(Text, nullable=False)
    source_filename = Column(Text, nullable=False)
    row_number = Column(Integer, nullable=True)
    raw_row_json = Column(JSONB, nullable=False)

    contract_transaction_unique_key = Column(Text, nullable=True)
    contract_award_unique_key = Column(Text, nullable=True)
    generated_unique_award_id = Column(Text, nullable=True)
    award_id_piid = Column(Text, nullable=True)
    parent_award_id_piid = Column(Text, nullable=True)
    modification_number = Column(Text, nullable=True)
    transaction_number = Column(Text, nullable=True)

    action_date = Column(Date, nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    transaction_obligated_amount = Column(Numeric(18, 2), nullable=True)
    total_dollars_obligated = Column(Numeric(18, 2), nullable=True)
    current_total_value_of_award = Column(Numeric(18, 2), nullable=True)
    potential_total_value_of_award = Column(Numeric(18, 2), nullable=True)

    recipient_name = Column(Text, nullable=True)
    recipient_state_code = Column(Text, nullable=True)
    recipient_state_name = Column(Text, nullable=True)
    recipient_county_name = Column(Text, nullable=True)
    recipient_city_name = Column(Text, nullable=True)
    recipient_country_code = Column(Text, nullable=True)
    recipient_country_name = Column(Text, nullable=True)
    recipient_zip = Column(Text, nullable=True)

    awarding_agency_name = Column(Text, nullable=True)
    awarding_sub_agency_name = Column(Text, nullable=True)
    funding_agency_name = Column(Text, nullable=True)
    funding_sub_agency_name = Column(Text, nullable=True)

    federal_account_symbol = Column(Text, nullable=True)
    treasury_account_symbol = Column(Text, nullable=True)
    federal_accounts_funding_this_award = Column(Text, nullable=True)
    treasury_accounts_funding_this_award = Column(Text, nullable=True)
    object_classes_funding_this_award = Column(Text, nullable=True)
    program_activities_funding_this_award = Column(Text, nullable=True)
    disaster_emergency_fund_code = Column(Text, nullable=True)
    appropriation_account = Column(Text, nullable=True)
    appropriation_type = Column(Text, nullable=True)

    award_description = Column(Text, nullable=True)
    transaction_description = Column(Text, nullable=True)
    prime_award_base_transaction_description = Column(Text, nullable=True)
    product_or_service_code = Column(Text, nullable=True)
    product_or_service_code_description = Column(Text, nullable=True)
    naics_code = Column(Text, nullable=True)
    naics_description = Column(Text, nullable=True)

    contract_award_type = Column(Text, nullable=True)
    contract_transaction_type = Column(Text, nullable=True)
    award_type = Column(Text, nullable=True)
    action_type = Column(Text, nullable=True)
    idv_type = Column(Text, nullable=True)
    idv_reference = Column(Text, nullable=True)

    legal_entity_country_code = Column(Text, nullable=True)
    legal_entity_state_code = Column(Text, nullable=True)
    normalized_recipient_state = Column(Text, nullable=True)
    normalized_federal_account_symbol = Column(Text, nullable=True)
    usaspending_permalink = Column(Text, nullable=True)

    loaded_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "source_filename",
            "row_number",
            name="uq_usaspending_contract_transactions_raw_source_row",
        ),
        Index("usaspending_contract_transactions_raw_fiscal_year_idx", "fiscal_year"),
        Index(
            "usaspending_contract_transactions_raw_recipient_state_code_idx",
            "recipient_state_code",
        ),
        Index(
            "usp_ct_raw_fas_idx",
            "federal_account_symbol",
        ),
        Index(
            "usp_ct_raw_defc_idx",
            "disaster_emergency_fund_code",
        ),
        Index(
            "usp_ct_raw_guid_idx",
            "generated_unique_award_id",
        ),
        Index("usaspending_contract_transactions_raw_award_id_piid_idx", "award_id_piid"),
        Index(
            "usaspending_contract_transactions_raw_awarding_agency_name_idx",
            "awarding_agency_name",
        ),
        Index(
            "usaspending_contract_transactions_raw_funding_agency_name_idx",
            "funding_agency_name",
        ),
        Index(
            "usp_ct_raw_psc_idx",
            "product_or_service_code",
        ),
        Index(
            "usaspending_contract_transactions_raw_contract_tx_key_idx",
            "contract_transaction_unique_key",
        ),
        Index("usaspending_contract_transactions_raw_raw_row_json_gin_idx", "raw_row_json", postgresql_using="gin"),
        {"schema": USASPENDING_SCHEMA},
    )


class UsaspendingContractStateYearSummary(Base):
    __tablename__ = "contract_state_year_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fiscal_year = Column(Integer, nullable=True)
    recipient_state_code = Column(Text, nullable=True)
    federal_account_symbol = Column(Text, nullable=True)
    funding_agency_name = Column(Text, nullable=True)
    awarding_agency_name = Column(Text, nullable=True)
    contract_category_guess = Column(Text, nullable=True)
    total_transaction_obligated_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    transaction_count = Column(Integer, nullable=False, server_default=text("0"))
    unique_award_count = Column(Integer, nullable=False, server_default=text("0"))
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("usaspending_contract_state_year_summary_fiscal_year_idx", "fiscal_year"),
        Index(
            "usaspending_contract_state_year_summary_state_fiscal_year_idx",
            "recipient_state_code",
            "fiscal_year",
        ),
        Index(
            "usaspending_contract_state_year_summary_category_idx",
            "contract_category_guess",
        ),
        {"schema": USASPENDING_SCHEMA},
    )


class UsaspendingContractFederalAccountInventory(Base):
    __tablename__ = "contract_federal_account_inventory"

    federal_account_symbol = Column(Text, primary_key=True)
    treasury_account_symbol = Column(Text, nullable=True)
    appropriation_type = Column(Text, nullable=True)
    first_fiscal_year = Column(Integer, nullable=True)
    last_fiscal_year = Column(Integer, nullable=True)
    total_transaction_obligated_amount = Column(Numeric(18, 2), nullable=True)
    transaction_count = Column(Integer, nullable=False, server_default=text("0"))
    unique_award_count = Column(Integer, nullable=False, server_default=text("0"))
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index(
            "usaspending_contract_federal_account_inventory_first_fy_idx",
            "first_fiscal_year",
        ),
        Index(
            "usaspending_contract_federal_account_inventory_last_fy_idx",
            "last_fiscal_year",
        ),
        {"schema": USASPENDING_SCHEMA},
    )


class UsaspendingContractCategoryRule(Base):
    __tablename__ = "contract_category_rules"

    rule_id = Column(Integer, primary_key=True, autoincrement=True)
    priority = Column(Integer, nullable=False)
    match_field = Column(Text, nullable=False)
    match_type = Column(Text, nullable=False)
    match_value = Column(Text, nullable=False)
    assigned_category = Column(Text, nullable=False)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "match_field",
            "match_type",
            "match_value",
            "assigned_category",
            name="uq_usaspending_contract_category_rules_match",
        ),
        Index(
            "usaspending_contract_category_rules_priority_idx",
            "priority",
        ),
        Index(
            "usaspending_contract_category_rules_active_idx",
            "is_active",
        ),
        {"schema": USASPENDING_SCHEMA},
    )


class UsaspendingIngestionRun(Base):
    __tablename__ = "ingestion_runs"

    run_id = Column(Integer, primary_key=True, autoincrement=True)
    pipeline_name = Column(Text, nullable=False)
    input_dir = Column(Text, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False)
    files_discovered = Column(Integer, nullable=False, server_default=text("0"))
    files_matched = Column(Integer, nullable=False, server_default=text("0"))
    rows_loaded = Column(Integer, nullable=False, server_default=text("0"))
    options_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    summary_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        Index("usaspending_ingestion_runs_started_at_idx", "started_at"),
        Index("usaspending_ingestion_runs_status_idx", "status"),
        {"schema": USASPENDING_SCHEMA},
    )
