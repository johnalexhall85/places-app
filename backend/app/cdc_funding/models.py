from sqlalchemy import Boolean, Column, Date, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base
from app.db_schemas import CDC_FUNDING_SCHEMA


class CdcPrimeAward(Base):
    __tablename__ = "prime_awards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    unique_key = Column(Text, nullable=False)
    fain = Column(Text, nullable=True)
    uri = Column(Text, nullable=True)
    recipient_name = Column(Text, nullable=True)
    recipient_state_code = Column(String(2), nullable=True)
    recipient_state_name = Column(Text, nullable=True)
    recipient_county_name = Column(Text, nullable=True)
    recipient_county_fips = Column(String(5), nullable=True)
    primary_place_of_performance_state_name = Column(Text, nullable=True)
    primary_place_of_performance_county_name = Column(Text, nullable=True)
    primary_place_of_performance_county_fips = Column(String(5), nullable=True)
    assistance_type_description = Column(Text, nullable=True)
    total_funding_amount = Column(Numeric(18, 2), nullable=True)
    total_obligated_amount = Column(Numeric(18, 2), nullable=True)
    total_outlayed_amount = Column(Numeric(18, 2), nullable=True)
    award_base_action_date = Column(Date, nullable=True)
    award_latest_action_date = Column(Date, nullable=True)
    award_latest_action_date_fiscal_year = Column(Integer, nullable=True)
    awarding_sub_agency_name = Column(Text, nullable=True)
    funding_sub_agency_name = Column(Text, nullable=True)
    awarding_office_name = Column(Text, nullable=True)
    funding_office_name = Column(Text, nullable=True)
    cfda_program_num = Column(Text, nullable=True)
    cfda_program_title = Column(Text, nullable=True)
    cfda_numbers_and_titles = Column(Text, nullable=True)
    prime_award_base_transaction_description = Column(Text, nullable=True)
    usaspending_permalink = Column(Text, nullable=True)
    recipient_state_fips_code = Column(String(2), nullable=True)
    raw = Column(JSONB, nullable=False)
    searchable_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("unique_key", name="uq_cdc_prime_awards_unique_key"),
        Index("cdc_prime_awards_fain_idx", "fain"),
        Index("cdc_prime_awards_recipient_state_code_idx", "recipient_state_code"),
        Index("cdc_prime_awards_recipient_county_fips_idx", "recipient_county_fips"),
        Index("cdc_prime_awards_fiscal_year_idx", "award_latest_action_date_fiscal_year"),
        Index("cdc_prime_awards_assistance_type_idx", "assistance_type_description"),
        Index("cdc_prime_awards_awarding_office_idx", "awarding_office_name"),
        Index("cdc_prime_awards_funding_office_idx", "funding_office_name"),
        Index("cdc_prime_awards_awarding_sub_agency_idx", "awarding_sub_agency_name"),
        Index("cdc_prime_awards_funding_sub_agency_idx", "funding_sub_agency_name"),
        Index("cdc_prime_awards_raw_gin_idx", "raw", postgresql_using="gin"),
        {"schema": CDC_FUNDING_SCHEMA},
    )


class CdcSubaward(Base):
    __tablename__ = "subawards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prime_award_unique_key = Column(Text, nullable=False)
    prime_award_fain = Column(Text, nullable=True)
    subaward_number = Column(Text, nullable=True)
    subaward_amount = Column(Numeric(18, 2), nullable=True)
    subaward_action_date = Column(Date, nullable=True)
    subaward_action_date_fiscal_year = Column(Integer, nullable=True)
    subawardee_name = Column(Text, nullable=True)
    subawardee_state_code = Column(String(2), nullable=True)
    subawardee_state_name = Column(Text, nullable=True)
    subawardee_city_name = Column(Text, nullable=True)
    subawardee_county_fips = Column(String(5), nullable=True)
    subaward_primary_place_of_performance_state_code = Column(String(2), nullable=True)
    subaward_primary_place_of_performance_state_name = Column(Text, nullable=True)
    subaward_description = Column(Text, nullable=True)
    prime_award_awarding_sub_agency_name = Column(Text, nullable=True)
    prime_award_funding_sub_agency_name = Column(Text, nullable=True)
    prime_award_awarding_office_name = Column(Text, nullable=True)
    prime_award_funding_office_name = Column(Text, nullable=True)
    prime_award_base_transaction_description = Column(Text, nullable=True)
    usaspending_permalink = Column(Text, nullable=True)
    prime_award_amount = Column(Numeric(18, 2), nullable=True)
    prime_award_total_outlayed_amount = Column(Numeric(18, 2), nullable=True)
    raw = Column(JSONB, nullable=False)
    searchable_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "prime_award_unique_key",
            "subaward_number",
            "subaward_action_date",
            "subaward_amount",
            "subawardee_name",
            name="uq_cdc_subawards_row",
        ),
        Index("cdc_subawards_prime_award_unique_key_idx", "prime_award_unique_key"),
        Index("cdc_subawards_prime_award_fain_idx", "prime_award_fain"),
        Index("cdc_subawards_state_code_idx", "subawardee_state_code"),
        Index("cdc_subawards_county_fips_idx", "subawardee_county_fips"),
        Index("cdc_subawards_fiscal_year_idx", "subaward_action_date_fiscal_year"),
        Index("cdc_subawards_awarding_office_idx", "prime_award_awarding_office_name"),
        Index("cdc_subawards_funding_office_idx", "prime_award_funding_office_name"),
        Index("cdc_subawards_awarding_sub_agency_idx", "prime_award_awarding_sub_agency_name"),
        Index("cdc_subawards_funding_sub_agency_idx", "prime_award_funding_sub_agency_name"),
        Index("cdc_subawards_raw_gin_idx", "raw", postgresql_using="gin"),
        {"schema": CDC_FUNDING_SCHEMA},
    )


class CdcPrimeTransaction(Base):
    __tablename__ = "prime_transactions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assistance_transaction_unique_key = Column(Text, nullable=False)
    assistance_award_unique_key = Column(Text, nullable=True)
    award_id_fain = Column(Text, nullable=True)
    modification_number = Column(Text, nullable=True)
    award_id_uri = Column(Text, nullable=True)
    federal_action_obligation = Column(Numeric(18, 2), nullable=True)
    total_obligated_amount = Column(Numeric(18, 2), nullable=True)
    total_outlayed_amount_for_overall_award = Column(Numeric(18, 2), nullable=True)
    action_date = Column(Date, nullable=True)
    action_date_fiscal_year = Column(Integer, nullable=True)
    awarding_sub_agency_name = Column(Text, nullable=True)
    funding_sub_agency_name = Column(Text, nullable=True)
    awarding_office_name = Column(Text, nullable=True)
    funding_office_name = Column(Text, nullable=True)
    recipient_name = Column(Text, nullable=True)
    recipient_city_name = Column(Text, nullable=True)
    recipient_county_name = Column(Text, nullable=True)
    prime_award_transaction_recipient_county_fips_code = Column(String(5), nullable=True)
    recipient_state_code = Column(String(2), nullable=True)
    recipient_state_name = Column(Text, nullable=True)
    primary_place_of_performance_county_name = Column(Text, nullable=True)
    prime_award_transaction_place_of_performance_county_fips_code = Column(String(5), nullable=True)
    primary_place_of_performance_state_name = Column(Text, nullable=True)
    assistance_type_description = Column(Text, nullable=True)
    transaction_description = Column(Text, nullable=True)
    prime_award_base_transaction_description = Column(Text, nullable=True)
    cfda_number = Column(Text, nullable=True)
    cfda_title = Column(Text, nullable=True)
    usaspending_permalink = Column(Text, nullable=True)
    raw = Column(JSONB, nullable=False)
    searchable_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "assistance_transaction_unique_key",
            name="uq_cdc_prime_transactions_assistance_transaction_unique_key",
        ),
        Index("cdc_prime_transactions_award_unique_key_idx", "assistance_award_unique_key"),
        Index("cdc_prime_transactions_transaction_unique_key_idx", "assistance_transaction_unique_key"),
        Index("cdc_prime_transactions_award_fain_idx", "award_id_fain"),
        Index("cdc_prime_transactions_fiscal_year_idx", "action_date_fiscal_year"),
        Index("cdc_prime_transactions_recipient_state_code_idx", "recipient_state_code"),
        Index(
            "cdc_prime_transactions_recipient_county_fips_idx",
            "prime_award_transaction_recipient_county_fips_code",
        ),
        Index("cdc_prime_transactions_assistance_type_idx", "assistance_type_description"),
        Index("cdc_prime_transactions_awarding_office_idx", "awarding_office_name"),
        Index("cdc_prime_transactions_funding_office_idx", "funding_office_name"),
        Index("cdc_prime_transactions_raw_gin_idx", "raw", postgresql_using="gin"),
        {"schema": CDC_FUNDING_SCHEMA},
    )


class CdcAwardScopeClassification(Base):
    __tablename__ = "award_scope_classification"

    id = Column(Integer, primary_key=True, autoincrement=True)
    assistance_award_unique_key = Column(Text, nullable=False)
    award_id_fain = Column(Text, nullable=True)
    scope_classification = Column(String(32), nullable=False)
    scope_score = Column(Integer, nullable=False, server_default=text("0"))
    scope_confidence = Column(String(16), nullable=False, server_default=text("'low'"))
    reason_codes = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    is_allocatable_to_counties = Column(Boolean, nullable=False, server_default=text("false"))
    allocation_method_default = Column(Text, nullable=True)
    classifier_version = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=False), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "assistance_award_unique_key",
            name="uq_cdc_award_scope_classification_award_key",
        ),
        Index(
            "cdc_award_scope_classification_award_key_idx",
            "assistance_award_unique_key",
        ),
        Index(
            "cdc_award_scope_classification_scope_idx",
            "scope_classification",
        ),
        Index(
            "cdc_award_scope_classification_allocatable_idx",
            "is_allocatable_to_counties",
        ),
        {"schema": CDC_FUNDING_SCHEMA},
    )


class CdcPrimeTransactionStateSummary(Base):
    __tablename__ = "prime_transaction_state_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    geography_id = Column(String(2), nullable=False)
    geography_name = Column(Text, nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    assistance_type_description = Column(Text, nullable=True)
    awarding_sub_agency_name = Column(Text, nullable=True)
    funding_sub_agency_name = Column(Text, nullable=True)
    awarding_office_name = Column(Text, nullable=True)
    funding_office_name = Column(Text, nullable=True)
    fy_obligated_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    fy_outlayed_amount_estimated = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    transaction_count = Column(Integer, nullable=False, server_default=text("0"))
    distinct_award_count = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        Index("cdc_prime_tx_state_summary_geography_idx", "geography_id"),
        Index("cdc_prime_tx_state_summary_fiscal_year_idx", "fiscal_year"),
        Index("cdc_prime_tx_state_summary_assistance_type_idx", "assistance_type_description"),
        Index("cdc_prime_tx_state_summary_awarding_office_idx", "awarding_office_name"),
        Index("cdc_prime_tx_state_summary_funding_office_idx", "funding_office_name"),
        Index("cdc_prime_tx_state_summary_awarding_sub_agency_idx", "awarding_sub_agency_name"),
        {"schema": CDC_FUNDING_SCHEMA},
    )


class CdcPrimeTransactionCountySummary(Base):
    __tablename__ = "prime_transaction_county_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    geography_id = Column(String(5), nullable=False)
    geography_name = Column(Text, nullable=True)
    state_code = Column(String(2), nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    assistance_type_description = Column(Text, nullable=True)
    awarding_sub_agency_name = Column(Text, nullable=True)
    funding_sub_agency_name = Column(Text, nullable=True)
    awarding_office_name = Column(Text, nullable=True)
    funding_office_name = Column(Text, nullable=True)
    fy_obligated_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    fy_outlayed_amount_estimated = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    transaction_count = Column(Integer, nullable=False, server_default=text("0"))
    distinct_award_count = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        Index("cdc_prime_tx_county_summary_geography_idx", "geography_id"),
        Index("cdc_prime_tx_county_summary_state_code_idx", "state_code"),
        Index("cdc_prime_tx_county_summary_fiscal_year_idx", "fiscal_year"),
        Index("cdc_prime_tx_county_summary_assistance_type_idx", "assistance_type_description"),
        Index("cdc_prime_tx_county_summary_awarding_office_idx", "awarding_office_name"),
        Index("cdc_prime_tx_county_summary_funding_office_idx", "funding_office_name"),
        Index("cdc_prime_tx_county_summary_awarding_sub_agency_idx", "awarding_sub_agency_name"),
        {"schema": CDC_FUNDING_SCHEMA},
    )


class CdcPrimeStateSummary(Base):
    __tablename__ = "prime_state_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    geography_id = Column(String(2), nullable=False)
    geography_name = Column(Text, nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    assistance_type_description = Column(Text, nullable=True)
    awarding_sub_agency_name = Column(Text, nullable=True)
    funding_sub_agency_name = Column(Text, nullable=True)
    awarding_office_name = Column(Text, nullable=True)
    funding_office_name = Column(Text, nullable=True)
    total_funding_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    total_obligated_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    total_outlayed_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    award_count = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        Index("cdc_prime_state_summary_geography_idx", "geography_id"),
        Index("cdc_prime_state_summary_fiscal_year_idx", "fiscal_year"),
        Index("cdc_prime_state_summary_assistance_type_idx", "assistance_type_description"),
        Index("cdc_prime_state_summary_awarding_office_idx", "awarding_office_name"),
        Index("cdc_prime_state_summary_funding_office_idx", "funding_office_name"),
        Index("cdc_prime_state_summary_awarding_sub_agency_idx", "awarding_sub_agency_name"),
        {"schema": CDC_FUNDING_SCHEMA},
    )


class CdcPrimeCountySummary(Base):
    __tablename__ = "prime_county_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    geography_id = Column(String(5), nullable=False)
    geography_name = Column(Text, nullable=True)
    state_code = Column(String(2), nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    assistance_type_description = Column(Text, nullable=True)
    awarding_sub_agency_name = Column(Text, nullable=True)
    funding_sub_agency_name = Column(Text, nullable=True)
    awarding_office_name = Column(Text, nullable=True)
    funding_office_name = Column(Text, nullable=True)
    total_funding_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    total_obligated_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    total_outlayed_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    award_count = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        Index("cdc_prime_county_summary_geography_idx", "geography_id"),
        Index("cdc_prime_county_summary_state_code_idx", "state_code"),
        Index("cdc_prime_county_summary_fiscal_year_idx", "fiscal_year"),
        Index("cdc_prime_county_summary_assistance_type_idx", "assistance_type_description"),
        Index("cdc_prime_county_summary_awarding_office_idx", "awarding_office_name"),
        Index("cdc_prime_county_summary_funding_office_idx", "funding_office_name"),
        Index("cdc_prime_county_summary_awarding_sub_agency_idx", "awarding_sub_agency_name"),
        {"schema": CDC_FUNDING_SCHEMA},
    )


class CdcSubawardStateSummary(Base):
    __tablename__ = "subaward_state_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    geography_id = Column(String(2), nullable=False)
    geography_name = Column(Text, nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    awarding_sub_agency_name = Column(Text, nullable=True)
    funding_sub_agency_name = Column(Text, nullable=True)
    awarding_office_name = Column(Text, nullable=True)
    funding_office_name = Column(Text, nullable=True)
    total_funding_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    total_obligated_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    total_outlayed_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    award_count = Column(Integer, nullable=False, server_default=text("0"))
    total_subaward_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    subaward_count = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        Index("cdc_subaward_state_summary_geography_idx", "geography_id"),
        Index("cdc_subaward_state_summary_fiscal_year_idx", "fiscal_year"),
        Index("cdc_subaward_state_summary_awarding_office_idx", "awarding_office_name"),
        Index("cdc_subaward_state_summary_funding_office_idx", "funding_office_name"),
        Index("cdc_subaward_state_summary_awarding_sub_agency_idx", "awarding_sub_agency_name"),
        {"schema": CDC_FUNDING_SCHEMA},
    )


class CdcSubawardCountySummary(Base):
    __tablename__ = "subaward_county_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    geography_id = Column(String(5), nullable=False)
    geography_name = Column(Text, nullable=True)
    state_code = Column(String(2), nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    awarding_sub_agency_name = Column(Text, nullable=True)
    funding_sub_agency_name = Column(Text, nullable=True)
    awarding_office_name = Column(Text, nullable=True)
    funding_office_name = Column(Text, nullable=True)
    total_funding_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    total_obligated_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    total_outlayed_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    award_count = Column(Integer, nullable=False, server_default=text("0"))
    total_subaward_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    subaward_count = Column(Integer, nullable=False, server_default=text("0"))

    __table_args__ = (
        Index("cdc_subaward_county_summary_geography_idx", "geography_id"),
        Index("cdc_subaward_county_summary_state_code_idx", "state_code"),
        Index("cdc_subaward_county_summary_fiscal_year_idx", "fiscal_year"),
        Index("cdc_subaward_county_summary_awarding_office_idx", "awarding_office_name"),
        Index("cdc_subaward_county_summary_funding_office_idx", "funding_office_name"),
        Index("cdc_subaward_county_summary_awarding_sub_agency_idx", "awarding_sub_agency_name"),
        {"schema": CDC_FUNDING_SCHEMA},
    )
