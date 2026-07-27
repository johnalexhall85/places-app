from __future__ import annotations

import csv
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.pool import StaticPool

from app.cdc_funding import outlay_backfill
from app.cdc_funding import source_ingest


ACCEPTANCE_TOTALS = {
    2021: ("10382283460.24", "9111612035.68", "1270671424.56"),
    2022: ("25460376021.95", "21830152705.53", "3630223316.42"),
    2023: ("22834810140.86", "18627827987.73", "4206982153.13"),
    2024: ("21205211857.68", "17613806554.78", "3591405302.90"),
    2025: ("18646362536.07", "15684906633.73", "2961455902.34"),
    2026: ("5941276527.62", "4936719982.91", "1004556544.71"),
}


def _csv_data(
    tmp_path: Path,
    name: str,
    row: dict,
) -> outlay_backfill.CsvData:
    return outlay_backfill.CsvData(
        path=tmp_path / name,
        checksum="a" * 64,
        file_size_bytes=100,
        columns=tuple(row),
        rows=[row],
    )


def _annual_pair(
    tmp_path: Path,
    *,
    source_outlay: Decimal | None = Decimal("12.34"),
    obligations: Decimal = Decimal("50.00"),
) -> outlay_backfill.SourcePair:
    spec = outlay_backfill.BACKFILL_TABLES[0]
    original_row = {
        "fiscal_year": 2024,
        "grant_or_contract": "Grant",
        "emergency": "NonEmergency",
        "federal_account_symbol": "075-0001",
        "federal_account_name": "Example",
        "row_count": 1,
        "numeric_obligation_rows": 1,
        "transaction_obligated_amount": obligations,
        "gross_outlay_amount_fyb_to_period_end": source_outlay,
    }
    updated_row = dict(original_row)
    return outlay_backfill.SourcePair(
        spec=spec,
        original=_csv_data(tmp_path, "original.csv", original_row),
        updated=_csv_data(tmp_path, "updated.csv", updated_row),
        ignored_added_columns=(),
    )


@pytest.fixture
def annual_connection():
    engine = sa.create_engine("sqlite://", poolclass=StaticPool)
    connection = engine.connect()
    connection.exec_driver_sql("ATTACH DATABASE ':memory:' AS cdc_funding")
    metadata = sa.MetaData()
    table = sa.Table(
        "cdc_funding_account_annual",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("grant_or_contract", sa.Text()),
        sa.Column("emergency", sa.Text()),
        sa.Column("federal_account_symbol", sa.Text()),
        sa.Column("federal_account_name", sa.Text()),
        sa.Column("row_count", sa.Integer()),
        sa.Column("numeric_obligation_rows", sa.Integer()),
        sa.Column("transaction_obligated_amount", sa.Numeric(24, 2)),
        sa.Column("gross_outlay_amount_fyb_to_period_end", sa.Numeric(24, 2)),
        schema="cdc_funding",
    )
    metadata.create_all(connection)
    connection.execute(
        table.insert(),
        {
            "id": 10,
            "fiscal_year": 2024,
            "grant_or_contract": "Grant",
            "emergency": "NonEmergency",
            "federal_account_symbol": "075-0001",
            "federal_account_name": "Example",
            "row_count": 1,
            "numeric_obligation_rows": 1,
            "transaction_obligated_amount": Decimal("50.00"),
            "gross_outlay_amount_fyb_to_period_end": None,
        },
    )
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()
        engine.dispose()


def test_outlay_parser_preserves_null_zero_positive_and_negative() -> None:
    assert source_ingest.parse_outlay_amount("") is None
    assert source_ingest.parse_outlay_amount("0.00") == Decimal("0.00")
    assert source_ingest.parse_outlay_amount("12.34") == Decimal("12.34")
    assert source_ingest.parse_outlay_amount("-12.34") == Decimal("-12.34")
    assert source_ingest.parse_outlay_count("0") == 0
    assert source_ingest.parse_outlay_count("12") == 12


@pytest.mark.parametrize("value", ["$1.00", "1,000.00", "1.234", "(1.00)", "NaN"])
def test_outlay_parser_rejects_unverified_formats(value: str) -> None:
    with pytest.raises(source_ingest.CdcFundingImportError, match="Invalid outlay"):
        source_ingest.parse_outlay_amount(value)


@pytest.mark.parametrize("value", ["1.5", "one", "-1"])
def test_numeric_outlay_rows_rejects_invalid_values(value: str) -> None:
    with pytest.raises(source_ingest.CdcFundingImportError):
        source_ingest.parse_outlay_count(value)


def test_source_pair_allows_only_outlays_and_ignored_metadata(tmp_path: Path) -> None:
    spec = outlay_backfill.BACKFILL_TABLES[3]
    original_row = {
        "fiscal_year": 2024,
        "category": "Example",
        "usaspending_obligations": Decimal("10.00"),
    }
    updated_row = {
        **original_row,
        "usaspending_outlays": Decimal("7.00"),
        "data_status": "Full fiscal year",
        "as_of_period": "P12",
    }
    pair = outlay_backfill._validate_source_pair(
        _csv_data(tmp_path, "original.csv", original_row),
        _csv_data(tmp_path, "updated.csv", updated_row),
        spec,
    )
    assert pair.ignored_added_columns == ("as_of_period", "data_status")


def test_source_pair_rejects_unexpected_added_non_outlay_column(tmp_path: Path) -> None:
    spec = outlay_backfill.BACKFILL_TABLES[3]
    original_row = {"fiscal_year": 2024, "category": "Example"}
    updated_row = {
        **original_row,
        "usaspending_outlays": Decimal("1.00"),
        "new_note": "not allowed",
    }
    with pytest.raises(
        outlay_backfill.CdcFundingOutlayBackfillError,
        match="unexpected non-outlay",
    ):
        outlay_backfill._validate_source_pair(
            _csv_data(tmp_path, "original.csv", original_row),
            _csv_data(tmp_path, "updated.csv", updated_row),
            spec,
        )


def test_source_pair_rejects_changed_original_value_or_key(tmp_path: Path) -> None:
    spec = outlay_backfill.BACKFILL_TABLES[0]
    original = {
        "fiscal_year": 2024,
        "grant_or_contract": "Grant",
        "emergency": "NonEmergency",
        "federal_account_symbol": "075-0001",
        "transaction_obligated_amount": Decimal("10.00"),
        "gross_outlay_amount_fyb_to_period_end": Decimal("5.00"),
    }
    changed_value = dict(original, transaction_obligated_amount=Decimal("11.00"))
    with pytest.raises(
        outlay_backfill.CdcFundingOutlayBackfillError,
        match="Original source value changed",
    ):
        outlay_backfill._validate_source_pair(
            _csv_data(tmp_path, "original.csv", original),
            _csv_data(tmp_path, "updated.csv", changed_value),
            spec,
        )

    changed_key = dict(original, emergency="Emergency")
    with pytest.raises(
        outlay_backfill.CdcFundingOutlayBackfillError,
        match="natural-key set changed",
    ):
        outlay_backfill._validate_source_pair(
            _csv_data(tmp_path, "original.csv", original),
            _csv_data(tmp_path, "updated.csv", changed_key),
            spec,
        )


def test_csv_reader_rejects_duplicate_natural_key(tmp_path: Path) -> None:
    spec = outlay_backfill.BACKFILL_TABLES[0]
    path = tmp_path / "FY2024_CDC_account_summary.csv"
    headers = [
        "fiscal_year",
        "grant_or_contract",
        "emergency",
        "federal_account_symbol",
        "gross_outlay_amount_FYB_to_period_end",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        row = {
            "fiscal_year": "2024",
            "grant_or_contract": "Grant",
            "emergency": "NonEmergency",
            "federal_account_symbol": "075-0001",
            "gross_outlay_amount_FYB_to_period_end": "1.00",
        }
        writer.writerows([row, row])
    with pytest.raises(
        outlay_backfill.CdcFundingOutlayBackfillError,
        match="duplicate natural key",
    ):
        outlay_backfill._read_csv(path, 2024, spec)


def test_initial_backfill_updates_only_outlay_and_is_idempotent(
    annual_connection,
    tmp_path: Path,
) -> None:
    pair = _annual_pair(tmp_path)
    before = outlay_backfill.build_table_plan(
        annual_connection,
        2024,
        pair,
        dry_run=False,
        replace_existing_outlays=False,
    )
    assert before.rows_updated == 1
    fingerprint = before.non_outlay_fingerprint
    outlay_backfill._apply_plan(annual_connection, before)
    after = outlay_backfill.build_table_plan(
        annual_connection,
        2024,
        pair,
        dry_run=False,
        replace_existing_outlays=False,
    )
    assert after.rows_updated == 0
    assert after.non_outlay_fingerprint == fingerprint


def test_database_mismatch_and_existing_outlay_conflict_abort(
    annual_connection,
    tmp_path: Path,
) -> None:
    pair = _annual_pair(tmp_path, obligations=Decimal("51.00"))
    with pytest.raises(
        outlay_backfill.CdcFundingOutlayBackfillError,
        match="Database no longer matches original",
    ):
        outlay_backfill.build_table_plan(
            annual_connection,
            2024,
            pair,
            dry_run=False,
            replace_existing_outlays=False,
        )

    pair = _annual_pair(tmp_path)
    annual_connection.exec_driver_sql(
        "UPDATE cdc_funding.cdc_funding_account_annual "
        "SET gross_outlay_amount_fyb_to_period_end = 99.99"
    )
    annual_connection.commit()
    with pytest.raises(
        outlay_backfill.CdcFundingOutlayBackfillError,
        match="replace-existing-outlays",
    ):
        outlay_backfill.build_table_plan(
            annual_connection,
            2024,
            pair,
            dry_run=False,
            replace_existing_outlays=False,
        )


def test_coordinated_apply_failure_rolls_back_every_year(
    monkeypatch,
    tmp_path: Path,
) -> None:
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE applied_years (fiscal_year INTEGER PRIMARY KEY)"
        )

    pair = _annual_pair(tmp_path)
    monkeypatch.setattr(
        outlay_backfill,
        "BACKFILL_TABLES",
        (pair.spec,),
    )
    monkeypatch.setattr(
        outlay_backfill,
        "load_source_year",
        lambda _original_root, _updated_root, _fiscal_year: {
            pair.spec.file_type: pair
        },
    )
    monkeypatch.setattr(
        outlay_backfill,
        "validate_source_reconciliation",
        lambda _updated_root, _fiscal_year, _pairs: {},
    )

    def fake_build_table_plan(
        _connection,
        fiscal_year,
        source_pair,
        **_kwargs,
    ):
        return outlay_backfill.TablePlan(
            fiscal_year=fiscal_year,
            pair=source_pair,
            updates=[{"id": fiscal_year, "values": {"outlay": Decimal("1.00")}}],
            existing_null_fields=1,
            existing_matching_fields=0,
            existing_conflicting_fields=0,
            missing_schema_columns=(),
            non_outlay_fingerprint="unchanged",
            source_value_counts={"null": 0, "zero": 0, "positive": 1, "negative": 0},
        )

    def fail_during_second_year(connection, plan):
        connection.execute(
            sa.text(
                "INSERT INTO applied_years (fiscal_year) VALUES (:fiscal_year)"
            ),
            {"fiscal_year": plan.fiscal_year},
        )
        if plan.fiscal_year == 2022:
            raise outlay_backfill.CdcFundingOutlayBackfillError("forced failure")

    monkeypatch.setattr(
        outlay_backfill,
        "build_table_plan",
        fake_build_table_plan,
    )
    monkeypatch.setattr(outlay_backfill, "_apply_plan", fail_during_second_year)

    with pytest.raises(
        outlay_backfill.CdcFundingOutlayBackfillError,
        match="forced failure",
    ):
        outlay_backfill.run_backfill(
            engine=engine,
            original_root=tmp_path,
            updated_root=tmp_path / "updated",
            fiscal_years=[2021, 2022],
        )

    with engine.connect() as connection:
        assert connection.scalar(
            sa.text("SELECT count(*) FROM applied_years")
        ) == 0


def test_missing_fiscal_year_folder_fails_coordinated_source_load(tmp_path: Path) -> None:
    with pytest.raises(
        outlay_backfill.CdcFundingOutlayBackfillError,
        match="Missing original fiscal-year folder",
    ):
        outlay_backfill.load_source_year(tmp_path, tmp_path / "updated", 2024)


def test_full_import_contracts_include_all_summary_outlays() -> None:
    expected = {
        "account_annual": {"gross_outlay_amount_fyb_to_period_end"},
        "account_monthly": {"numeric_outlay_rows", "gross_outlay_amount_fyb_to_period_end"},
        "account_quarterly": {"numeric_outlay_rows", "gross_outlay_amount_fyb_to_period_end"},
        "category_comparison": {"usaspending_outlays"},
        "category_monthly": {"numeric_outlay_rows", "gross_outlay_amount_fyb_to_period_end"},
        "category_quarterly": {"numeric_outlay_rows", "gross_outlay_amount_fyb_to_period_end"},
        "unmapped_accounts": {"gross_outlay_amount_fyb_to_period_end"},
    }
    for file_type, columns in expected.items():
        assert columns <= set(source_ingest.CSV_SPECS_BY_TYPE[file_type].db_columns)


def test_migration_adds_only_expected_nullable_fixed_precision_columns(monkeypatch) -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "e8f1a3c5d7b9_add_cdc_funding_summary_outlay_columns.py"
    )
    module_spec = importlib.util.spec_from_file_location("cdc_outlay_migration", migration_path)
    assert module_spec is not None and module_spec.loader is not None
    migration = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(migration)
    added: list[sa.Column] = []
    dropped: list[str] = []

    class FakeOp:
        def add_column(self, _table_name, column, **_kwargs):
            added.append(column)

        def drop_column(self, _table_name, column_name, **_kwargs):
            dropped.append(column_name)

    monkeypatch.setattr(migration, "op", FakeOp())
    migration.upgrade()
    migration.downgrade()

    assert len(added) == 9
    assert len(dropped) == 9
    assert all(column.nullable and column.server_default is None for column in added)
    money = [column for column in added if column.name != "numeric_outlay_rows"]
    assert all(
        isinstance(column.type, sa.Numeric)
        and column.type.precision == 24
        and column.type.scale == 2
        for column in money
    )


def test_all_six_real_source_years_match_acceptance_totals() -> None:
    root = Path(__file__).resolve().parents[2] / "data" / "chipfunding"
    updated_root = root / "with_outlays"
    for fiscal_year, expected in ACCEPTANCE_TOTALS.items():
        pairs = outlay_backfill.load_source_year(root, updated_root, fiscal_year)
        result = outlay_backfill.validate_source_reconciliation(
            updated_root,
            fiscal_year,
            pairs,
        )
        assert (
            result["annual_outlays"],
            result["mapped_outlays"],
            result["unmapped_outlays"],
        ) == expected
        assert result["reconciliation_difference"] == "0.00"
        assert set(pairs) == {
            "account_annual",
            "account_monthly",
            "account_quarterly",
            "category_comparison",
            "category_monthly",
            "category_quarterly",
            "unmapped_accounts",
        }
