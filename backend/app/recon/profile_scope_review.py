from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from app.db import DEFAULT_DB_URL

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "recon" / "profile_scope_review_pack"


def _decimal_or_zero(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _format_currency(value: Any) -> str:
    amount = _decimal_or_zero(value)
    return f"${amount:,.2f}"


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(str(key))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _stringify(value) for key, value in row.items()})


def _markdown_table(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> str:
    if not rows:
        return "_No rows returned._"
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(_stringify(row.get(column)) for column in columns) + " |"
        for row in rows
    ]
    return "\n".join([header, separator, *body])


def _fetch_rows(connection: Any, sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    result = connection.execute(text(sql), params or {})
    return [dict(row) for row in result.mappings().all()]


def _top_uncertain_totals_by_year(connection: Any) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        connection,
        """
        SELECT
            fiscal_year,
            COUNT(*) AS row_count,
            SUM(raw_amount)::numeric(18, 2) AS raw_amount
        FROM recon.profile_scope_transactions
        WHERE include_in_profile_scope IS NULL
        GROUP BY fiscal_year
        ORDER BY fiscal_year
        """,
    )
    for row in rows:
        row["raw_amount_formatted"] = _format_currency(row["raw_amount"])
    return rows


def _top_uncertain_decision_contexts(connection: Any, limit: int) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        connection,
        """
        SELECT
            source_system,
            decision_context,
            COUNT(*) AS row_count,
            SUM(transaction_obligated_amount)::numeric(18, 2) AS raw_amount
        FROM (
            SELECT
                source_system,
                decision_context,
                transaction_obligated_amount
            FROM recon.assistance_transactions_profile_enriched
            WHERE include_in_profile_scope IS NULL
            UNION ALL
            SELECT
                source_system,
                decision_context,
                transaction_obligated_amount
            FROM recon.contract_transactions_profile_enriched
            WHERE include_in_profile_scope IS NULL
        ) q
        GROUP BY source_system, decision_context
        ORDER BY raw_amount DESC NULLS LAST, row_count DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )
    for row in rows:
        row["raw_amount_formatted"] = _format_currency(row["raw_amount"])
    return rows


def _top_uncertain_buckets(connection: Any, limit: int) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        connection,
        """
        SELECT
            source_system,
            fiscal_year,
            multi_account_interpretation,
            COUNT(*) AS row_count,
            SUM(raw_amount)::numeric(18, 2) AS raw_amount
        FROM recon.profile_scope_transactions
        WHERE include_in_profile_scope IS NULL
        GROUP BY source_system, fiscal_year, multi_account_interpretation
        ORDER BY raw_amount DESC NULLS LAST, row_count DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )
    for row in rows:
        row["raw_amount_formatted"] = _format_currency(row["raw_amount"])
    return rows


def _top_uncertain_families(connection: Any, limit: int) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        connection,
        """
        SELECT
            source_system,
            fiscal_year,
            federal_account_combination_key,
            multi_account_interpretation,
            COUNT(*) AS row_count,
            SUM(raw_amount)::numeric(18, 2) AS raw_amount
        FROM recon.profile_scope_transactions
        WHERE include_in_profile_scope IS NULL
          AND federal_account_combination_key IS NOT NULL
        GROUP BY source_system, fiscal_year, federal_account_combination_key, multi_account_interpretation
        ORDER BY raw_amount DESC NULLS LAST, row_count DESC
        LIMIT :limit
        """,
        {"limit": limit},
    )
    for row in rows:
        row["raw_amount_formatted"] = _format_currency(row["raw_amount"])
    return rows


def _family_sample_rows(
    connection: Any,
    *,
    source_system: str,
    fiscal_year: int,
    federal_account_combination_key: str,
    row_limit: int,
) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        connection,
        """
        SELECT
            source_transaction_id,
            recipient_name,
            state_code,
            effective_funding_scope,
            multi_account_interpretation,
            federal_account_titles_combined,
            conservative_inclusion_reason,
            raw_amount::numeric(18, 2) AS raw_amount
        FROM recon.profile_scope_transactions
        WHERE include_in_profile_scope IS NULL
          AND source_system = :source_system
          AND fiscal_year = :fiscal_year
          AND federal_account_combination_key = :federal_account_combination_key
        ORDER BY raw_amount DESC NULLS LAST, source_transaction_id
        LIMIT :row_limit
        """,
        {
            "source_system": source_system,
            "fiscal_year": fiscal_year,
            "federal_account_combination_key": federal_account_combination_key,
            "row_limit": row_limit,
        },
    )
    for row in rows:
        row["raw_amount_formatted"] = _format_currency(row["raw_amount"])
    return rows


def _family_state_rollup(
    connection: Any,
    *,
    source_system: str,
    fiscal_year: int,
    federal_account_combination_key: str,
) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        connection,
        """
        SELECT
            state_code,
            COUNT(*) AS row_count,
            SUM(raw_amount)::numeric(18, 2) AS raw_amount
        FROM recon.profile_scope_transactions
        WHERE include_in_profile_scope IS NULL
          AND source_system = :source_system
          AND fiscal_year = :fiscal_year
          AND federal_account_combination_key = :federal_account_combination_key
        GROUP BY state_code
        ORDER BY raw_amount DESC NULLS LAST, row_count DESC, state_code
        """,
        {
            "source_system": source_system,
            "fiscal_year": fiscal_year,
            "federal_account_combination_key": federal_account_combination_key,
        },
    )
    for row in rows:
        row["raw_amount_formatted"] = _format_currency(row["raw_amount"])
    return rows


def _family_recipient_rollup(
    connection: Any,
    *,
    source_system: str,
    fiscal_year: int,
    federal_account_combination_key: str,
    limit: int,
) -> list[dict[str, Any]]:
    rows = _fetch_rows(
        connection,
        """
        SELECT
            recipient_name,
            COUNT(*) AS row_count,
            SUM(raw_amount)::numeric(18, 2) AS raw_amount
        FROM recon.profile_scope_transactions
        WHERE include_in_profile_scope IS NULL
          AND source_system = :source_system
          AND fiscal_year = :fiscal_year
          AND federal_account_combination_key = :federal_account_combination_key
        GROUP BY recipient_name
        ORDER BY raw_amount DESC NULLS LAST, row_count DESC, recipient_name
        LIMIT :limit
        """,
        {
            "source_system": source_system,
            "fiscal_year": fiscal_year,
            "federal_account_combination_key": federal_account_combination_key,
            "limit": limit,
        },
    )
    for row in rows:
        row["raw_amount_formatted"] = _format_currency(row["raw_amount"])
    return rows


def _safe_key(token: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in token).strip("_").lower()


def _family_slug(row: Mapping[str, Any], index: int) -> str:
    return (
        f"{index:02d}_"
        f"{_safe_key(str(row.get('source_system') or 'unknown'))}_"
        f"fy{row.get('fiscal_year')}_"
        f"{_safe_key(str(row.get('multi_account_interpretation') or 'unknown'))}"
    )


def _build_markdown_summary(
    *,
    year_totals: Sequence[Mapping[str, Any]],
    decision_contexts: Sequence[Mapping[str, Any]],
    top_buckets: Sequence[Mapping[str, Any]],
    top_families: Sequence[Mapping[str, Any]],
    family_sections: Sequence[dict[str, Any]],
) -> str:
    lines = [
        "# Profile Scope Uncertain Review Pack",
        "",
        "This pack is read-only. It summarizes the current `include_in_profile_scope IS NULL` population",
        "from the frozen `recon.profile_scope_transactions` outputs and points review toward the largest",
        "repeat uncertain families first.",
        "",
        "## Step 1: Confirm the size of the uncertain population",
        "",
        _markdown_table(
            year_totals,
            ["fiscal_year", "row_count", "raw_amount_formatted"],
        ),
        "",
        "## Step 2: Identify the biggest decision contexts",
        "",
        _markdown_table(
            decision_contexts,
            ["source_system", "decision_context", "row_count", "raw_amount_formatted"],
        ),
        "",
        "## Step 3: Start with the biggest uncertain buckets",
        "",
        _markdown_table(
            top_buckets,
            ["source_system", "fiscal_year", "multi_account_interpretation", "row_count", "raw_amount_formatted"],
        ),
        "",
        "## Step 4: Review the biggest uncertain families",
        "",
        _markdown_table(
            top_families,
            ["source_system", "fiscal_year", "multi_account_interpretation", "row_count", "raw_amount_formatted", "federal_account_combination_key"],
        ),
        "",
        "## Step 5: Family drilldowns to review next",
        "",
    ]

    for family in family_sections:
        lines.extend(
            [
                f"### {family['slug']}",
                "",
                f"- Source: `{family['source_system']}`",
                f"- Fiscal year: `{family['fiscal_year']}`",
                f"- Multi-account interpretation: `{family['multi_account_interpretation']}`",
                f"- Family raw amount: `{family['raw_amount_formatted']}`",
                f"- Family row count: `{family['row_count']}`",
                f"- Account combination: `{family['federal_account_combination_key']}`",
                f"- Sample rows CSV: `{family['sample_rows_csv']}`",
                f"- State rollup CSV: `{family['state_rollup_csv']}`",
                f"- Recipient rollup CSV: `{family['recipient_rollup_csv']}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def build_review_pack(
    *,
    db_url: str,
    output_dir: Path,
    family_limit: int,
    row_limit: int,
) -> dict[str, Any]:
    engine = create_engine(db_url, pool_pre_ping=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    with engine.connect() as connection:
        year_totals = _top_uncertain_totals_by_year(connection)
        decision_contexts = _top_uncertain_decision_contexts(connection, limit=20)
        top_buckets = _top_uncertain_buckets(connection, limit=20)
        top_families = _top_uncertain_families(connection, limit=family_limit)

        family_sections: list[dict[str, Any]] = []
        family_dir = output_dir / "families"
        for index, family in enumerate(top_families, start=1):
            slug = _family_slug(family, index)
            sample_rows = _family_sample_rows(
                connection,
                source_system=str(family["source_system"]),
                fiscal_year=int(family["fiscal_year"]),
                federal_account_combination_key=str(family["federal_account_combination_key"]),
                row_limit=row_limit,
            )
            state_rollup = _family_state_rollup(
                connection,
                source_system=str(family["source_system"]),
                fiscal_year=int(family["fiscal_year"]),
                federal_account_combination_key=str(family["federal_account_combination_key"]),
            )
            recipient_rollup = _family_recipient_rollup(
                connection,
                source_system=str(family["source_system"]),
                fiscal_year=int(family["fiscal_year"]),
                federal_account_combination_key=str(family["federal_account_combination_key"]),
                limit=row_limit,
            )

            sample_rows_csv = family_dir / f"{slug}_sample_rows.csv"
            state_rollup_csv = family_dir / f"{slug}_state_rollup.csv"
            recipient_rollup_csv = family_dir / f"{slug}_recipient_rollup.csv"
            _write_csv(sample_rows_csv, sample_rows)
            _write_csv(state_rollup_csv, state_rollup)
            _write_csv(recipient_rollup_csv, recipient_rollup)

            family_sections.append(
                {
                    **family,
                    "slug": slug,
                    "sample_rows_csv": str(sample_rows_csv.relative_to(output_dir)),
                    "state_rollup_csv": str(state_rollup_csv.relative_to(output_dir)),
                    "recipient_rollup_csv": str(recipient_rollup_csv.relative_to(output_dir)),
                }
            )

    markdown_summary = _build_markdown_summary(
        year_totals=year_totals,
        decision_contexts=decision_contexts,
        top_buckets=top_buckets,
        top_families=top_families,
        family_sections=family_sections,
    )
    summary_path = output_dir / "README.md"
    summary_path.write_text(markdown_summary, encoding="utf-8")

    json_summary_path = output_dir / "review_summary.json"
    json_summary_path.write_text(
        json.dumps(
            {
                "year_totals": year_totals,
                "decision_contexts": decision_contexts,
                "top_buckets": top_buckets,
                "top_families": top_families,
                "family_sections": family_sections,
            },
            default=_stringify,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    _write_csv(output_dir / "uncertain_totals_by_year.csv", year_totals)
    _write_csv(output_dir / "top_uncertain_decision_contexts.csv", decision_contexts)
    _write_csv(output_dir / "top_uncertain_buckets.csv", top_buckets)
    _write_csv(output_dir / "top_uncertain_families.csv", top_families)

    return {
        "summary_path": summary_path,
        "json_summary_path": json_summary_path,
        "output_dir": output_dir,
        "family_count": len(family_sections),
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a read-only review pack for profile-scope transactions marked include_in_profile_scope IS NULL.",
    )
    parser.add_argument(
        "--db-url",
        default=DEFAULT_DB_URL,
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for markdown and CSV review artifacts (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--family-limit",
        type=int,
        default=10,
        help="Number of top uncertain families to export drilldowns for.",
    )
    parser.add_argument(
        "--row-limit",
        type=int,
        default=50,
        help="Number of top sample rows and recipients to export per family.",
    )
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    result = build_review_pack(
        db_url=str(args.db_url),
        output_dir=Path(args.output_dir).expanduser().resolve(),
        family_limit=max(1, int(args.family_limit)),
        row_limit=max(1, int(args.row_limit)),
    )
    print(f"Wrote profile-scope review pack to {result['output_dir']}")
    print(f"Summary: {result['summary_path']}")
    print(f"JSON: {result['json_summary_path']}")
    print(f"Families exported: {result['family_count']}")


if __name__ == "__main__":
    main()
