from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Index, Integer, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB

from app.db import Base
from app.db_schemas import RECON_SCHEMA


class CdcProfileCalibration(Base):
    __tablename__ = "cdc_profile_calibration"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fiscal_year = Column(Integer, nullable=False)
    state_code = Column(String(2), nullable=False)
    source_system = Column(Text, nullable=False)
    raw_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    classified_profile_scope_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    cdc_profile_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    residual_difference = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    major_difference_drivers = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    normalization_method = Column(Text, nullable=False, server_default=text("'funding_scope_reconstruction_calibration_layer'"))
    normalized_amount_target = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    raw_minus_target = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    domestic_exclusion_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    included_special_stream_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    action_duplication_adjustment = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    vfc_adjustment = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    other_identified_adjustment = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    unresolved_residual = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    normalization_factor = Column(Numeric(18, 6), nullable=True)
    methodology_version = Column(Text, nullable=False)
    confidence_note = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "fiscal_year",
            "state_code",
            "source_system",
            name="uq_recon_cdc_profile_calibration_state_year_source",
        ),
        Index("recon_cdc_profile_calibration_fy_idx", "fiscal_year"),
        Index("recon_cdc_profile_calibration_state_idx", "state_code"),
        Index("recon_cdc_profile_calibration_source_idx", "source_system"),
        {"schema": RECON_SCHEMA},
    )


class NormalizationRuleByYear(Base):
    __tablename__ = "normalization_rules_by_year"

    id = Column(Integer, primary_key=True, autoincrement=True)
    fiscal_year = Column(Integer, nullable=False)
    source_system = Column(Text, nullable=False)
    rule_name = Column(Text, nullable=False)
    rule_type = Column(Text, nullable=False)
    parameter_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    effective_start = Column(Date, nullable=True)
    effective_end = Column(Date, nullable=True)
    methodology_version = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_normalization_rules_fy_idx", "fiscal_year"),
        Index("recon_normalization_rules_source_idx", "source_system"),
        Index("recon_normalization_rules_name_idx", "rule_name"),
        {"schema": RECON_SCHEMA},
    )


class NormalizedStateFunding(Base):
    __tablename__ = "normalized_state_funding"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_system = Column(Text, nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    state_code = Column(String(2), nullable=False)
    raw_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    normalized_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    normalized_amount_type = Column(Text, nullable=False)
    normalization_method = Column(Text, nullable=False, server_default=text("'funding_scope_reconstruction_calibration_layer'"))
    funding_stream_logic_version = Column(Text, nullable=False, server_default=text("'funding_stream_logic_v2026_03_13'"))
    cdc_profile_reference_amount = Column(Numeric(18, 2), nullable=True)
    residual_amount = Column(Numeric(18, 2), nullable=True)
    residual_pct = Column(Numeric(12, 6), nullable=True)
    core_public_health_amount = Column(Numeric(18, 2), nullable=True)
    emergency_public_health_amount = Column(Numeric(18, 2), nullable=True)
    federal_health_transfer_amount = Column(Numeric(18, 2), nullable=True)
    procurement_support_scope_amount = Column(Numeric(18, 2), nullable=True)
    special_transfer_amount = Column(Numeric(18, 2), nullable=True)
    other_public_health_amount = Column(Numeric(18, 2), nullable=True)
    biomedical_research_amount = Column(Numeric(18, 2), nullable=True)
    international_health_assistance_amount = Column(Numeric(18, 2), nullable=True)
    unknown_funding_scope_amount = Column(Numeric(18, 2), nullable=True)
    funding_scope_components_json = Column(JSONB, nullable=True)
    methodology_version = Column(Text, nullable=False)
    confidence_note = Column(Text, nullable=True)
    calibration_basis = Column(Text, nullable=True)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "fiscal_year",
            "state_code",
            name="uq_recon_normalized_state_funding_source_year_state",
        ),
        Index("recon_normalized_state_funding_fy_idx", "fiscal_year"),
        Index("recon_normalized_state_funding_state_idx", "state_code"),
        Index("recon_normalized_state_funding_source_idx", "source_system"),
        {"schema": RECON_SCHEMA},
    )


class ProfileReconciliationStateYear(Base):
    __tablename__ = "profile_reconciliation_state_year"

    fiscal_year = Column(Integer, primary_key=True)
    state_code = Column(String(2), primary_key=True)
    source_system = Column(Text, primary_key=True)

    cdc_profile_amount = Column(Numeric(18, 2), nullable=True)
    reconstructed_profile_scope_amount = Column(Numeric(18, 2), nullable=True)
    raw_reconstructed_amount = Column(Numeric(18, 2), nullable=True)

    residual_amount = Column(Numeric(18, 2), nullable=True)
    residual_pct = Column(Numeric(12, 6), nullable=True)
    abs_residual_amount = Column(Numeric(18, 2), nullable=True)

    regular_appropriation_amount = Column(Numeric(18, 2), nullable=True)
    covid_emergency_amount = Column(Numeric(18, 2), nullable=True)
    arpa_amount = Column(Numeric(18, 2), nullable=True)
    other_emergency_or_disaster_amount = Column(Numeric(18, 2), nullable=True)
    non_covid_supplemental_amount = Column(Numeric(18, 2), nullable=True)
    transfer_or_special_amount = Column(Numeric(18, 2), nullable=True)
    procurement_support_amount = Column(Numeric(18, 2), nullable=True)
    unknown_stream_amount = Column(Numeric(18, 2), nullable=True)
    unknown_stream_included_amount = Column(Numeric(18, 2), nullable=True)
    core_public_health_amount = Column(Numeric(18, 2), nullable=True)
    emergency_public_health_amount = Column(Numeric(18, 2), nullable=True)
    federal_health_transfer_amount = Column(Numeric(18, 2), nullable=True)
    procurement_support_scope_amount = Column(Numeric(18, 2), nullable=True)
    special_transfer_amount = Column(Numeric(18, 2), nullable=True)
    other_public_health_amount = Column(Numeric(18, 2), nullable=True)
    biomedical_research_amount = Column(Numeric(18, 2), nullable=True)
    international_health_assistance_amount = Column(Numeric(18, 2), nullable=True)
    unknown_funding_scope_amount = Column(Numeric(18, 2), nullable=True)
    excluded_non_domestic_amount = Column(Numeric(18, 2), nullable=True)
    excluded_contract_amount = Column(Numeric(18, 2), nullable=True)
    uncertain_amount = Column(Numeric(18, 2), nullable=True)

    included_transaction_count = Column(Integer, nullable=False, server_default=text("0"))
    excluded_transaction_count = Column(Integer, nullable=False, server_default=text("0"))
    uncertain_transaction_count = Column(Integer, nullable=False, server_default=text("0"))

    calibration_status = Column(Text, nullable=True)
    confidence_label = Column(Text, nullable=True)
    methodology_version = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_profile_reconciliation_state_year_fy_idx", "fiscal_year"),
        Index("recon_profile_reconciliation_state_year_state_idx", "state_code"),
        Index("recon_profile_reconciliation_state_year_source_idx", "source_system"),
        {"schema": RECON_SCHEMA},
    )


class ProfileReconciliationDriverBreakdown(Base):
    __tablename__ = "profile_reconciliation_driver_breakdown"

    fiscal_year = Column(Integer, primary_key=True)
    state_code = Column(String(2), primary_key=True)
    source_system = Column(Text, primary_key=True)
    driver_name = Column(Text, primary_key=True)
    inclusion_status = Column(Text, primary_key=True)
    driver_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    methodology_version = Column(Text, nullable=True)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_profile_reconciliation_driver_fy_idx", "fiscal_year"),
        Index("recon_profile_reconciliation_driver_state_idx", "state_code"),
        Index("recon_profile_reconciliation_driver_source_idx", "source_system"),
        Index("recon_profile_reconciliation_driver_name_idx", "driver_name"),
        {"schema": RECON_SCHEMA},
    )


class ProfileReconciliationSummary(Base):
    __tablename__ = "profile_reconciliation_summary"

    fiscal_year = Column(Integer, primary_key=True)
    source_system = Column(Text, primary_key=True)
    state_count = Column(Integer, nullable=False, server_default=text("0"))
    avg_abs_residual_pct = Column(Numeric(12, 6), nullable=True)
    median_abs_residual_pct = Column(Numeric(12, 6), nullable=True)
    max_abs_residual_pct = Column(Numeric(12, 6), nullable=True)
    exact_window_state_count = Column(Integer, nullable=False, server_default=text("0"))
    calibrated_state_count = Column(Integer, nullable=False, server_default=text("0"))
    needs_review_state_count = Column(Integer, nullable=False, server_default=text("0"))
    sparse_state_count = Column(Integer, nullable=False, server_default=text("0"))
    total_unknown_stream_amount = Column(Numeric(18, 2), nullable=True)
    total_uncertain_amount = Column(Numeric(18, 2), nullable=True)
    methodology_version = Column(Text, nullable=True)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_profile_reconciliation_summary_source_idx", "source_system"),
        {"schema": RECON_SCHEMA},
    )


class ManualReviewExceptionOverlay(Base):
    __tablename__ = "manual_review_exception_overlay"

    review_id = Column(Text, primary_key=True)
    active = Column(Boolean, nullable=False, server_default=text("true"))
    apply_in_production = Column(Boolean, nullable=False, server_default=text("false"))
    fiscal_year = Column(Integer, nullable=True)
    assistance_only = Column(Boolean, nullable=False, server_default=text("false"))
    contracts_only = Column(Boolean, nullable=False, server_default=text("false"))
    state_code = Column(String(2), nullable=True)
    aln = Column(Text, nullable=True)
    award_family = Column(Text, nullable=True)
    federal_account_combination_key = Column(Text, nullable=True)
    current_multi_account_interpretation = Column(Text, nullable=True)
    recommended_review_disposition = Column(Text, nullable=False, server_default=text("'manual_review_only'"))
    analyst_notes = Column(Text, nullable=True)
    evidence_source = Column(Text, nullable=True)
    methodology_version = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_manual_review_exception_overlay_fy_idx", "fiscal_year"),
        Index("recon_manual_review_exception_overlay_state_idx", "state_code"),
        Index("recon_manual_review_exception_overlay_aln_idx", "aln"),
        Index("recon_manual_review_exception_overlay_family_idx", "award_family"),
        Index(
            "recon_manual_review_exception_overlay_combo_idx",
            "federal_account_combination_key",
        ),
        {"schema": RECON_SCHEMA},
    )


class NormalizationMethodologyLog(Base):
    __tablename__ = "normalization_methodology_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    methodology_version = Column(Text, nullable=False)
    logged_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    note = Column(Text, nullable=False)
    metadata_json = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    __table_args__ = (
        Index("recon_normalization_methodology_log_version_idx", "methodology_version"),
        Index("recon_normalization_methodology_log_logged_at_idx", "logged_at"),
        {"schema": RECON_SCHEMA},
    )


class DefcClassificationRule(Base):
    __tablename__ = "defc_classification_rules"

    defc_code = Column(String(16), primary_key=True)
    funding_stream = Column(Text, nullable=False)
    appropriation_type_normalized = Column(Text, nullable=True)
    is_covid_related = Column(Boolean, nullable=False, server_default=text("false"))
    is_arpa_related = Column(Boolean, nullable=False, server_default=text("false"))
    include_in_cdc_profile_scope_default = Column(Boolean, nullable=False, server_default=text("false"))
    default_inclusion_weight = Column(Numeric(5, 2), nullable=False, server_default=text("0"))
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_defc_classification_rules_stream_idx", "funding_stream"),
        {"schema": RECON_SCHEMA},
    )


class AppropriationTypeRule(Base):
    __tablename__ = "appropriation_type_rules"

    appropriation_type_raw = Column(Text, primary_key=True)
    appropriation_type_normalized = Column(Text, nullable=False)
    default_funding_stream = Column(Text, nullable=False)
    default_include_in_cdc_profile_scope = Column(Boolean, nullable=False, server_default=text("false"))
    default_inclusion_weight = Column(Numeric(5, 2), nullable=False, server_default=text("0"))
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_appropriation_type_rules_norm_idx", "appropriation_type_normalized"),
        {"schema": RECON_SCHEMA},
    )


class FederalAccountInclusionRule(Base):
    __tablename__ = "federal_account_inclusion_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    federal_account_symbol = Column(Text, nullable=True)
    treasury_account_symbol = Column(Text, nullable=True)
    program_activity_name = Column(Text, nullable=True)
    can_like_program_hint = Column(Text, nullable=True)
    default_funding_stream = Column(Text, nullable=True)
    include_in_cdc_profile_scope_default = Column(Boolean, nullable=False, server_default=text("false"))
    default_inclusion_weight = Column(Numeric(5, 2), nullable=False, server_default=text("0"))
    notes = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_federal_account_rules_symbol_idx", "federal_account_symbol"),
        Index("recon_federal_account_rules_tas_idx", "treasury_account_symbol"),
        {"schema": RECON_SCHEMA},
    )


class CdcProfileScopeRule(Base):
    __tablename__ = "cdc_profile_scope_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_system = Column(Text, nullable=False)
    funding_stream = Column(Text, nullable=True)
    can_code = Column(Text, nullable=True)
    federal_account_symbol = Column(Text, nullable=True)
    treasury_account_symbol = Column(Text, nullable=True)
    program_activity_name = Column(Text, nullable=True)
    include_in_profile_scope = Column(Boolean, nullable=False)
    inclusion_weight = Column(Numeric(5, 2), nullable=False, server_default=text("0"))
    rationale = Column(Text, nullable=False)
    methodology_version = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_cdc_profile_scope_rules_source_idx", "source_system"),
        Index("recon_cdc_profile_scope_rules_stream_idx", "funding_stream"),
        Index("recon_cdc_profile_scope_rules_can_idx", "can_code"),
        {"schema": RECON_SCHEMA},
    )


class FederalAccountLookup(Base):
    __tablename__ = "federal_account_lookup"

    federal_account_symbol = Column(Text, primary_key=True)
    agency_identifier = Column(Text, nullable=True)
    main_account_code = Column(Text, nullable=True)
    sub_account_code = Column(Text, nullable=True)
    account_title = Column(Text, nullable=True)
    account_title_normalized = Column(Text, nullable=True)
    treasury_account_group_hint = Column(Text, nullable=True)
    source_metadata_json = Column(JSONB, nullable=True)
    observed_in_contracts = Column(Boolean, nullable=False, server_default=text("false"))
    observed_in_assistance = Column(Boolean, nullable=False, server_default=text("false"))
    first_fiscal_year = Column(Integer, nullable=True)
    last_fiscal_year = Column(Integer, nullable=True)
    observed_transaction_count = Column(Integer, nullable=False, server_default=text("0"))
    observed_total_obligations = Column(Numeric(18, 2), nullable=True)
    funding_stream_guess = Column(Text, nullable=True)
    funding_scope_guess = Column(Text, nullable=True)
    funding_scope_method = Column(Text, nullable=True)
    appropriations_scope_guess = Column(Text, nullable=True)
    likely_profile_relevant = Column(Boolean, nullable=True)
    likely_core_public_health = Column(Boolean, nullable=True)
    likely_emergency_public_health = Column(Boolean, nullable=True)
    likely_federal_health_transfer = Column(Boolean, nullable=True)
    likely_procurement_support = Column(Boolean, nullable=True)
    likely_other_public_health = Column(Boolean, nullable=True)
    likely_biomedical_research = Column(Boolean, nullable=True)
    likely_international_health_assistance = Column(Boolean, nullable=True)
    likely_vfc_related = Column(Boolean, nullable=True)
    likely_emergency_related = Column(Boolean, nullable=True)
    likely_arpa_related = Column(Boolean, nullable=True)
    likely_regular_appropriation = Column(Boolean, nullable=True)
    classification_confidence = Column(Numeric(5, 2), nullable=True)
    classification_method = Column(Text, nullable=True)
    classification_notes = Column(Text, nullable=True)
    manual_funding_stream = Column(Text, nullable=True)
    manual_funding_scope = Column(Text, nullable=True)
    manual_scope_guess = Column(Text, nullable=True)
    manual_profile_relevant = Column(Boolean, nullable=True)
    manual_notes = Column(Text, nullable=True)
    is_manually_verified = Column(Boolean, nullable=False, server_default=text("false"))
    effective_funding_stream = Column(Text, nullable=True)
    effective_funding_scope = Column(Text, nullable=True)
    effective_scope_guess = Column(Text, nullable=True)
    effective_profile_relevant = Column(Boolean, nullable=True)
    effective_classification_method = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_federal_account_lookup_first_fy_idx", "first_fiscal_year"),
        Index("recon_federal_account_lookup_last_fy_idx", "last_fiscal_year"),
        Index("recon_federal_account_lookup_stream_idx", "effective_funding_stream"),
        Index("recon_federal_account_lookup_scope_idx", "effective_funding_scope"),
        Index("recon_federal_account_lookup_profile_idx", "effective_profile_relevant"),
        {"schema": RECON_SCHEMA},
    )


class FederalAccountObservation(Base):
    __tablename__ = "federal_account_observations"

    federal_account_symbol = Column(Text, primary_key=True)
    source_system = Column(Text, primary_key=True)
    fiscal_year = Column(Integer, primary_key=True)
    transaction_count = Column(Integer, nullable=False, server_default=text("0"))
    total_obligations = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    awarding_agency_name = Column(Text, nullable=True)
    funding_agency_name = Column(Text, nullable=True)
    top_psc_or_aln = Column(Text, nullable=True)
    top_description_hint = Column(Text, nullable=True)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_federal_account_observations_source_idx", "source_system"),
        Index("recon_federal_account_observations_fy_idx", "fiscal_year"),
        {"schema": RECON_SCHEMA},
    )


class FederalAccountClassificationRule(Base):
    __tablename__ = "federal_account_classification_rules"

    rule_id = Column(BigInteger, primary_key=True, autoincrement=True)
    priority = Column(Integer, nullable=False)
    match_field = Column(Text, nullable=False)
    match_type = Column(Text, nullable=False)
    match_value = Column(Text, nullable=False)
    assigned_funding_stream = Column(Text, nullable=True)
    assigned_funding_scope = Column(Text, nullable=True)
    assigned_scope_guess = Column(Text, nullable=True)
    assigned_profile_relevant = Column(Boolean, nullable=True)
    assigned_vfc_related = Column(Boolean, nullable=True)
    assigned_emergency_related = Column(Boolean, nullable=True)
    assigned_arpa_related = Column(Boolean, nullable=True)
    assigned_regular_appropriation = Column(Boolean, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "priority",
            "match_field",
            "match_type",
            "match_value",
            name="uq_recon_federal_account_classification_rule_match",
        ),
        Index("recon_federal_account_classification_rules_priority_idx", "priority"),
        Index("recon_federal_account_classification_rules_active_idx", "is_active"),
        {"schema": RECON_SCHEMA},
    )


class AssistanceTransactionAccount(Base):
    __tablename__ = "assistance_transaction_accounts"

    source_transaction_id = Column(Text, primary_key=True)
    federal_account_symbol = Column(Text, primary_key=True)
    account_position = Column(Integer, primary_key=True)
    source_row_id = Column(Integer, nullable=True)
    award_key = Column(Text, nullable=True)
    fiscal_year = Column(Integer, nullable=True)
    state_code = Column(Text, nullable=True)
    transaction_obligated_amount = Column(Numeric(18, 2), nullable=True)
    awarding_agency_name = Column(Text, nullable=True)
    funding_agency_name = Column(Text, nullable=True)
    treasury_account_symbol = Column(Text, nullable=True)
    appropriation_type = Column(Text, nullable=True)
    appropriation_subtype = Column(Text, nullable=True)
    raw_emergency_code = Column(Text, nullable=True)
    psc_or_aln = Column(Text, nullable=True)
    psc_or_aln_description = Column(Text, nullable=True)
    award_description = Column(Text, nullable=True)
    transaction_description = Column(Text, nullable=True)
    prime_award_base_transaction_description = Column(Text, nullable=True)
    naics_description = Column(Text, nullable=True)
    program_activity_name = Column(Text, nullable=True)
    raw_federal_account_symbol = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_assistance_transaction_accounts_symbol_idx", "federal_account_symbol"),
        Index("recon_assistance_transaction_accounts_fy_idx", "fiscal_year"),
        Index("recon_assistance_transaction_accounts_state_idx", "state_code"),
        Index("recon_assistance_transaction_accounts_tx_idx", "source_transaction_id"),
        {"schema": RECON_SCHEMA},
    )


class AssistanceTransactionAccountSummary(Base):
    __tablename__ = "assistance_transaction_account_summary"

    source_transaction_id = Column(Text, primary_key=True)
    account_count = Column(Integer, nullable=False, server_default=text("0"))
    distinct_account_count = Column(Integer, nullable=False, server_default=text("0"))
    joined_account_symbols = Column(Text, nullable=True)
    has_regular_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_emergency_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_arpa_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_core_public_health_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_emergency_public_health_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_federal_health_transfer_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_special_transfer_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_procurement_support_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_other_public_health_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_biomedical_research_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_international_health_assistance_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_profile_relevant_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_unknown_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_transfer_or_special_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_procurement_account = Column(Boolean, nullable=False, server_default=text("false"))
    has_non_profile_relevant_account = Column(Boolean, nullable=False, server_default=text("false"))
    effective_funding_stream = Column(Text, nullable=True)
    effective_funding_scope = Column(Text, nullable=True)
    effective_scope_guess = Column(Text, nullable=True)
    effective_profile_relevant = Column(Boolean, nullable=True)
    effective_classification_method = Column(Text, nullable=True)
    funding_scope_method = Column(Text, nullable=True)
    federal_account_count = Column(Integer, nullable=False, server_default=text("0"))
    federal_account_combination_key = Column(Text, nullable=True)
    federal_account_titles_combined = Column(Text, nullable=True)
    component_account_scopes = Column(JSONB, nullable=True)
    component_scope_count = Column(Integer, nullable=False, server_default=text("0"))
    has_mixed_scopes = Column(Boolean, nullable=False, server_default=text("false"))
    account_structure_type = Column(Text, nullable=True)
    multi_account_interpretation = Column(Text, nullable=True)
    conservative_inclusion_reason = Column(Text, nullable=True)
    manual_review_recommended = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_core = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_emergency = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_transfer = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_procurement = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_research = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_international = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_special_transfer = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_unknown = Column(Boolean, nullable=False, server_default=text("false"))
    classification_notes = Column(Text, nullable=True)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_assistance_account_summary_stream_idx", "effective_funding_stream"),
        Index("recon_assistance_account_summary_profile_idx", "effective_profile_relevant"),
        Index("recon_assistance_account_summary_unknown_idx", "has_unknown_account"),
        {"schema": RECON_SCHEMA},
    )


class UsaspendingFundingStream(Base):
    __tablename__ = "usaspending_funding_streams"

    assistance_transaction_unique_key = Column(Text, primary_key=True)
    assistance_award_unique_key = Column(Text, nullable=True)
    award_id_fain = Column(Text, nullable=True)
    fiscal_year = Column(Integer, nullable=False)
    state_code = Column(String(2), nullable=False)
    raw_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    appropriation_type_raw = Column(Text, nullable=True)
    appropriation_type_normalized = Column(Text, nullable=True)
    appropriation_subtype_raw = Column(Text, nullable=True)
    defc_code_normalized = Column(Text, nullable=True)
    federal_account_symbol = Column(Text, nullable=True)
    treasury_account_symbol = Column(Text, nullable=True)
    appropriation_account = Column(Text, nullable=True)
    program_activity_name = Column(Text, nullable=True)
    funding_stream = Column(Text, nullable=False)
    include_in_cdc_profile_scope = Column(Boolean, nullable=False, server_default=text("false"))
    inclusion_weight = Column(Numeric(5, 2), nullable=False, server_default=text("0"))
    inclusion_reason = Column(Text, nullable=True)
    exclusion_reason = Column(Text, nullable=True)
    methodology_version = Column(Text, nullable=False)
    funding_stream_logic_version = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_usaspending_funding_streams_fy_idx", "fiscal_year"),
        Index("recon_usaspending_funding_streams_state_idx", "state_code"),
        Index("recon_usaspending_funding_streams_stream_idx", "funding_stream"),
        {"schema": RECON_SCHEMA},
    )


class TaggsFundingStream(Base):
    __tablename__ = "taggs_funding_streams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    award_number = Column(Text, nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    state_code = Column(String(2), nullable=False)
    can_code = Column(Text, nullable=True)
    raw_amount = Column(Numeric(18, 2), nullable=False, server_default=text("0"))
    raw_funding_stream = Column(Text, nullable=True)
    funding_stream = Column(Text, nullable=False)
    include_in_cdc_profile_scope = Column(Boolean, nullable=False, server_default=text("false"))
    inclusion_weight = Column(Numeric(5, 2), nullable=False, server_default=text("0"))
    profile_scope_reason = Column(Text, nullable=True)
    methodology_version = Column(Text, nullable=False)
    funding_stream_logic_version = Column(Text, nullable=False)
    can_mapping_version = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "award_number",
            "fiscal_year",
            "state_code",
            "can_code",
            name="uq_recon_taggs_funding_streams_award_state_year_can",
        ),
        Index("recon_taggs_funding_streams_fy_idx", "fiscal_year"),
        Index("recon_taggs_funding_streams_state_idx", "state_code"),
        Index("recon_taggs_funding_streams_stream_idx", "funding_stream"),
        {"schema": RECON_SCHEMA},
    )


class ProfileScopeRule(Base):
    __tablename__ = "profile_scope_rules"

    rule_id = Column(BigInteger, primary_key=True, autoincrement=True)
    priority = Column(Integer, nullable=False)
    source_system = Column(Text, nullable=False)
    match_field = Column(Text, nullable=False)
    match_type = Column(Text, nullable=False)
    match_value = Column(Text, nullable=False)
    include_in_profile_scope = Column(Boolean, nullable=True)
    inclusion_weight = Column(Numeric(5, 2), nullable=True)
    assigned_reason = Column(Text, nullable=True)
    confidence_label = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "priority",
            "source_system",
            "match_field",
            "match_type",
            "match_value",
            name="uq_recon_profile_scope_rule_match",
        ),
        Index("recon_profile_scope_rules_priority_idx", "priority"),
        Index("recon_profile_scope_rules_source_idx", "source_system"),
        Index("recon_profile_scope_rules_active_idx", "is_active"),
        {"schema": RECON_SCHEMA},
    )


class AssistanceTransactionProfileEnriched(Base):
    __tablename__ = "assistance_transactions_profile_enriched"

    source_transaction_id = Column(Text, primary_key=True)
    source_system = Column(Text, nullable=False, server_default=text("'assistance'"))
    fiscal_year = Column(Integer, nullable=True)
    state_code = Column(Text, nullable=True)
    recipient_name = Column(Text, nullable=True)
    recipient_country_name = Column(Text, nullable=True)
    awarding_agency_name = Column(Text, nullable=True)
    funding_agency_name = Column(Text, nullable=True)
    assistance_listing_number = Column(Text, nullable=True)
    assistance_listing_title = Column(Text, nullable=True)
    program_activity_name = Column(Text, nullable=True)
    federal_account_symbol = Column(Text, nullable=True)
    treasury_account_symbol = Column(Text, nullable=True)
    appropriation_type = Column(Text, nullable=True)
    disaster_emergency_fund_code = Column(Text, nullable=True)
    transaction_obligated_amount = Column(Numeric(18, 2), nullable=True)
    effective_funding_stream = Column(Text, nullable=True)
    funding_scope_method = Column(Text, nullable=True)
    effective_funding_scope = Column(Text, nullable=True)
    effective_scope_guess = Column(Text, nullable=True)
    federal_account_profile_relevant = Column(Boolean, nullable=True)
    federal_account_count = Column(Integer, nullable=False, server_default=text("0"))
    federal_account_combination_key = Column(Text, nullable=True)
    federal_account_titles_combined = Column(Text, nullable=True)
    component_account_scopes = Column(JSONB, nullable=True)
    component_scope_count = Column(Integer, nullable=False, server_default=text("0"))
    has_mixed_scopes = Column(Boolean, nullable=False, server_default=text("false"))
    account_structure_type = Column(Text, nullable=True)
    multi_account_interpretation = Column(Text, nullable=True)
    conservative_inclusion_reason = Column(Text, nullable=True)
    manual_review_recommended = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_core = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_emergency = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_transfer = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_procurement = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_research = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_international = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_special_transfer = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_unknown = Column(Boolean, nullable=False, server_default=text("false"))
    include_in_profile_scope = Column(Boolean, nullable=True)
    inclusion_weight = Column(Numeric(5, 2), nullable=True)
    inclusion_reason = Column(Text, nullable=True)
    exclusion_reason = Column(Text, nullable=True)
    confidence_label = Column(Text, nullable=True)
    likely_domestic = Column(Boolean, nullable=True)
    likely_core_public_health = Column(Boolean, nullable=True)
    likely_emergency_public_health = Column(Boolean, nullable=True)
    likely_federal_health_transfer = Column(Boolean, nullable=True)
    likely_procurement_support = Column(Boolean, nullable=True)
    likely_other_public_health = Column(Boolean, nullable=True)
    likely_biomedical_research = Column(Boolean, nullable=True)
    likely_international_health_assistance = Column(Boolean, nullable=True)
    likely_special_transfer = Column(Boolean, nullable=True)
    likely_regular_assistance = Column(Boolean, nullable=True)
    likely_emergency_related = Column(Boolean, nullable=True)
    likely_arpa_related = Column(Boolean, nullable=True)
    decision_context = Column(Text, nullable=True)
    matched_rule_id = Column(BigInteger, nullable=True)
    methodology_version = Column(Text, nullable=True)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_assistance_profile_enriched_fy_idx", "fiscal_year"),
        Index("recon_assistance_profile_enriched_state_idx", "state_code"),
        Index("recon_assistance_profile_enriched_account_idx", "federal_account_symbol"),
        Index("recon_assistance_profile_enriched_stream_idx", "effective_funding_stream"),
        Index("recon_assistance_profile_enriched_include_idx", "include_in_profile_scope"),
        {"schema": RECON_SCHEMA},
    )


class ContractTransactionProfileEnriched(Base):
    __tablename__ = "contract_transactions_profile_enriched"

    source_transaction_id = Column(Text, primary_key=True)
    source_system = Column(Text, nullable=False, server_default=text("'contracts'"))
    fiscal_year = Column(Integer, nullable=True)
    state_code = Column(Text, nullable=True)
    recipient_name = Column(Text, nullable=True)
    recipient_country_name = Column(Text, nullable=True)
    awarding_agency_name = Column(Text, nullable=True)
    funding_agency_name = Column(Text, nullable=True)
    federal_account_symbol = Column(Text, nullable=True)
    treasury_account_symbol = Column(Text, nullable=True)
    appropriation_type = Column(Text, nullable=True)
    disaster_emergency_fund_code = Column(Text, nullable=True)
    award_description = Column(Text, nullable=True)
    product_or_service_code = Column(Text, nullable=True)
    transaction_obligated_amount = Column(Numeric(18, 2), nullable=True)
    contract_category_guess = Column(Text, nullable=True)
    likely_profile_relevant_contract = Column(Boolean, nullable=True)
    effective_funding_stream = Column(Text, nullable=True)
    funding_scope_method = Column(Text, nullable=True)
    effective_funding_scope = Column(Text, nullable=True)
    effective_scope_guess = Column(Text, nullable=True)
    federal_account_profile_relevant = Column(Boolean, nullable=True)
    federal_account_count = Column(Integer, nullable=False, server_default=text("0"))
    federal_account_combination_key = Column(Text, nullable=True)
    federal_account_titles_combined = Column(Text, nullable=True)
    component_account_scopes = Column(JSONB, nullable=True)
    component_scope_count = Column(Integer, nullable=False, server_default=text("0"))
    has_mixed_scopes = Column(Boolean, nullable=False, server_default=text("false"))
    account_structure_type = Column(Text, nullable=True)
    multi_account_interpretation = Column(Text, nullable=True)
    conservative_inclusion_reason = Column(Text, nullable=True)
    manual_review_recommended = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_core = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_emergency = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_transfer = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_procurement = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_research = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_international = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_special_transfer = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_unknown = Column(Boolean, nullable=False, server_default=text("false"))
    include_in_profile_scope = Column(Boolean, nullable=True)
    inclusion_weight = Column(Numeric(5, 2), nullable=True)
    inclusion_reason = Column(Text, nullable=True)
    exclusion_reason = Column(Text, nullable=True)
    confidence_label = Column(Text, nullable=True)
    likely_core_public_health = Column(Boolean, nullable=True)
    likely_emergency_public_health = Column(Boolean, nullable=True)
    likely_federal_health_transfer = Column(Boolean, nullable=True)
    likely_procurement_support = Column(Boolean, nullable=True)
    likely_other_public_health = Column(Boolean, nullable=True)
    likely_biomedical_research = Column(Boolean, nullable=True)
    likely_international_health_assistance = Column(Boolean, nullable=True)
    likely_vfc_related = Column(Boolean, nullable=True)
    likely_immunization_related = Column(Boolean, nullable=True)
    likely_emergency_related = Column(Boolean, nullable=True)
    decision_context = Column(Text, nullable=True)
    matched_rule_id = Column(BigInteger, nullable=True)
    methodology_version = Column(Text, nullable=True)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_contract_profile_enriched_fy_idx", "fiscal_year"),
        Index("recon_contract_profile_enriched_state_idx", "state_code"),
        Index("recon_contract_profile_enriched_account_idx", "federal_account_symbol"),
        Index("recon_contract_profile_enriched_stream_idx", "effective_funding_stream"),
        Index("recon_contract_profile_enriched_include_idx", "include_in_profile_scope"),
        {"schema": RECON_SCHEMA},
    )


class ProfileScopeTransaction(Base):
    __tablename__ = "profile_scope_transactions"

    source_system = Column(Text, primary_key=True)
    source_transaction_id = Column(Text, primary_key=True)
    fiscal_year = Column(Integer, nullable=True)
    state_code = Column(Text, nullable=True)
    recipient_name = Column(Text, nullable=True)
    federal_account_symbol = Column(Text, nullable=True)
    effective_funding_stream = Column(Text, nullable=True)
    funding_scope_method = Column(Text, nullable=True)
    effective_funding_scope = Column(Text, nullable=True)
    federal_account_count = Column(Integer, nullable=False, server_default=text("0"))
    federal_account_combination_key = Column(Text, nullable=True)
    federal_account_titles_combined = Column(Text, nullable=True)
    component_account_scopes = Column(JSONB, nullable=True)
    component_scope_count = Column(Integer, nullable=False, server_default=text("0"))
    has_mixed_scopes = Column(Boolean, nullable=False, server_default=text("false"))
    account_structure_type = Column(Text, nullable=True)
    multi_account_interpretation = Column(Text, nullable=True)
    conservative_inclusion_reason = Column(Text, nullable=True)
    manual_review_recommended = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_core = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_emergency = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_transfer = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_procurement = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_research = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_international = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_special_transfer = Column(Boolean, nullable=False, server_default=text("false"))
    mixed_scope_contains_unknown = Column(Boolean, nullable=False, server_default=text("false"))
    include_in_profile_scope = Column(Boolean, nullable=True)
    inclusion_weight = Column(Numeric(5, 2), nullable=True)
    inclusion_reason = Column(Text, nullable=True)
    confidence_label = Column(Text, nullable=True)
    raw_amount = Column(Numeric(18, 2), nullable=True)
    normalized_profile_scope_amount = Column(Numeric(18, 2), nullable=True)
    methodology_version = Column(Text, nullable=True)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        Index("recon_profile_scope_transactions_fy_idx", "fiscal_year"),
        Index("recon_profile_scope_transactions_state_idx", "state_code"),
        Index("recon_profile_scope_transactions_source_idx", "source_system"),
        Index("recon_profile_scope_transactions_include_idx", "include_in_profile_scope"),
        {"schema": RECON_SCHEMA},
    )


class ProfileScopeStateYearSummary(Base):
    __tablename__ = "profile_scope_state_year_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_system = Column(Text, nullable=False)
    fiscal_year = Column(Integer, nullable=False)
    state_code = Column(Text, nullable=False)
    raw_amount = Column(Numeric(18, 2), nullable=True)
    profile_scope_amount = Column(Numeric(18, 2), nullable=True)
    core_public_health_amount = Column(Numeric(18, 2), nullable=True)
    emergency_public_health_amount = Column(Numeric(18, 2), nullable=True)
    federal_health_transfer_amount = Column(Numeric(18, 2), nullable=True)
    procurement_support_scope_amount = Column(Numeric(18, 2), nullable=True)
    special_transfer_amount = Column(Numeric(18, 2), nullable=True)
    other_public_health_amount = Column(Numeric(18, 2), nullable=True)
    biomedical_research_amount = Column(Numeric(18, 2), nullable=True)
    international_health_assistance_amount = Column(Numeric(18, 2), nullable=True)
    unknown_funding_scope_amount = Column(Numeric(18, 2), nullable=True)
    transaction_count = Column(Integer, nullable=False, server_default=text("0"))
    included_transaction_count = Column(Integer, nullable=False, server_default=text("0"))
    methodology_version = Column(Text, nullable=False)
    refreshed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "fiscal_year",
            "state_code",
            name="uq_recon_profile_scope_state_year_source",
        ),
        Index("recon_profile_scope_state_year_summary_fy_idx", "fiscal_year"),
        Index("recon_profile_scope_state_year_summary_state_idx", "state_code"),
        Index("recon_profile_scope_state_year_summary_source_idx", "source_system"),
        {"schema": RECON_SCHEMA},
    )
