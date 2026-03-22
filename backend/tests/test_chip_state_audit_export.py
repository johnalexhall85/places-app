from __future__ import annotations

import csv
import logging
from pathlib import Path

import pytest

from app.recon import chip_state_audit_export


def _write_header_only_csv(path: Path, header: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)


class _FakeCopy:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)

    def __enter__(self) -> _FakeCopy:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        if self._chunks:
            return self._chunks.pop(0)
        return b""


class _FakeCursor:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.copy_calls: list[str] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def copy(self, sql: str) -> _FakeCopy:
        self.copy_calls.append(sql)
        return _FakeCopy(self._chunks)


class _FakeConnection:
    def __init__(self, chunks: list[bytes]) -> None:
        self.cursor_obj = _FakeCursor(chunks)

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


def test_transaction_headers_match_across_three_bucket_files(tmp_path: Path) -> None:
    header = [
        *chip_state_audit_export.TRANSACTION_FIXED_COLUMNS,
        *chip_state_audit_export.PROVENANCE_COLUMNS,
        "usaspending_prime_transaction_award_id_fain",
        "taggs_raw_award_award_title",
    ]
    included_path = tmp_path / "included.csv"
    excluded_path = tmp_path / "excluded.csv"
    null_path = tmp_path / "null.csv"

    _write_header_only_csv(included_path, header)
    _write_header_only_csv(excluded_path, header)
    _write_header_only_csv(null_path, header)

    headers_by_file = {
        "included": chip_state_audit_export._read_csv_header(included_path),  # noqa: SLF001
        "excluded": chip_state_audit_export._read_csv_header(excluded_path),  # noqa: SLF001
        "unresolved": chip_state_audit_export._read_csv_header(null_path),  # noqa: SLF001
    }

    assert chip_state_audit_export.headers_are_identical(headers_by_file) is True


def test_partition_validation_enforces_mutually_exclusive_row_ids() -> None:
    partitions = {
        "included": [{"chip_row_id": "assistance:1"}],
        "excluded": [{"chip_row_id": "contracts:2"}],
        chip_state_audit_export.NULL_BUCKET: [{"chip_row_id": "assistance:3"}],
    }

    violations = chip_state_audit_export.validate_partition_row_ids(partitions, total_candidate_rows=3)

    assert violations == []


def test_inclusion_bucket_routing_uses_true_false_and_null() -> None:
    rows = [
        {"chip_row_id": "assistance:1", "chip_inclusion_flag": True},
        {"chip_row_id": "assistance:2", "chip_inclusion_flag": False},
        {"chip_row_id": "assistance:3", "chip_inclusion_flag": None},
    ]

    partitions = chip_state_audit_export.partition_transaction_rows(rows)

    assert [row["chip_row_id"] for row in partitions["included"]] == ["assistance:1"]
    assert [row["chip_row_id"] for row in partitions["excluded"]] == ["assistance:2"]
    assert [row["chip_row_id"] for row in partitions[chip_state_audit_export.NULL_BUCKET]] == ["assistance:3"]


def test_resolve_db_url_falls_back_when_cli_value_is_blank(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    resolved = chip_state_audit_export._resolve_db_url("")  # noqa: SLF001

    assert resolved == chip_state_audit_export.DEFAULT_DB_URL


def test_resolve_db_url_prefers_environment_when_cli_value_is_blank(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://demo:demo@localhost:5432/demo")

    resolved = chip_state_audit_export._resolve_db_url("   ")  # noqa: SLF001

    assert resolved == "postgresql+psycopg://demo:demo@localhost:5432/demo"


def test_final_export_sql_normalizes_on_nonzero_state_year_weight() -> None:
    sql = " ".join(chip_state_audit_export._build_final_export_table_sql().split())  # noqa: SLF001

    assert ") OVER (PARTITION BY fb.fiscal_year, fb.chip_state) <> 0 THEN (" in sql
    assert "WHEN af.chip_inclusion_flag IS TRUE AND COALESCE(af.state_year_weight_total, 0) = 0 THEN 0::numeric(18, 2)" in sql


def test_validate_metrics_still_rejects_true_zero_weight_targets() -> None:
    with pytest.raises(RuntimeError, match="zero allocation weight"):
        chip_state_audit_export._validate_metrics(  # noqa: SLF001
            {
                "duplicate_row_id_count": 0,
                "missing_normalization_target_count": 0,
                "zero_weight_target_count": 1,
            }
        )


def test_copy_query_to_csv_streams_copy_output_after_header(tmp_path: Path) -> None:
    output_path = tmp_path / "streamed.csv"
    logger = logging.getLogger("chip_state_audit_export_test")
    logger.handlers[:] = [logging.NullHandler()]
    connection = _FakeConnection([b"1,alpha\n", b"2,beta\n"])

    chip_state_audit_export._copy_query_to_csv(  # noqa: SLF001
        connection,
        path=output_path,
        header=["id", "name"],
        select_sql="SELECT 1",
        logger=logger,
    )

    assert connection.cursor_obj.copy_calls == ["COPY (SELECT 1) TO STDOUT WITH CSV"]
    assert output_path.read_text(encoding="utf-8") == "id,name\n1,alpha\n2,beta\n"
