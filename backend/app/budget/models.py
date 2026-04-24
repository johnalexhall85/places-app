from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
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
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.dialects.postgresql import JSONB

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


class CdcBudgetClassificationV1(Base):
    __tablename__ = "cdc_budget_classification_v1"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    raw_budget_id = Column(
        BigInteger,
        ForeignKey(f"{BUDGET_SCHEMA}.cdc_budget_tracker_raw.id", ondelete="CASCADE"),
        nullable=False,
    )
    unique_id = Column(Text, nullable=False)
    fiscal_year = Column(Integer, nullable=True)
    source_file = Column(Text, nullable=False)
    source_sheet = Column(Text, nullable=False)
    classification_version = Column(Text, nullable=False)
    classification_method = Column(Text, nullable=False)
    classified_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    classification_batch_id = Column(UUID(as_uuid=True), nullable=False)

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
    amount_dollars = Column(Numeric(20, 2), nullable=True)
    funding_type = Column(Text, nullable=True)
    program_status = Column(Text, nullable=True)
    is_non_add = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    verified = Column(Text, nullable=True)
    crosswalk_note = Column(Text, nullable=True)
    source_id = Column(Text, nullable=True)
    source_page = Column(Integer, nullable=True)

    norm_program = Column(Text, nullable=True)
    norm_sub_program = Column(Text, nullable=True)
    norm_sub_program_2 = Column(Text, nullable=True)
    norm_sub_program_3 = Column(Text, nullable=True)
    norm_funding_type = Column(Text, nullable=True)
    norm_budget_source = Column(Text, nullable=True)
    norm_budget_stage = Column(Text, nullable=True)
    norm_program_status = Column(Text, nullable=True)
    norm_notes = Column(Text, nullable=True)
    norm_crosswalk_note = Column(Text, nullable=True)

    signal_budget_stage_enacted = Column(Boolean, nullable=False, server_default=text("false"))
    signal_budget_stage_operating_plan = Column(Boolean, nullable=False, server_default=text("false"))
    signal_budget_stage_request = Column(Boolean, nullable=False, server_default=text("false"))
    signal_funding_type_discretionary = Column(Boolean, nullable=False, server_default=text("false"))
    signal_funding_type_mandatory = Column(Boolean, nullable=False, server_default=text("false"))
    signal_non_add = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_pphf = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_supplemental = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_emergency = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_transfer = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_reprogramming = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_total = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_subtotal = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_base = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_prevention_fund = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_covid = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_arp = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_cares = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_rescue_plan = Column(Boolean, nullable=False, server_default=text("false"))
    signal_keyword_nonrecurring = Column(Boolean, nullable=False, server_default=text("false"))

    signal_program_has_substructure = Column(Boolean, nullable=False, server_default=text("false"))
    signal_record_is_leaf_like = Column(Boolean, nullable=False, server_default=text("false"))
    signal_program_repeats_across_years = Column(Boolean, nullable=False, server_default=text("false"))
    program_year_count = Column(Integer, nullable=True)
    program_first_year = Column(Integer, nullable=True)
    program_last_year = Column(Integer, nullable=True)

    appropriation_category = Column(Text, nullable=False)
    appropriation_subtype = Column(Text, nullable=True)
    is_regular_appropriation = Column(Boolean, nullable=False, server_default=text("false"))
    classification_confidence = Column(Numeric(4, 3), nullable=False)
    primary_rule_code = Column(Text, nullable=True)
    supporting_rule_codes = Column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    rule_explanation = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "raw_budget_id",
            "classification_version",
            name="uq_cdc_budget_classification_v1_raw_version",
        ),
        CheckConstraint(
            "appropriation_category IN ("
            "'REGULAR', 'PPHF', 'SUPPLEMENTAL', 'TRANSFER', 'NON_ADD', "
            "'REQUEST_ONLY', 'MANDATORY', 'TOTAL_OR_SUBTOTAL', 'UNKNOWN'"
            ")",
            name="ck_cdc_budget_classification_v1_category",
        ),
        CheckConstraint(
            "classification_confidence >= 0 AND classification_confidence <= 1",
            name="ck_cdc_budget_classification_v1_confidence",
        ),
        Index("cdc_budget_classification_v1_fiscal_year_idx", "fiscal_year"),
        Index("cdc_budget_classification_v1_category_idx", "appropriation_category"),
        Index("cdc_budget_classification_v1_regular_idx", "is_regular_appropriation"),
        Index("cdc_budget_classification_v1_sub_agency_idx", "sub_agency"),
        Index("cdc_budget_classification_v1_budget_stage_idx", "budget_stage"),
        Index("cdc_budget_classification_v1_budget_source_idx", "budget_source"),
        Index("cdc_budget_classification_v1_funding_type_idx", "funding_type"),
        Index("cdc_budget_classification_v1_primary_rule_idx", "primary_rule_code"),
        {"schema": BUDGET_SCHEMA},
    )


class CdcBudgetClassificationRuleRegistry(Base):
    __tablename__ = "cdc_budget_classification_rule_registry"

    rule_code = Column(Text, primary_key=True)
    classification_version = Column(Text, nullable=False)
    rule_group = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    category_output = Column(Text, nullable=True)
    subtype_output = Column(Text, nullable=True)
    confidence_output = Column(Numeric(4, 3), nullable=True)
    priority = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "confidence_output IS NULL OR (confidence_output >= 0 AND confidence_output <= 1)",
            name="ck_cdc_budget_classification_rule_registry_confidence",
        ),
        Index(
            "cdc_budget_classification_rule_registry_version_priority_idx",
            "classification_version",
            "priority",
        ),
        Index("cdc_budget_classification_rule_registry_active_idx", "is_active"),
        {"schema": BUDGET_SCHEMA},
    )


class CdcBudgetSpendingBridgeV1(Base):
    __tablename__ = "cdc_budget_spending_bridge_v1"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    bridge_batch_id = Column(UUID(as_uuid=True), nullable=False)
    bridge_version = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    budget_anchor_id = Column(Text, nullable=False)
    classification_id = Column(
        BigInteger,
        ForeignKey(f"{BUDGET_SCHEMA}.cdc_budget_classification_v1.id", ondelete="CASCADE"),
        nullable=False,
    )
    raw_budget_id = Column(
        BigInteger,
        ForeignKey(f"{BUDGET_SCHEMA}.cdc_budget_tracker_raw.id", ondelete="CASCADE"),
        nullable=False,
    )
    unique_id = Column(Text, nullable=False)
    fiscal_year = Column(Integer, nullable=True)
    budget_agency = Column(Text, nullable=True)
    budget_sub_agency = Column(Text, nullable=True)
    budget_program = Column(Text, nullable=True)
    budget_sub_program = Column(Text, nullable=True)
    budget_sub_program_2 = Column(Text, nullable=True)
    budget_sub_program_3 = Column(Text, nullable=True)
    budget_program_key = Column(Text, nullable=True)
    appropriation_category = Column(Text, nullable=False)
    appropriation_subtype = Column(Text, nullable=True)
    is_regular_appropriation = Column(Boolean, nullable=False, server_default=text("false"))
    classification_confidence = Column(Numeric(4, 3), nullable=False)
    primary_rule_code = Column(Text, nullable=True)

    system_name = Column(Text, nullable=False)
    source_table = Column(Text, nullable=False)
    source_record_id = Column(Text, nullable=False)
    source_parent_record_id = Column(Text, nullable=True)
    source_fiscal_year = Column(Integer, nullable=True)

    match_rule_code = Column(Text, nullable=False)
    match_tier = Column(Text, nullable=False)
    match_type = Column(Text, nullable=False)
    match_score = Column(Numeric(5, 4), nullable=False)
    match_confidence = Column(Numeric(5, 4), nullable=False)
    confidence_band = Column(Text, nullable=False)
    is_auto_accepted = Column(Boolean, nullable=False, server_default=text("false"))
    is_excluded = Column(Boolean, nullable=False, server_default=text("false"))
    exclusion_reason = Column(Text, nullable=True)

    match_explanation = Column(Text, nullable=False)
    matched_on_fields = Column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))
    budget_side_values = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    spending_side_values = Column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    review_status = Column(Text, nullable=False, server_default=text("'unreviewed'"))
    review_notes = Column(Text, nullable=True)

    allocation_pct = Column(Numeric(8, 6), nullable=True)
    allocation_method = Column(Text, nullable=True)
    allocation_notes = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "bridge_version",
            "budget_anchor_id",
            "system_name",
            "source_record_id",
            "match_type",
            name="uq_cdc_budget_spending_bridge_v1_key",
        ),
        CheckConstraint(
            "system_name IN ('usaspending', 'taggs')",
            name="ck_cdc_budget_spending_bridge_v1_system_name",
        ),
        CheckConstraint(
            "match_tier IN ('TIER_A_DETERMINISTIC', 'TIER_B_STRUCTURED', 'TIER_C_FUZZY_CANDIDATE')",
            name="ck_cdc_budget_spending_bridge_v1_match_tier",
        ),
        CheckConstraint(
            "confidence_band IN ('HIGH', 'MEDIUM', 'LOW')",
            name="ck_cdc_budget_spending_bridge_v1_confidence_band",
        ),
        CheckConstraint(
            "review_status IN ('unreviewed', 'accepted', 'rejected', 'needs_review')",
            name="ck_cdc_budget_spending_bridge_v1_review_status",
        ),
        CheckConstraint(
            "match_score >= 0 AND match_score <= 1",
            name="ck_cdc_budget_spending_bridge_v1_match_score",
        ),
        CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_cdc_budget_spending_bridge_v1_match_confidence",
        ),
        CheckConstraint(
            "allocation_pct IS NULL OR (allocation_pct >= 0 AND allocation_pct <= 1)",
            name="ck_cdc_budget_spending_bridge_v1_allocation_pct",
        ),
        Index("cdc_budget_spending_bridge_v1_fiscal_year_idx", "fiscal_year"),
        Index("cdc_budget_spending_bridge_v1_system_name_idx", "system_name"),
        Index("cdc_budget_spending_bridge_v1_category_idx", "appropriation_category"),
        Index("cdc_budget_spending_bridge_v1_regular_idx", "is_regular_appropriation"),
        Index("cdc_budget_spending_bridge_v1_match_tier_idx", "match_tier"),
        Index("cdc_budget_spending_bridge_v1_confidence_band_idx", "confidence_band"),
        Index("cdc_budget_spending_bridge_v1_review_status_idx", "review_status"),
        Index("cdc_budget_spending_bridge_v1_source_record_idx", "source_record_id"),
        Index("cdc_budget_spending_bridge_v1_budget_program_key_idx", "budget_program_key"),
        Index("cdc_budget_spending_bridge_v1_match_rule_code_idx", "match_rule_code"),
        Index("cdc_budget_spending_bridge_v1_budget_anchor_idx", "budget_anchor_id"),
        {"schema": BUDGET_SCHEMA},
    )


class CdcBudgetSpendingBridgeRuleRegistry(Base):
    __tablename__ = "cdc_budget_spending_bridge_rule_registry"

    rule_code = Column(Text, primary_key=True)
    bridge_version = Column(Text, nullable=False)
    rule_group = Column(Text, nullable=False)
    tier = Column(Text, nullable=False)
    system_name = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    match_type = Column(Text, nullable=False)
    default_match_score = Column(Numeric(5, 4), nullable=True)
    default_match_confidence = Column(Numeric(5, 4), nullable=True)
    default_confidence_band = Column(Text, nullable=True)
    priority = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "tier IN ('TIER_A_DETERMINISTIC', 'TIER_B_STRUCTURED', 'TIER_C_FUZZY_CANDIDATE')",
            name="ck_cdc_budget_spending_bridge_rule_registry_tier",
        ),
        CheckConstraint(
            "system_name IN ('usaspending', 'taggs')",
            name="ck_cdc_budget_spending_bridge_rule_registry_system_name",
        ),
        CheckConstraint(
            "default_match_score IS NULL OR (default_match_score >= 0 AND default_match_score <= 1)",
            name="ck_cdc_budget_spending_bridge_rule_registry_score",
        ),
        CheckConstraint(
            "default_match_confidence IS NULL OR (default_match_confidence >= 0 AND default_match_confidence <= 1)",
            name="ck_cdc_budget_spending_bridge_rule_registry_confidence",
        ),
        CheckConstraint(
            "default_confidence_band IS NULL OR default_confidence_band IN ('HIGH', 'MEDIUM', 'LOW')",
            name="ck_cdc_budget_spending_bridge_rule_registry_confidence_band",
        ),
        Index(
            "cdc_budget_spending_bridge_rule_registry_version_priority_idx",
            "bridge_version",
            "priority",
        ),
        Index("cdc_budget_spending_bridge_rule_registry_active_idx", "is_active"),
        {"schema": BUDGET_SCHEMA},
    )


class CdcBudgetSpendingBridgeResolutionV1(Base):
    __tablename__ = "cdc_budget_spending_bridge_resolution_v1"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    resolution_batch_id = Column(UUID(as_uuid=True), nullable=False)
    resolution_version = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    bridge_id = Column(
        BigInteger,
        ForeignKey(f"{BUDGET_SCHEMA}.cdc_budget_spending_bridge_v1.id", ondelete="CASCADE"),
        nullable=False,
    )
    resolution_rule_code = Column(Text, nullable=True)
    bridge_version = Column(Text, nullable=False)
    budget_anchor_id = Column(Text, nullable=False)
    classification_id = Column(BigInteger, nullable=False)
    raw_budget_id = Column(BigInteger, nullable=False)
    unique_id = Column(Text, nullable=False)
    system_name = Column(Text, nullable=False)
    source_record_id = Column(Text, nullable=False)
    match_tier = Column(Text, nullable=False)
    match_type = Column(Text, nullable=False)
    match_score = Column(Numeric(5, 4), nullable=False)
    match_confidence = Column(Numeric(5, 4), nullable=False)
    confidence_band = Column(Text, nullable=False)

    fiscal_year = Column(Integer, nullable=True)
    budget_agency = Column(Text, nullable=True)
    budget_sub_agency = Column(Text, nullable=True)
    budget_program = Column(Text, nullable=True)
    budget_sub_program = Column(Text, nullable=True)
    budget_sub_program_2 = Column(Text, nullable=True)
    budget_sub_program_3 = Column(Text, nullable=True)
    budget_program_key = Column(Text, nullable=True)
    appropriation_category = Column(Text, nullable=False)
    appropriation_subtype = Column(Text, nullable=True)
    is_regular_appropriation = Column(Boolean, nullable=False, server_default=text("false"))
    classification_confidence = Column(Numeric(4, 3), nullable=False)
    primary_rule_code = Column(Text, nullable=True)

    resolution_status = Column(Text, nullable=False)
    scope_include_flag = Column(Boolean, nullable=False, server_default=text("false"))
    allocation_pct = Column(Numeric(8, 6), nullable=True)
    allocation_method = Column(Text, nullable=True)
    resolution_method = Column(Text, nullable=False)
    resolution_confidence = Column(Numeric(5, 4), nullable=True)
    resolution_priority = Column(Integer, nullable=True)
    auto_seeded = Column(Boolean, nullable=False, server_default=text("false"))
    analyst_reviewed = Column(Boolean, nullable=False, server_default=text("false"))

    resolution_reason_code = Column(Text, nullable=True)
    resolution_explanation = Column(Text, nullable=False)
    reviewer_name = Column(Text, nullable=True)
    reviewer_email = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_notes = Column(Text, nullable=True)

    supersedes_resolution_id = Column(
        BigInteger,
        ForeignKey(f"{BUDGET_SCHEMA}.cdc_budget_spending_bridge_resolution_v1.id"),
        nullable=True,
    )
    is_current = Column(Boolean, nullable=False, server_default=text("true"))

    __table_args__ = (
        CheckConstraint(
            "system_name IN ('usaspending', 'taggs')",
            name="ck_cdc_budget_spend_bridge_res_v1_system",
        ),
        CheckConstraint(
            "match_tier IN ('TIER_A_DETERMINISTIC', 'TIER_B_STRUCTURED', 'TIER_C_FUZZY_CANDIDATE')",
            name="ck_cdc_budget_spend_bridge_res_v1_tier",
        ),
        CheckConstraint(
            "confidence_band IN ('HIGH', 'MEDIUM', 'LOW')",
            name="ck_cdc_budget_spend_bridge_res_v1_band",
        ),
        CheckConstraint(
            "resolution_status IN ('accepted', 'rejected', 'accepted_partial', 'superseded', 'unresolved')",
            name="ck_cdc_budget_spend_bridge_res_v1_status",
        ),
        CheckConstraint(
            "resolution_method IN ('analyst', 'auto_seed', 'overlay', 'manual_sql')",
            name="ck_cdc_budget_spend_bridge_res_v1_method",
        ),
        CheckConstraint(
            "match_score >= 0 AND match_score <= 1",
            name="ck_cdc_budget_spend_bridge_res_v1_match_score",
        ),
        CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_cdc_budget_spend_bridge_res_v1_match_conf",
        ),
        CheckConstraint(
            "resolution_confidence IS NULL OR (resolution_confidence >= 0 AND resolution_confidence <= 1)",
            name="ck_cdc_budget_spend_bridge_res_v1_res_conf",
        ),
        CheckConstraint(
            "allocation_pct IS NULL OR (allocation_pct >= 0 AND allocation_pct <= 1)",
            name="ck_cdc_budget_spend_bridge_res_v1_alloc",
        ),
        CheckConstraint(
            "(resolution_status = 'accepted' AND allocation_pct IS NOT NULL) "
            "OR (resolution_status <> 'accepted' AND allocation_pct IS NULL) "
            "OR resolution_status = 'accepted_partial'",
            name="ck_cdc_budget_spend_bridge_res_v1_accept_alloc",
        ),
        CheckConstraint(
            "resolution_status <> 'accepted_partial' "
            "OR (allocation_pct IS NOT NULL AND allocation_pct > 0 AND allocation_pct < 1)",
            name="ck_cdc_budget_spend_bridge_res_v1_partial_alloc",
        ),
        CheckConstraint(
            "resolution_status <> 'accepted' OR allocation_pct = 1",
            name="ck_cdc_budget_spend_bridge_res_v1_full_alloc",
        ),
        CheckConstraint(
            "(resolution_status IN ('accepted', 'accepted_partial') AND scope_include_flag = TRUE) "
            "OR (resolution_status NOT IN ('accepted', 'accepted_partial') AND scope_include_flag = FALSE)",
            name="ck_cdc_budget_spend_bridge_res_v1_scope_flag",
        ),
        Index(
            "uq_cdc_budget_spend_bridge_res_v1_current",
            "resolution_version",
            "bridge_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("cdc_budget_spend_bridge_res_v1_current_idx", "resolution_version", "is_current"),
        Index("cdc_budget_spend_bridge_res_v1_bridge_idx", "bridge_id"),
        Index("cdc_budget_spend_bridge_res_v1_anchor_idx", "budget_anchor_id"),
        Index("cdc_budget_spend_bridge_res_v1_system_idx", "system_name"),
        Index("cdc_budget_spend_bridge_res_v1_category_idx", "appropriation_category"),
        Index("cdc_budget_spend_bridge_res_v1_scope_idx", "scope_include_flag"),
        Index("cdc_budget_spend_bridge_res_v1_status_idx", "resolution_status"),
        Index("cdc_budget_spend_bridge_res_v1_analyst_idx", "analyst_reviewed"),
        Index("cdc_budget_spend_bridge_res_v1_auto_idx", "auto_seeded"),
        Index("cdc_budget_spend_bridge_res_v1_fy_idx", "fiscal_year"),
        Index("cdc_budget_spend_bridge_res_v1_source_idx", "source_record_id"),
        {"schema": BUDGET_SCHEMA},
    )


class CdcBudgetSpendingBridgeResolutionRuleRegistry(Base):
    __tablename__ = "cdc_budget_spending_bridge_resolution_rule_registry"

    rule_code = Column(Text, primary_key=True)
    resolution_version = Column(Text, nullable=False)
    rule_group = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    resolution_status_output = Column(Text, nullable=True)
    scope_include_output = Column(Boolean, nullable=True)
    default_allocation_pct = Column(Numeric(8, 6), nullable=True)
    resolution_method_output = Column(Text, nullable=True)
    priority = Column(Integer, nullable=False)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "resolution_status_output IS NULL OR "
            "resolution_status_output IN ('accepted', 'rejected', 'accepted_partial', 'superseded', 'unresolved')",
            name="ck_cdc_budget_spend_bridge_res_rule_v1_status",
        ),
        CheckConstraint(
            "default_allocation_pct IS NULL OR (default_allocation_pct >= 0 AND default_allocation_pct <= 1)",
            name="ck_cdc_budget_spend_bridge_res_rule_v1_alloc",
        ),
        CheckConstraint(
            "resolution_method_output IS NULL OR "
            "resolution_method_output IN ('analyst', 'auto_seed', 'overlay', 'manual_sql')",
            name="ck_cdc_budget_spend_bridge_res_rule_v1_method",
        ),
        Index(
            "cdc_budget_spend_bridge_res_rule_v1_ver_pri_idx",
            "resolution_version",
            "priority",
        ),
        Index("cdc_budget_spend_bridge_res_rule_v1_active_idx", "is_active"),
        {"schema": BUDGET_SCHEMA},
    )


class CdcBudgetSpendingBridgeAnalystActionV1(Base):
    __tablename__ = "cdc_budget_spending_bridge_analyst_action_v1"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    action_batch_id = Column(UUID(as_uuid=True), nullable=False)
    action_version = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    bridge_id = Column(
        BigInteger,
        ForeignKey(f"{BUDGET_SCHEMA}.cdc_budget_spending_bridge_v1.id", ondelete="CASCADE"),
        nullable=False,
    )
    resolution_version = Column(Text, nullable=False)
    bridge_version = Column(Text, nullable=False)
    budget_anchor_id = Column(Text, nullable=False)
    classification_id = Column(BigInteger, nullable=False)
    raw_budget_id = Column(BigInteger, nullable=False)
    unique_id = Column(Text, nullable=False)
    system_name = Column(Text, nullable=False)
    source_record_id = Column(Text, nullable=False)

    fiscal_year = Column(Integer, nullable=True)
    budget_program = Column(Text, nullable=True)
    budget_sub_program = Column(Text, nullable=True)
    budget_program_key = Column(Text, nullable=True)
    appropriation_category = Column(Text, nullable=False)
    is_regular_appropriation = Column(Boolean, nullable=False, server_default=text("false"))
    match_tier = Column(Text, nullable=False)
    match_type = Column(Text, nullable=False)
    match_confidence = Column(Numeric(5, 4), nullable=False)
    confidence_band = Column(Text, nullable=False)

    analyst_action = Column(Text, nullable=False)
    allocation_pct = Column(Numeric(8, 6), nullable=True)
    scope_include_flag = Column(Boolean, nullable=True)
    action_reason_code = Column(Text, nullable=False)
    action_explanation = Column(Text, nullable=False)
    action_priority = Column(Integer, nullable=True)
    action_is_final = Column(Boolean, nullable=False, server_default=text("true"))

    reviewer_name = Column(Text, nullable=False)
    reviewer_email = Column(Text, nullable=True)
    reviewer_team = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    review_notes = Column(Text, nullable=True)

    import_source = Column(Text, nullable=True)
    anchor_review_group = Column(Text, nullable=True)
    is_current = Column(Boolean, nullable=False, server_default=text("true"))
    supersedes_action_id = Column(
        BigInteger,
        ForeignKey(f"{BUDGET_SCHEMA}.cdc_budget_spending_bridge_analyst_action_v1.id"),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "system_name IN ('usaspending', 'taggs')",
            name="ck_cdc_budget_spend_bridge_act_v1_system",
        ),
        CheckConstraint(
            "match_tier IN ('TIER_A_DETERMINISTIC', 'TIER_B_STRUCTURED', 'TIER_C_FUZZY_CANDIDATE')",
            name="ck_cdc_budget_spend_bridge_act_v1_tier",
        ),
        CheckConstraint(
            "confidence_band IN ('HIGH', 'MEDIUM', 'LOW')",
            name="ck_cdc_budget_spend_bridge_act_v1_band",
        ),
        CheckConstraint(
            "analyst_action IN ("
            "'accept_full', 'accept_partial', 'reject', "
            "'leave_unresolved', 'supersede_prior', 'mark_needs_followup'"
            ")",
            name="ck_cdc_budget_spend_bridge_act_v1_action",
        ),
        CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_cdc_budget_spend_bridge_act_v1_conf",
        ),
        CheckConstraint(
            "allocation_pct IS NULL OR (allocation_pct >= 0 AND allocation_pct <= 1)",
            name="ck_cdc_budget_spend_bridge_act_v1_alloc",
        ),
        CheckConstraint(
            "analyst_action <> 'accept_full' OR allocation_pct = 1",
            name="ck_cdc_budget_spend_bridge_act_v1_full_alloc",
        ),
        CheckConstraint(
            "analyst_action <> 'accept_partial' "
            "OR (allocation_pct IS NOT NULL AND allocation_pct > 0 AND allocation_pct < 1)",
            name="ck_cdc_budget_spend_bridge_act_v1_partial_alloc",
        ),
        CheckConstraint(
            "analyst_action NOT IN ('reject', 'leave_unresolved', 'supersede_prior', 'mark_needs_followup') "
            "OR allocation_pct IS NULL",
            name="ck_cdc_budget_spend_bridge_act_v1_no_alloc",
        ),
        Index(
            "uq_cdc_budget_spend_bridge_act_v1_current",
            "action_version",
            "bridge_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index("cdc_budget_spend_bridge_act_v1_anchor_idx", "budget_anchor_id"),
        Index("cdc_budget_spend_bridge_act_v1_action_idx", "analyst_action"),
        Index("cdc_budget_spend_bridge_act_v1_reviewer_idx", "reviewer_name"),
        Index("cdc_budget_spend_bridge_act_v1_reviewer_email_idx", "reviewer_email"),
        Index("cdc_budget_spend_bridge_act_v1_category_idx", "appropriation_category"),
        Index("cdc_budget_spend_bridge_act_v1_regular_idx", "is_regular_appropriation"),
        Index("cdc_budget_spend_bridge_act_v1_fy_idx", "fiscal_year"),
        Index("cdc_budget_spend_bridge_act_v1_system_idx", "system_name"),
        {"schema": BUDGET_SCHEMA},
    )


class CdcBudgetGroundedScopeUniverseV1(Base):
    __tablename__ = "cdc_budget_grounded_scope_universe_v1"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    scope_universe_version = Column(Text, nullable=False)
    built_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    resolution_id = Column(BigInteger, nullable=False)
    resolution_version = Column(Text, nullable=False)
    bridge_version = Column(Text, nullable=False)
    bridge_id = Column(BigInteger, nullable=False)
    budget_anchor_id = Column(Text, nullable=False)
    classification_id = Column(BigInteger, nullable=False)
    raw_budget_id = Column(BigInteger, nullable=False)
    unique_id = Column(Text, nullable=False)
    fiscal_year = Column(Integer, nullable=True)
    budget_agency = Column(Text, nullable=True)
    budget_sub_agency = Column(Text, nullable=True)
    budget_program = Column(Text, nullable=True)
    budget_sub_program = Column(Text, nullable=True)
    budget_sub_program_2 = Column(Text, nullable=True)
    budget_sub_program_3 = Column(Text, nullable=True)
    budget_program_key = Column(Text, nullable=True)
    appropriation_category = Column(Text, nullable=False)
    appropriation_subtype = Column(Text, nullable=True)
    classification_confidence = Column(Numeric(4, 3), nullable=True)
    primary_rule_code = Column(Text, nullable=True)
    system_name = Column(Text, nullable=False)
    source_record_id = Column(Text, nullable=False)
    source_parent_record_id = Column(Text, nullable=True)
    source_fiscal_year = Column(Integer, nullable=True)
    match_tier = Column(Text, nullable=True)
    match_type = Column(Text, nullable=True)
    match_score = Column(Numeric(5, 4), nullable=True)
    match_confidence = Column(Numeric(5, 4), nullable=True)
    confidence_band = Column(Text, nullable=True)
    resolution_status = Column(Text, nullable=False)
    allocation_pct = Column(Numeric(8, 6), nullable=True)
    allocation_method = Column(Text, nullable=True)
    resolution_method = Column(Text, nullable=False)
    resolution_confidence = Column(Numeric(5, 4), nullable=True)
    analyst_reviewed = Column(Boolean, nullable=False, server_default=text("false"))
    auto_seeded = Column(Boolean, nullable=False, server_default=text("false"))
    resolution_reason_code = Column(Text, nullable=True)
    reviewer_name = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    analyst_review_state = Column(Text, nullable=True)
    allocation_balance_status = Column(Text, nullable=True)
    spending_program_name = Column(Text, nullable=True)
    spending_assistance_listing_title = Column(Text, nullable=True)
    spending_aln = Column(Text, nullable=True)
    spending_can_code = Column(Text, nullable=True)
    spending_program_office = Column(Text, nullable=True)
    spending_award_title = Column(Text, nullable=True)
    spending_award_description = Column(Text, nullable=True)
    spending_appropriation_type = Column(Text, nullable=True)
    discretionary_mandatory_type = Column(Text, nullable=False)
    emergency_flag = Column(Boolean, nullable=False, server_default=text("false"))
    supplemental_flag = Column(Boolean, nullable=False, server_default=text("false"))
    pphf_flag = Column(Boolean, nullable=False, server_default=text("false"))
    transfer_flag = Column(Boolean, nullable=False, server_default=text("false"))
    non_add_flag = Column(Boolean, nullable=False, server_default=text("false"))
    include_in_master_universe = Column(Boolean, nullable=False, server_default=text("false"))
    inclusion_reason = Column(Text, nullable=False)
    double_count_exclusion_flag = Column(Boolean, nullable=False, server_default=text("false"))
    double_count_exclusion_reason = Column(Text, nullable=True)
    effective_allocation_pct = Column(Numeric(8, 6), nullable=False)
    scoped_amount_multiplier = Column(Numeric(8, 6), nullable=False)
    effective_scope_weight = Column(Numeric(10, 6), nullable=False)
    trusted_auto_seed_flag = Column(Boolean, nullable=False, server_default=text("false"))
    category_display_label = Column(Text, nullable=True)
    filter_bucket = Column(Text, nullable=True)
    budget_amount_dollars = Column(Numeric(20, 2), nullable=True)
    budget_amount_millions = Column(Numeric(18, 6), nullable=True)
    allocated_budget_amount_dollars = Column(Numeric(20, 2), nullable=True)
    allocated_budget_amount_millions = Column(Numeric(18, 6), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "scope_universe_version",
            "resolution_id",
            name="uq_cdc_budget_grounded_scope_universe_v1_ver_resolution",
        ),
        Index("cdc_budget_grounded_scope_universe_v1_version_idx", "scope_universe_version"),
        Index("cdc_budget_grounded_scope_universe_v1_fy_idx", "fiscal_year"),
        Index("cdc_budget_grounded_scope_universe_v1_system_idx", "system_name"),
        Index("cdc_budget_grounded_scope_universe_v1_category_idx", "appropriation_category"),
        Index("cdc_budget_grounded_scope_universe_v1_disc_mand_idx", "discretionary_mandatory_type"),
        Index("cdc_budget_grounded_scope_universe_v1_emergency_idx", "emergency_flag"),
        Index("cdc_budget_grounded_scope_universe_v1_supplemental_idx", "supplemental_flag"),
        Index("cdc_budget_grounded_scope_universe_v1_pphf_idx", "pphf_flag"),
        Index("cdc_budget_grounded_scope_universe_v1_transfer_idx", "transfer_flag"),
        Index("cdc_budget_grounded_scope_universe_v1_analyst_idx", "analyst_reviewed"),
        Index("cdc_budget_grounded_scope_universe_v1_auto_idx", "auto_seeded"),
        Index("cdc_budget_grounded_scope_universe_v1_include_idx", "include_in_master_universe"),
        Index("cdc_budget_grounded_scope_universe_v1_budget_program_key_idx", "budget_program_key"),
        Index("cdc_budget_grounded_scope_universe_v1_source_record_idx", "source_record_id"),
        {"schema": BUDGET_SCHEMA},
    )


class CdcBudgetSpendingBridgeAnalystReasonRegistry(Base):
    __tablename__ = "cdc_budget_spending_bridge_analyst_reason_registry"

    reason_code = Column(Text, primary_key=True)
    action_version = Column(Text, nullable=False)
    analyst_action = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    requires_allocation = Column(Boolean, nullable=False, server_default=text("false"))
    scope_include_default = Column(Boolean, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        CheckConstraint(
            "analyst_action IN ("
            "'accept_full', 'accept_partial', 'reject', "
            "'leave_unresolved', 'supersede_prior', 'mark_needs_followup'"
            ")",
            name="ck_cdc_budget_spend_bridge_reason_v1_action",
        ),
        Index(
            "cdc_budget_spend_bridge_reason_v1_ver_action_idx",
            "action_version",
            "analyst_action",
        ),
        Index("cdc_budget_spend_bridge_reason_v1_active_idx", "is_active"),
        {"schema": BUDGET_SCHEMA},
    )
