from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.db import DEFAULT_DB_URL
from app.db_fqtn import recon_table
from app.recon.assistance_accounts import fetch_assistance_transaction_account_rows
from app.recon.federal_accounts import build_federal_account_lookup
from app.recon.profile_calibration import rebuild as rebuild_profile_calibration
from app.recon.profile_scope import rebuild as rebuild_profile_scope

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUMMARY_PATH = REPO_ROOT / "data" / "recon" / "assistance_multi_account_fix_summary.json"
PROFILE_SCOPE_TX_FQTN = recon_table("profile_scope_transactions")
PROFILE_RECONCILIATION_FQTN = recon_table("profile_reconciliation_state_year")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize semicolon-delimited USAspending assistance federal accounts and rebuild downstream layers.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--summary-path",
        default=str(DEFAULT_SUMMARY_PATH),
        help="Output path for the before/after diagnostics JSON.",
    )
    parser.add_argument(
        "--export-review-csv",
        action="store_true",
        help="Also export the federal-account review CSV during the lookup rebuild.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the summary payload after the rebuild completes.",
    )
    return parser.parse_args()


def _serialize_json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _serialize_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize_json_value(item) for item in value]
    return value


def _relation_exists(connection: Any, relation_name: str) -> bool:
    row = connection.execute(
        text("SELECT to_regclass(:relation_name) AS exists"),
        {"relation_name": relation_name},
    ).mappings().one()
    return row["exists"] is not None


def _included_assistance_amount(connection: Any) -> Decimal:
    if not _relation_exists(connection, PROFILE_SCOPE_TX_FQTN):
        return Decimal("0.00")
    row = connection.execute(
        text(
            f"""
            SELECT COALESCE(SUM(normalized_profile_scope_amount), 0)::numeric(18, 2) AS amount
            FROM {PROFILE_SCOPE_TX_FQTN}
            WHERE source_system = 'assistance'
              AND include_in_profile_scope IS TRUE
            """
        )
    ).mappings().one()
    return Decimal(str(row["amount"] or 0)).quantize(Decimal("0.01"))


def _avg_abs_residual_pct(connection: Any) -> Decimal | None:
    if not _relation_exists(connection, PROFILE_RECONCILIATION_FQTN):
        return None
    row = connection.execute(
        text(
            f"""
            SELECT AVG(ABS(residual_pct))::numeric(12, 6) AS avg_abs_residual_pct
            FROM {PROFILE_RECONCILIATION_FQTN}
            WHERE source_system = 'usaspending'
              AND residual_pct IS NOT NULL
            """
        )
    ).mappings().one()
    if row["avg_abs_residual_pct"] is None:
        return None
    return Decimal(str(row["avg_abs_residual_pct"]))


def _state_residuals(connection: Any) -> dict[str, Decimal]:
    if not _relation_exists(connection, PROFILE_RECONCILIATION_FQTN):
        return {}
    rows = connection.execute(
        text(
            f"""
            SELECT
                state_code,
                AVG(ABS(residual_pct))::numeric(12, 6) AS avg_abs_residual_pct
            FROM {PROFILE_RECONCILIATION_FQTN}
            WHERE source_system = 'usaspending'
              AND residual_pct IS NOT NULL
            GROUP BY state_code
            """
        )
    ).mappings().all()
    return {
        str(row["state_code"]): Decimal(str(row["avg_abs_residual_pct"]))
        for row in rows
        if row.get("state_code") and row.get("avg_abs_residual_pct") is not None
    }


def _assistance_transaction_amounts(connection: Any) -> dict[str, Decimal]:
    if not _relation_exists(connection, PROFILE_SCOPE_TX_FQTN):
        return {}
    rows = connection.execute(
        text(
            f"""
            SELECT
                source_transaction_id,
                COALESCE(normalized_profile_scope_amount, 0)::numeric(18, 2) AS normalized_profile_scope_amount
            FROM {PROFILE_SCOPE_TX_FQTN}
            WHERE source_system = 'assistance'
            """
        )
    ).mappings().all()
    return {
        str(row["source_transaction_id"]): Decimal(str(row["normalized_profile_scope_amount"] or 0))
        for row in rows
        if row.get("source_transaction_id")
    }


def snapshot_metrics(connection: Any) -> dict[str, Any]:
    return {
        "included_assistance_amount": _included_assistance_amount(connection),
        "avg_abs_residual_pct": _avg_abs_residual_pct(connection),
        "state_residuals": _state_residuals(connection),
        "assistance_transaction_amounts": _assistance_transaction_amounts(connection),
    }


def build_state_improvements(
    before_state_residuals: dict[str, Decimal],
    after_state_residuals: dict[str, Decimal],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for state_code in sorted(set(before_state_residuals) | set(after_state_residuals)):
        before_value = before_state_residuals.get(state_code)
        after_value = after_state_residuals.get(state_code)
        if before_value is None or after_value is None:
            continue
        improvement = before_value - after_value
        if improvement <= 0:
            continue
        rows.append(
            {
                "state_code": state_code,
                "avg_abs_residual_pct_before": before_value,
                "avg_abs_residual_pct_after": after_value,
                "improvement_pct_points": improvement,
            }
        )
    rows.sort(key=lambda row: (row["improvement_pct_points"], row["state_code"]), reverse=True)
    return rows[:10]


def build_account_improvements(
    *,
    before_transaction_amounts: dict[str, Decimal],
    after_transaction_amounts: dict[str, Decimal],
    account_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    symbols_by_transaction: dict[str, list[str]] = {}
    for account_row in account_rows:
        transaction_id = str(account_row.get("source_transaction_id") or "")
        symbol = str(account_row.get("federal_account_symbol") or "").strip()
        if not transaction_id or not symbol:
            continue
        symbols_by_transaction.setdefault(transaction_id, [])
        if symbol not in symbols_by_transaction[transaction_id]:
            symbols_by_transaction[transaction_id].append(symbol)

    totals: dict[str, Decimal] = {}
    for transaction_id in sorted(set(before_transaction_amounts) | set(after_transaction_amounts)):
        before_amount = before_transaction_amounts.get(transaction_id, Decimal("0.00"))
        after_amount = after_transaction_amounts.get(transaction_id, Decimal("0.00"))
        delta = after_amount - before_amount
        if delta <= 0:
            continue
        linked_symbols = symbols_by_transaction.get(transaction_id, [])
        if not linked_symbols:
            continue
        allocated_delta = (delta / Decimal(len(linked_symbols))).quantize(Decimal("0.01"))
        for symbol in linked_symbols:
            totals[symbol] = totals.get(symbol, Decimal("0.00")) + allocated_delta

    rows = [
        {
            "federal_account_symbol": symbol,
            "allocated_improvement_amount": amount.quantize(Decimal("0.01")),
        }
        for symbol, amount in totals.items()
        if amount > 0
    ]
    rows.sort(key=lambda row: (row["allocated_improvement_amount"], row["federal_account_symbol"]), reverse=True)
    return rows[:15]


def build_fix_summary_payload(
    *,
    before_metrics: dict[str, Any],
    after_metrics: dict[str, Any],
    lookup_summary: dict[str, Any],
    profile_scope_summary: dict[str, Any],
    calibration_summary: dict[str, Any],
    top_account_improvements: list[dict[str, Any]],
) -> dict[str, Any]:
    bridge_summary = lookup_summary.get("assistance_account_bridge") or {}
    return {
        "included_assistance_amount_before": before_metrics.get("included_assistance_amount"),
        "included_assistance_amount_after": after_metrics.get("included_assistance_amount"),
        "avg_abs_residual_pct_before": before_metrics.get("avg_abs_residual_pct"),
        "avg_abs_residual_pct_after": after_metrics.get("avg_abs_residual_pct"),
        "single_account_rows": bridge_summary.get("single_account_rows"),
        "multi_account_rows": bridge_summary.get("multi_account_rows"),
        "missing_account_rows": bridge_summary.get("missing_account_rows"),
        "top_individual_account_symbols_extracted_from_multi_account_rows": bridge_summary.get(
            "top_individual_account_symbols_from_multi_account_rows",
            [],
        ),
        "top_multi_account_combinations_by_amount": bridge_summary.get("top_multi_account_combinations", []),
        "states_with_biggest_improvement": build_state_improvements(
            before_metrics.get("state_residuals", {}),
            after_metrics.get("state_residuals", {}),
        ),
        "top_individual_accounts_driving_improvement": top_account_improvements,
        "lookup_rebuild": lookup_summary,
        "profile_scope_rebuild": profile_scope_summary,
        "calibration_rebuild": calibration_summary,
    }


def write_summary_file(path: str | Path, summary: dict[str, Any]) -> None:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(_serialize_json_value(summary), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def rebuild_and_summarize(
    *,
    db_url: str,
    summary_path: str | Path = DEFAULT_SUMMARY_PATH,
    export_review_csv: bool = False,
) -> dict[str, Any]:
    engine = create_engine(db_url, pool_pre_ping=True)

    with engine.begin() as connection:
        before_metrics = snapshot_metrics(connection)
        lookup_summary = build_federal_account_lookup(
            connection,
            reseed_from_observed=True,
            rebuild_observations=True,
            rebuild_classification=True,
            export_review_csv=export_review_csv,
            dry_run=False,
        )

    profile_scope_summary = rebuild_profile_scope(
        db_url=db_url,
        dry_run=False,
    )
    calibration_summary = rebuild_profile_calibration(
        db_url=db_url,
        dry_run=False,
        export_summary=True,
    )

    with engine.begin() as connection:
        after_metrics = snapshot_metrics(connection)
        top_account_improvements = build_account_improvements(
            before_transaction_amounts=before_metrics.get("assistance_transaction_amounts", {}),
            after_transaction_amounts=after_metrics.get("assistance_transaction_amounts", {}),
            account_rows=fetch_assistance_transaction_account_rows(connection),
        )

    summary = build_fix_summary_payload(
        before_metrics=before_metrics,
        after_metrics=after_metrics,
        lookup_summary=lookup_summary,
        profile_scope_summary=profile_scope_summary,
        calibration_summary=calibration_summary,
        top_account_improvements=top_account_improvements,
    )
    write_summary_file(summary_path, summary)
    return summary


def print_summary(summary: dict[str, Any]) -> None:
    print(json.dumps(_serialize_json_value(summary), indent=2, sort_keys=True))


def main() -> None:
    args = parse_args()
    summary = rebuild_and_summarize(
        db_url=args.db_url,
        summary_path=args.summary_path,
        export_review_csv=bool(args.export_review_csv),
    )
    if args.verbose:
        print_summary(summary)


if __name__ == "__main__":
    main()
