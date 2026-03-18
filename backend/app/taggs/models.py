from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base
from app.db_schemas import TAGGS_SCHEMA


class TaggsRawAward(Base):
    __tablename__ = "raw_awards"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source_file = Column(Text, nullable=False)
    source_filename = Column(Text, nullable=False)
    source_opdiv_hint = Column(Text, nullable=True)
    source_state_hint = Column(Text, nullable=True)
    source_is_territory_file = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    source_metadata_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    row_number_main = Column(Integer, nullable=True)

    issue_date_fiscal_year = Column(Integer, nullable=True)
    opdiv = Column(Text, nullable=True)
    program_office = Column(Text, nullable=True)
    legal_entity_name = Column(Text, nullable=True)
    legal_entity_city = Column(Text, nullable=True)
    legal_entity_state = Column(Text, nullable=True)
    legal_entity_zip_code = Column(Text, nullable=True)
    legal_entity_congressional_district = Column(Text, nullable=True)
    legal_entity_county = Column(Text, nullable=True)
    legal_entity_country = Column(Text, nullable=True)
    period_of_performance_start_date = Column(Date, nullable=True)
    period_of_performance_end_date = Column(Date, nullable=True)
    award_termination_date = Column(Date, nullable=True)
    uei = Column(Text, nullable=True)
    fon = Column(Text, nullable=True)
    metro_non_metro = Column(Text, nullable=True)
    recipient_class = Column(Text, nullable=True)
    recipient_type = Column(Text, nullable=True)
    recovery_act_flag = Column(Text, nullable=True)
    award_number = Column(Text, nullable=True)
    award_title = Column(Text, nullable=True)
    award_description = Column(Text, nullable=True)
    budget_year = Column(Integer, nullable=True)
    action_issue_date = Column(Date, nullable=True)
    award_code = Column(Text, nullable=True)
    award_class = Column(Text, nullable=True)
    award_activity_type = Column(Text, nullable=True)
    award_action_type = Column(Text, nullable=True)
    aln = Column(Text, nullable=True)
    assistance_listing_title = Column(Text, nullable=True)
    transaction_aln = Column(Text, nullable=True)
    transaction_assistance_listing_title = Column(Text, nullable=True)
    funding_fiscal_year = Column(Integer, nullable=True)
    can_code = Column(Text, nullable=True)
    distinct_award_count = Column(Integer, nullable=True)
    sum_of_actions = Column(Numeric(18, 2), nullable=True)

    legal_entity_state_normalized = Column(Text, nullable=True)
    legal_entity_county_normalized = Column(Text, nullable=True)
    legal_entity_country_normalized = Column(Text, nullable=True)
    raw_header_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    raw_row_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    loaded_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("taggs_raw_awards_funding_fiscal_year_idx", "funding_fiscal_year"),
        Index("taggs_raw_awards_issue_date_fiscal_year_idx", "issue_date_fiscal_year"),
        Index("taggs_raw_awards_award_number_idx", "award_number"),
        Index("taggs_raw_awards_can_code_idx", "can_code"),
        Index("taggs_raw_awards_program_office_idx", "program_office"),
        Index("taggs_raw_awards_opdiv_idx", "opdiv"),
        Index(
            "taggs_raw_awards_legal_entity_state_normalized_idx",
            "legal_entity_state_normalized",
        ),
        Index(
            "taggs_raw_awards_legal_entity_county_normalized_idx",
            "legal_entity_county_normalized",
        ),
        Index("taggs_raw_awards_aln_idx", "aln"),
        {"schema": TAGGS_SCHEMA},
    )


class TaggsAwardFundingSummary(Base):
    __tablename__ = "award_funding_summary"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    award_number = Column(Text, nullable=False)
    funding_fiscal_year = Column(Integer, nullable=False)
    opdiv = Column(Text, nullable=True)
    can_code = Column(Text, nullable=True)
    legal_entity_state_normalized = Column(Text, nullable=True)
    legal_entity_county_normalized = Column(Text, nullable=True)
    legal_entity_country_normalized = Column(Text, nullable=True)
    program_office = Column(Text, nullable=True)
    aln = Column(Text, nullable=True)
    assistance_listing_title = Column(Text, nullable=True)
    award_title = Column(Text, nullable=True)
    award_description = Column(Text, nullable=True)
    legal_entity_name = Column(Text, nullable=True)
    legal_entity_city = Column(Text, nullable=True)
    effective_program_name = Column(Text, nullable=True)
    effective_category = Column(Text, nullable=True)
    effective_subcategory = Column(Text, nullable=True)
    effective_mapping_method = Column(Text, nullable=True)
    funding_stream = Column(Text, nullable=True)
    appropriation_type = Column(Text, nullable=True)
    has_profile_assisted_mapping = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    has_fallback_inference = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    can_mapping_version = Column(Text, nullable=True)
    total_sum_of_actions = Column(
        Numeric(18, 2),
        nullable=False,
        server_default=text("0"),
    )
    raw_row_count = Column(Integer, nullable=False, server_default=text("0"))
    is_domestic_scope = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    refreshed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("taggs_award_funding_summary_fy_idx", "funding_fiscal_year"),
        Index(
            "taggs_award_funding_summary_state_fy_idx",
            "legal_entity_state_normalized",
            "funding_fiscal_year",
        ),
        Index("taggs_award_funding_summary_opdiv_idx", "opdiv"),
        Index("taggs_award_funding_summary_can_code_idx", "can_code"),
        Index("taggs_award_funding_summary_program_office_idx", "program_office"),
        Index("taggs_award_funding_summary_aln_idx", "aln"),
        Index("taggs_award_funding_summary_effective_category_idx", "effective_category"),
        Index("taggs_award_funding_summary_funding_stream_idx", "funding_stream"),
        Index("taggs_award_funding_summary_award_number_idx", "award_number"),
        Index("taggs_award_funding_summary_domestic_scope_idx", "is_domestic_scope"),
        {"schema": TAGGS_SCHEMA},
    )


class TaggsStateFundingSummary(Base):
    __tablename__ = "state_funding_summary"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    funding_fiscal_year = Column(Integer, nullable=False)
    legal_entity_state_normalized = Column(Text, nullable=False)
    opdiv = Column(Text, nullable=True)
    can_code = Column(Text, nullable=True)
    program_office = Column(Text, nullable=True)
    aln = Column(Text, nullable=True)
    effective_program_name = Column(Text, nullable=True)
    effective_category = Column(Text, nullable=True)
    effective_subcategory = Column(Text, nullable=True)
    effective_mapping_method = Column(Text, nullable=True)
    funding_stream = Column(Text, nullable=True)
    appropriation_type = Column(Text, nullable=True)
    has_profile_assisted_mapping = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    has_fallback_inference = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    can_mapping_version = Column(Text, nullable=True)
    total_sum_of_actions = Column(
        Numeric(18, 2),
        nullable=False,
        server_default=text("0"),
    )
    award_count = Column(Integer, nullable=False, server_default=text("0"))
    unique_recipient_count = Column(Integer, nullable=False, server_default=text("0"))
    unique_county_count = Column(Integer, nullable=False, server_default=text("0"))
    is_domestic_scope = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    refreshed_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("taggs_state_funding_summary_fy_idx", "funding_fiscal_year"),
        Index(
            "taggs_state_funding_summary_state_fy_idx",
            "legal_entity_state_normalized",
            "funding_fiscal_year",
        ),
        Index("taggs_state_funding_summary_opdiv_idx", "opdiv"),
        Index("taggs_state_funding_summary_can_code_idx", "can_code"),
        Index("taggs_state_funding_summary_program_office_idx", "program_office"),
        Index("taggs_state_funding_summary_aln_idx", "aln"),
        Index("taggs_state_funding_summary_effective_category_idx", "effective_category"),
        Index("taggs_state_funding_summary_funding_stream_idx", "funding_stream"),
        Index("taggs_state_funding_summary_domestic_scope_idx", "is_domestic_scope"),
        {"schema": TAGGS_SCHEMA},
    )


class TaggsCanClassification(Base):
    __tablename__ = "can_classification"

    can_code = Column(Text, primary_key=True)
    funding_stream = Column(Text, nullable=True)
    appropriation_type = Column(Text, nullable=True)
    category_override = Column(Text, nullable=True)
    subcategory_override = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_covid_related = Column(Boolean, nullable=True)
    is_arpa_related = Column(Boolean, nullable=True)
    is_supplemental = Column(Boolean, nullable=True)
    is_regular_appropriation = Column(Boolean, nullable=True)
    observed_first_fy = Column(Integer, nullable=True)
    observed_last_fy = Column(Integer, nullable=True)
    observed_row_count = Column(Integer, nullable=False, server_default=text("0"))
    observed_total_funding = Column(Numeric(18, 2), nullable=True)
    dominant_opdiv = Column(Text, nullable=True)
    dominant_program_office = Column(Text, nullable=True)
    dominant_aln = Column(Text, nullable=True)
    dominant_assistance_listing_title = Column(Text, nullable=True)
    profile_inferred_program_name = Column(Text, nullable=True)
    profile_inferred_category = Column(Text, nullable=True)
    profile_inferred_subcategory = Column(Text, nullable=True)
    profile_match_count = Column(Integer, nullable=True)
    profile_match_confidence = Column(Numeric(5, 2), nullable=True)
    profile_match_evidence_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    fallback_inferred_program_name = Column(Text, nullable=True)
    fallback_inferred_category = Column(Text, nullable=True)
    fallback_inferred_subcategory = Column(Text, nullable=True)
    fallback_guess_confidence = Column(Numeric(5, 2), nullable=True)
    fallback_guess_evidence_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    manual_program_name = Column(Text, nullable=True)
    manual_category = Column(Text, nullable=True)
    manual_subcategory = Column(Text, nullable=True)
    manual_notes = Column(Text, nullable=True)
    is_manually_verified = Column(
        Boolean,
        nullable=False,
        server_default=text("false"),
    )
    effective_program_name = Column(Text, nullable=True)
    effective_category = Column(Text, nullable=True)
    effective_subcategory = Column(Text, nullable=True)
    effective_mapping_method = Column(Text, nullable=True)
    can_mapping_version = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        Index("taggs_can_classification_funding_stream_idx", "funding_stream"),
        Index("taggs_can_classification_appropriation_type_idx", "appropriation_type"),
        Index("taggs_can_classification_effective_category_idx", "effective_category"),
        Index("taggs_can_classification_effective_method_idx", "effective_mapping_method"),
        {"schema": TAGGS_SCHEMA},
    )


class TaggsCanProfileMatchAudit(Base):
    __tablename__ = "can_profile_match_audit"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    can_code = Column(Text, nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    state_code = Column(Text, nullable=False)
    matched_profile_row_id = Column(BigInteger, nullable=False)
    matched_taggs_row_id = Column(BigInteger, nullable=False)
    match_score = Column(Numeric(6, 4), nullable=False)
    match_strength = Column(Text, nullable=False)
    match_method = Column(Text, nullable=True)
    evidence_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    can_mapping_version = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    __table_args__ = (
        UniqueConstraint(
            "matched_profile_row_id",
            "can_mapping_version",
            name="uq_taggs_can_profile_match_audit_profile_row_version",
        ),
        Index("taggs_can_profile_match_audit_can_idx", "can_code"),
        Index("taggs_can_profile_match_audit_fy_idx", "fiscal_year"),
        Index("taggs_can_profile_match_audit_state_idx", "state_code"),
        Index("taggs_can_profile_match_audit_strength_idx", "match_strength"),
        {"schema": TAGGS_SCHEMA},
    )


class TaggsIngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    started_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(Text, nullable=False, server_default=text("'running'"))
    input_dir = Column(Text, nullable=False)
    summary_path = Column(Text, nullable=True)
    dry_run = Column(Boolean, nullable=False, server_default=text("false"))
    truncate_requested = Column(Boolean, nullable=False, server_default=text("false"))
    drop_and_recreate = Column(Boolean, nullable=False, server_default=text("false"))
    rebuild_summaries = Column(Boolean, nullable=False, server_default=text("true"))
    rebuild_can_table = Column(Boolean, nullable=False, server_default=text("true"))
    files_discovered = Column(Integer, nullable=False, server_default=text("0"))
    files_processed = Column(Integer, nullable=False, server_default=text("0"))
    raw_main_rows_parsed = Column(BigInteger, nullable=False, server_default=text("0"))
    description_rows_paired = Column(BigInteger, nullable=False, server_default=text("0"))
    orphan_description_rows = Column(BigInteger, nullable=False, server_default=text("0"))
    raw_rows_loaded = Column(BigInteger, nullable=False, server_default=text("0"))
    award_summary_rows_loaded = Column(BigInteger, nullable=False, server_default=text("0"))
    state_summary_rows_loaded = Column(BigInteger, nullable=False, server_default=text("0"))
    distinct_can_codes = Column(Integer, nullable=False, server_default=text("0"))
    summary_json = Column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("taggs_ingestion_runs_status_idx", "status"),
        Index("taggs_ingestion_runs_started_at_idx", "started_at"),
        {"schema": TAGGS_SCHEMA},
    )
