from __future__ import annotations

import csv
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.cdc_funding import source_ingest as ingest


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _minimal_row(spec: ingest.CsvSpec, fiscal_year: int) -> dict[str, str]:
    row = {header: "" for header in spec.headers}
    for header in spec.headers:
        column = ingest.normalize_header(header)
        if column == "fiscal_year":
            row[header] = str(fiscal_year)
        elif column == "submission_period":
            row[header] = f"FY{fiscal_year}P01"
        elif column == "fiscal_quarter":
            row[header] = "Q1"
        elif column == "period_label":
            row[header] = "P01"
        elif column == "grant_or_contract":
            row[header] = "Grant"
        elif column == "emergency":
            row[header] = "NonEmergency"
        elif column == "federal_account_symbol":
            row[header] = "075-0000"
        elif column == "federal_account_name":
            row[header] = "Example Account"
        elif column == "category":
            row[header] = "Example Category"
        elif column == "mapping_status":
            row[header] = "Mapped"
        elif column in ingest.INT_COLUMNS:
            row[header] = "1"
        elif column in ingest.MONEY_COLUMNS:
            row[header] = "0.00"
        elif column in ingest.PERCENT_COLUMNS:
            row[header] = "0.0000"
        elif column in ingest.DATE_COLUMNS:
            row[header] = "2024-01-01"
        elif column in ingest.BOOL_COLUMNS:
            row[header] = "true"
        else:
            row[header] = f"{column}-value"
    if spec.file_type == "awards":
        row["submission_period"] = f"FY{fiscal_year}P01"
        row["transaction_obligated_amount"] = "0.00"
        row["recipient_duns"] = "001234567"
        row["recipient_zip_code"] = "012340000"
        row["cfda_number"] = "01.234"
        row["naics_code"] = "001234"
        row["Emergency"] = "NonEmergency"
    return row


def _write_minimal_source_dir(tmp_path: Path, fiscal_year: int = 2024) -> Path:
    for spec in ingest.CSV_SPECS:
        filename = spec.filename.format(fiscal_year=fiscal_year)
        _write_csv(tmp_path / filename, spec.headers, [_minimal_row(spec, fiscal_year)])
    for template in ingest.AUDIT_FILES:
        filename = template.format(fiscal_year=fiscal_year)
        payload = {"fiscal_year": fiscal_year, "reference_name": filename, "checks": [{"passed": True}]}
        if "validation" in filename:
            payload["passed"] = True
        (tmp_path / filename).write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def test_parse_amount_preserves_null_zero_and_negative_values() -> None:
    assert ingest.parse_amount("") is None
    assert ingest.parse_amount("0.00") == Decimal("0.00")
    assert ingest.parse_amount("-15.25") == Decimal("-15.25")
    assert ingest.parse_amount("18,654,414,464.47") == Decimal("18654414464.47")


def test_source_headers_are_exact_and_ordered(tmp_path: Path) -> None:
    source_dir = _write_minimal_source_dir(tmp_path)
    awards = source_dir / "FY2024_CDC_awards_clean.csv"
    rows = list(csv.DictReader(awards.open(encoding="utf-8", newline="")))
    reordered = ingest.AWARD_HEADERS[:]
    reordered[0], reordered[1] = reordered[1], reordered[0]
    _write_csv(awards, reordered, [{header: rows[0].get(header, "") for header in reordered}])

    with pytest.raises(ingest.CdcFundingImportError, match="reordered"):
        ingest.validate_source_files(source_dir, 2024)


def test_missing_required_file_fails_before_database_work(tmp_path: Path) -> None:
    source_dir = _write_minimal_source_dir(tmp_path)
    (source_dir / "FY2024_CFP_unmapped_accounts.csv").unlink()

    with pytest.raises(ingest.CdcFundingImportError, match="Missing required"):
        ingest.validate_source_files(source_dir, 2024)


def test_invalid_fiscal_year_in_source_row_fails(tmp_path: Path) -> None:
    source_dir = _write_minimal_source_dir(tmp_path)
    spec = ingest.CSV_SPECS_BY_TYPE["account_annual"]
    row = _minimal_row(spec, 2023)
    _write_csv(source_dir / "FY2024_CDC_account_summary.csv", spec.headers, [row])

    with pytest.raises(ingest.CdcFundingImportError, match="expected fiscal_year 2024"):
        ingest.validate_source_files(source_dir, 2024)


def test_award_submission_period_accepts_quarter_labels(tmp_path: Path) -> None:
    source_dir = _write_minimal_source_dir(tmp_path, fiscal_year=2020)
    spec = ingest.CSV_SPECS_BY_TYPE["awards"]
    path = source_dir / "FY2020_CDC_awards_clean.csv"
    row = _minimal_row(spec, 2020)
    row["submission_period"] = "FY2020Q2"
    _write_csv(path, spec.headers, [row])

    result = ingest.validate_source_files(source_dir, 2020)

    assert result.row_counts["awards"] == 1


def test_identifier_like_values_remain_text_when_loaded(tmp_path: Path) -> None:
    source_dir = _write_minimal_source_dir(tmp_path)
    spec = ingest.CSV_SPECS_BY_TYPE["awards"]
    path = source_dir / "FY2024_CDC_awards_clean.csv"
    row = _minimal_row(spec, 2024)
    row["recipient_duns"] = "001234567"
    row["recipient_zip_code"] = "012340000"
    row["cfda_number"] = "01.234"
    row["naics_code"] = "001234"
    _write_csv(path, spec.headers, [row])

    loaded = list(ingest._iter_csv_load_rows(spec, path, 2024, import_run_id=99))

    assert loaded[0]["recipient_duns"] == "001234567"
    assert loaded[0]["recipient_zip_code"] == "012340000"
    assert loaded[0]["cfda_number"] == "01.234"
    assert loaded[0]["naics_code"] == "001234"


def test_mapping_no_match_rows_with_null_account_fields_parse(tmp_path: Path) -> None:
    source_dir = _write_minimal_source_dir(tmp_path)
    spec = ingest.CSV_SPECS_BY_TYPE["category_mapping"]
    path = source_dir / "FY2024_CFP_mapping_detail.csv"
    row = _minimal_row(spec, 2024)
    row.update(
        {
            "category": "Childhood Obesity Demonstration Project",
            "mapping_status": "No match",
            "grant_or_contract": "",
            "emergency": "",
            "federal_account_symbol": "",
            "federal_account_name": "",
            "transaction_obligated_amount": "",
            "row_count": "",
            "name_matches_expectation": "",
        }
    )
    _write_csv(path, spec.headers, [row])

    loaded = list(ingest._iter_csv_load_rows(spec, path, 2024, import_run_id=1))

    assert loaded[0]["mapping_status"] == "No match"
    assert loaded[0]["federal_account_symbol"] is None
    assert loaded[0]["transaction_obligated_amount"] is None
    assert loaded[0]["name_matches_expectation"] is None


def test_json_audits_preserve_missing_passed_distinction(tmp_path: Path) -> None:
    source_dir = _write_minimal_source_dir(tmp_path)

    result = ingest.validate_source_files(source_dir, 2024)
    audit_files = {file.file_name: file.passed for file in result.files if file.file_name.endswith(".json")}

    assert audit_files["FY2024_CFP_reference_validation.json"] is True
    assert audit_files["FY2024_CFP_comparison_audit.json"] is None


def test_new_category_file_names_and_headers_are_accepted(tmp_path: Path) -> None:
    source_dir = _write_minimal_source_dir(tmp_path, fiscal_year=2024)
    (source_dir / "FY2024_CFP_category_comparison.csv").unlink()
    (source_dir / "FY2024_CFP_mapping_detail.csv").unlink()
    (source_dir / "FY2024_CFP_unmapped_accounts.csv").unlink()
    (source_dir / "FY2024_CFP_comparison_audit.json").unlink()
    (source_dir / "FY2024_CFP_reference_validation.json").unlink()

    summary_spec = ingest.CSV_SPECS_BY_TYPE["category_comparison"]
    mapping_spec = ingest.CSV_SPECS_BY_TYPE["category_mapping"]
    unmapped_spec = ingest.CSV_SPECS_BY_TYPE["unmapped_accounts"]
    _write_csv(
        source_dir / "FY2024_category_summary.csv",
        summary_spec.alternate_headers["category_summary.csv"],
        [
            {
                "fiscal_year": "2024",
                "category": "Example Category",
                "mapping_status": "Mapped",
                "mapped_account_rows": "1",
                "usaspending_obligations": "0.00",
                "methodology_note": "source note",
            }
        ],
    )
    _write_csv(
        source_dir / "FY2024_category_mapping_detail.csv",
        mapping_spec.alternate_headers["category_mapping_detail.csv"],
        [
            {
                "fiscal_year": "2024",
                "category": "Example Category",
                "mapping_status": "Mapped",
                "grant_or_contract": "Grant",
                "emergency": "NonEmergency",
                "federal_account_symbol": "075-0000",
                "expected_account_name": "Expected",
                "actual_account_name": "Actual",
                "account_name_match": "false",
                "transaction_obligated_amount": "0.00",
                "notes": "",
            }
        ],
    )
    _write_csv(
        source_dir / "FY2024_category_unmapped_accounts.csv",
        unmapped_spec.headers,
        [_minimal_row(unmapped_spec, 2024)],
    )
    (source_dir / "FY2024_category_summary_audit.json").write_text(
        json.dumps({"fiscal_year": 2024, "checks": [{"passed": True}]}),
        encoding="utf-8",
    )
    (source_dir / "FY2024_category_reference_validation.json").write_text(
        json.dumps({"passed": True, "checks": [{"passed": True}]}),
        encoding="utf-8",
    )

    result = ingest.validate_source_files(source_dir, 2024)
    loaded = list(
        ingest._iter_csv_load_rows(
            mapping_spec,
            source_dir / "FY2024_category_mapping_detail.csv",
            2024,
            import_run_id=1,
        )
    )

    assert result.row_counts["category_comparison"] == 1
    assert result.row_counts["category_mapping"] == 1
    assert loaded[0]["expected_account_name"] == "Expected"
    assert loaded[0]["account_name_match"] is False


def test_duplicate_import_with_same_checksums_is_skipped(monkeypatch, tmp_path: Path) -> None:
    validation = ingest.validate_source_files(_write_minimal_source_dir(tmp_path), 2024)
    incoming = {file.file_name: file.sha256 for file in validation.files}
    monkeypatch.setattr(ingest, "_existing_completed_manifest", lambda _connection, _year: incoming)

    assert ingest._check_idempotence(object(), validation, replace_fiscal_year=False) == ingest.STATUS_SKIPPED


def test_changed_import_requires_replace_flag(monkeypatch, tmp_path: Path) -> None:
    validation = ingest.validate_source_files(_write_minimal_source_dir(tmp_path), 2024)
    existing = {file.file_name: file.sha256 for file in validation.files}
    first_key = next(iter(existing))
    existing[first_key] = "0" * 64
    monkeypatch.setattr(ingest, "_existing_completed_manifest", lambda _connection, _year: existing)

    with pytest.raises(ingest.CdcFundingImportError, match="--replace-fiscal-year"):
        ingest._check_idempotence(object(), validation, replace_fiscal_year=False)
    assert ingest._check_idempotence(object(), validation, replace_fiscal_year=True) == "replace"


def test_replace_failure_records_failed_run(monkeypatch, tmp_path: Path) -> None:
    validation = ingest.validate_source_files(_write_minimal_source_dir(tmp_path), 2024)
    events: list[tuple[str, str | int]] = []

    class FakeBegin:
        def __init__(self, connection_name: str):
            self.connection_name = connection_name

        def __enter__(self):
            events.append(("begin", self.connection_name))
            return self.connection_name

        def __exit__(self, exc_type, exc, tb):
            events.append(("end", self.connection_name))
            return False

    class FakeEngine:
        def __init__(self):
            self.count = 0

        def begin(self):
            self.count += 1
            return FakeBegin(f"connection-{self.count}")

    monkeypatch.setattr(ingest, "validate_source_files", lambda _source_dir, _fiscal_year: validation)
    monkeypatch.setattr(ingest, "_check_idempotence", lambda *_args, **_kwargs: "replace")
    monkeypatch.setattr(ingest, "_delete_fiscal_year", lambda _connection, fiscal_year: events.append(("delete", fiscal_year)))

    def fake_insert_run(_connection, **kwargs):
        events.append(("run_status", kwargs["status"]))
        return len([event for event in events if event[0] == "run_status"])

    monkeypatch.setattr(ingest, "_insert_import_run", fake_insert_run)
    monkeypatch.setattr(ingest, "_load_csv", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        ingest.run_import(
            engine=FakeEngine(),
            fiscal_year=2024,
            source_dir=tmp_path,
            replace_fiscal_year=True,
        )

    assert ("delete", 2024) in events
    assert ("run_status", ingest.STATUS_LOADING) in events
    assert ("run_status", ingest.STATUS_FAILED) in events
    assert ("begin", "connection-2") in events


def test_migration_upgrade_and_downgrade_are_wired(monkeypatch) -> None:
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "e5c7a9d1b3f0_add_cdc_funding_source_ingestion_tables.py"
    )
    spec = importlib.util.spec_from_file_location("cdc_funding_source_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    calls: list[tuple[str, str]] = []

    class FakeOp:
        def execute(self, statement):
            calls.append(("execute", str(statement)))

        def create_table(self, name, *args, **kwargs):
            calls.append(("create_table", name))

        def create_index(self, name, table_name, columns, **kwargs):
            calls.append(("create_index", name))

        def drop_table(self, name, **kwargs):
            calls.append(("drop_table", name))

    monkeypatch.setattr(migration, "op", FakeOp())

    migration.upgrade()
    migration.downgrade()

    created = [name for action, name in calls if action == "create_table"]
    dropped = [name for action, name in calls if action == "drop_table"]
    assert "cdc_funding_awards" in created
    assert "cdc_funding_audits" in created
    assert dropped[0] == "cdc_funding_audits"
    assert dropped[-1] == "cdc_funding_import_runs"


def test_fy2023_source_directory_acceptance_controls() -> None:
    source_dir = Path(__file__).resolve().parents[2] / "data" / "chipfunding" / "FY2023"

    result = ingest.validate_source_files(source_dir, 2023)

    assert result.row_counts["awards"] == 146293
    assert result.totals["award_obligations"] == Decimal("18654414464.47")
    assert result.quarter_totals["Q4"] == Decimal("5425952537.17")
    assert all(check["passed"] for check in result.checks)
