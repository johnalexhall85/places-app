from __future__ import annotations

from app.cdc_funding import budget_grounded


def test_scoped_records_cte_excludes_mandatory_rows_when_include_mandatory_is_false() -> None:
    filters = budget_grounded._normalize_filters(
        fiscal_year=2024,
        metric="total_funding",
        funding_type="total_cdc_funding",
        geography_level="state",
        time_aggregation="single_fiscal_year",
        include_mandatory=False,
        include_emergency=False,
        include_supplemental=False,
        include_pphf=True,
        include_transfers=True,
        review_mode="trusted_auto",
    )

    cte_sql, params = budget_grounded._scoped_records_cte(filters)

    assert "discretionary_mandatory_type <> 'mandatory'" in cte_sql
    assert "COALESCE(pphf_flag, FALSE) = FALSE" not in cte_sql
    assert params["fiscal_year"] == 2024


def test_scoped_records_cte_supports_mandatory_only_with_pphf_filter() -> None:
    filters = budget_grounded._normalize_filters(
        fiscal_year=2024,
        metric="total_funding",
        funding_type="mandatory_only",
        geography_level="state",
        time_aggregation="single_fiscal_year",
        include_mandatory=True,
        include_emergency=False,
        include_supplemental=True,
        include_pphf=False,
        include_transfers=True,
        review_mode="analyst_only",
    )

    cte_sql, _params = budget_grounded._scoped_records_cte(filters)

    assert "discretionary_mandatory_type = 'mandatory'" in cte_sql
    assert "COALESCE(pphf_flag, FALSE) = FALSE" in cte_sql
    assert "analyst_reviewed = TRUE" in cte_sql


def test_scoped_records_cte_uses_trusted_auto_review_filter() -> None:
    filters = budget_grounded._normalize_filters(
        fiscal_year=2024,
        metric="total_funding",
        funding_type="total_cdc_funding",
        geography_level="state",
        time_aggregation="single_fiscal_year",
        include_mandatory=True,
        include_emergency=False,
        include_supplemental=False,
        include_pphf=True,
        include_transfers=True,
        review_mode="trusted_auto",
    )

    cte_sql, _params = budget_grounded._scoped_records_cte(filters)

    assert "(analyst_reviewed = TRUE OR trusted_auto_seed_flag = TRUE)" in cte_sql
    assert "analyst_reviewed = TRUE" not in cte_sql.replace(
        "(analyst_reviewed = TRUE OR trusted_auto_seed_flag = TRUE)", ""
    )


def test_scoped_records_cte_all_master_universe_does_not_add_review_subset_clause() -> None:
    filters = budget_grounded._normalize_filters(
        fiscal_year=2024,
        metric="total_funding",
        funding_type="total_cdc_funding",
        geography_level="state",
        time_aggregation="single_fiscal_year",
        include_mandatory=True,
        include_emergency=False,
        include_supplemental=False,
        include_pphf=True,
        include_transfers=True,
        review_mode="all_master_universe",
    )

    cte_sql, _params = budget_grounded._scoped_records_cte(filters)

    assert "(analyst_reviewed = TRUE OR trusted_auto_seed_flag = TRUE)" not in cte_sql
    assert "analyst_reviewed = TRUE" not in cte_sql


def test_filter_defaults_use_all_master_universe_for_budget_grounded_mode() -> None:
    defaults = budget_grounded.filter_defaults()

    assert defaults["review_mode"] == "all_master_universe"
    assert defaults["include_mandatory"] is True
    assert defaults["include_pphf"] is True


def test_budget_grounded_constants_use_simplified_geometry_tolerances() -> None:
    assert budget_grounded.STATE_SIMPLIFY_DEGREES == 0.04
    assert budget_grounded.COUNTY_SIMPLIFY_DEGREES == 0.02
