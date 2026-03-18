from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa


def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "9d4e6b2f1c33_rebuild_taggs_redo_schema.py"
    )
    spec = importlib.util.spec_from_file_location("taggs_redo_migration_9d4e6b2f1c33", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeInspector:
    def __init__(self, *, columns: dict[str, list[str]], indexes: dict[str, list[str]]) -> None:
        self._columns = columns
        self._indexes = indexes

    def get_columns(self, table_name: str, schema: str | None = None) -> list[dict[str, str]]:
        return [{"name": name} for name in self._columns.get(table_name, [])]

    def get_indexes(self, table_name: str, schema: str | None = None) -> list[dict[str, str]]:
        return [{"name": name} for name in self._indexes.get(table_name, [])]


def test_migration_helper_detects_existing_columns_and_indexes(monkeypatch) -> None:
    module = _load_migration_module()
    inspector = _FakeInspector(
        columns={"raw_awards": ["source_opdiv_hint"]},
        indexes={"raw_awards": ["taggs_raw_awards_opdiv_idx"]},
    )
    monkeypatch.setattr(module, "_get_inspector", lambda: inspector)

    assert module._column_exists("taggs", "raw_awards", "source_opdiv_hint") is True
    assert module._column_exists("taggs", "raw_awards", "legal_entity_zip_code") is False
    assert module._index_exists("taggs", "raw_awards", "taggs_raw_awards_opdiv_idx") is True
    assert module._index_exists("taggs", "raw_awards", "taggs_raw_awards_issue_date_fiscal_year_idx") is False


def test_add_column_if_missing_skips_existing_column(monkeypatch) -> None:
    module = _load_migration_module()
    inspector = _FakeInspector(
        columns={"raw_awards": ["source_opdiv_hint"]},
        indexes={},
    )
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(module, "_get_inspector", lambda: inspector)
    monkeypatch.setattr(
        module,
        "op",
        SimpleNamespace(add_column=lambda *args, **kwargs: calls.append((args, kwargs))),
    )

    module._add_column_if_missing(
        "raw_awards",
        sa.Column("source_opdiv_hint", sa.Text(), nullable=True),
        schema="taggs",
    )

    assert calls == []


def test_add_column_if_missing_adds_missing_column(monkeypatch) -> None:
    module = _load_migration_module()
    inspector = _FakeInspector(columns={"raw_awards": []}, indexes={})
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(module, "_get_inspector", lambda: inspector)
    monkeypatch.setattr(
        module,
        "op",
        SimpleNamespace(add_column=lambda *args, **kwargs: calls.append((args, kwargs))),
    )

    module._add_column_if_missing(
        "raw_awards",
        sa.Column("source_opdiv_hint", sa.Text(), nullable=True),
        schema="taggs",
    )

    assert len(calls) == 1
    assert calls[0][0][0] == "raw_awards"
    assert calls[0][0][1].name == "source_opdiv_hint"
    assert calls[0][1]["schema"] == "taggs"


def test_create_index_if_missing_skips_existing_and_adds_missing(monkeypatch) -> None:
    module = _load_migration_module()
    create_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        module,
        "op",
        SimpleNamespace(create_index=lambda *args, **kwargs: create_calls.append((args, kwargs))),
    )

    existing_inspector = _FakeInspector(
        columns={},
        indexes={"raw_awards": ["taggs_raw_awards_opdiv_idx"]},
    )
    monkeypatch.setattr(module, "_get_inspector", lambda: existing_inspector)
    module._create_index_if_missing(
        "taggs_raw_awards_opdiv_idx",
        "raw_awards",
        ["opdiv"],
        unique=False,
        schema="taggs",
    )
    assert create_calls == []

    missing_inspector = _FakeInspector(columns={}, indexes={"raw_awards": []})
    monkeypatch.setattr(module, "_get_inspector", lambda: missing_inspector)
    module._create_index_if_missing(
        "taggs_raw_awards_issue_date_fiscal_year_idx",
        "raw_awards",
        ["issue_date_fiscal_year"],
        unique=False,
        schema="taggs",
    )

    assert len(create_calls) == 1
    assert create_calls[0][0][0] == "taggs_raw_awards_issue_date_fiscal_year_idx"
    assert create_calls[0][0][1] == "raw_awards"
    assert create_calls[0][0][2] == ["issue_date_fiscal_year"]
    assert create_calls[0][1]["schema"] == "taggs"
