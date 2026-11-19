"""Independent reconciliation audit for the active CDC state funding build.

Implements Contract §5 invariants 1–6 plus Amendment 1 (by_category and invariant 7)
and Amendment 2 (default award_type=grant alongside award_type=all) against the active
build in the configured database (places_staging).

Read-only SQL and in-process function calls only; writes no database rows.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.cdc_funding_api.schemas import CdcFundingScope
from app.cdc_funding_api.service import get_overview
from app.db import SessionLocal
from app.state_funding import lookup

pytestmark = pytest.mark.integration

TOLERANCE_DECIMAL = Decimal("0.01")
TOLERANCE_FLOAT = 0.01

FIXED_STATES = ("CA", "TX", "NY", "GA", "WY", "VT", "DC", "PR", "AK")
FUNDING_TYPES = ("all", "regular", "supplemental")
AWARD_TYPES = ("all", "grant", "contract")
OVERVIEW_YEARS = (2023, 2024, 2025, 2026)

VALID_NAME_SOURCES = frozenset(
    {
        "grants_gov_nofo_title",
        "cdc_funding_profiles_nofo_title",
        "taggs_award_title",
        "assistance_listing_title",
        "award_description",
    }
)


def _format_filters(filters: dict[str, Any]) -> str:
    return ", ".join(f"{k}={filters[k]!r}" for k in sorted(filters))


def _select_sampled_states(db, build_id: int) -> tuple[str, ...]:
    """Return FIXED_STATES plus the next state with the most negative FY2025 supplemental total.

    Note: TX is both in FIXED_STATES and the overall most negative FY2025 supplemental state,
    so selecting the most negative state outside FIXED_STATES yields 10 distinct states while
    covering both the #1 (TX) and #2 most negative FY2025 supplemental states.
    """
    extra_state = db.execute(
        text(
            """
            SELECT state
            FROM state_funding.obligation
            WHERE build_id = :build_id
              AND fiscal_year = 2025
              AND is_supplemental IS TRUE
              AND state <> '__'
              AND state <> ALL(:fixed_states)
            GROUP BY state
            ORDER BY sum(amount) ASC, state ASC
            LIMIT 1
            """
        ),
        {"build_id": build_id, "fixed_states": list(FIXED_STATES)},
    ).scalar()
    if not extra_state:
        return FIXED_STATES
    return (*FIXED_STATES, str(extra_state))


@pytest.fixture(scope="module")
def audit_context():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1")).scalar()
        build = lookup.build_info(db)
    except SQLAlchemyError as exc:
        db.close()
        pytest.skip(f"Database unreachable or state_funding schema unavailable: {exc}")

    if not build:
        db.close()
        pytest.skip("No active state_funding build available")

    try:
        fy_info = lookup.fiscal_years(db)
        fiscal_years = tuple(sorted(fy_info["fiscal_years"]))
        if not fiscal_years:
            pytest.skip("Active state_funding build contains no fiscal years")
        sampled_states = _select_sampled_states(db, build["build_id"])
        yield {
            "db": db,
            "build": build,
            "build_id": build["build_id"],
            "fiscal_years": fiscal_years,
            "sampled_states": sampled_states,
        }
    finally:
        db.rollback()
        db.close()


def _source_file_c_sum(db, fy: int, funding_type: str, award_type: str, *, unattributed_only: bool = False) -> Decimal:
    clauses = ["fiscal_year = :fy"]
    if funding_type == "regular":
        clauses.append("emergency <> 'Emergency'")
    elif funding_type == "supplemental":
        clauses.append("emergency = 'Emergency'")
    if award_type == "grant":
        clauses.append("grant_or_contract = 'Grant'")
    elif award_type == "contract":
        clauses.append("grant_or_contract <> 'Grant'")
    if unattributed_only:
        clauses.append("nullif(trim(recipient_state), '') IS NULL")
    sql = (
        "SELECT coalesce(sum(transaction_obligated_amount), 0) "
        "FROM cdc_funding.cdc_funding_awards WHERE " + " AND ".join(clauses)
    )
    return Decimal(db.execute(text(sql), {"fy": fy}).scalar())


def _build_obligation_sum(
    db, build_id: int, fy: int, funding_type: str, award_type: str, *, unattributed_only: bool = False
) -> Decimal:
    clauses = ["o.build_id = :build_id", "o.fiscal_year = :fy"]
    if funding_type == "regular":
        clauses.append("o.is_supplemental IS FALSE")
    elif funding_type == "supplemental":
        clauses.append("o.is_supplemental IS TRUE")
    if award_type == "grant":
        clauses.append("a.award_type = 'grant'")
    elif award_type == "contract":
        clauses.append("a.award_type = 'contract'")
    if unattributed_only:
        clauses.append("o.state = '__'")
    sql = (
        "SELECT coalesce(sum(o.amount), 0) "
        "FROM state_funding.obligation o "
        "JOIN state_funding.award a USING (build_id, award_unique_key) "
        "WHERE " + " AND ".join(clauses)
    )
    return Decimal(db.execute(text(sql), {"build_id": build_id, "fy": fy}).scalar())


def test_invariant_1_obligation_reconciles_to_file_c(audit_context):
    """Invariant 1: sum of obligation.amount (incl. '__') equals cdc_funding_awards within $0.01."""
    db = audit_context["db"]
    build_id = audit_context["build_id"]

    for fy in audit_context["fiscal_years"]:
        for funding_type in FUNDING_TYPES:
            for award_type in AWARD_TYPES:
                filters_label = _format_filters({"funding_type": funding_type, "award_type": award_type})
                expected = _source_file_c_sum(db, fy, funding_type, award_type)
                actual = _build_obligation_sum(db, build_id, fy, funding_type, award_type)
                diff = abs(actual - expected)
                assert diff <= TOLERANCE_DECIMAL, (
                    f"Invariant 1 failed: fy={fy} state='ALL (incl. __)' filters=({filters_label}) "
                    f"file_c={expected:.2f} build_obligation={actual:.2f} diff={diff:.2f}"
                )

        # Also verify the Unattributed ('__') slice directly for each fiscal year.
        expected_unattr = _source_file_c_sum(db, fy, "all", "all", unattributed_only=True)
        actual_unattr = _build_obligation_sum(db, build_id, fy, "all", "all", unattributed_only=True)
        diff_unattr = abs(actual_unattr - expected_unattr)
        assert diff_unattr <= TOLERANCE_DECIMAL, (
            f"Invariant 1 (unattributed) failed: fy={fy} state='__' "
            f"filters=(award_type='all', funding_type='all') "
            f"file_c={expected_unattr:.2f} build_obligation={actual_unattr:.2f} diff={diff_unattr:.2f}"
        )


def test_invariant_2_national_totals_match_cdc_funding_overview(audit_context):
    """Invariant 2: FY2023–FY2026 national totals match app.cdc_funding_api.service.get_overview."""
    db = audit_context["db"]
    build_id = audit_context["build_id"]

    for fy in OVERVIEW_YEARS:
        overview = get_overview(db, fiscal_year=fy, scope=CdcFundingScope.all_accounts)
        expected_by_combo: dict[tuple[str, str], Decimal] = {
            ("all", "all"): Decimal(overview.total_obligations),
            ("regular", "all"): Decimal(overview.totals.nonemergency),
            ("supplemental", "all"): Decimal(overview.totals.emergency),
            ("all", "grant"): Decimal(overview.totals.grants),
            ("all", "contract"): Decimal(overview.totals.contracts),
        }
        for cls in overview.classifications:
            ft = "supplemental" if cls.emergency_status == "emergency" else "regular"
            expected_by_combo[(ft, cls.award_type)] = Decimal(cls.obligations)

        for funding_type in FUNDING_TYPES:
            for award_type in AWARD_TYPES:
                filters_label = _format_filters({"funding_type": funding_type, "award_type": award_type})
                expected = expected_by_combo[(funding_type, award_type)]
                actual = _build_obligation_sum(db, build_id, fy, funding_type, award_type)
                diff = abs(actual - expected)
                assert diff <= TOLERANCE_DECIMAL, (
                    f"Invariant 2 failed: fy={fy} state='ALL (national)' filters=({filters_label}) "
                    f"cdc_funding_overview={expected:.2f} build_obligation={actual:.2f} diff={diff:.2f}"
                )


def test_invariant_3_summary_categories_and_grants_match(audit_context):
    """Invariant 3 (Amendment 1): summary.totals.total == sum(by_category.total) == grants.sum_total."""
    db = audit_context["db"]
    build = audit_context["build"]
    sampled_states = audit_context["sampled_states"]
    assert len(sampled_states) == 10, (
        f"Invariant 3 setup failed: fy='ALL' state='ALL' filters=(none) "
        f"expected_state_count=10 actual_state_count={len(sampled_states)} states={sampled_states}"
    )

    filter_sets = [
        {"funding_type": "all", "award_type": "grant", "category": None, "recipient_type": "all"},
        {"funding_type": "all", "award_type": "all", "category": None, "recipient_type": "all"},
        {"funding_type": "regular", "award_type": "grant", "category": None, "recipient_type": "all"},
        {"funding_type": "supplemental", "award_type": "grant", "category": None, "recipient_type": "all"},
        {"funding_type": "all", "award_type": "contract", "category": None, "recipient_type": "all"},
        {"funding_type": "all", "award_type": "grant", "category": None, "recipient_type": "state_government"},
    ]

    for state in sampled_states:
        for fy in audit_context["fiscal_years"]:
            for filters in filter_sets:
                filters_label = _format_filters(filters)
                s = lookup.summary(db, state, fy, filters, build)
                g = lookup.grants(db, state, fy, filters, build, page=1, page_size=25, all_rows=False)

                summary_total = s["totals"]["total"]
                summary_regular = s["totals"]["regular"]
                summary_supplemental = s["totals"]["supplemental"]
                cat_total = round(sum(c["total"] for c in s["by_category"]), 2)
                cat_regular = round(sum(c["regular"] for c in s["by_category"]), 2)
                cat_supplemental = round(sum(c["supplemental"] for c in s["by_category"]), 2)
                grants_sum_total = g["sum_total"]

                assert abs(summary_total - cat_total) <= TOLERANCE_FLOAT, (
                    f"Invariant 3 (summary vs by_category total) failed: fy={fy} state={state!r} "
                    f"filters=({filters_label}) summary_total={summary_total:.2f} by_category_sum={cat_total:.2f}"
                )
                assert abs(summary_regular - cat_regular) <= TOLERANCE_FLOAT, (
                    f"Invariant 3 (summary vs by_category regular) failed: fy={fy} state={state!r} "
                    f"filters=({filters_label}) summary_regular={summary_regular:.2f} "
                    f"by_category_regular_sum={cat_regular:.2f}"
                )
                assert abs(summary_supplemental - cat_supplemental) <= TOLERANCE_FLOAT, (
                    f"Invariant 3 (summary vs by_category supplemental) failed: fy={fy} state={state!r} "
                    f"filters=({filters_label}) summary_supplemental={summary_supplemental:.2f} "
                    f"by_category_supplemental_sum={cat_supplemental:.2f}"
                )
                assert abs(summary_total - grants_sum_total) <= TOLERANCE_FLOAT, (
                    f"Invariant 3 (summary vs grants.sum_total) failed: fy={fy} state={state!r} "
                    f"filters=({filters_label}) summary_total={summary_total:.2f} grants_sum_total={grants_sum_total:.2f}"
                )
                assert s["totals"]["award_count"] == g["total_rows"], (
                    f"Invariant 3 (award_count vs grants.total_rows) failed: fy={fy} state={state!r} "
                    f"filters=({filters_label}) summary_award_count={s['totals']['award_count']} "
                    f"grants_total_rows={g['total_rows']}"
                )


def test_invariant_4_grant_rows_reconcile_internally(audit_context):
    """Invariant 4: in each grant row, regular + supplemental = total, and account/category amounts sum to the row."""
    db = audit_context["db"]
    build = audit_context["build"]
    sampled_states = audit_context["sampled_states"]
    assert len(sampled_states) == 10, (
        f"Invariant 4 setup failed: fy='ALL' state='ALL' filters=(none) "
        f"expected_state_count=10 actual_state_count={len(sampled_states)}"
    )

    for state in sampled_states:
        for fy in audit_context["fiscal_years"]:
            for award_type in ("grant", "all"):
                filters = {
                    "funding_type": "all",
                    "award_type": award_type,
                    "category": None,
                    "recipient_type": "all",
                }
                filters_label = _format_filters(filters)
                g = lookup.grants(db, state, fy, filters, build, all_rows=True)
                for row in g["rows"]:
                    key = row["award_unique_key"]
                    row_reg = row["regular"]
                    row_sup = row["supplemental"]
                    row_tot = row["total"]

                    reg_plus_sup = round(row_reg + row_sup, 2)
                    assert abs(reg_plus_sup - row_tot) <= TOLERANCE_FLOAT, (
                        f"Invariant 4 (regular+supplemental != total) failed: fy={fy} state={state!r} "
                        f"filters=({filters_label}) award={key!r} "
                        f"regular_plus_supplemental={reg_plus_sup:.2f} row_total={row_tot:.2f}"
                    )

                    acct_reg = round(sum(a["regular"] for a in row["accounts"]), 2)
                    acct_sup = round(sum(a["supplemental"] for a in row["accounts"]), 2)
                    acct_tot = round(acct_reg + acct_sup, 2)
                    assert abs(acct_reg - row_reg) <= TOLERANCE_FLOAT, (
                        f"Invariant 4 (accounts regular sum) failed: fy={fy} state={state!r} "
                        f"filters=({filters_label}) award={key!r} "
                        f"accounts_regular_sum={acct_reg:.2f} row_regular={row_reg:.2f}"
                    )
                    assert abs(acct_sup - row_sup) <= TOLERANCE_FLOAT, (
                        f"Invariant 4 (accounts supplemental sum) failed: fy={fy} state={state!r} "
                        f"filters=({filters_label}) award={key!r} "
                        f"accounts_supplemental_sum={acct_sup:.2f} row_supplemental={row_sup:.2f}"
                    )
                    assert abs(acct_tot - row_tot) <= TOLERANCE_FLOAT, (
                        f"Invariant 4 (accounts total sum) failed: fy={fy} state={state!r} "
                        f"filters=({filters_label}) award={key!r} "
                        f"accounts_total_sum={acct_tot:.2f} row_total={row_tot:.2f}"
                    )

                    cat_reg = round(sum(c["regular"] for c in row["categories"]), 2)
                    cat_sup = round(sum(c["supplemental"] for c in row["categories"]), 2)
                    cat_tot = round(cat_reg + cat_sup, 2)
                    assert abs(cat_reg - row_reg) <= TOLERANCE_FLOAT, (
                        f"Invariant 4 (categories regular sum) failed: fy={fy} state={state!r} "
                        f"filters=({filters_label}) award={key!r} "
                        f"categories_regular_sum={cat_reg:.2f} row_regular={row_reg:.2f}"
                    )
                    assert abs(cat_sup - row_sup) <= TOLERANCE_FLOAT, (
                        f"Invariant 4 (categories supplemental sum) failed: fy={fy} state={state!r} "
                        f"filters=({filters_label}) award={key!r} "
                        f"categories_supplemental_sum={cat_sup:.2f} row_supplemental={row_sup:.2f}"
                    )
                    assert abs(cat_tot - row_tot) <= TOLERANCE_FLOAT, (
                        f"Invariant 4 (categories total sum) failed: fy={fy} state={state!r} "
                        f"filters=({filters_label}) award={key!r} "
                        f"categories_total_sum={cat_tot:.2f} row_total={row_tot:.2f}"
                    )


def test_invariant_5_awards_have_grant_name_and_valid_name_source(audit_context):
    """Invariant 5: every award row has a non-empty grant_name and a valid name_source."""
    db = audit_context["db"]
    build_id = audit_context["build_id"]

    total_awards = db.execute(
        text("SELECT count(*) FROM state_funding.award WHERE build_id = :build_id"),
        {"build_id": build_id},
    ).scalar()
    assert total_awards > 0, (
        f"Invariant 5 failed: fy='ALL' state='ALL' filters=(whole_build) "
        f"expected_award_count=>0 actual_award_count={total_awards}"
    )

    empty_names = db.execute(
        text(
            """
            SELECT count(*)
            FROM state_funding.award
            WHERE build_id = :build_id
              AND (grant_name IS NULL OR trim(grant_name) = '')
            """
        ),
        {"build_id": build_id},
    ).scalar()
    assert empty_names == 0, (
        f"Invariant 5 (empty grant_name) failed: fy='ALL' state='ALL' filters=(whole_build) "
        f"expected_empty_count=0 actual_empty_count={empty_names}"
    )

    observed_sources = dict(
        db.execute(
            text(
                """
                SELECT name_source, count(*)
                FROM state_funding.award
                WHERE build_id = :build_id
                GROUP BY name_source
                """
            ),
            {"build_id": build_id},
        ).all()
    )
    invalid_sources = {src: cnt for src, cnt in observed_sources.items() if src not in VALID_NAME_SOURCES}
    assert not invalid_sources, (
        f"Invariant 5 (invalid name_source) failed: fy='ALL' state='ALL' filters=(whole_build) "
        f"allowed_sources={sorted(VALID_NAME_SOURCES)} invalid_sources={invalid_sources}"
    )


def test_invariant_6_no_orphaned_or_missing_awards(audit_context):
    """Invariant 6: no award row is orphaned or missing relative to obligation."""
    db = audit_context["db"]
    build_id = audit_context["build_id"]

    orphaned_awards = db.execute(
        text(
            """
            SELECT count(*)
            FROM state_funding.award a
            LEFT JOIN state_funding.obligation o
              ON o.build_id = a.build_id AND o.award_unique_key = a.award_unique_key
            WHERE a.build_id = :build_id
              AND o.award_unique_key IS NULL
            """
        ),
        {"build_id": build_id},
    ).scalar()
    assert orphaned_awards == 0, (
        f"Invariant 6 (orphaned awards) failed: fy='ALL' state='ALL' filters=(whole_build) "
        f"expected_orphaned=0 actual_orphaned={orphaned_awards}"
    )

    missing_awards = db.execute(
        text(
            """
            SELECT count(DISTINCT o.award_unique_key)
            FROM state_funding.obligation o
            LEFT JOIN state_funding.award a
              ON a.build_id = o.build_id AND a.award_unique_key = o.award_unique_key
            WHERE o.build_id = :build_id
              AND a.award_unique_key IS NULL
            """
        ),
        {"build_id": build_id},
    ).scalar()
    assert missing_awards == 0, (
        f"Invariant 6 (missing awards) failed: fy='ALL' state='ALL' filters=(whole_build) "
        f"expected_missing=0 actual_missing={missing_awards}"
    )


def test_invariant_7_budget_category_crosswalk_and_category_account_sums(audit_context):
    """Invariant 7 (Amendment 1): every obligation account has a crosswalk row and category = sum(accounts)."""
    db = audit_context["db"]
    build = audit_context["build"]
    build_id = audit_context["build_id"]

    unmapped_symbols = (
        db.execute(
            text(
                """
                SELECT DISTINCT o.federal_account_symbol
                FROM state_funding.obligation o
                LEFT JOIN state_funding.budget_category c
                  ON c.federal_account_symbol = o.federal_account_symbol
                WHERE o.build_id = :build_id
                  AND c.federal_account_symbol IS NULL
                ORDER BY 1
                """
            ),
            {"build_id": build_id},
        )
        .scalars()
        .all()
    )
    assert not unmapped_symbols, (
        f"Invariant 7 (crosswalk coverage) failed: fy='ALL' state='ALL' filters=(whole_build) "
        f"expected_unmapped=[] actual_unmapped={unmapped_symbols}"
    )

    # Check lookup.summary() category totals against nested account sums across all 10 sampled states × FYs.
    for state in audit_context["sampled_states"]:
        for fy in audit_context["fiscal_years"]:
            for award_type in ("grant", "all"):
                filters = {
                    "funding_type": "all",
                    "award_type": award_type,
                    "category": None,
                    "recipient_type": "all",
                }
                filters_label = _format_filters(filters)
                s = lookup.summary(db, state, fy, filters, build)
                for cat in s["by_category"]:
                    assert cat["accounts"], (
                        f"Invariant 7 (empty category accounts) failed: fy={fy} state={state!r} "
                        f"filters=({filters_label}) category={cat['code']!r} expected=>=1 actual=0"
                    )
                    acct_total = round(sum(a["total"] for a in cat["accounts"]), 2)
                    acct_regular = round(sum(a["regular"] for a in cat["accounts"]), 2)
                    acct_supplemental = round(sum(a["supplemental"] for a in cat["accounts"]), 2)

                    assert abs(cat["total"] - acct_total) <= TOLERANCE_FLOAT, (
                        f"Invariant 7 (category total vs accounts sum) failed: fy={fy} state={state!r} "
                        f"filters=({filters_label}) category={cat['code']!r} "
                        f"category_total={cat['total']:.2f} accounts_sum={acct_total:.2f}"
                    )
                    assert abs(cat["regular"] - acct_regular) <= TOLERANCE_FLOAT, (
                        f"Invariant 7 (category regular vs accounts sum) failed: fy={fy} state={state!r} "
                        f"filters=({filters_label}) category={cat['code']!r} "
                        f"category_regular={cat['regular']:.2f} accounts_regular_sum={acct_regular:.2f}"
                    )
                    assert abs(cat["supplemental"] - acct_supplemental) <= TOLERANCE_FLOAT, (
                        f"Invariant 7 (category supplemental vs accounts sum) failed: fy={fy} state={state!r} "
                        f"filters=({filters_label}) category={cat['code']!r} "
                        f"category_supplemental={cat['supplemental']:.2f} "
                        f"accounts_supplemental_sum={acct_supplemental:.2f}"
                    )

    # Also verify across the whole build (every FY × state incl. '__') via SQL that category sum == sum of account sums.
    sql_mismatches = db.execute(
        text(
            """
            WITH by_acct AS (
                SELECT o.fiscal_year, o.state, c.category_code, o.federal_account_symbol,
                       sum(o.amount) AS acct_total
                FROM state_funding.obligation o
                JOIN state_funding.budget_category c USING (federal_account_symbol)
                WHERE o.build_id = :build_id
                GROUP BY 1, 2, 3, 4
            ),
            sum_of_accts AS (
                SELECT fiscal_year, state, category_code, sum(acct_total) AS acct_sum
                FROM by_acct
                GROUP BY 1, 2, 3
            ),
            by_cat AS (
                SELECT o.fiscal_year, o.state, c.category_code, sum(o.amount) AS cat_total
                FROM state_funding.obligation o
                JOIN state_funding.budget_category c USING (federal_account_symbol)
                WHERE o.build_id = :build_id
                GROUP BY 1, 2, 3
            )
            SELECT c.fiscal_year, c.state, c.category_code, c.cat_total, a.acct_sum
            FROM by_cat c
            FULL JOIN sum_of_accts a USING (fiscal_year, state, category_code)
            WHERE abs(coalesce(c.cat_total, 0) - coalesce(a.acct_sum, 0)) > 0.01
            LIMIT 10
            """
        ),
        {"build_id": build_id},
    ).all()
    assert not sql_mismatches, (
        f"Invariant 7 (whole-build SQL category vs account sum) failed: fy='ALL' state='ALL' "
        f"filters=(whole_build) expected_mismatches=[] actual_mismatches={sql_mismatches}"
    )
