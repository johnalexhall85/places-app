from __future__ import annotations

from decimal import Decimal

from app.recon import funding_streams
from app.recon import normalization


def test_taggs_normalization_compatibility_rejects_filtered_subset() -> None:
    supported, reason = normalization.taggs_normalization_compatibility(
        metric="total_funding",
        program_office="NCIRD",
        aln=None,
        can_code=None,
        funding_stream=None,
    )

    assert supported is False
    assert "statewide overall TAGGS totals" in str(reason)


def test_usaspending_normalization_compatibility_requires_prime_obligations() -> None:
    supported, reason = normalization.usaspending_normalization_compatibility(
        basis="subaward",
        metric="total_subaward",
        funding_geography_mode="recipient_location",
        appropriation_type="all",
        assistance_type=None,
        awarding_office=None,
        funding_office=None,
        center=None,
    )

    assert supported is False
    assert "prime-award obligations" in str(reason)


def test_build_normalization_note_marks_estimated_years() -> None:
    note = normalization.build_normalization_note(
        fiscal_year=2025,
        normalization_applied=True,
    )

    assert "funding-scope classification" in str(note)
    assert "Medicaid-like federal health financing transfers" in str(note)
    assert "FY2020-FY2023 profile-scope calibration rules" in str(note)


def test_classify_usaspending_record_prioritizes_arpa_defc_and_scope_rules() -> None:
    rules = funding_streams.load_rule_payloads()

    classification = funding_streams.classify_usaspending_record(
        {
            "appropriation_type_raw": "covid_emergency",
            "appropriation_subtype_raw": "ARP",
            "raw_emergency_code": "V: Emergency P.L. 117-2",
            "program_activity_name": "General response",
            "federal_account_symbol": None,
            "treasury_account_symbol": None,
            "transaction_description": None,
            "prime_award_base_transaction_description": None,
            "cfda_title": None,
            "cfda_program_title": None,
            "cfda_numbers_and_titles": None,
            "appropriation_account": None,
        },
        rules=rules,
    )

    assert classification["funding_stream"] == funding_streams.FUNDING_STREAM_ARPA
    assert classification["include_in_cdc_profile_scope"] is False
    assert classification["defc_code_normalized"] == "V"


def test_classify_usaspending_record_uses_program_rule_for_vfc() -> None:
    rules = funding_streams.load_rule_payloads()

    classification = funding_streams.classify_usaspending_record(
        {
            "appropriation_type_raw": "regular",
            "appropriation_subtype_raw": None,
            "raw_emergency_code": None,
            "program_activity_name": "Vaccines for Children",
            "federal_account_symbol": None,
            "treasury_account_symbol": None,
            "transaction_description": "Vaccines for Children cooperative agreement",
            "prime_award_base_transaction_description": None,
            "cfda_title": None,
            "cfda_program_title": None,
            "cfda_numbers_and_titles": None,
            "appropriation_account": None,
        },
        rules=rules,
    )

    assert classification["funding_stream"] == funding_streams.FUNDING_STREAM_TRANSFER_SPECIAL
    assert classification["include_in_cdc_profile_scope"] is True
    assert classification["inclusion_weight"] == Decimal("1.00")


def test_classify_taggs_record_excludes_non_domestic_rows() -> None:
    rules = funding_streams.load_rule_payloads()

    classification = funding_streams.classify_taggs_record(
        {
            "raw_funding_stream": "Vaccines for Children",
            "appropriation_type": "regular",
            "is_domestic_scope": False,
            "is_arpa_related": False,
            "is_covid_related": False,
            "is_supplemental": False,
            "is_regular_appropriation": True,
            "award_title": None,
            "assistance_listing_title": None,
            "effective_program_name": None,
            "effective_category": None,
            "effective_subcategory": None,
            "can_code": "93-1850",
        },
        rules=rules,
    )

    assert classification["include_in_cdc_profile_scope"] is False
    assert classification["inclusion_weight"] == Decimal("0.00")
    assert "domestic recipient scope" in str(classification["profile_scope_reason"])


def test_build_calibration_rows_uses_classified_scope_amount_not_flat_factor() -> None:
    profile_targets = {
        (2023, "AL"): {"amount": Decimal("110")},
    }
    source_rows = {
        (2023, "AL"): {
            "raw_amount": Decimal("200"),
            "classified_profile_scope_amount": Decimal("120"),
            "domestic_exclusion_amount": Decimal("20"),
            "included_special_stream_amount": Decimal("5"),
            "action_duplication_adjustment": Decimal("0"),
            "vfc_adjustment": Decimal("0"),
            "other_identified_adjustment": Decimal("0"),
            "funding_stream_totals": {
                "regular_appropriation": {
                    "raw_amount": Decimal("140"),
                    "included_amount": Decimal("120"),
                },
                "covid_emergency": {
                    "raw_amount": Decimal("60"),
                    "included_amount": Decimal("0"),
                },
            },
        }
    }

    calibration_rows, normalized_rows = normalization._build_calibration_rows(  # noqa: SLF001
        source_system="taggs",
        source_rows=source_rows,
        profile_targets=profile_targets,
    )

    assert calibration_rows[0]["classified_profile_scope_amount"] == Decimal("120")
    assert calibration_rows[0]["cdc_profile_amount"] == Decimal("110")
    assert calibration_rows[0]["residual_difference"] == Decimal("-10")
    assert normalized_rows[0]["normalized_amount"] == Decimal("120")
    assert normalized_rows[0]["normalized_amount_type"] == normalization.NORMALIZED_AMOUNT_TYPE_OBSERVED


def test_fetch_state_normalization_lookup_selects_new_metadata_columns(monkeypatch) -> None:
    class _Result:
        def mappings(self) -> "_Result":
            return self

        def all(self) -> list[dict[str, object]]:
            return [
                {
                    "state_code": "AL",
                    "raw_amount": Decimal("100"),
                    "normalized_amount": Decimal("90"),
                "normalized_amount_type": normalization.NORMALIZED_AMOUNT_TYPE_ESTIMATED,
                "normalization_method": "funding_scope_reconstruction_calibration_layer",
                "funding_stream_logic_version": "test_logic",
                "methodology_version": "test_method",
                "confidence_note": "test note",
                "normalization_factor": Decimal("0.9"),
                "core_public_health_amount": Decimal("80"),
                "funding_scope_components_json": {"core_public_health": "80"},
            }
        ]

    class _Db:
        def __init__(self) -> None:
            self.last_sql = ""

        def execute(self, statement, _params=None) -> _Result:
            self.last_sql = str(statement)
            return _Result()

    monkeypatch.setattr(normalization, "_ensure_normalization_tables", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(normalization, "_column_exists", lambda *_args, **_kwargs: True)
    db = _Db()
    lookup = normalization.fetch_state_normalization_lookup(db, source_system="taggs", fiscal_year=2025)

    assert "normalization_method" in db.last_sql
    assert "funding_stream_logic_version" in db.last_sql
    assert "funding_scope_components_json" in db.last_sql
    assert lookup["AL"]["normalization_method"] == "funding_scope_reconstruction_calibration_layer"
    assert lookup["AL"]["funding_stream_logic_version"] == "test_logic"
