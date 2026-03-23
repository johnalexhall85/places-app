from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.cdc_funding import v11_emergency
from app.db import DEFAULT_DB_URL

DEFAULT_EXPORTS_ROOT = Path(__file__).resolve().parents[3] / "exports"

EXPORT_FILE_NAMES = {
    "all": "chip_v11_emergency_classification_all.csv",
    "included": "chip_v11_emergency_state_profile_included.csv",
    "centralized": "chip_v11_emergency_centralized.csv",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the CHIP v1.1 emergency-classification analytics views to CSV.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_EXPORTS_ROOT),
        help=f"Directory that will receive the export files (default: {DEFAULT_EXPORTS_ROOT}).",
    )
    parser.add_argument("--fiscal-year", type=int, default=None, help="Optional fiscal year filter.")
    parser.add_argument("--state", default=None, help="Optional 2-letter state filter.")
    return parser.parse_args()


def _where_sql(*, fiscal_year: int | None, state: str | None, alias: str = "c") -> tuple[str, dict[str, Any]]:
    clauses: list[str] = ["1 = 1"]
    params: dict[str, Any] = {}
    if fiscal_year is not None:
        clauses.append(f"{alias}.fiscal_year = :fiscal_year")
        params["fiscal_year"] = int(fiscal_year)
    if str(state or "").strip():
        clauses.append(f"{alias}.state_code = :state_code")
        params["state_code"] = str(state).strip().upper()
    return "WHERE " + " AND ".join(clauses), params


def _fetch_rows(connection: Any, *, sql: str, params: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    result = connection.execute(text(sql), params)
    rows = [dict(row) for row in result.mappings().all()]
    return list(result.keys()), rows


def _write_csv(path: Path, *, columns: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def export_views(
    *,
    db_url: str,
    output_dir: Path,
    fiscal_year: int | None = None,
    state: str | None = None,
) -> dict[str, Path]:
    where_sql, params = _where_sql(fiscal_year=fiscal_year, state=state, alias="c")
    all_sql = f"""
        SELECT *
        FROM {v11_emergency.FUNDING_CLASSIFICATION_VIEW} AS c
        {where_sql}
        ORDER BY c.fiscal_year NULLS LAST, c.state_code NULLS LAST, c.source_system ASC, c.source_transaction_id ASC
    """
    included_sql = f"""
        SELECT *
        FROM {v11_emergency.FUNDING_CLASSIFICATION_VIEW} AS c
        {where_sql} AND c.chip_include_in_state_profile IS TRUE
        ORDER BY c.fiscal_year NULLS LAST, c.state_code NULLS LAST, c.source_system ASC, c.source_transaction_id ASC
    """
    centralized_sql = f"""
        SELECT *
        FROM {v11_emergency.CENTRALIZED_VIEW} AS c
        {where_sql}
        ORDER BY c.fiscal_year NULLS LAST, c.state_code NULLS LAST, c.source_system ASC, c.source_transaction_id ASC
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    engine = create_engine(db_url, pool_pre_ping=True)
    with engine.connect() as connection:
        for export_name, sql in {
            "all": all_sql,
            "included": included_sql,
            "centralized": centralized_sql,
        }.items():
            columns, rows = _fetch_rows(connection, sql=sql, params=params)
            path = output_dir / EXPORT_FILE_NAMES[export_name]
            _write_csv(path, columns=columns, rows=rows)
            written[export_name] = path
    return written


def main() -> None:
    args = parse_args()
    written = export_views(
        db_url=str(args.db_url),
        output_dir=Path(args.output_dir),
        fiscal_year=args.fiscal_year,
        state=args.state,
    )
    for name, path in written.items():
        print(f"[chip_v11_export] wrote {name}: {path}")


if __name__ == "__main__":
    main()
