from __future__ import annotations

from decimal import Decimal

from app.budget import master_scope


def test_regular_discretionary_flags_derive_without_optional_markers() -> None:
    emergency_flag = master_scope.resolve_emergency_flag(
        appropriation_category="REGULAR",
        signal_keyword_emergency=True,
    )

    assert master_scope.resolve_discretionary_mandatory_type(
        appropriation_category="REGULAR",
    ) == "discretionary"
    assert emergency_flag is False
    assert master_scope.resolve_supplemental_flag(
        appropriation_category="REGULAR",
        emergency_flag=emergency_flag,
    ) is False
    assert master_scope.resolve_pphf_flag(appropriation_category="REGULAR") is False
    assert master_scope.resolve_transfer_flag(appropriation_category="REGULAR") is False
    assert master_scope.resolve_filter_bucket(
        discretionary_mandatory_type="discretionary",
        emergency_flag=False,
        supplemental_flag=False,
        pphf_flag=False,
        transfer_flag=False,
    ) == "regular_discretionary"


def test_mandatory_flag_derives_from_budget_category() -> None:
    assert master_scope.resolve_discretionary_mandatory_type(
        appropriation_category="MANDATORY",
    ) == "mandatory"
    assert master_scope.resolve_category_display_label(
        discretionary_mandatory_type="mandatory",
        emergency_flag=False,
        supplemental_flag=False,
        pphf_flag=False,
        transfer_flag=False,
    ) == "Mandatory"


def test_pphf_and_transfer_flags_derive_from_category_and_subtype() -> None:
    assert master_scope.resolve_pphf_flag(
        appropriation_category="PPHF",
        appropriation_subtype=None,
    ) is True
    assert master_scope.resolve_pphf_flag(
        appropriation_category="REGULAR",
        appropriation_subtype="prevention_fund",
    ) is True
    assert master_scope.resolve_transfer_flag(
        appropriation_category="TRANSFER",
        appropriation_subtype=None,
    ) is True
    assert master_scope.resolve_transfer_flag(
        appropriation_category="REGULAR",
        appropriation_subtype="special_transfer",
    ) is True


def test_emergency_and_other_supplemental_flags_split_correctly() -> None:
    emergency_flag = master_scope.resolve_emergency_flag(
        appropriation_category="SUPPLEMENTAL",
        signal_keyword_covid=True,
    )
    non_emergency_flag = master_scope.resolve_emergency_flag(
        appropriation_category="SUPPLEMENTAL",
        signal_keyword_emergency=False,
        signal_keyword_covid=False,
    )

    assert emergency_flag is True
    assert master_scope.resolve_supplemental_flag(
        appropriation_category="SUPPLEMENTAL",
        emergency_flag=emergency_flag,
    ) is False
    assert non_emergency_flag is False
    assert master_scope.resolve_supplemental_flag(
        appropriation_category="SUPPLEMENTAL",
        emergency_flag=non_emergency_flag,
    ) is True


def test_included_analyst_reviewed_row_enters_master_universe() -> None:
    include_flag, double_count_flag, double_count_reason, inclusion_reason = master_scope.resolve_master_universe_inclusion(
        resolution_status="accepted",
        scope_include_flag=True,
        allocation_balance_status="balanced",
        duplicate_source_record_count=1,
        duplicate_source_record_rank=1,
        appropriation_category="REGULAR",
        non_add_flag=False,
        analyst_reviewed=True,
        auto_seeded=False,
        trusted_auto_seed_flag=False,
    )

    assert include_flag is True
    assert double_count_flag is False
    assert double_count_reason is None
    assert "analyst-reviewed" in inclusion_reason


def test_balanced_partial_row_enters_master_universe() -> None:
    include_flag, _, _, inclusion_reason = master_scope.resolve_master_universe_inclusion(
        resolution_status="accepted_partial",
        scope_include_flag=True,
        allocation_balance_status="balanced",
        duplicate_source_record_count=1,
        duplicate_source_record_rank=1,
        appropriation_category="REGULAR",
        non_add_flag=False,
        analyst_reviewed=True,
        auto_seeded=False,
        trusted_auto_seed_flag=False,
    )

    assert include_flag is True
    assert "accepted_partial" in inclusion_reason


def test_unbalanced_allocation_excludes_row() -> None:
    include_flag, double_count_flag, double_count_reason, inclusion_reason = master_scope.resolve_master_universe_inclusion(
        resolution_status="accepted",
        scope_include_flag=True,
        allocation_balance_status="under_allocated",
        duplicate_source_record_count=1,
        duplicate_source_record_rank=1,
        appropriation_category="REGULAR",
        non_add_flag=False,
        analyst_reviewed=True,
        auto_seeded=False,
        trusted_auto_seed_flag=False,
    )

    assert include_flag is False
    assert double_count_flag is True
    assert double_count_reason == "unbalanced_allocation"
    assert "not balanced" in inclusion_reason


def test_duplicate_noncanonical_row_is_excluded_for_double_count_protection() -> None:
    include_flag, double_count_flag, double_count_reason, inclusion_reason = master_scope.resolve_master_universe_inclusion(
        resolution_status="accepted",
        scope_include_flag=True,
        allocation_balance_status="balanced",
        duplicate_source_record_count=2,
        duplicate_source_record_rank=2,
        appropriation_category="REGULAR",
        non_add_flag=False,
        analyst_reviewed=True,
        auto_seeded=False,
        trusted_auto_seed_flag=False,
    )

    assert include_flag is False
    assert double_count_flag is True
    assert double_count_reason == "duplicate_anchor_source_noncanonical"
    assert "canonical" in inclusion_reason


def test_trusted_auto_seed_flag_requires_strict_deterministic_conditions() -> None:
    assert (
        master_scope.trusted_auto_seed_candidate(
            resolution_status="accepted",
            auto_seeded=True,
            analyst_reviewed=False,
            match_tier="TIER_A_DETERMINISTIC",
            confidence_band="HIGH",
            anchor_has_analyst_review_conflict=False,
        )
        is True
    )
    assert (
        master_scope.trusted_auto_seed_candidate(
            resolution_status="accepted_partial",
            auto_seeded=True,
            analyst_reviewed=False,
            match_tier="TIER_A_DETERMINISTIC",
            confidence_band="HIGH",
            anchor_has_analyst_review_conflict=False,
        )
        is False
    )
    assert (
        master_scope.trusted_auto_seed_candidate(
            resolution_status="accepted",
            auto_seeded=True,
            analyst_reviewed=False,
            match_tier="TIER_A_DETERMINISTIC",
            confidence_band="HIGH",
            anchor_has_analyst_review_conflict=True,
        )
        is False
    )


def test_untrusted_auto_seed_is_excluded_from_master_universe() -> None:
    include_flag, _, _, inclusion_reason = master_scope.resolve_master_universe_inclusion(
        resolution_status="accepted",
        scope_include_flag=True,
        allocation_balance_status="balanced",
        duplicate_source_record_count=1,
        duplicate_source_record_rank=1,
        appropriation_category="REGULAR",
        non_add_flag=False,
        analyst_reviewed=False,
        auto_seeded=True,
        trusted_auto_seed_flag=False,
    )

    assert include_flag is False
    assert "trusted deterministic auto-seed rules" in inclusion_reason


def test_review_mode_logic_respects_analyst_and_trusted_auto_rows() -> None:
    assert (
        master_scope.review_mode_allows_row(
            review_mode="analyst_only",
            include_in_master_universe=True,
            analyst_reviewed=True,
            trusted_auto_seed_flag=False,
        )
        is True
    )
    assert (
        master_scope.review_mode_allows_row(
            review_mode="analyst_only",
            include_in_master_universe=True,
            analyst_reviewed=False,
            trusted_auto_seed_flag=True,
        )
        is False
    )
    assert (
        master_scope.review_mode_allows_row(
            review_mode="trusted_auto",
            include_in_master_universe=True,
            analyst_reviewed=False,
            trusted_auto_seed_flag=True,
        )
        is True
    )
    assert (
        master_scope.review_mode_allows_row(
            review_mode="trusted_auto",
            include_in_master_universe=True,
            analyst_reviewed=False,
            trusted_auto_seed_flag=False,
        )
        is False
    )
    assert (
        master_scope.review_mode_allows_row(
            review_mode="all_master_universe",
            include_in_master_universe=True,
            analyst_reviewed=False,
            trusted_auto_seed_flag=False,
        )
        is True
    )


def test_scope_filters_allow_toggle_exclusions() -> None:
    assert (
        master_scope.scope_filters_allow_row(
            discretionary_mandatory_type="mandatory",
            emergency_flag=False,
            supplemental_flag=False,
            pphf_flag=False,
            transfer_flag=False,
            include_mandatory=False,
            include_emergency=True,
            include_supplemental=True,
            include_pphf=True,
            include_transfers=True,
        )
        is False
    )
    assert (
        master_scope.scope_filters_allow_row(
            discretionary_mandatory_type="discretionary",
            emergency_flag=True,
            supplemental_flag=False,
            pphf_flag=False,
            transfer_flag=False,
            include_mandatory=True,
            include_emergency=False,
            include_supplemental=True,
            include_pphf=True,
            include_transfers=True,
        )
        is False
    )
    assert (
        master_scope.scope_filters_allow_row(
            discretionary_mandatory_type="discretionary",
            emergency_flag=False,
            supplemental_flag=True,
            pphf_flag=False,
            transfer_flag=False,
            include_mandatory=True,
            include_emergency=True,
            include_supplemental=False,
            include_pphf=True,
            include_transfers=True,
        )
        is False
    )
    assert (
        master_scope.scope_filters_allow_row(
            discretionary_mandatory_type="discretionary",
            emergency_flag=False,
            supplemental_flag=False,
            pphf_flag=True,
            transfer_flag=False,
            include_mandatory=True,
            include_emergency=True,
            include_supplemental=True,
            include_pphf=False,
            include_transfers=True,
        )
        is False
    )
    assert (
        master_scope.scope_filters_allow_row(
            discretionary_mandatory_type="discretionary",
            emergency_flag=False,
            supplemental_flag=False,
            pphf_flag=False,
            transfer_flag=True,
            include_mandatory=True,
            include_emergency=True,
            include_supplemental=True,
            include_pphf=True,
            include_transfers=False,
        )
        is False
    )


def test_allocation_pct_is_applied_to_budget_grounded_amount() -> None:
    assert master_scope.allocated_amount(
        amount=Decimal("100.00"),
        allocation_pct=Decimal("0.250000"),
    ) == Decimal("25.000000")


def test_effective_allocation_pct_defaults_to_one_when_missing() -> None:
    assert master_scope.effective_allocation_pct(None) == Decimal("1.000000")
