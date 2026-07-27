from __future__ import annotations

import inspect
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.cdc_funding_api import repository, router, service
from app.cdc_funding_api.schemas import CdcFundingScope


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, *, annual_rows=None, category_mapping_rows=None, import_runs=None):
        self.annual_rows = annual_rows or []
        self.category_mapping_rows = category_mapping_rows or []
        self.import_runs = import_runs or []
        self.sql_calls: list[str] = []

    def _mapped_keys(self) -> set[tuple[int, str, str, str]]:
        keys = set()
        for row in self.category_mapping_rows:
            if row.get("mapping_status") != "Mapped":
                continue
            fiscal_year = row.get("fiscal_year")
            symbol = str(row.get("federal_account_symbol") or "").strip()
            grant_or_contract = str(row.get("grant_or_contract") or "").strip()
            emergency = str(row.get("emergency") or "").strip()
            if not symbol or not grant_or_contract or not emergency:
                continue
            keys.add((fiscal_year, symbol, grant_or_contract, emergency))
        return keys

    def _mapped_key_categories(self) -> dict[tuple[int, str, str, str], set[str]]:
        categories: dict[tuple[int, str, str, str], set[str]] = {}
        for row in self.category_mapping_rows:
            if row.get("mapping_status") != "Mapped":
                continue
            fiscal_year = row.get("fiscal_year")
            symbol = str(row.get("federal_account_symbol") or "").strip()
            grant_or_contract = str(row.get("grant_or_contract") or "").strip()
            emergency = str(row.get("emergency") or "").strip()
            category = str(row.get("category") or "").strip()
            if not symbol or not grant_or_contract or not emergency:
                continue
            categories.setdefault((fiscal_year, symbol, grant_or_contract, emergency), set()).add(category)
        return categories

    def _filtered_annual_rows(self, sql: str, fiscal_year: int | None = None):
        mapped_scope = "cdc_funding_category_mapping" in sql and "mapping.mapping_status = 'Mapped'" in sql
        mapped_keys = self._mapped_keys() if mapped_scope else set()
        rows = []
        for row in self.annual_rows:
            if fiscal_year is not None and row["fiscal_year"] != fiscal_year:
                continue
            if mapped_scope:
                key = (
                    row["fiscal_year"],
                    row["federal_account_symbol"],
                    row["grant_or_contract"],
                    row["emergency"],
                )
                if key not in mapped_keys:
                    continue
            rows.append(row)
        return rows

    def execute(self, statement, params=None):
        sql = str(statement)
        self.sql_calls.append(sql)
        params = params or {}
        if "WHERE EXISTS" in sql and "cdc_funding_import_runs" in sql:
            completed = {row["fiscal_year"] for row in self.import_runs if row["import_status"] == "completed"}
            min_fiscal_year = int(params.get("min_fiscal_year") or 0)
            years = sorted(
                {
                    row["fiscal_year"]
                    for row in self._filtered_annual_rows(sql)
                    if row["fiscal_year"] in completed and row["fiscal_year"] >= min_fiscal_year
                },
                reverse=True,
            )
            return _FakeResult([{"fiscal_year": year} for year in years])
        if (
            "GROUP BY grant_or_contract, emergency" in sql
            or "GROUP BY annual.grant_or_contract, annual.emergency" in sql
        ):
            fy = params["fiscal_year"]
            totals: dict[tuple[str, str], Decimal] = {}
            for row in self._filtered_annual_rows(sql, fy):
                key = (row["grant_or_contract"], row["emergency"])
                amount = row.get("transaction_obligated_amount")
                if amount is not None:
                    totals[key] = totals.get(key, Decimal("0.00")) + amount
            return _FakeResult(
                [
                    {
                        "grant_or_contract": grant_or_contract,
                        "emergency": emergency,
                        "obligations": obligations,
                    }
                    for (grant_or_contract, emergency), obligations in totals.items()
                ]
            )
        if "ARRAY_AGG" in sql:
            fy = params["fiscal_year"]
            if "mapping.category" in sql and "cdc_funding_category_mapping" in sql:
                conflicts = []
                for (fiscal_year, symbol, grant_or_contract, emergency), categories in self._mapped_key_categories().items():
                    nonblank_categories = {category for category in categories if category}
                    if fiscal_year == fy and len(nonblank_categories) > 1:
                        conflicts.append(
                            {
                                "fiscal_year": fiscal_year,
                                "federal_account_symbol": symbol,
                                "grant_or_contract": grant_or_contract,
                                "emergency": emergency,
                                "categories": sorted(nonblank_categories),
                            }
                        )
                return _FakeResult(conflicts)
            names_by_symbol: dict[str, set[str]] = {}
            for row in self._filtered_annual_rows(sql, fy):
                name = (row.get("federal_account_name") or "").strip()
                if name:
                    names_by_symbol.setdefault(row["federal_account_symbol"], set()).add(name)
            return _FakeResult(
                [
                    {"federal_account_symbol": symbol, "account_names": sorted(names)}
                    for symbol, names in names_by_symbol.items()
                    if len(names) > 1
                ]
            )
        if "NULLIF(BTRIM(mapping.category), '') IS NULL" in sql:
            fy = params["fiscal_year"]
            rows = []
            for (fiscal_year, symbol, grant_or_contract, emergency), categories in self._mapped_key_categories().items():
                if fiscal_year == fy and "" in categories:
                    rows.append(
                        {
                            "fiscal_year": fiscal_year,
                            "federal_account_symbol": symbol,
                            "grant_or_contract": grant_or_contract,
                            "emergency": emergency,
                        }
                    )
            return _FakeResult(rows)
        if "GROUP BY annual.fiscal_year, mapped_keys.category" in sql:
            fy = params["fiscal_year"]
            mapped_categories = self._mapped_key_categories()
            grouped: dict[str, dict] = {}
            seen_combinations: dict[str, set[tuple[int, str, str, str]]] = {}
            for row in self.annual_rows:
                if row["fiscal_year"] != fy:
                    continue
                key = (
                    row["fiscal_year"],
                    row["federal_account_symbol"],
                    row["grant_or_contract"],
                    row["emergency"],
                )
                categories = {category for category in mapped_categories.get(key, set()) if category}
                for category in categories:
                    bucket = grouped.setdefault(
                        category,
                        {
                            "fiscal_year": fy,
                            "category": category,
                            "mapped_account_combination_count": 0,
                            "total_obligations": Decimal("0.00"),
                            "emergency_obligations": Decimal("0.00"),
                            "nonemergency_obligations": Decimal("0.00"),
                            "grant_obligations": Decimal("0.00"),
                            "contract_obligations": Decimal("0.00"),
                            "emergency_grants": Decimal("0.00"),
                            "emergency_contracts": Decimal("0.00"),
                            "nonemergency_grants": Decimal("0.00"),
                            "nonemergency_contracts": Decimal("0.00"),
                        },
                    )
                    seen_combinations.setdefault(category, set()).add(key)
                    amount = row.get("transaction_obligated_amount") or Decimal("0.00")
                    bucket["total_obligations"] += amount
                    if row["emergency"] == "Emergency":
                        bucket["emergency_obligations"] += amount
                    elif row["emergency"] == "NonEmergency":
                        bucket["nonemergency_obligations"] += amount
                    if row["grant_or_contract"] == "Grant":
                        bucket["grant_obligations"] += amount
                    elif row["grant_or_contract"] == "Contract":
                        bucket["contract_obligations"] += amount
                    if row["emergency"] == "Emergency" and row["grant_or_contract"] == "Grant":
                        bucket["emergency_grants"] += amount
                    elif row["emergency"] == "Emergency" and row["grant_or_contract"] == "Contract":
                        bucket["emergency_contracts"] += amount
                    elif row["emergency"] == "NonEmergency" and row["grant_or_contract"] == "Grant":
                        bucket["nonemergency_grants"] += amount
                    elif row["emergency"] == "NonEmergency" and row["grant_or_contract"] == "Contract":
                        bucket["nonemergency_contracts"] += amount
            for category, combinations in seen_combinations.items():
                grouped[category]["mapped_account_combination_count"] = len(combinations)
            return _FakeResult(
                sorted(
                    grouped.values(),
                    key=lambda row: (-row["total_obligations"], row["category"]),
                )
            )
        if "GROUP BY federal_account_symbol" in sql or "GROUP BY annual.federal_account_symbol" in sql:
            fy = params["fiscal_year"]
            grouped: dict[str, dict] = {}
            for row in self._filtered_annual_rows(sql, fy):
                symbol = row["federal_account_symbol"]
                account = grouped.setdefault(
                    symbol,
                    {
                        "federal_account_symbol": symbol,
                        "federal_account_name": (row.get("federal_account_name") or "").strip() or None,
                        "total_obligations": Decimal("0.00"),
                        "emergency_obligations": Decimal("0.00"),
                        "nonemergency_obligations": Decimal("0.00"),
                        "emergency_grants": Decimal("0.00"),
                        "emergency_contracts": Decimal("0.00"),
                        "nonemergency_grants": Decimal("0.00"),
                        "nonemergency_contracts": Decimal("0.00"),
                    },
                )
                amount = row.get("transaction_obligated_amount") or Decimal("0.00")
                account["total_obligations"] += amount
                if row["emergency"] == "Emergency":
                    account["emergency_obligations"] += amount
                    if row["grant_or_contract"] == "Grant":
                        account["emergency_grants"] += amount
                    elif row["grant_or_contract"] == "Contract":
                        account["emergency_contracts"] += amount
                elif row["emergency"] == "NonEmergency":
                    account["nonemergency_obligations"] += amount
                    if row["grant_or_contract"] == "Grant":
                        account["nonemergency_grants"] += amount
                    elif row["grant_or_contract"] == "Contract":
                        account["nonemergency_contracts"] += amount
            rows = sorted(
                grouped.values(),
                key=lambda row: (
                    -row["total_obligations"],
                    row["federal_account_name"] is None,
                    row["federal_account_name"] or "",
                    row["federal_account_symbol"],
                ),
            )
            return _FakeResult(rows)
        raise AssertionError(f"Unexpected SQL: {sql}")


def _row(
    fiscal_year: int,
    symbol: str,
    name: str | None,
    emergency: str,
    grant_or_contract: str,
    amount: str,
):
    return {
        "fiscal_year": fiscal_year,
        "federal_account_symbol": symbol,
        "federal_account_name": name,
        "emergency": emergency,
        "grant_or_contract": grant_or_contract,
        "transaction_obligated_amount": Decimal(amount),
    }


def _mapping(
    fiscal_year: int,
    symbol: str | None,
    emergency: str | None,
    grant_or_contract: str | None,
    status: str = "Mapped",
    category: str = "Category",
):
    return {
        "fiscal_year": fiscal_year,
        "category": category,
        "mapping_status": status,
        "federal_account_symbol": symbol,
        "emergency": emergency,
        "grant_or_contract": grant_or_contract,
    }


def _fy2023_rows():
    return [
        _row(2023, "075-A", "Account A", "Emergency", "Grant", "5820366186.77"),
        _row(2023, "075-A", "Account A", "Emergency", "Contract", "681288736.13"),
        _row(2023, "075-B", "Account B", "NonEmergency", "Grant", "4934414807.93"),
        _row(2023, "075-C", "Account C", "NonEmergency", "Contract", "7218344733.64"),
    ]


def _fy2023_mapped_rows():
    rows = [
        _row(2023, "075-0140", "Public Health and Social Services Emergency Fund", "Emergency", "Grant", "5820366186.77"),
        _row(2023, "075-0512", "Grants to States for Medicaid", "NonEmergency", "Contract", "5011645993.92"),
    ]
    for index in range(15):
        rows.append(
            _row(
                2023,
                "075-0140" if index == 0 else f"075-M{index:02d}",
                "Public Health and Social Services Emergency Fund" if index == 0 else f"Mapped Account {index:02d}",
                "NonEmergency",
                "Grant",
                "299173290.09" if index < 14 else "299173290.05",
            )
        )
    return rows


def _fy2023_mapped_categories():
    categories = [f"Category {index:02d}" for index in range(15)]
    return [
        _mapping(
            row["fiscal_year"],
            row["federal_account_symbol"],
            row["emergency"],
            row["grant_or_contract"],
            category=categories[index % len(categories)],
        )
        for index, row in enumerate(_fy2023_mapped_rows())
    ]


def _session(rows=None, mappings=None, runs=None):
    return _FakeSession(
        annual_rows=rows if rows is not None else _fy2023_rows(),
        category_mapping_rows=mappings or [],
        import_runs=runs
        if runs is not None
        else [{"fiscal_year": 2023, "import_status": "completed"}],
    )


def test_fiscal_years_return_only_completed_years_with_annual_rows() -> None:
    db = _session(
        rows=[
            _row(2024, "075-A", "A", "Emergency", "Grant", "10"),
            _row(2023, "075-A", "A", "Emergency", "Grant", "10"),
            _row(2022, "075-A", "A", "Emergency", "Grant", "10"),
            _row(2020, "075-A", "A", "Emergency", "Grant", "10"),
        ],
        runs=[
            {"fiscal_year": 2024, "import_status": "completed"},
            {"fiscal_year": 2023, "import_status": "completed"},
            {"fiscal_year": 2022, "import_status": "failed"},
            {"fiscal_year": 2021, "import_status": "completed"},
            {"fiscal_year": 2020, "import_status": "loading"},
        ],
    )

    payload = service.list_fiscal_years(db)

    assert [year.fiscal_year for year in payload.fiscal_years] == [2024, 2023]
    assert payload.latest_fiscal_year == 2024
    assert [year.is_latest for year in payload.fiscal_years] == [True, False]
    assert payload.scope == CdcFundingScope.all_accounts


def test_all_account_fiscal_years_include_fy2021_through_fy2026_and_mark_latest() -> None:
    db = _session(
        rows=[
            _row(2020, "075-2020", "Account 2020", "Emergency", "Grant", "10.00"),
            *[
                _row(year, f"075-{year}", f"Account {year}", "Emergency", "Grant", "10.00")
                for year in range(2021, 2027)
            ],
        ],
        mappings=[],
        runs=[
            {"fiscal_year": 2020, "import_status": "completed"},
            *[
                {"fiscal_year": year, "import_status": "completed"}
                for year in range(2021, 2027)
            ],
        ],
    )

    payload = service.list_fiscal_years(db, scope=CdcFundingScope.all_accounts)

    assert payload.scope == CdcFundingScope.all_accounts
    assert [year.fiscal_year for year in payload.fiscal_years] == [2026, 2025, 2024, 2023, 2022, 2021]
    assert payload.latest_fiscal_year == 2026
    assert [year.is_latest for year in payload.fiscal_years] == [True, False, False, False, False, False]


def test_fiscal_years_empty_success_when_no_available_years() -> None:
    payload = service.list_fiscal_years(_session(rows=[], runs=[]))

    assert payload.scope == CdcFundingScope.all_accounts
    assert payload.fiscal_years == []
    assert payload.latest_fiscal_year is None


def test_mapped_scope_fiscal_years_require_exact_mapped_annual_rows() -> None:
    db = _session(
        rows=[
            _row(2026, "075-A", "A", "Emergency", "Grant", "10.00"),
            _row(2025, "075-B", "B", "Emergency", "Grant", "20.00"),
            _row(2024, "075-C", "C", "Emergency", "Grant", "30.00"),
        ],
        mappings=[
            _mapping(2026, "075-A", "Emergency", "Grant"),
            _mapping(2025, "075-B", "Emergency", "Contract"),
            _mapping(2024, None, None, None, status="No match"),
        ],
        runs=[
            {"fiscal_year": 2026, "import_status": "completed"},
            {"fiscal_year": 2025, "import_status": "completed"},
            {"fiscal_year": 2024, "import_status": "completed"},
        ],
    )

    payload = service.list_fiscal_years(db, scope=CdcFundingScope.cdc_funding_profiles)

    assert payload.scope == CdcFundingScope.cdc_funding_profiles
    assert [year.fiscal_year for year in payload.fiscal_years] == [2026]
    assert payload.latest_fiscal_year == 2026


def test_overview_defaults_to_latest_and_reproduces_fy2023_totals() -> None:
    payload = service.get_overview(_session(), fiscal_year=None)

    assert payload.fiscal_year == 2023
    assert payload.scope == CdcFundingScope.all_accounts
    assert payload.total_obligations == "18654414464.47"
    assert [item.label for item in payload.classifications] == [
        "Emergency Grants",
        "Emergency Contracts",
        "Nonemergency Grants",
        "Nonemergency Contracts",
    ]
    assert [item.obligations for item in payload.classifications] == [
        "5820366186.77",
        "681288736.13",
        "4934414807.93",
        "7218344733.64",
    ]
    assert payload.totals.emergency == "6501654922.90"
    assert payload.totals.nonemergency == "12152759541.57"
    assert payload.totals.grants == "10754780994.70"
    assert payload.totals.contracts == "7899633469.77"
    assert payload.reconciliation.classification_sum == "18654414464.47"
    assert payload.reconciliation.difference == "0.00"
    assert [item.percent_of_total for item in payload.classifications] == [
        "31.2010",
        "3.6522",
        "26.4517",
        "38.6951",
    ]


def test_overview_explicit_year_zero_missing_combination_negative_values_and_exact_percent() -> None:
    db = _session(
        rows=[
            _row(2024, "075-A", "A", "Emergency", "Grant", "100.00"),
            _row(2024, "075-A", "A", "NonEmergency", "Grant", "-25.00"),
            _row(2024, "075-B", "B", "NonEmergency", "Contract", "25.00"),
        ],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )

    payload = service.get_overview(db, fiscal_year=2024)

    assert payload.total_obligations == "100.00"
    assert [item.obligations for item in payload.classifications] == ["100.00", "0.00", "-25.00", "25.00"]
    assert [item.percent_of_total for item in payload.classifications] == ["100.0000", "0.0000", "-25.0000", "25.0000"]
    assert payload.reconciliation.difference == "0.00"


def test_overview_unavailable_and_no_default_year_raise_404() -> None:
    unavailable = service.get_overview

    try:
        unavailable(_session(), fiscal_year=2022)
    except Exception as exc:
        assert exc.status_code == 404
        assert exc.detail["code"] == "cdc_funding_fiscal_year_not_found"
    else:
        raise AssertionError("Expected 404")

    try:
        unavailable(_session(rows=[], runs=[]), fiscal_year=None)
    except Exception as exc:
        assert exc.status_code == 404
        assert exc.detail["code"] == "cdc_funding_no_fiscal_years_available"
    else:
        raise AssertionError("Expected 404")


def test_accounts_group_by_symbol_with_breakdowns_sorting_and_reconciliation() -> None:
    db = _session(
        rows=[
            _row(2024, "075-B", "Beta", "NonEmergency", "Grant", "50.00"),
            _row(2024, "075-A", "Alpha", "Emergency", "Grant", "60.00"),
            _row(2024, "075-A", "Alpha", "Emergency", "Contract", "40.00"),
            _row(2024, "075-A", "Alpha", "NonEmergency", "Contract", "-10.00"),
            _row(2024, "075-C", None, "NonEmergency", "Grant", "0.00"),
        ],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )

    payload = service.get_accounts(db, fiscal_year=2024)

    assert payload.scope == CdcFundingScope.all_accounts
    assert payload.total_accounts == 3
    assert [account.federal_account_symbol for account in payload.accounts] == ["075-A", "075-B", "075-C"]
    first = payload.accounts[0]
    assert first.total_obligations == "90.00"
    assert first.emergency_obligations == "100.00"
    assert first.nonemergency_obligations == "-10.00"
    assert first.emergency_share == "111.1111"
    assert first.breakdown.emergency_grants == "60.00"
    assert first.breakdown.emergency_contracts == "40.00"
    assert first.breakdown.nonemergency_grants == "0.00"
    assert first.breakdown.nonemergency_contracts == "-10.00"
    assert payload.accounts[2].emergency_share is None
    assert payload.reconciliation.account_total == "140.00"
    assert payload.reconciliation.overview_total == "140.00"
    assert payload.reconciliation.difference == "0.00"


def test_accounts_conflicting_names_for_same_symbol_returns_internal_error() -> None:
    db = _session(
        rows=[
            _row(2024, "075-A", "Alpha", "Emergency", "Grant", "10.00"),
            _row(2024, "075-A", "Alpha Renamed", "NonEmergency", "Grant", "10.00"),
        ],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )

    try:
        service.get_accounts(db, fiscal_year=2024)
    except Exception as exc:
        assert exc.status_code == 500
        assert exc.detail["code"] == "cdc_funding_internal_reconciliation_error"
    else:
        raise AssertionError("Expected 500")


def test_accounts_reproduce_fy2023_overall_total() -> None:
    payload = service.get_accounts(_session(), fiscal_year=2023)

    assert payload.scope == CdcFundingScope.all_accounts
    assert payload.total_accounts == 3
    assert payload.reconciliation.account_total == "18654414464.47"
    assert payload.reconciliation.overview_total == "18654414464.47"
    assert payload.reconciliation.difference == "0.00"


def test_scope_all_accounts_explicit_preserves_existing_totals() -> None:
    omitted = service.get_overview(_session(), fiscal_year=2023)
    explicit = service.get_overview(_session(), fiscal_year=2023, scope=CdcFundingScope.all_accounts)

    assert omitted.total_obligations == "18654414464.47"
    assert explicit.total_obligations == omitted.total_obligations
    assert [item.obligations for item in explicit.classifications] == [
        "5820366186.77",
        "681288736.13",
        "4934414807.93",
        "7218344733.64",
    ]


def test_all_accounts_scope_ignores_mapping_status_and_includes_mapped_unmapped_mixed_and_negative_rows() -> None:
    db = _session(
        rows=[
            _row(2024, "075-MIX", "Mixed", "NonEmergency", "Grant", "100.00"),
            _row(2024, "075-MIX", "Mixed", "Emergency", "Contract", "40.00"),
            _row(2024, "075-MAPPED", "Mapped", "Emergency", "Grant", "-25.00"),
            _row(2024, "075-UNMAPPED", "Unmapped", "NonEmergency", "Contract", "-10.00"),
            _row(2024, "075-NOMATCH", "No Match", "Emergency", "Grant", "5.00"),
        ],
        mappings=[
            _mapping(2024, "075-MIX", "NonEmergency", "Grant", status="Mapped"),
            _mapping(2024, "075-MIX", "Emergency", "Contract", status="No match"),
            _mapping(2024, "075-MAPPED", "Emergency", "Grant", status="Mapped"),
            _mapping(2024, "075-UNMAPPED", "NonEmergency", "Contract", status="No match"),
        ],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )

    overview = service.get_overview(db, fiscal_year=2024, scope=CdcFundingScope.all_accounts)
    accounts = service.get_accounts(db, fiscal_year=2024, scope=CdcFundingScope.all_accounts)
    sql = "\n".join(db.sql_calls)

    assert "cdc_funding.cdc_funding_category_mapping" not in sql
    assert overview.total_obligations == "110.00"
    assert [item.obligations for item in overview.classifications] == ["-20.00", "40.00", "100.00", "-10.00"]
    assert {account.federal_account_symbol for account in accounts.accounts} == {
        "075-MIX",
        "075-MAPPED",
        "075-UNMAPPED",
        "075-NOMATCH",
    }
    mixed = next(account for account in accounts.accounts if account.federal_account_symbol == "075-MIX")
    assert mixed.total_obligations == "140.00"
    assert mixed.emergency_obligations == "40.00"
    assert mixed.nonemergency_obligations == "100.00"
    assert mixed.breakdown.emergency_grants == "0.00"
    assert mixed.breakdown.emergency_contracts == "40.00"
    assert mixed.breakdown.nonemergency_grants == "100.00"
    assert mixed.breakdown.nonemergency_contracts == "0.00"
    assert accounts.reconciliation.account_total == "110.00"
    assert accounts.reconciliation.overview_total == "110.00"
    assert accounts.reconciliation.difference == "0.00"


def test_mapped_scope_filters_by_exact_composite_key_and_preserves_mixed_symbol_semantics() -> None:
    db = _session(
        rows=[
            _row(2024, "075-MIX", "Mixed", "NonEmergency", "Grant", "100.00"),
            _row(2024, "075-MIX", "Mixed", "Emergency", "Contract", "40.00"),
            _row(2024, "075-MAPPED", "Mapped", "Emergency", "Grant", "25.00"),
            _row(2024, "075-UNMAPPED", "Unmapped", "NonEmergency", "Contract", "80.00"),
        ],
        mappings=[
            _mapping(2024, "075-MIX", "NonEmergency", "Grant"),
            _mapping(2024, "075-MAPPED", "Emergency", "Grant"),
        ],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )

    overview = service.get_overview(db, fiscal_year=2024, scope=CdcFundingScope.cdc_funding_profiles)
    accounts = service.get_accounts(db, fiscal_year=2024, scope=CdcFundingScope.cdc_funding_profiles)

    assert overview.scope == CdcFundingScope.cdc_funding_profiles
    assert overview.total_obligations == "125.00"
    assert [item.obligations for item in overview.classifications] == ["25.00", "0.00", "100.00", "0.00"]
    assert [item.percent_of_total for item in overview.classifications] == ["20.0000", "0.0000", "80.0000", "0.0000"]
    assert accounts.scope == CdcFundingScope.cdc_funding_profiles
    assert [account.federal_account_symbol for account in accounts.accounts] == ["075-MIX", "075-MAPPED"]
    mixed = next(account for account in accounts.accounts if account.federal_account_symbol == "075-MIX")
    assert mixed.total_obligations == "100.00"
    assert mixed.emergency_obligations == "0.00"
    assert mixed.nonemergency_obligations == "100.00"
    assert mixed.breakdown.emergency_grants == "0.00"
    assert mixed.breakdown.emergency_contracts == "0.00"
    assert mixed.breakdown.nonemergency_grants == "100.00"
    assert mixed.breakdown.nonemergency_contracts == "0.00"
    assert accounts.reconciliation.account_total == "125.00"
    assert accounts.reconciliation.overview_total == "125.00"
    assert accounts.reconciliation.difference == "0.00"


def test_mapped_scope_matching_requires_each_key_field_and_ignores_account_name() -> None:
    rows = [
        _row(2024, "075-A", "Annual Name", "Emergency", "Grant", "10.00"),
        _row(2024, "075-B", "Annual Name", "Emergency", "Grant", "20.00"),
        _row(2024, "075-C", "Annual Name", "Emergency", "Grant", "30.00"),
        _row(2024, "075-D", "Annual Name", "Emergency", "Grant", "40.00"),
        _row(2024, "075-E", "Annual Name", "Emergency", "Grant", "50.00"),
        _row(2025, "075-A", "Annual Name", "Emergency", "Grant", "60.00"),
    ]
    mappings = [
        _mapping(2024, "075-A", "Emergency", "Grant", category="Different account name category"),
        _mapping(2023, "075-B", "Emergency", "Grant"),
        _mapping(2024, "075-C-WRONG", "Emergency", "Grant"),
        _mapping(2024, "075-D", "Emergency", "Contract"),
        _mapping(2024, "075-E", "NonEmergency", "Grant"),
        _mapping(2024, "", "", "", status="No match"),
    ]
    db = _session(
        rows=rows,
        mappings=mappings,
        runs=[
            {"fiscal_year": 2024, "import_status": "completed"},
            {"fiscal_year": 2025, "import_status": "completed"},
        ],
    )

    payload = service.get_accounts(db, fiscal_year=2024, scope=CdcFundingScope.cdc_funding_profiles)

    assert payload.total_accounts == 1
    assert payload.accounts[0].federal_account_symbol == "075-A"
    assert payload.accounts[0].total_obligations == "10.00"


def test_duplicate_mapping_rows_do_not_duplicate_annual_amounts() -> None:
    db = _session(
        rows=[
            _row(2024, "075-DUP", "Duplicate", "Emergency", "Grant", "10.00"),
        ],
        mappings=[
            _mapping(2024, "075-DUP", "Emergency", "Grant", category="Category A"),
            _mapping(2024, "075-DUP", "Emergency", "Grant", category="Category B"),
        ],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )

    payload = service.get_overview(db, fiscal_year=2024, scope=CdcFundingScope.cdc_funding_profiles)

    assert payload.total_obligations == "10.00"
    assert payload.classifications[0].obligations == "10.00"


def test_mapped_scope_name_conflicts_are_checked_only_within_included_rows() -> None:
    db = _session(
        rows=[
            _row(2024, "075-MIX", "Mapped Name", "NonEmergency", "Grant", "100.00"),
            _row(2024, "075-MIX", "Excluded Name", "Emergency", "Contract", "40.00"),
        ],
        mappings=[
            _mapping(2024, "075-MIX", "NonEmergency", "Grant"),
        ],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )

    payload = service.get_accounts(db, fiscal_year=2024, scope=CdcFundingScope.cdc_funding_profiles)

    assert payload.total_accounts == 1
    assert payload.accounts[0].federal_account_name == "Mapped Name"


def test_mapped_scope_negative_values_include_mapped_and_exclude_unmapped() -> None:
    db = _session(
        rows=[
            _row(2024, "075-MAPPED", "Mapped", "NonEmergency", "Grant", "-10.00"),
            _row(2024, "075-UNMAPPED", "Unmapped", "NonEmergency", "Grant", "-90.00"),
        ],
        mappings=[
            _mapping(2024, "075-MAPPED", "NonEmergency", "Grant"),
        ],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )

    payload = service.get_overview(db, fiscal_year=2024, scope=CdcFundingScope.cdc_funding_profiles)

    assert payload.total_obligations == "-10.00"
    assert [item.obligations for item in payload.classifications] == ["0.00", "0.00", "-10.00", "0.00"]


def test_fy2023_mapped_scope_reproduces_acceptance_controls() -> None:
    db = _session(
        rows=[*_fy2023_mapped_rows(), *_fy2023_rows()],
        mappings=_fy2023_mapped_categories(),
        runs=[{"fiscal_year": 2023, "import_status": "completed"}],
    )

    overview = service.get_overview(db, fiscal_year=2023, scope=CdcFundingScope.cdc_funding_profiles)
    accounts = service.get_accounts(db, fiscal_year=2023, scope=CdcFundingScope.cdc_funding_profiles)

    assert overview.total_obligations == "15319611532.00"
    assert [item.obligations for item in overview.classifications] == [
        "5820366186.77",
        "0.00",
        "4487599351.31",
        "5011645993.92",
    ]
    assert overview.totals.emergency == "5820366186.77"
    assert overview.totals.nonemergency == "9499245345.23"
    assert overview.totals.grants == "10307965538.08"
    assert overview.totals.contracts == "5011645993.92"
    assert overview.reconciliation.difference == "0.00"
    assert accounts.total_accounts == 16
    assert accounts.reconciliation.account_total == "15319611532.00"
    assert accounts.reconciliation.overview_total == "15319611532.00"
    assert accounts.reconciliation.difference == "0.00"


def test_categories_default_to_latest_mapped_year_and_aggregate_by_category() -> None:
    db = _session(
        rows=[
            _row(2026, "075-A", "Account A", "Emergency", "Grant", "100.00"),
            _row(2026, "075-B", "Account B", "NonEmergency", "Grant", "50.00"),
            _row(2026, "075-B", "Account B", "Emergency", "Contract", "25.00"),
            _row(2025, "075-C", "Account C", "Emergency", "Grant", "10.00"),
        ],
        mappings=[
            _mapping(2026, "075-A", "Emergency", "Grant", category="Category A"),
            _mapping(2026, "075-B", "NonEmergency", "Grant", category="Category A"),
            _mapping(2026, "075-B", "Emergency", "Contract", category="Category A"),
            _mapping(2025, "075-C", "Emergency", "Grant", category="Category C"),
        ],
        runs=[
            {"fiscal_year": 2026, "import_status": "completed"},
            {"fiscal_year": 2025, "import_status": "completed"},
        ],
    )

    payload = service.get_categories(db)

    assert payload.scope == CdcFundingScope.cdc_funding_profiles
    assert payload.fiscal_year == 2026
    assert payload.total_categories == 1
    category = payload.categories[0]
    assert category.category == "Category A"
    assert category.mapped_account_combination_count == 3
    assert category.total_obligations == "175.00"
    assert category.emergency_obligations == "125.00"
    assert category.nonemergency_obligations == "50.00"
    assert category.grant_obligations == "150.00"
    assert category.contract_obligations == "25.00"
    assert category.breakdown.emergency_grants == "100.00"
    assert category.breakdown.emergency_contracts == "25.00"
    assert category.breakdown.nonemergency_grants == "50.00"
    assert category.breakdown.nonemergency_contracts == "0.00"
    assert payload.reconciliation.category_total == "175.00"
    assert payload.reconciliation.overview_total == "175.00"
    assert payload.reconciliation.difference == "0.00"


def test_categories_exact_key_status_name_duplicate_and_negative_semantics() -> None:
    db = _session(
        rows=[
            _row(2024, "075-A", "Annual Name", "Emergency", "Grant", "100.00"),
            _row(2024, "075-A", "Annual Name", "NonEmergency", "Grant", "-25.00"),
            _row(2024, "075-B", "Same Name", "Emergency", "Grant", "999.00"),
            _row(2024, "075-C", "No Match", "Emergency", "Grant", "888.00"),
            _row(2024, "075-D", "Wrong Combo", "Emergency", "Contract", "777.00"),
        ],
        mappings=[
            _mapping(2024, "075-A", "Emergency", "Grant", category="Category A"),
            _mapping(2024, "075-A", "Emergency", "Grant", category="Category A"),
            _mapping(2024, "075-A", "NonEmergency", "Grant", category="Category B"),
            _mapping(2024, "075-B-WRONG", "Emergency", "Grant", category="Category Hidden"),
            _mapping(2024, "075-C", "Emergency", "Grant", status="No match", category="No match category"),
            _mapping(2024, "075-D", "NonEmergency", "Contract", category="Wrong Combination"),
        ],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )

    payload = service.get_categories(db, fiscal_year=2024)

    assert [category.category for category in payload.categories] == ["Category A", "Category B"]
    assert [category.total_obligations for category in payload.categories] == ["100.00", "-25.00"]
    assert payload.categories[0].mapped_account_combination_count == 1
    assert payload.reconciliation.category_total == "75.00"
    assert payload.reconciliation.overview_total == "75.00"


def test_categories_reject_all_accounts_scope_unavailable_year_and_conflicts() -> None:
    db = _session(
        rows=[_row(2024, "075-A", "A", "Emergency", "Grant", "10.00")],
        mappings=[_mapping(2024, "075-A", "Emergency", "Grant", category="Category A")],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )

    try:
        service.get_categories(db, fiscal_year=2024, scope=CdcFundingScope.all_accounts)
    except Exception as exc:
        assert exc.status_code == 422
        assert exc.detail["code"] == "cdc_funding_scope_not_supported"
    else:
        raise AssertionError("Expected 422")

    try:
        service.get_categories(db, fiscal_year=1999)
    except Exception as exc:
        assert exc.status_code == 404
        assert exc.detail["code"] == "cdc_funding_fiscal_year_not_found"
    else:
        raise AssertionError("Expected 404")

    conflict_db = _session(
        rows=[_row(2024, "075-A", "A", "Emergency", "Grant", "10.00")],
        mappings=[
            _mapping(2024, "075-A", "Emergency", "Grant", category="Category A"),
            _mapping(2024, "075-A", "Emergency", "Grant", category="Category B"),
        ],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )
    try:
        service.get_categories(conflict_db, fiscal_year=2024)
    except Exception as exc:
        assert exc.status_code == 500
        assert exc.detail["code"] == "cdc_funding_internal_reconciliation_error"
    else:
        raise AssertionError("Expected 500")


def test_categories_reject_blank_category_labels() -> None:
    db = _session(
        rows=[_row(2024, "075-A", "A", "Emergency", "Grant", "10.00")],
        mappings=[_mapping(2024, "075-A", "Emergency", "Grant", category=" ")],
        runs=[{"fiscal_year": 2024, "import_status": "completed"}],
    )

    try:
        service.get_categories(db, fiscal_year=2024)
    except Exception as exc:
        assert exc.status_code == 500
        assert exc.detail["code"] == "cdc_funding_internal_reconciliation_error"
    else:
        raise AssertionError("Expected 500")


def test_fy2023_categories_return_profile_category_rows_not_account_rows() -> None:
    db = _session(
        rows=[*_fy2023_mapped_rows(), *_fy2023_rows()],
        mappings=_fy2023_mapped_categories(),
        runs=[{"fiscal_year": 2023, "import_status": "completed"}],
    )

    payload = service.get_categories(db, fiscal_year=2023)

    assert payload.total_categories == 15
    assert len(payload.categories) == 15
    assert payload.reconciliation.category_total == "15319611532.00"
    assert payload.reconciliation.overview_total == "15319611532.00"
    assert payload.reconciliation.difference == "0.00"
    assert all(category.category for category in payload.categories)
    assert {category.category for category in payload.categories} == {
        f"Category {index:02d}" for index in range(15)
    }


def test_router_validation_and_error_shape() -> None:
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[router.get_db] = lambda: _session(
        mappings=[_mapping(2023, "075-A", "Emergency", "Grant")]
    )
    client = TestClient(app)

    malformed = client.get("/api/cdc-funding/v1/overview?fiscal_year=abc")
    assert malformed.status_code == 422

    invalid_scope = client.get("/api/cdc-funding/v1/overview?scope=unknown")
    assert invalid_scope.status_code == 422

    scoped = client.get("/api/cdc-funding/v1/fiscal-years?scope=all_accounts")
    assert scoped.status_code == 200
    assert scoped.json()["scope"] == "all_accounts"

    categories = client.get("/api/cdc-funding/v1/categories?scope=cdc_funding_profiles")
    assert categories.status_code == 200
    assert categories.json()["scope"] == "cdc_funding_profiles"

    categories_all = client.get("/api/cdc-funding/v1/categories?scope=all_accounts")
    assert categories_all.status_code == 422
    assert categories_all.json()["detail"]["code"] == "cdc_funding_scope_not_supported"

    unavailable = client.get("/api/cdc-funding/v1/overview?fiscal_year=2022")
    assert unavailable.status_code == 404
    assert unavailable.json()["detail"]["code"] == "cdc_funding_fiscal_year_not_found"


def test_source_isolation_queries_only_new_cdc_funding_tables() -> None:
    db = _session(mappings=[_mapping(2023, "075-A", "Emergency", "Grant")])

    service.get_accounts(db, fiscal_year=2023)
    service.get_accounts(db, fiscal_year=2023, scope=CdcFundingScope.cdc_funding_profiles)
    service.get_categories(db, fiscal_year=2023)

    sql = "\n".join(db.sql_calls)
    assert "cdc_funding.cdc_funding_account_annual" in sql
    assert "cdc_funding.cdc_funding_import_runs" in sql
    assert "cdc_funding.cdc_funding_category_mapping" in sql
    assert "cdc_funding.cdc_funding_unmapped_accounts" not in sql
    for forbidden in [
        "mv_cdc_funding_map",
        "fact_cdc_funding_prime_transaction",
        "chip_v1",
        "normalized_state_funding",
        "cdc_budget",
        "raw_usaspending",
    ]:
        assert forbidden not in sql


def test_new_api_modules_do_not_import_existing_map_services() -> None:
    module_source = "\n".join(
        inspect.getsource(module)
        for module in [repository, service, router]
    )

    for forbidden in [
        "app.cdc_funding.services",
        "app.cdc_funding.chip_v1",
        "app.cdc_funding.canonical",
        "app.cdc_funding.budget_grounded",
        "app.cdc_funding.intelligence",
        "app.funding.services",
    ]:
        assert forbidden not in module_source
