from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

from app.db import DEFAULT_DB_URL
from app.db_fqtn import cdc_funding_table, places_table, recon_table, taggs_table, usaspending_table
from app.recon.profile_scope import METHODOLOGY_VERSION as PROFILE_SCOPE_METHODOLOGY_VERSION
from app.services.chip_funding_model import FUNDING_MODEL_VERSION

DEFAULT_MOUNT_ROOT = Path("/mnt/chip-data")
DEFAULT_TMP_ROOT = DEFAULT_MOUNT_ROOT / "tmp"
DEFAULT_EXPORTS_ROOT = DEFAULT_MOUNT_ROOT / "exports"
DEFAULT_LOGS_ROOT = DEFAULT_MOUNT_ROOT / "logs"
DEFAULT_MIN_FREE_GB = 25

PROFILE_SCOPE_TX_TABLE = recon_table("profile_scope_transactions")
ASSISTANCE_PROFILE_TABLE = recon_table("assistance_transactions_profile_enriched")
CONTRACT_PROFILE_TABLE = recon_table("contract_transactions_profile_enriched")
NORMALIZED_TABLE = recon_table("normalized_state_funding")
PRIME_TX_TABLE = cdc_funding_table("prime_transactions")
PRIME_AWARD_TABLE = cdc_funding_table("prime_awards")
CONTRACT_TABLE = usaspending_table("contract_transactions_raw")
TAGGS_RAW_TABLE = taggs_table("raw_awards")
TAGGS_SUMMARY_TABLE = taggs_table("award_funding_summary")
STATE_DIM_TABLE = places_table("dim_state_boundary")

TEMP_EXPORT_TABLE = "temp_chip_state_audit_rows"
TEMP_TX_BASE_TABLE = "temp_chip_state_tx_base"
TEMP_ASSISTANCE_TABLE = "temp_chip_state_assistance_tx"
TEMP_TAGGS_LOOKUP_TABLE = "temp_chip_state_taggs_lookup"
TEMP_TAGGS_MATCH_TABLE = "temp_chip_state_taggs_best"
EXPORT_PROCESS_NAME = "chip_state_audit_export_v1"
EXPORT_LOGIC_VERSION = "chip_state_audit_v1"
TRANSFORMATION_STAGE = "recon.profile_scope_transactions_to_chip_state_audit_export"
NULL_BUCKET = "unresolved"
NON_WORD_RE = re.compile(r"[^a-z0-9]+")

EXPORT_FILE_NAMES = {
    "included": "chip_state_transactions_included.csv",
    "excluded": "chip_state_transactions_excluded.csv",
    "null": "chip_state_transactions_null.csv",
    "profile": "chip_state_funding_profile.csv",
    "dictionary": "chip_state_data_dictionary.csv",
    "methodology": "chip_state_methodology.md",
    "validation": "chip_state_validation_summary.csv",
}

TRANSACTION_BUCKET_TO_FILE_KEY = {
    "included": "included",
    "excluded": "excluded",
    NULL_BUCKET: "null",
}

TRANSACTION_FIXED_COLUMNS = [
    "chip_row_id",
    "chip_model_version",
    "chip_run_id",
    "chip_export_timestamp",
    "chip_export_batch_id",
    "chip_inclusion_flag",
    "chip_inclusion_bucket",
    "chip_inclusion_reason",
    "chip_inclusion_reason_detail",
    "chip_review_status",
    "chip_state",
    "chip_state_fips",
    "state_assignment_method",
    "state_assignment_confidence",
    "chip_data_source_primary",
    "chip_data_source_secondary",
    "chip_join_method",
    "chip_join_status",
    "chip_join_confidence",
    "chip_normalization_method",
    "chip_raw_amount",
    "chip_net_amount_for_model",
    "chip_normalized_amount",
    "chip_provenance_notes",
]

PROVENANCE_COLUMNS = [
    "prov_usaspending_source_file",
    "prov_usaspending_extract_date",
    "prov_usaspending_table_name",
    "prov_usaspending_record_id",
    "prov_taggs_source_file",
    "prov_taggs_extract_date",
    "prov_taggs_table_name",
    "prov_taggs_record_id",
    "prov_merge_run_id",
    "prov_transformation_stage",
    "prov_last_modified_by_process",
]

PROFILE_COLUMNS = [
    "state",
    "state_fips",
    "fiscal_year",
    "transaction_count",
    "total_raw_funding",
    "total_net_funding",
    "total_normalized_funding",
    "dominant_program",
    "data_quality_score",
    "model_version",
    "run_id",
]

VALIDATION_COLUMNS = [
    "total_candidate_rows",
    "included_rows",
    "excluded_rows",
    "unresolved_rows",
    "included_raw_amount_sum",
    "included_net_amount_sum",
    "included_normalized_amount_sum",
    "excluded_net_amount_sum",
    "unresolved_net_amount_sum",
    "matched_both_sources_count",
    "usaspending_only_count",
    "taggs_only_count",
    "unknown_state_count",
    "duplicate_row_id_count",
    "schema_mismatch_flag",
]

TRANSACTION_APPEARS_IN_FILES = ";".join(
    [
        EXPORT_FILE_NAMES["included"],
        EXPORT_FILE_NAMES["excluded"],
        EXPORT_FILE_NAMES["null"],
    ]
)
PROFILE_APPEARS_IN_FILES = EXPORT_FILE_NAMES["profile"]
VALIDATION_APPEARS_IN_FILES = EXPORT_FILE_NAMES["validation"]

CHIP_MODEL_VERSION = f"{FUNDING_MODEL_VERSION}+{PROFILE_SCOPE_METHODOLOGY_VERSION}+{EXPORT_LOGIC_VERSION}"


@dataclass(frozen=True)
class RawFieldSpec:
    source_system: str
    source_subsystem: str
    json_column: str
    output_prefix: str
    original_key: str
    output_column: str


@dataclass(frozen=True)
class ExportLayout:
    tmp_root: Path
    exports_root: Path
    logs_root: Path
    scratch_dir: Path
    partial_export_dir: Path
    final_export_dir: Path
    log_file: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a disk-safe CHIP state funding audit export package.",
    )
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (defaults to DATABASE_URL or the local development DSN).",
    )
    parser.add_argument(
        "--tmp-root",
        default=str(DEFAULT_TMP_ROOT),
        help=f"Scratch directory root for this export (default: {DEFAULT_TMP_ROOT}).",
    )
    parser.add_argument(
        "--exports-root",
        default=str(DEFAULT_EXPORTS_ROOT),
        help=f"Export directory root (default: {DEFAULT_EXPORTS_ROOT}).",
    )
    parser.add_argument(
        "--logs-root",
        default=str(DEFAULT_LOGS_ROOT),
        help=f"Log directory root (default: {DEFAULT_LOGS_ROOT}).",
    )
    parser.add_argument(
        "--export-date",
        default=None,
        help="Optional UTC export date in YYYYMMDD format. Defaults to the current UTC date.",
    )
    parser.add_argument(
        "--min-free-gb",
        type=int,
        default=int(os.getenv("CHIP_STATE_AUDIT_MIN_FREE_GB", DEFAULT_MIN_FREE_GB)),
        help=f"Minimum free space required on /mnt/chip-data before export (default: {DEFAULT_MIN_FREE_GB}).",
    )
    parser.add_argument(
        "--overwrite",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Replace an existing dated export directory if present.",
    )
    return parser.parse_args()


def _normalize_identifier(value: str) -> str:
    token = NON_WORD_RE.sub("_", str(value).strip().lower()).strip("_")
    return token or "field"


def _normalize_raw_output_column(prefix: str, key: str, seen: set[str]) -> str:
    base = f"{prefix}_{_normalize_identifier(key)}"
    output = base
    suffix = 2
    while output in seen:
        output = f"{base}_{suffix}"
        suffix += 1
    seen.add(output)
    return output


def _resolve_db_url(db_url: str | None) -> str:
    explicit = str(db_url or "").strip()
    if explicit:
        return explicit

    env_db_url = str(os.getenv("DATABASE_URL") or "").strip()
    if env_db_url:
        return env_db_url

    fallback = str(DEFAULT_DB_URL).strip()
    if fallback:
        return fallback

    raise ValueError(
        "No database URL is configured. Set DATABASE_URL or pass --db-url with a PostgreSQL DSN."
    )


def _psycopg_connect_dsn(db_url: str) -> str:
    url = make_url(_resolve_db_url(db_url))
    if not url.drivername.startswith("postgresql"):
        raise ValueError(f"Unsupported database driver for CHIP state audit export: {url.drivername!r}")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


def _configure_postgres_session(connection: psycopg.Connection[Any], *, logger: logging.Logger) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET max_parallel_workers_per_gather = 0")
        cursor.execute("SET jit = off")
        cursor.execute("SET work_mem = '64MB'")
        cursor.execute("SET temp_buffers = '16MB'")
        cursor.execute("SET statement_timeout = 0")
        cursor.execute("SET lock_timeout = '5s'")
    logger.info(
        "PostgreSQL session tuned for export safety: parallel query disabled, jit disabled, work_mem=64MB, temp_buffers=16MB."
    )


def _build_run_id(export_timestamp: datetime) -> str:
    seed = export_timestamp.isoformat()
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:12]
    return f"chip_state_audit_{export_timestamp.strftime('%Y%m%dT%H%M%SZ')}_{digest}"


def _build_export_batch_id(export_date: date) -> str:
    return f"chip_state_audit_export_{export_date.strftime('%Y%m%d')}"


def _parse_export_date(value: str | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    return datetime.strptime(str(value).strip(), "%Y%m%d").date()


def _setup_logger(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("chip_state_audit_export")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def _log_disk_usage(logger: logging.Logger, label: str, mount_root: Path) -> None:
    total, used, free = shutil.disk_usage(mount_root)
    logger.info(
        "%s disk usage for %s: free=%.2f GiB used=%.2f GiB total=%.2f GiB",
        label,
        mount_root,
        free / 1024**3,
        used / 1024**3,
        total / 1024**3,
    )


def _ensure_free_space(mount_root: Path, *, min_free_gb: int, logger: logging.Logger) -> None:
    free_bytes = shutil.disk_usage(mount_root).free
    min_free_bytes = int(min_free_gb) * 1024**3
    if free_bytes < min_free_bytes:
        raise RuntimeError(
            f"{mount_root} has only {free_bytes / 1024**3:.2f} GiB free; "
            f"the export requires at least {min_free_gb} GiB."
        )
    logger.info("Free-space preflight passed on %s with %.2f GiB free.", mount_root, free_bytes / 1024**3)


def _remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def _build_layout(
    *,
    tmp_root: Path,
    exports_root: Path,
    logs_root: Path,
    export_batch_id: str,
    run_id: str,
    overwrite: bool,
) -> ExportLayout:
    tmp_root.mkdir(parents=True, exist_ok=True)
    exports_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)

    scratch_dir = tmp_root / run_id
    partial_export_dir = exports_root / f".{export_batch_id}.{run_id}.partial"
    final_export_dir = exports_root / export_batch_id
    log_file = logs_root / f"{run_id}.log"

    _remove_tree(scratch_dir)
    _remove_tree(partial_export_dir)

    if final_export_dir.exists():
        if not overwrite:
            raise FileExistsError(
                f"Export directory {final_export_dir} already exists. Re-run with --overwrite to replace it."
            )
        _remove_tree(final_export_dir)

    scratch_dir.mkdir(parents=True, exist_ok=True)
    partial_export_dir.mkdir(parents=True, exist_ok=True)

    return ExportLayout(
        tmp_root=tmp_root,
        exports_root=exports_root,
        logs_root=logs_root,
        scratch_dir=scratch_dir,
        partial_export_dir=partial_export_dir,
        final_export_dir=final_export_dir,
        log_file=log_file,
    )


def _configure_temp_environment(tmp_root: Path, logger: logging.Logger) -> None:
    tmp_root.mkdir(parents=True, exist_ok=True)
    temp_value = str(tmp_root)
    for env_name in ("TMPDIR", "TEMP", "TMP", "TEMPDIR"):
        os.environ[env_name] = temp_value

    # Pandas inherits Python's tempfile settings; GNU sort honors TMPDIR.
    os.environ["POLARS_TEMP_DIR"] = temp_value
    os.environ["JOBLIB_TEMP_FOLDER"] = temp_value
    tempfile.tempdir = temp_value

    logger.info(
        "Temporary directories pinned to %s via TMPDIR/TEMP/TMP/TEMPDIR, POLARS_TEMP_DIR, JOBLIB_TEMP_FOLDER, and tempfile.tempdir.",
        tmp_root,
    )


def inclusion_bucket_for_flag(value: bool | None) -> str:
    if value is True:
        return "included"
    if value is False:
        return "excluded"
    return NULL_BUCKET


def partition_transaction_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    partitions: dict[str, list[Mapping[str, Any]]] = {"included": [], "excluded": [], NULL_BUCKET: []}
    for row in rows:
        partitions[inclusion_bucket_for_flag(row.get("chip_inclusion_flag"))].append(row)
    return partitions


def validate_partition_row_ids(
    partitions: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    total_candidate_rows: int,
) -> list[str]:
    violations: list[str] = []
    seen: set[str] = set()
    union: set[str] = set()

    for bucket_name in ("included", "excluded", NULL_BUCKET):
        bucket_rows = partitions.get(bucket_name, [])
        for row in bucket_rows:
            row_id = str(row.get("chip_row_id") or "").strip()
            if not row_id:
                violations.append(f"{bucket_name} partition contains a row without chip_row_id.")
                continue
            if row_id in union:
                violations.append(f"chip_row_id {row_id!r} appears in more than one partition.")
            union.add(row_id)
            if row_id in seen:
                violations.append(f"Duplicate chip_row_id {row_id!r} encountered while validating partitions.")
            seen.add(row_id)

    if len(union) != int(total_candidate_rows):
        violations.append(
            f"Partition row-id union size {len(union)} does not equal expected candidate row count {total_candidate_rows}."
        )

    return violations


def headers_are_identical(headers_by_file: Mapping[str, Sequence[str]]) -> bool:
    headers = list(headers_by_file.values())
    return all(list(header) == list(headers[0]) for header in headers[1:]) if headers else True


def _serialize_csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _write_rows_to_csv(path: Path, *, fieldnames: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        for row in rows:
            writer.writerow({fieldname: _serialize_csv_cell(row.get(fieldname)) for fieldname in fieldnames})


def _read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        return next(reader)


def _count_csv_data_rows(path: Path) -> int:
    line_count = 0
    with path.open("rb") as handle:
        for _line in handle:
            line_count += 1
    return max(0, line_count - 1)


def _table_exists(connection: psycopg.Connection[Any], table_name: str) -> bool:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute("SELECT to_regclass(%s) AS table_name", (table_name,))
        row = cursor.fetchone()
    return bool(row and row["table_name"])


def _require_tables(connection: psycopg.Connection[Any], table_names: Sequence[str]) -> None:
    missing = [table_name for table_name in table_names if not _table_exists(connection, table_name)]
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            "Required CHIP state audit export tables are missing: "
            f"{joined}. Rebuild the CDC funding, USAspending, TAGGS, and profile-scope layers first."
        )


def _fetch_json_object_keys(
    connection: psycopg.Connection[Any],
    *,
    table_name: str,
    json_column: str,
) -> list[str]:
    query = f"""
        SELECT DISTINCT key
        FROM (
            SELECT jsonb_object_keys({json_column}) AS key
            FROM {table_name}
            WHERE {json_column} IS NOT NULL
        ) AS raw_keys
        WHERE NULLIF(BTRIM(key), '') IS NOT NULL
        ORDER BY key
    """
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query)
        return [str(row["key"]) for row in cursor.fetchall()]


def _build_raw_field_specs(
    *,
    source_system: str,
    source_subsystem: str,
    json_column: str,
    output_prefix: str,
    keys: Sequence[str],
) -> list[RawFieldSpec]:
    seen: set[str] = set()
    specs: list[RawFieldSpec] = []
    for key in sorted({str(item) for item in keys}, key=lambda value: value.lower()):
        specs.append(
            RawFieldSpec(
                source_system=source_system,
                source_subsystem=source_subsystem,
                json_column=json_column,
                output_prefix=output_prefix,
                original_key=key,
                output_column=_normalize_raw_output_column(output_prefix, key, seen),
            )
        )
    return specs


def _discover_raw_field_specs(
    connection: psycopg.Connection[Any],
    *,
    logger: logging.Logger,
) -> list[RawFieldSpec]:
    specs = [
        *_build_raw_field_specs(
            source_system="usaspending",
            source_subsystem="prime_transaction_raw_json",
            json_column="usaspending_prime_transaction_raw",
            output_prefix="usaspending_prime_transaction",
            keys=_fetch_json_object_keys(
                connection,
                table_name=PRIME_TX_TABLE,
                json_column="raw",
            ),
        ),
        *_build_raw_field_specs(
            source_system="usaspending",
            source_subsystem="prime_award_raw_json",
            json_column="usaspending_prime_award_raw",
            output_prefix="usaspending_prime_award",
            keys=_fetch_json_object_keys(
                connection,
                table_name=PRIME_AWARD_TABLE,
                json_column="raw",
            ),
        ),
        *_build_raw_field_specs(
            source_system="usaspending",
            source_subsystem="contract_transaction_raw_json",
            json_column="usaspending_contract_raw",
            output_prefix="usaspending_contract",
            keys=_fetch_json_object_keys(
                connection,
                table_name=CONTRACT_TABLE,
                json_column="raw_row_json",
            ),
        ),
        *_build_raw_field_specs(
            source_system="taggs",
            source_subsystem="raw_award_raw_json",
            json_column="taggs_raw_award_raw",
            output_prefix="taggs_raw_award",
            keys=_fetch_json_object_keys(
                connection,
                table_name=TAGGS_RAW_TABLE,
                json_column="raw_row_json",
            ),
        ),
    ]
    logger.info("Discovered %s raw source columns for the CHIP state audit export.", len(specs))
    return specs


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _json_extract_expression(spec: RawFieldSpec) -> str:
    return f"jsonb_extract_path_text({TEMP_EXPORT_TABLE}.{spec.json_column}, {_sql_literal(spec.original_key)})"


def _normalized_aln_sql(expr: str) -> str:
    return f"LPAD(REGEXP_REPLACE(COALESCE({expr}, ''), '[^0-9]', '', 'g'), 5, '0')"


def _state_dim_join_condition(raw_expr: str, alias: str) -> str:
    return f"""
        NULLIF(BTRIM({raw_expr}), '') IS NOT NULL
        AND (
            {alias}.state_abbr = UPPER(BTRIM({raw_expr}))
            OR {alias}.state_name = UPPER(BTRIM({raw_expr}))
            OR {alias}.state_fips = LPAD(REGEXP_REPLACE(COALESCE({raw_expr}, ''), '[^0-9]', '', 'g'), 2, '0')
        )
    """


def _taggs_best_candidates_ctes(candidate_relation: str = "taggs_candidates") -> str:
    return f"""
        taggs_ranked AS (
            SELECT
                candidates.*,
                MIN(rank) OVER (PARTITION BY source_transaction_id) AS best_rank
            FROM {candidate_relation} AS candidates
        ),
        taggs_best_rank AS (
            SELECT *
            FROM taggs_ranked
            WHERE rank = best_rank
        ),
        taggs_best AS (
            SELECT *
            FROM (
                SELECT
                    taggs_best_rank.*,
                    COUNT(*) OVER (PARTITION BY source_transaction_id) AS candidate_count,
                    ROW_NUMBER() OVER (
                        PARTITION BY source_transaction_id
                        ORDER BY
                            ABS(COALESCE(sum_of_actions, 0) - COALESCE(raw_amount, 0)),
                            taggs_record_id ASC
                    ) AS rn
                FROM taggs_best_rank
            ) AS ranked_candidates
            WHERE rn = 1
        )
    """


def _build_temp_table_sql() -> str:
    assistance_recipient_state_raw = """
        COALESCE(
            NULLIF(BTRIM(pt.recipient_state_code), ''),
            NULLIF(BTRIM(pa.recipient_state_code), ''),
            NULLIF(BTRIM(pt.recipient_state_name), ''),
            NULLIF(BTRIM(pa.recipient_state_name), '')
        )
    """
    contract_recipient_state_raw = """
        COALESCE(
            NULLIF(BTRIM(uc.normalized_recipient_state), ''),
            NULLIF(BTRIM(uc.recipient_state_code), ''),
            NULLIF(BTRIM(uc.recipient_state_name), ''),
            NULLIF(BTRIM(uc.raw_row_json ->> 'recipient_state_code'), ''),
            NULLIF(BTRIM(uc.raw_row_json ->> 'recipient_state_name'), '')
        )
    """
    assistance_pop_state_raw = """
        COALESCE(
            NULLIF(BTRIM(pt.raw ->> 'primary_place_of_performance_state_code'), ''),
            NULLIF(BTRIM(pa.raw ->> 'primary_place_of_performance_state_code'), ''),
            NULLIF(BTRIM(pt.primary_place_of_performance_state_name), ''),
            NULLIF(BTRIM(pa.primary_place_of_performance_state_name), ''),
            NULLIF(BTRIM(pt.raw ->> 'primary_place_of_performance_state_name'), ''),
            NULLIF(BTRIM(pa.raw ->> 'primary_place_of_performance_state_name'), '')
        )
    """
    contract_pop_state_raw = """
        COALESCE(
            NULLIF(BTRIM(uc.raw_row_json ->> 'place_of_performance_state_code'), ''),
            NULLIF(BTRIM(uc.raw_row_json ->> 'primary_place_of_performance_state_code'), ''),
            NULLIF(BTRIM(uc.raw_row_json ->> 'place_of_performance_state_name'), ''),
            NULLIF(BTRIM(uc.raw_row_json ->> 'primary_place_of_performance_state_name'), '')
        )
    """
    usaspending_aln = _normalized_aln_sql(
        "COALESCE(NULLIF(BTRIM(pt.cfda_number), ''), NULLIF(BTRIM(pa.cfda_program_num), ''))"
    )
    taggs_aln = _normalized_aln_sql("COALESCE(NULLIF(BTRIM(tr.transaction_aln), ''), NULLIF(BTRIM(tr.aln), ''))")

    return f"""
        CREATE TEMP TABLE {TEMP_EXPORT_TABLE} ON COMMIT DROP AS
        WITH state_dim AS (
            SELECT
                state_fips,
                UPPER(BTRIM(state_abbr)) AS state_abbr,
                UPPER(BTRIM(state_name)) AS state_name
            FROM {STATE_DIM_TABLE}
        ),
        tx_base AS (
            SELECT
                tx.source_system,
                tx.source_transaction_id,
                tx.fiscal_year,
                tx.include_in_profile_scope AS model_inclusion_flag,
                tx.inclusion_reason AS model_inclusion_reason,
                tx.raw_amount::numeric(18, 2) AS chip_raw_amount,
                tx.normalized_profile_scope_amount::numeric(18, 2) AS model_net_amount,
                tx.methodology_version AS profile_scope_methodology_version,
                tx.effective_funding_stream,
                tx.funding_scope_method,
                tx.effective_funding_scope,
                COALESCE(ae.manual_review_recommended, ce.manual_review_recommended, tx.manual_review_recommended) AS manual_review_recommended,
                COALESCE(ae.decision_context, ce.decision_context) AS decision_context,
                COALESCE(ae.exclusion_reason, ce.exclusion_reason) AS model_exclusion_reason,
                COALESCE(ae.recipient_country_name, ce.recipient_country_name) AS recipient_country_name,
                COALESCE(ae.awarding_agency_name, ce.awarding_agency_name) AS awarding_agency_name,
                COALESCE(ae.funding_agency_name, ce.funding_agency_name) AS funding_agency_name,
                COALESCE(ae.assistance_listing_title, ce.award_description) AS primary_program_title,
                ce.contract_category_guess,
                CASE
                    WHEN tx.source_system = 'assistance' THEN {assistance_recipient_state_raw}
                    ELSE {contract_recipient_state_raw}
                END AS recipient_state_raw,
                CASE
                    WHEN tx.source_system = 'assistance' THEN {assistance_pop_state_raw}
                    ELSE {contract_pop_state_raw}
                END AS place_of_performance_state_raw,
                UPPER(
                    BTRIM(
                        COALESCE(
                            CASE
                                WHEN tx.source_system = 'assistance' THEN {assistance_recipient_state_raw}
                                ELSE {contract_recipient_state_raw}
                            END,
                            CASE
                                WHEN tx.source_system = 'assistance' THEN {assistance_pop_state_raw}
                                ELSE {contract_pop_state_raw}
                            END,
                            ''
                        )
                    )
                ) AS usaspending_state_key,
                NULLIF(BTRIM(COALESCE(pt.award_id_fain, pa.fain)), '') AS award_number_key,
                {usaspending_aln} AS normalized_usaspending_aln,
                pt.raw AS usaspending_prime_transaction_raw,
                pa.raw AS usaspending_prime_award_raw,
                uc.raw_row_json AS usaspending_contract_raw,
                COALESCE(pt.source_file_name, pa.source_file_name, uc.source_filename) AS prov_usaspending_source_file,
                CASE
                    WHEN tx.source_system = 'assistance'
                        THEN COALESCE(pt.source_imported_at::date::text, pa.source_imported_at::date::text)
                    ELSE uc.loaded_at::date::text
                END AS prov_usaspending_extract_date,
                CASE
                    WHEN tx.source_system = 'assistance'
                        THEN { _sql_literal(PRIME_TX_TABLE) }
                    ELSE { _sql_literal(CONTRACT_TABLE) }
                END AS prov_usaspending_table_name,
                CASE
                    WHEN tx.source_system = 'assistance'
                        THEN COALESCE(NULLIF(BTRIM(pt.assistance_transaction_unique_key), ''), pt.id::text)
                    ELSE COALESCE(NULLIF(BTRIM(uc.contract_transaction_unique_key), ''), uc.id::text)
                END AS prov_usaspending_record_id
            FROM {PROFILE_SCOPE_TX_TABLE} AS tx
            LEFT JOIN {ASSISTANCE_PROFILE_TABLE} AS ae
                ON tx.source_system = 'assistance'
               AND ae.source_transaction_id = tx.source_transaction_id
            LEFT JOIN {CONTRACT_PROFILE_TABLE} AS ce
                ON tx.source_system = 'contracts'
               AND ce.source_transaction_id = tx.source_transaction_id
            LEFT JOIN {PRIME_TX_TABLE} AS pt
                ON tx.source_system = 'assistance'
               AND tx.source_transaction_id = COALESCE(NULLIF(BTRIM(pt.assistance_transaction_unique_key), ''), pt.id::text)
            LEFT JOIN {PRIME_AWARD_TABLE} AS pa
                ON tx.source_system = 'assistance'
               AND pa.unique_key = pt.assistance_award_unique_key
            LEFT JOIN {CONTRACT_TABLE} AS uc
                ON tx.source_system = 'contracts'
               AND tx.source_transaction_id = COALESCE(NULLIF(BTRIM(uc.contract_transaction_unique_key), ''), uc.id::text)
        ),
        assistance_tx AS MATERIALIZED (
            SELECT
                source_transaction_id,
                fiscal_year,
                chip_raw_amount,
                usaspending_state_key,
                award_number_key,
                normalized_usaspending_aln
            FROM tx_base
            WHERE source_system = 'assistance'
        ),
        taggs_base AS MATERIALIZED (
            SELECT
                tr.id AS taggs_record_id,
                tr.raw_row_json AS taggs_raw_award_raw,
                tr.source_filename AS prov_taggs_source_file,
                tr.loaded_at::date::text AS prov_taggs_extract_date,
                NULLIF(BTRIM(tr.award_number), '') AS award_number_key,
                {taggs_aln} AS normalized_taggs_aln,
                NULLIF(
                    BTRIM(COALESCE(tr.legal_entity_state_normalized, tr.legal_entity_state)),
                    ''
                ) AS taggs_state_raw,
                UPPER(
                    BTRIM(
                        COALESCE(tr.legal_entity_state_normalized, tr.legal_entity_state, '')
                    )
                ) AS taggs_state_key,
                tr.funding_fiscal_year,
                tr.sum_of_actions,
                COALESCE(
                    summary.effective_program_name,
                    summary.effective_subcategory,
                    summary.assistance_listing_title,
                    tr.award_title,
                    tr.assistance_listing_title
                ) AS dominant_program_candidate
            FROM {TAGGS_RAW_TABLE} AS tr
            LEFT JOIN {TAGGS_SUMMARY_TABLE} AS summary
                ON summary.award_number = tr.award_number
               AND summary.funding_fiscal_year = tr.funding_fiscal_year
               AND COALESCE(summary.can_code, '') = COALESCE(tr.can_code, '')
               AND UPPER(COALESCE(summary.legal_entity_state_normalized, '')) =
                   UPPER(COALESCE(tr.legal_entity_state_normalized, ''))
        ),
        taggs_candidates AS (
            SELECT
                tx.source_transaction_id,
                tx.chip_raw_amount AS raw_amount,
                taggs.taggs_record_id,
                taggs.sum_of_actions,
                taggs.taggs_raw_award_raw,
                taggs.prov_taggs_source_file,
                taggs.prov_taggs_extract_date,
                taggs.taggs_state_raw,
                taggs.dominant_program_candidate,
                1 AS rank,
                'award_number_state_year' AS join_method,
                'high' AS join_confidence
            FROM assistance_tx AS tx
            JOIN taggs_base AS taggs
                ON tx.award_number_key IS NOT NULL
               AND taggs.award_number_key = tx.award_number_key
               AND taggs.funding_fiscal_year = tx.fiscal_year
               AND tx.usaspending_state_key <> ''
               AND taggs.taggs_state_key = tx.usaspending_state_key

            UNION ALL

            SELECT
                tx.source_transaction_id,
                tx.chip_raw_amount AS raw_amount,
                taggs.taggs_record_id,
                taggs.sum_of_actions,
                taggs.taggs_raw_award_raw,
                taggs.prov_taggs_source_file,
                taggs.prov_taggs_extract_date,
                taggs.taggs_state_raw,
                taggs.dominant_program_candidate,
                2 AS rank,
                'award_number_fiscal_year' AS join_method,
                'medium' AS join_confidence
            FROM assistance_tx AS tx
            JOIN taggs_base AS taggs
                ON tx.award_number_key IS NOT NULL
               AND taggs.award_number_key = tx.award_number_key
               AND taggs.funding_fiscal_year = tx.fiscal_year

            UNION ALL

            SELECT
                tx.source_transaction_id,
                tx.chip_raw_amount AS raw_amount,
                taggs.taggs_record_id,
                taggs.sum_of_actions,
                taggs.taggs_raw_award_raw,
                taggs.prov_taggs_source_file,
                taggs.prov_taggs_extract_date,
                taggs.taggs_state_raw,
                taggs.dominant_program_candidate,
                3 AS rank,
                'aln_state_year' AS join_method,
                'medium' AS join_confidence
            FROM assistance_tx AS tx
            JOIN taggs_base AS taggs
                ON tx.normalized_usaspending_aln <> '00000'
               AND taggs.normalized_taggs_aln = tx.normalized_usaspending_aln
               AND taggs.funding_fiscal_year = tx.fiscal_year
               AND tx.usaspending_state_key <> ''
               AND taggs.taggs_state_key = tx.usaspending_state_key

            UNION ALL

            SELECT
                tx.source_transaction_id,
                tx.chip_raw_amount AS raw_amount,
                taggs.taggs_record_id,
                taggs.sum_of_actions,
                taggs.taggs_raw_award_raw,
                taggs.prov_taggs_source_file,
                taggs.prov_taggs_extract_date,
                taggs.taggs_state_raw,
                taggs.dominant_program_candidate,
                4 AS rank,
                'aln_fiscal_year' AS join_method,
                'low' AS join_confidence
            FROM assistance_tx AS tx
            JOIN taggs_base AS taggs
                ON tx.normalized_usaspending_aln <> '00000'
               AND taggs.normalized_taggs_aln = tx.normalized_usaspending_aln
               AND taggs.funding_fiscal_year = tx.fiscal_year
        ),
        {_taggs_best_candidates_ctes()}
        ,
        state_assignment AS (
            SELECT
                tx.*,
                taggs_best.taggs_record_id AS prov_taggs_record_id,
                taggs_best.taggs_raw_award_raw,
                taggs_best.prov_taggs_source_file,
                taggs_best.prov_taggs_extract_date,
                CASE
                    WHEN taggs_best.taggs_record_id IS NOT NULL THEN { _sql_literal(TAGGS_RAW_TABLE) }
                    ELSE NULL
                END AS prov_taggs_table_name,
                taggs_best.taggs_state_raw,
                taggs_best.join_method AS matched_join_method,
                taggs_best.join_confidence AS matched_join_confidence,
                taggs_best.candidate_count AS matched_join_candidate_count,
                taggs_best.dominant_program_candidate AS taggs_program_candidate,
                (tx.award_number_key IS NOT NULL OR tx.normalized_usaspending_aln <> '00000') AS join_input_available,
                recipient_dim.state_abbr AS recipient_state_resolved,
                recipient_dim.state_fips AS recipient_state_fips,
                recipient_dim.state_name AS recipient_state_name,
                pop_dim.state_abbr AS pop_state_resolved,
                pop_dim.state_fips AS pop_state_fips,
                pop_dim.state_name AS pop_state_name,
                taggs_dim.state_abbr AS taggs_state_resolved,
                taggs_dim.state_fips AS taggs_state_fips,
                taggs_dim.state_name AS taggs_state_name
            FROM tx_base AS tx
            LEFT JOIN taggs_best
                ON tx.source_system = 'assistance'
               AND taggs_best.source_transaction_id = tx.source_transaction_id
            LEFT JOIN state_dim AS recipient_dim
                ON { _state_dim_join_condition("tx.recipient_state_raw", "recipient_dim") }
            LEFT JOIN state_dim AS pop_dim
                ON { _state_dim_join_condition("tx.place_of_performance_state_raw", "pop_dim") }
            LEFT JOIN state_dim AS taggs_dim
                ON { _state_dim_join_condition("taggs_best.taggs_state_raw", "taggs_dim") }
        ),
        decision_base AS (
            SELECT
                sa.*,
                CASE
                    WHEN sa.source_system <> 'assistance' THEN 'not_applicable'
                    WHEN sa.prov_taggs_record_id IS NOT NULL AND COALESCE(sa.matched_join_candidate_count, 0) > 1 THEN 'matched_ambiguous'
                    WHEN sa.prov_taggs_record_id IS NOT NULL THEN 'matched'
                    WHEN sa.join_input_available THEN 'unmatched'
                    ELSE 'not_attempted'
                END AS chip_join_status,
                CASE
                    WHEN sa.recipient_state_resolved IS NOT NULL THEN sa.recipient_state_resolved
                    WHEN sa.pop_state_resolved IS NOT NULL THEN sa.pop_state_resolved
                    WHEN sa.taggs_state_resolved IS NOT NULL THEN sa.taggs_state_resolved
                    ELSE NULL
                END AS chip_state,
                CASE
                    WHEN sa.recipient_state_resolved IS NOT NULL THEN sa.recipient_state_fips
                    WHEN sa.pop_state_resolved IS NOT NULL THEN sa.pop_state_fips
                    WHEN sa.taggs_state_resolved IS NOT NULL THEN sa.taggs_state_fips
                    ELSE NULL
                END AS chip_state_fips,
                CASE
                    WHEN sa.recipient_state_resolved IS NOT NULL THEN 'usaspending_recipient_state'
                    WHEN sa.pop_state_resolved IS NOT NULL THEN 'usaspending_place_of_performance_state'
                    WHEN sa.taggs_state_resolved IS NOT NULL THEN 'taggs_state'
                    ELSE 'unknown'
                END AS state_assignment_method,
                CASE
                    WHEN sa.recipient_state_resolved IS NOT NULL THEN 'high'
                    WHEN sa.pop_state_resolved IS NOT NULL THEN 'medium'
                    WHEN sa.taggs_state_resolved IS NOT NULL THEN 'low'
                    ELSE NULL
                END AS state_assignment_confidence
            FROM state_assignment AS sa
        ),
        final_base AS (
            SELECT
                db.source_system || ':' || db.source_transaction_id AS chip_row_id,
                %(chip_model_version)s::text AS chip_model_version,
                %(run_id)s::text AS chip_run_id,
                %(export_timestamp)s::text AS chip_export_timestamp,
                %(export_batch_id)s::text AS chip_export_batch_id,
                CASE
                    WHEN db.chip_state IS NULL THEN NULL
                    ELSE db.model_inclusion_flag
                END AS chip_inclusion_flag,
                CASE
                    WHEN db.chip_state IS NULL THEN { _sql_literal(NULL_BUCKET) }
                    WHEN db.model_inclusion_flag IS TRUE THEN 'included'
                    WHEN db.model_inclusion_flag IS FALSE THEN 'excluded'
                    ELSE { _sql_literal(NULL_BUCKET) }
                END AS chip_inclusion_bucket,
                CASE
                    WHEN db.chip_state IS NULL THEN
                        CASE
                            WHEN NULLIF(BTRIM(COALESCE(db.recipient_state_raw, db.place_of_performance_state_raw, db.taggs_state_raw)), '') IS NOT NULL
                                THEN 'invalid_state_mapping'
                            ELSE 'missing_state'
                        END
                    WHEN db.model_inclusion_flag IS TRUE THEN 'included_valid_state_model_row'
                    WHEN COALESCE(db.chip_raw_amount, 0) < 0 OR COALESCE(db.model_net_amount, 0) < 0 THEN 'negative_adjustment_excluded'
                    WHEN POSITION('duplicate' IN LOWER(COALESCE(db.model_inclusion_reason, '') || ' ' || COALESCE(db.model_exclusion_reason, '') || ' ' || COALESCE(db.decision_context, ''))) > 0
                        THEN 'duplicate_transaction'
                    WHEN POSITION('non_cdc' IN LOWER(COALESCE(db.model_inclusion_reason, '') || ' ' || COALESCE(db.model_exclusion_reason, '') || ' ' || COALESCE(db.decision_context, ''))) > 0
                        OR POSITION('international' IN LOWER(COALESCE(db.model_inclusion_reason, '') || ' ' || COALESCE(db.model_exclusion_reason, '') || ' ' || COALESCE(db.decision_context, ''))) > 0
                        OR POSITION('non_domestic' IN LOWER(COALESCE(db.model_inclusion_reason, '') || ' ' || COALESCE(db.model_exclusion_reason, '') || ' ' || COALESCE(db.decision_context, ''))) > 0
                        THEN 'non_cdc_or_out_of_scope'
                    WHEN db.source_system = 'assistance' AND db.chip_join_status IN ('unmatched', 'not_attempted') AND db.model_inclusion_flag IS NULL
                        THEN 'failed_join'
                    WHEN db.fiscal_year IS NULL THEN 'outside_fiscal_scope'
                    WHEN db.model_inclusion_flag IS FALSE THEN 'no_relevant_program_mapping'
                    ELSE 'manual_review_required'
                END AS chip_inclusion_reason,
                CONCAT_WS(
                    ' | ',
                    NULLIF(BTRIM(db.model_inclusion_reason), ''),
                    NULLIF(BTRIM(db.model_exclusion_reason), ''),
                    NULLIF(BTRIM(db.decision_context), ''),
                    CASE WHEN db.state_assignment_method IS NOT NULL THEN 'state_assignment=' || db.state_assignment_method ELSE NULL END,
                    CASE WHEN db.chip_join_status IS NOT NULL THEN 'join_status=' || db.chip_join_status ELSE NULL END
                ) AS chip_inclusion_reason_detail,
                CASE
                    WHEN db.chip_state IS NULL THEN 'manual_review_required'
                    WHEN db.manual_review_recommended IS TRUE OR db.model_inclusion_flag IS NULL THEN 'manual_review_required'
                    WHEN db.model_inclusion_flag IS TRUE THEN 'auto_included'
                    ELSE 'auto_excluded'
                END AS chip_review_status,
                db.chip_state,
                db.chip_state_fips,
                db.state_assignment_method,
                db.state_assignment_confidence,
                'USAspending'::text AS chip_data_source_primary,
                CASE
                    WHEN db.chip_join_status IN ('matched', 'matched_ambiguous') THEN 'TAGGS'
                    ELSE NULL
                END AS chip_data_source_secondary,
                CASE
                    WHEN db.source_system = 'contracts' THEN 'not_applicable'
                    WHEN db.prov_taggs_record_id IS NOT NULL THEN db.matched_join_method
                    ELSE NULL
                END AS chip_join_method,
                db.chip_join_status,
                CASE
                    WHEN db.prov_taggs_record_id IS NOT NULL THEN db.matched_join_confidence
                    ELSE NULL
                END AS chip_join_confidence,
                norm.normalization_method AS chip_normalization_method,
                db.chip_raw_amount,
                CASE
                    WHEN db.chip_state IS NULL THEN NULL
                    WHEN db.model_inclusion_flag IS TRUE THEN db.model_net_amount
                    WHEN db.model_inclusion_flag IS FALSE THEN 0::numeric(18, 2)
                    ELSE NULL
                END AS chip_net_amount_for_model,
                CONCAT_WS(
                    '; ',
                    CASE
                        WHEN db.profile_scope_methodology_version IS NOT NULL
                            THEN 'profile_scope_methodology=' || db.profile_scope_methodology_version
                        ELSE NULL
                    END,
                    CASE
                        WHEN db.funding_scope_method IS NOT NULL
                            THEN 'funding_scope_method=' || db.funding_scope_method
                        ELSE NULL
                    END,
                    'state_assignment=' || COALESCE(db.state_assignment_method, 'unknown'),
                    'join_status=' || COALESCE(db.chip_join_status, 'unknown'),
                    CASE
                        WHEN norm.normalization_method IS NOT NULL
                            THEN 'normalization_method=' || norm.normalization_method
                        ELSE NULL
                    END
                ) AS chip_provenance_notes,
                db.prov_usaspending_source_file,
                db.prov_usaspending_extract_date,
                db.prov_usaspending_table_name,
                db.prov_usaspending_record_id,
                db.prov_taggs_source_file,
                db.prov_taggs_extract_date,
                db.prov_taggs_table_name,
                db.prov_taggs_record_id::text AS prov_taggs_record_id,
                %(run_id)s::text AS prov_merge_run_id,
                { _sql_literal(TRANSFORMATION_STAGE) }::text AS prov_transformation_stage,
                { _sql_literal(EXPORT_PROCESS_NAME) }::text AS prov_last_modified_by_process,
                db.fiscal_year,
                db.primary_program_title,
                db.contract_category_guess,
                COALESCE(
                    NULLIF(BTRIM(db.taggs_program_candidate), ''),
                    NULLIF(BTRIM(db.primary_program_title), ''),
                    NULLIF(BTRIM(db.contract_category_guess), ''),
                    NULLIF(BTRIM(db.effective_funding_scope), ''),
                    'unknown'
                ) AS dominant_program_candidate,
                norm.normalized_amount::numeric(18, 2) AS chip_normalization_target_total,
                db.usaspending_prime_transaction_raw,
                db.usaspending_prime_award_raw,
                db.usaspending_contract_raw,
                db.taggs_raw_award_raw
            FROM decision_base AS db
            LEFT JOIN {NORMALIZED_TABLE} AS norm
                ON norm.source_system = 'usaspending'
               AND norm.fiscal_year = db.fiscal_year
               AND norm.state_code = db.chip_state
        ),
        allocation_base AS (
            SELECT
                fb.*,
                SUM(
                    CASE
                        WHEN fb.chip_inclusion_flag IS TRUE THEN COALESCE(fb.chip_net_amount_for_model, 0)
                        ELSE 0
                    END
                ) OVER (PARTITION BY fb.fiscal_year, fb.chip_state) AS state_year_weight_total,
                CASE
                    WHEN fb.chip_inclusion_flag IS TRUE
                     AND fb.chip_normalization_target_total IS NOT NULL
                     AND SUM(
                        CASE
                            WHEN fb.chip_inclusion_flag IS TRUE THEN COALESCE(fb.chip_net_amount_for_model, 0)
                            ELSE 0
                        END
                     ) OVER (PARTITION BY fb.fiscal_year, fb.chip_state) <> 0
                    THEN (
                        fb.chip_normalization_target_total
                        * COALESCE(fb.chip_net_amount_for_model, 0)
                        / SUM(
                            CASE
                                WHEN fb.chip_inclusion_flag IS TRUE THEN COALESCE(fb.chip_net_amount_for_model, 0)
                                ELSE 0
                            END
                        ) OVER (PARTITION BY fb.fiscal_year, fb.chip_state)
                    )
                    ELSE NULL
                END AS exact_normalized_amount
            FROM final_base AS fb
        ),
        allocation_floor AS (
            SELECT
                ab.*,
                CASE
                    WHEN ab.exact_normalized_amount IS NOT NULL
                        THEN TRUNC(ab.exact_normalized_amount * 100) / 100
                    ELSE NULL
                END AS floored_normalized_amount,
                SUM(
                    CASE
                        WHEN ab.exact_normalized_amount IS NOT NULL
                            THEN TRUNC(ab.exact_normalized_amount * 100) / 100
                        ELSE 0
                    END
                ) OVER (PARTITION BY ab.fiscal_year, ab.chip_state) AS floored_group_sum,
                ROW_NUMBER() OVER (
                    PARTITION BY ab.fiscal_year, ab.chip_state
                    ORDER BY
                        COALESCE(
                            ab.exact_normalized_amount - (TRUNC(ab.exact_normalized_amount * 100) / 100),
                            -1
                        ) DESC,
                        ab.chip_row_id ASC
                ) AS normalized_remainder_rank
            FROM allocation_base AS ab
        )
        SELECT
            af.chip_row_id,
            af.chip_model_version,
            af.chip_run_id,
            af.chip_export_timestamp,
            af.chip_export_batch_id,
            af.chip_inclusion_flag,
            af.chip_inclusion_bucket,
            af.chip_inclusion_reason,
            af.chip_inclusion_reason_detail,
            af.chip_review_status,
            af.chip_state,
            af.chip_state_fips,
            af.state_assignment_method,
            af.state_assignment_confidence,
            af.chip_data_source_primary,
            af.chip_data_source_secondary,
            af.chip_join_method,
            af.chip_join_status,
            af.chip_join_confidence,
            af.chip_normalization_method,
            af.chip_raw_amount,
            af.chip_net_amount_for_model,
            CASE
                WHEN af.chip_inclusion_flag IS TRUE AND af.chip_normalization_target_total IS NULL THEN NULL
                WHEN af.chip_inclusion_flag IS TRUE AND COALESCE(af.state_year_weight_total, 0) = 0 THEN 0::numeric(18, 2)
                WHEN af.chip_inclusion_flag IS TRUE THEN
                    (
                        COALESCE(af.floored_normalized_amount, 0)
                        + CASE
                            WHEN af.normalized_remainder_rank <= COALESCE(
                                ((af.chip_normalization_target_total - af.floored_group_sum) * 100)::integer,
                                0
                            )
                            THEN 0.01
                            ELSE 0
                        END
                    )::numeric(18, 2)
                WHEN af.chip_inclusion_flag IS FALSE THEN 0::numeric(18, 2)
                ELSE NULL
            END AS chip_normalized_amount,
            af.chip_provenance_notes,
            af.prov_usaspending_source_file,
            af.prov_usaspending_extract_date,
            af.prov_usaspending_table_name,
            af.prov_usaspending_record_id,
            af.prov_taggs_source_file,
            af.prov_taggs_extract_date,
            af.prov_taggs_table_name,
            af.prov_taggs_record_id,
            af.prov_merge_run_id,
            af.prov_transformation_stage,
            af.prov_last_modified_by_process,
            af.fiscal_year,
            af.dominant_program_candidate,
            af.chip_normalization_target_total,
            af.state_year_weight_total,
            af.usaspending_prime_transaction_raw,
            af.usaspending_prime_award_raw,
            af.usaspending_contract_raw,
            af.taggs_raw_award_raw
        FROM allocation_floor AS af
    """


def _build_tx_base_table_sql() -> str:
    assistance_recipient_state_raw = """
        COALESCE(
            NULLIF(BTRIM(pt.recipient_state_code), ''),
            NULLIF(BTRIM(pa.recipient_state_code), ''),
            NULLIF(BTRIM(pt.recipient_state_name), ''),
            NULLIF(BTRIM(pa.recipient_state_name), '')
        )
    """
    contract_recipient_state_raw = """
        COALESCE(
            NULLIF(BTRIM(uc.normalized_recipient_state), ''),
            NULLIF(BTRIM(uc.recipient_state_code), ''),
            NULLIF(BTRIM(uc.recipient_state_name), ''),
            NULLIF(BTRIM(uc.raw_row_json ->> 'recipient_state_code'), ''),
            NULLIF(BTRIM(uc.raw_row_json ->> 'recipient_state_name'), '')
        )
    """
    assistance_pop_state_raw = """
        COALESCE(
            NULLIF(BTRIM(pt.raw ->> 'primary_place_of_performance_state_code'), ''),
            NULLIF(BTRIM(pa.raw ->> 'primary_place_of_performance_state_code'), ''),
            NULLIF(BTRIM(pt.primary_place_of_performance_state_name), ''),
            NULLIF(BTRIM(pa.primary_place_of_performance_state_name), ''),
            NULLIF(BTRIM(pt.raw ->> 'primary_place_of_performance_state_name'), ''),
            NULLIF(BTRIM(pa.raw ->> 'primary_place_of_performance_state_name'), '')
        )
    """
    contract_pop_state_raw = """
        COALESCE(
            NULLIF(BTRIM(uc.raw_row_json ->> 'place_of_performance_state_code'), ''),
            NULLIF(BTRIM(uc.raw_row_json ->> 'primary_place_of_performance_state_code'), ''),
            NULLIF(BTRIM(uc.raw_row_json ->> 'place_of_performance_state_name'), ''),
            NULLIF(BTRIM(uc.raw_row_json ->> 'primary_place_of_performance_state_name'), '')
        )
    """
    usaspending_aln = _normalized_aln_sql(
        "COALESCE(NULLIF(BTRIM(pt.cfda_number), ''), NULLIF(BTRIM(pa.cfda_program_num), ''))"
    )

    return f"""
        CREATE TEMP TABLE {TEMP_TX_BASE_TABLE} ON COMMIT DROP AS
        SELECT
            tx.source_system,
            tx.source_transaction_id,
            tx.fiscal_year,
            tx.include_in_profile_scope AS model_inclusion_flag,
            tx.inclusion_reason AS model_inclusion_reason,
            tx.raw_amount::numeric(18, 2) AS chip_raw_amount,
            tx.normalized_profile_scope_amount::numeric(18, 2) AS model_net_amount,
            tx.methodology_version AS profile_scope_methodology_version,
            tx.effective_funding_stream,
            tx.funding_scope_method,
            tx.effective_funding_scope,
            COALESCE(ae.manual_review_recommended, ce.manual_review_recommended, tx.manual_review_recommended) AS manual_review_recommended,
            COALESCE(ae.decision_context, ce.decision_context) AS decision_context,
            COALESCE(ae.exclusion_reason, ce.exclusion_reason) AS model_exclusion_reason,
            COALESCE(ae.recipient_country_name, ce.recipient_country_name) AS recipient_country_name,
            COALESCE(ae.awarding_agency_name, ce.awarding_agency_name) AS awarding_agency_name,
            COALESCE(ae.funding_agency_name, ce.funding_agency_name) AS funding_agency_name,
            COALESCE(ae.assistance_listing_title, ce.award_description) AS primary_program_title,
            ce.contract_category_guess,
            CASE
                WHEN tx.source_system = 'assistance' THEN {assistance_recipient_state_raw}
                ELSE {contract_recipient_state_raw}
            END AS recipient_state_raw,
            CASE
                WHEN tx.source_system = 'assistance' THEN {assistance_pop_state_raw}
                ELSE {contract_pop_state_raw}
            END AS place_of_performance_state_raw,
            UPPER(
                BTRIM(
                    COALESCE(
                        CASE
                            WHEN tx.source_system = 'assistance' THEN {assistance_recipient_state_raw}
                            ELSE {contract_recipient_state_raw}
                        END,
                        CASE
                            WHEN tx.source_system = 'assistance' THEN {assistance_pop_state_raw}
                            ELSE {contract_pop_state_raw}
                        END,
                        ''
                    )
                )
            ) AS usaspending_state_key,
            NULLIF(BTRIM(COALESCE(pt.award_id_fain, pa.fain)), '') AS award_number_key,
            {usaspending_aln} AS normalized_usaspending_aln,
            pt.raw AS usaspending_prime_transaction_raw,
            pa.raw AS usaspending_prime_award_raw,
            uc.raw_row_json AS usaspending_contract_raw,
            COALESCE(pt.source_file_name, pa.source_file_name, uc.source_filename) AS prov_usaspending_source_file,
            CASE
                WHEN tx.source_system = 'assistance'
                    THEN COALESCE(pt.source_imported_at::date::text, pa.source_imported_at::date::text)
                ELSE uc.loaded_at::date::text
            END AS prov_usaspending_extract_date,
            CASE
                WHEN tx.source_system = 'assistance'
                    THEN { _sql_literal(PRIME_TX_TABLE) }
                ELSE { _sql_literal(CONTRACT_TABLE) }
            END AS prov_usaspending_table_name,
            CASE
                WHEN tx.source_system = 'assistance'
                    THEN COALESCE(NULLIF(BTRIM(pt.assistance_transaction_unique_key), ''), pt.id::text)
                ELSE COALESCE(NULLIF(BTRIM(uc.contract_transaction_unique_key), ''), uc.id::text)
            END AS prov_usaspending_record_id
        FROM {PROFILE_SCOPE_TX_TABLE} AS tx
        LEFT JOIN {ASSISTANCE_PROFILE_TABLE} AS ae
            ON tx.source_system = 'assistance'
           AND ae.source_transaction_id = tx.source_transaction_id
        LEFT JOIN {CONTRACT_PROFILE_TABLE} AS ce
            ON tx.source_system = 'contracts'
           AND ce.source_transaction_id = tx.source_transaction_id
        LEFT JOIN {PRIME_TX_TABLE} AS pt
            ON tx.source_system = 'assistance'
           AND tx.source_transaction_id = COALESCE(NULLIF(BTRIM(pt.assistance_transaction_unique_key), ''), pt.id::text)
        LEFT JOIN {PRIME_AWARD_TABLE} AS pa
            ON tx.source_system = 'assistance'
           AND pa.unique_key = pt.assistance_award_unique_key
        LEFT JOIN {CONTRACT_TABLE} AS uc
            ON tx.source_system = 'contracts'
           AND tx.source_transaction_id = COALESCE(NULLIF(BTRIM(uc.contract_transaction_unique_key), ''), uc.id::text)
    """


def _build_assistance_table_sql() -> str:
    return f"""
        CREATE TEMP TABLE {TEMP_ASSISTANCE_TABLE} ON COMMIT DROP AS
        SELECT
            source_transaction_id,
            fiscal_year,
            chip_raw_amount,
            usaspending_state_key,
            award_number_key,
            normalized_usaspending_aln
        FROM {TEMP_TX_BASE_TABLE}
        WHERE source_system = 'assistance'
    """


def _build_taggs_lookup_table_sql() -> str:
    taggs_aln = _normalized_aln_sql("COALESCE(NULLIF(BTRIM(tr.transaction_aln), ''), NULLIF(BTRIM(tr.aln), ''))")
    return f"""
        CREATE TEMP TABLE {TEMP_TAGGS_LOOKUP_TABLE} ON COMMIT DROP AS
        SELECT
            tr.id AS taggs_record_id,
            NULLIF(BTRIM(tr.award_number), '') AS award_number_key,
            {taggs_aln} AS normalized_taggs_aln,
            tr.funding_fiscal_year,
            UPPER(BTRIM(COALESCE(tr.legal_entity_state_normalized, tr.legal_entity_state, ''))) AS taggs_state_key,
            tr.sum_of_actions::numeric(18, 2) AS sum_of_actions
        FROM {TAGGS_RAW_TABLE} AS tr
        WHERE tr.funding_fiscal_year IS NOT NULL
          AND (
              NULLIF(BTRIM(tr.award_number), '') IS NOT NULL
              OR {taggs_aln} <> '00000'
          )
    """


def _taggs_lateral_match_sql(*, join_method: str, join_confidence: str, condition_sql: str) -> str:
    return f"""
        JOIN LATERAL (
            SELECT
                MIN(taggs_record_id) FILTER (WHERE ord = 1) AS prov_taggs_record_id,
                CASE WHEN COUNT(*) > 1 THEN 2 ELSE 1 END AS matched_join_candidate_count,
                { _sql_literal(join_method) }::text AS matched_join_method,
                { _sql_literal(join_confidence) }::text AS matched_join_confidence
            FROM (
                SELECT
                    t.taggs_record_id,
                    ROW_NUMBER() OVER (
                        ORDER BY ABS(COALESCE(t.sum_of_actions, 0) - COALESCE(a.chip_raw_amount, 0)), t.taggs_record_id
                    ) AS ord
                FROM {TEMP_TAGGS_LOOKUP_TABLE} AS t
                WHERE {condition_sql}
                ORDER BY ABS(COALESCE(t.sum_of_actions, 0) - COALESCE(a.chip_raw_amount, 0)), t.taggs_record_id
                LIMIT 2
            ) AS ranked
        ) AS picked
            ON picked.prov_taggs_record_id IS NOT NULL
    """


def _build_taggs_match_table_sql() -> str:
    match1 = _taggs_lateral_match_sql(
        join_method="award_number_state_year",
        join_confidence="high",
        condition_sql=(
            "a.award_number_key IS NOT NULL "
            "AND t.award_number_key = a.award_number_key "
            "AND t.funding_fiscal_year = a.fiscal_year "
            "AND a.usaspending_state_key <> '' "
            "AND t.taggs_state_key = a.usaspending_state_key"
        ),
    )
    match2 = _taggs_lateral_match_sql(
        join_method="award_number_fiscal_year",
        join_confidence="medium",
        condition_sql=(
            "a.award_number_key IS NOT NULL "
            "AND t.award_number_key = a.award_number_key "
            "AND t.funding_fiscal_year = a.fiscal_year"
        ),
    )
    match3 = _taggs_lateral_match_sql(
        join_method="aln_state_year",
        join_confidence="medium",
        condition_sql=(
            "a.normalized_usaspending_aln <> '00000' "
            "AND t.normalized_taggs_aln = a.normalized_usaspending_aln "
            "AND t.funding_fiscal_year = a.fiscal_year "
            "AND a.usaspending_state_key <> '' "
            "AND t.taggs_state_key = a.usaspending_state_key"
        ),
    )
    match4 = _taggs_lateral_match_sql(
        join_method="aln_fiscal_year",
        join_confidence="low",
        condition_sql=(
            "a.normalized_usaspending_aln <> '00000' "
            "AND t.normalized_taggs_aln = a.normalized_usaspending_aln "
            "AND t.funding_fiscal_year = a.fiscal_year"
        ),
    )
    return f"""
        CREATE TEMP TABLE {TEMP_TAGGS_MATCH_TABLE} ON COMMIT DROP AS
        WITH match1 AS (
            SELECT
                a.source_transaction_id,
                picked.prov_taggs_record_id,
                picked.matched_join_candidate_count,
                picked.matched_join_method,
                picked.matched_join_confidence
            FROM {TEMP_ASSISTANCE_TABLE} AS a
            {match1}
        ),
        remaining1 AS (
            SELECT a.*
            FROM {TEMP_ASSISTANCE_TABLE} AS a
            LEFT JOIN match1 AS m USING (source_transaction_id)
            WHERE m.source_transaction_id IS NULL
        ),
        match2 AS (
            SELECT
                a.source_transaction_id,
                picked.prov_taggs_record_id,
                picked.matched_join_candidate_count,
                picked.matched_join_method,
                picked.matched_join_confidence
            FROM remaining1 AS a
            {match2}
        ),
        remaining2 AS (
            SELECT a.*
            FROM remaining1 AS a
            LEFT JOIN match2 AS m USING (source_transaction_id)
            WHERE m.source_transaction_id IS NULL
        ),
        match3 AS (
            SELECT
                a.source_transaction_id,
                picked.prov_taggs_record_id,
                picked.matched_join_candidate_count,
                picked.matched_join_method,
                picked.matched_join_confidence
            FROM remaining2 AS a
            {match3}
        ),
        remaining3 AS (
            SELECT a.*
            FROM remaining2 AS a
            LEFT JOIN match3 AS m USING (source_transaction_id)
            WHERE m.source_transaction_id IS NULL
        ),
        match4 AS (
            SELECT
                a.source_transaction_id,
                picked.prov_taggs_record_id,
                picked.matched_join_candidate_count,
                picked.matched_join_method,
                picked.matched_join_confidence
            FROM remaining3 AS a
            {match4}
        )
        SELECT * FROM match1
        UNION ALL
        SELECT * FROM match2
        UNION ALL
        SELECT * FROM match3
        UNION ALL
        SELECT * FROM match4
    """


def _build_final_export_table_sql() -> str:
    return f"""
        CREATE TEMP TABLE {TEMP_EXPORT_TABLE} ON COMMIT DROP AS
        WITH state_dim AS (
            SELECT
                state_fips,
                UPPER(BTRIM(state_abbr)) AS state_abbr,
                UPPER(BTRIM(state_name)) AS state_name
            FROM {STATE_DIM_TABLE}
        ),
        decision_base AS (
            SELECT
                tx.*,
                best.prov_taggs_record_id AS matched_taggs_record_id,
                best.matched_join_method,
                best.matched_join_confidence,
                best.matched_join_candidate_count,
                (tx.award_number_key IS NOT NULL OR tx.normalized_usaspending_aln <> '00000') AS join_input_available,
                tr.source_filename AS prov_taggs_source_file,
                tr.loaded_at::date::text AS prov_taggs_extract_date,
                CASE
                    WHEN best.prov_taggs_record_id IS NOT NULL THEN { _sql_literal(TAGGS_RAW_TABLE) }
                    ELSE NULL
                END AS prov_taggs_table_name,
                tr.id::text AS prov_taggs_record_id,
                tr.raw_row_json AS taggs_raw_award_raw,
                NULLIF(BTRIM(COALESCE(tr.legal_entity_state_normalized, tr.legal_entity_state)), '') AS taggs_state_raw,
                COALESCE(
                    summary.effective_program_name,
                    summary.effective_subcategory,
                    summary.assistance_listing_title,
                    tr.award_title,
                    tr.assistance_listing_title
                ) AS taggs_program_candidate,
                recipient_dim.state_abbr AS recipient_state_resolved,
                recipient_dim.state_fips AS recipient_state_fips,
                pop_dim.state_abbr AS pop_state_resolved,
                pop_dim.state_fips AS pop_state_fips,
                taggs_dim.state_abbr AS taggs_state_resolved,
                taggs_dim.state_fips AS taggs_state_fips,
                CASE
                    WHEN tx.source_system <> 'assistance' THEN 'not_applicable'
                    WHEN best.prov_taggs_record_id IS NOT NULL AND COALESCE(best.matched_join_candidate_count, 0) > 1 THEN 'matched_ambiguous'
                    WHEN best.prov_taggs_record_id IS NOT NULL THEN 'matched'
                    WHEN (tx.award_number_key IS NOT NULL OR tx.normalized_usaspending_aln <> '00000') THEN 'unmatched'
                    ELSE 'not_attempted'
                END AS chip_join_status
            FROM {TEMP_TX_BASE_TABLE} AS tx
            LEFT JOIN {TEMP_TAGGS_MATCH_TABLE} AS best
                ON tx.source_system = 'assistance'
               AND best.source_transaction_id = tx.source_transaction_id
            LEFT JOIN {TAGGS_RAW_TABLE} AS tr
                ON tr.id = best.prov_taggs_record_id
            LEFT JOIN LATERAL (
                SELECT
                    summary.effective_program_name,
                    summary.effective_subcategory,
                    summary.assistance_listing_title
                FROM {TAGGS_SUMMARY_TABLE} AS summary
                WHERE summary.award_number = tr.award_number
                  AND summary.funding_fiscal_year = tr.funding_fiscal_year
                  AND COALESCE(summary.can_code, '') = COALESCE(tr.can_code, '')
                  AND UPPER(COALESCE(summary.legal_entity_state_normalized, '')) =
                      UPPER(COALESCE(tr.legal_entity_state_normalized, ''))
                ORDER BY summary.id
                LIMIT 1
            ) AS summary ON TRUE
            LEFT JOIN state_dim AS recipient_dim
                ON { _state_dim_join_condition("tx.recipient_state_raw", "recipient_dim") }
            LEFT JOIN state_dim AS pop_dim
                ON { _state_dim_join_condition("tx.place_of_performance_state_raw", "pop_dim") }
            LEFT JOIN state_dim AS taggs_dim
                ON { _state_dim_join_condition("NULLIF(BTRIM(COALESCE(tr.legal_entity_state_normalized, tr.legal_entity_state)), '')", "taggs_dim") }
        ),
        final_base AS (
            SELECT
                db.source_system || ':' || db.source_transaction_id AS chip_row_id,
                %(chip_model_version)s::text AS chip_model_version,
                %(run_id)s::text AS chip_run_id,
                %(export_timestamp)s::text AS chip_export_timestamp,
                %(export_batch_id)s::text AS chip_export_batch_id,
                CASE
                    WHEN CASE
                        WHEN db.recipient_state_resolved IS NOT NULL THEN db.recipient_state_resolved
                        WHEN db.pop_state_resolved IS NOT NULL THEN db.pop_state_resolved
                        WHEN db.taggs_state_resolved IS NOT NULL THEN db.taggs_state_resolved
                        ELSE NULL
                    END IS NULL THEN NULL
                    ELSE db.model_inclusion_flag
                END AS chip_inclusion_flag,
                CASE
                    WHEN CASE
                        WHEN db.recipient_state_resolved IS NOT NULL THEN db.recipient_state_resolved
                        WHEN db.pop_state_resolved IS NOT NULL THEN db.pop_state_resolved
                        WHEN db.taggs_state_resolved IS NOT NULL THEN db.taggs_state_resolved
                        ELSE NULL
                    END IS NULL THEN { _sql_literal(NULL_BUCKET) }
                    WHEN db.model_inclusion_flag IS TRUE THEN 'included'
                    WHEN db.model_inclusion_flag IS FALSE THEN 'excluded'
                    ELSE { _sql_literal(NULL_BUCKET) }
                END AS chip_inclusion_bucket,
                CASE
                    WHEN CASE
                        WHEN db.recipient_state_resolved IS NOT NULL THEN db.recipient_state_resolved
                        WHEN db.pop_state_resolved IS NOT NULL THEN db.pop_state_resolved
                        WHEN db.taggs_state_resolved IS NOT NULL THEN db.taggs_state_resolved
                        ELSE NULL
                    END IS NULL THEN
                        CASE
                            WHEN NULLIF(BTRIM(COALESCE(db.recipient_state_raw, db.place_of_performance_state_raw, db.taggs_state_raw)), '') IS NOT NULL
                                THEN 'invalid_state_mapping'
                            ELSE 'missing_state'
                        END
                    WHEN db.model_inclusion_flag IS TRUE THEN 'included_valid_state_model_row'
                    WHEN COALESCE(db.chip_raw_amount, 0) < 0 OR COALESCE(db.model_net_amount, 0) < 0 THEN 'negative_adjustment_excluded'
                    WHEN POSITION('duplicate' IN LOWER(COALESCE(db.model_inclusion_reason, '') || ' ' || COALESCE(db.model_exclusion_reason, '') || ' ' || COALESCE(db.decision_context, ''))) > 0
                        THEN 'duplicate_transaction'
                    WHEN POSITION('non_cdc' IN LOWER(COALESCE(db.model_inclusion_reason, '') || ' ' || COALESCE(db.model_exclusion_reason, '') || ' ' || COALESCE(db.decision_context, ''))) > 0
                        OR POSITION('international' IN LOWER(COALESCE(db.model_inclusion_reason, '') || ' ' || COALESCE(db.model_exclusion_reason, '') || ' ' || COALESCE(db.decision_context, ''))) > 0
                        OR POSITION('non_domestic' IN LOWER(COALESCE(db.model_inclusion_reason, '') || ' ' || COALESCE(db.model_exclusion_reason, '') || ' ' || COALESCE(db.decision_context, ''))) > 0
                        THEN 'non_cdc_or_out_of_scope'
                    WHEN db.source_system = 'assistance' AND db.chip_join_status IN ('unmatched', 'not_attempted') AND db.model_inclusion_flag IS NULL
                        THEN 'failed_join'
                    WHEN db.fiscal_year IS NULL THEN 'outside_fiscal_scope'
                    WHEN db.model_inclusion_flag IS FALSE THEN 'no_relevant_program_mapping'
                    ELSE 'manual_review_required'
                END AS chip_inclusion_reason,
                CONCAT_WS(
                    ' | ',
                    NULLIF(BTRIM(db.model_inclusion_reason), ''),
                    NULLIF(BTRIM(db.model_exclusion_reason), ''),
                    NULLIF(BTRIM(db.decision_context), ''),
                    CASE
                        WHEN CASE
                            WHEN db.recipient_state_resolved IS NOT NULL THEN 'usaspending_recipient_state'
                            WHEN db.pop_state_resolved IS NOT NULL THEN 'usaspending_place_of_performance_state'
                            WHEN db.taggs_state_resolved IS NOT NULL THEN 'taggs_state'
                            ELSE 'unknown'
                        END IS NOT NULL
                            THEN 'state_assignment=' || CASE
                                WHEN db.recipient_state_resolved IS NOT NULL THEN 'usaspending_recipient_state'
                                WHEN db.pop_state_resolved IS NOT NULL THEN 'usaspending_place_of_performance_state'
                                WHEN db.taggs_state_resolved IS NOT NULL THEN 'taggs_state'
                                ELSE 'unknown'
                            END
                        ELSE NULL
                    END,
                    CASE WHEN db.chip_join_status IS NOT NULL THEN 'join_status=' || db.chip_join_status ELSE NULL END
                ) AS chip_inclusion_reason_detail,
                CASE
                    WHEN CASE
                        WHEN db.recipient_state_resolved IS NOT NULL THEN db.recipient_state_resolved
                        WHEN db.pop_state_resolved IS NOT NULL THEN db.pop_state_resolved
                        WHEN db.taggs_state_resolved IS NOT NULL THEN db.taggs_state_resolved
                        ELSE NULL
                    END IS NULL THEN 'manual_review_required'
                    WHEN db.manual_review_recommended IS TRUE OR db.model_inclusion_flag IS NULL THEN 'manual_review_required'
                    WHEN db.model_inclusion_flag IS TRUE THEN 'auto_included'
                    ELSE 'auto_excluded'
                END AS chip_review_status,
                CASE
                    WHEN db.recipient_state_resolved IS NOT NULL THEN db.recipient_state_resolved
                    WHEN db.pop_state_resolved IS NOT NULL THEN db.pop_state_resolved
                    WHEN db.taggs_state_resolved IS NOT NULL THEN db.taggs_state_resolved
                    ELSE NULL
                END AS chip_state,
                CASE
                    WHEN db.recipient_state_resolved IS NOT NULL THEN db.recipient_state_fips
                    WHEN db.pop_state_resolved IS NOT NULL THEN db.pop_state_fips
                    WHEN db.taggs_state_resolved IS NOT NULL THEN db.taggs_state_fips
                    ELSE NULL
                END AS chip_state_fips,
                CASE
                    WHEN db.recipient_state_resolved IS NOT NULL THEN 'usaspending_recipient_state'
                    WHEN db.pop_state_resolved IS NOT NULL THEN 'usaspending_place_of_performance_state'
                    WHEN db.taggs_state_resolved IS NOT NULL THEN 'taggs_state'
                    ELSE 'unknown'
                END AS state_assignment_method,
                CASE
                    WHEN db.recipient_state_resolved IS NOT NULL THEN 'high'
                    WHEN db.pop_state_resolved IS NOT NULL THEN 'medium'
                    WHEN db.taggs_state_resolved IS NOT NULL THEN 'low'
                    ELSE NULL
                END AS state_assignment_confidence,
                'USAspending'::text AS chip_data_source_primary,
                CASE
                    WHEN db.chip_join_status IN ('matched', 'matched_ambiguous') THEN 'TAGGS'
                    ELSE NULL
                END AS chip_data_source_secondary,
                CASE
                    WHEN db.source_system = 'contracts' THEN 'not_applicable'
                    WHEN db.matched_taggs_record_id IS NOT NULL THEN db.matched_join_method
                    ELSE NULL
                END AS chip_join_method,
                db.chip_join_status,
                CASE
                    WHEN db.matched_taggs_record_id IS NOT NULL THEN db.matched_join_confidence
                    ELSE NULL
                END AS chip_join_confidence,
                norm.normalization_method AS chip_normalization_method,
                db.chip_raw_amount,
                CASE
                    WHEN CASE
                        WHEN db.recipient_state_resolved IS NOT NULL THEN db.recipient_state_resolved
                        WHEN db.pop_state_resolved IS NOT NULL THEN db.pop_state_resolved
                        WHEN db.taggs_state_resolved IS NOT NULL THEN db.taggs_state_resolved
                        ELSE NULL
                    END IS NULL THEN NULL
                    WHEN db.model_inclusion_flag IS TRUE THEN db.model_net_amount
                    WHEN db.model_inclusion_flag IS FALSE THEN 0::numeric(18, 2)
                    ELSE NULL
                END AS chip_net_amount_for_model,
                CONCAT_WS(
                    '; ',
                    CASE
                        WHEN db.profile_scope_methodology_version IS NOT NULL
                            THEN 'profile_scope_methodology=' || db.profile_scope_methodology_version
                        ELSE NULL
                    END,
                    CASE
                        WHEN db.funding_scope_method IS NOT NULL
                            THEN 'funding_scope_method=' || db.funding_scope_method
                        ELSE NULL
                    END,
                    'state_assignment=' || CASE
                        WHEN db.recipient_state_resolved IS NOT NULL THEN 'usaspending_recipient_state'
                        WHEN db.pop_state_resolved IS NOT NULL THEN 'usaspending_place_of_performance_state'
                        WHEN db.taggs_state_resolved IS NOT NULL THEN 'taggs_state'
                        ELSE 'unknown'
                    END,
                    'join_status=' || COALESCE(db.chip_join_status, 'unknown'),
                    CASE
                        WHEN norm.normalization_method IS NOT NULL
                            THEN 'normalization_method=' || norm.normalization_method
                        ELSE NULL
                    END
                ) AS chip_provenance_notes,
                db.prov_usaspending_source_file,
                db.prov_usaspending_extract_date,
                db.prov_usaspending_table_name,
                db.prov_usaspending_record_id,
                db.prov_taggs_source_file,
                db.prov_taggs_extract_date,
                db.prov_taggs_table_name,
                db.prov_taggs_record_id,
                %(run_id)s::text AS prov_merge_run_id,
                { _sql_literal(TRANSFORMATION_STAGE) }::text AS prov_transformation_stage,
                { _sql_literal(EXPORT_PROCESS_NAME) }::text AS prov_last_modified_by_process,
                db.fiscal_year,
                COALESCE(
                    NULLIF(BTRIM(db.taggs_program_candidate), ''),
                    NULLIF(BTRIM(db.primary_program_title), ''),
                    NULLIF(BTRIM(db.contract_category_guess), ''),
                    NULLIF(BTRIM(db.effective_funding_scope), ''),
                    'unknown'
                ) AS dominant_program_candidate,
                norm.normalized_amount::numeric(18, 2) AS chip_normalization_target_total,
                db.usaspending_prime_transaction_raw,
                db.usaspending_prime_award_raw,
                db.usaspending_contract_raw,
                db.taggs_raw_award_raw
            FROM decision_base AS db
            LEFT JOIN {NORMALIZED_TABLE} AS norm
                ON norm.source_system = 'usaspending'
               AND norm.fiscal_year = db.fiscal_year
               AND norm.state_code = CASE
                    WHEN db.recipient_state_resolved IS NOT NULL THEN db.recipient_state_resolved
                    WHEN db.pop_state_resolved IS NOT NULL THEN db.pop_state_resolved
                    WHEN db.taggs_state_resolved IS NOT NULL THEN db.taggs_state_resolved
                    ELSE NULL
               END
        ),
        allocation_base AS (
            SELECT
                fb.*,
                SUM(
                    CASE
                        WHEN fb.chip_inclusion_flag IS TRUE THEN COALESCE(fb.chip_net_amount_for_model, 0)
                        ELSE 0
                    END
                ) OVER (PARTITION BY fb.fiscal_year, fb.chip_state) AS state_year_weight_total,
                CASE
                    WHEN fb.chip_inclusion_flag IS TRUE
                     AND fb.chip_normalization_target_total IS NOT NULL
                     AND SUM(
                        CASE
                            WHEN fb.chip_inclusion_flag IS TRUE THEN COALESCE(fb.chip_net_amount_for_model, 0)
                            ELSE 0
                        END
                     ) OVER (PARTITION BY fb.fiscal_year, fb.chip_state) <> 0
                    THEN (
                        fb.chip_normalization_target_total
                        * COALESCE(fb.chip_net_amount_for_model, 0)
                        / SUM(
                            CASE
                                WHEN fb.chip_inclusion_flag IS TRUE THEN COALESCE(fb.chip_net_amount_for_model, 0)
                                ELSE 0
                            END
                        ) OVER (PARTITION BY fb.fiscal_year, fb.chip_state)
                    )
                    ELSE NULL
                END AS exact_normalized_amount
            FROM final_base AS fb
        ),
        allocation_floor AS (
            SELECT
                ab.*,
                CASE
                    WHEN ab.exact_normalized_amount IS NOT NULL
                        THEN TRUNC(ab.exact_normalized_amount * 100) / 100
                    ELSE NULL
                END AS floored_normalized_amount,
                SUM(
                    CASE
                        WHEN ab.exact_normalized_amount IS NOT NULL
                            THEN TRUNC(ab.exact_normalized_amount * 100) / 100
                        ELSE 0
                    END
                ) OVER (PARTITION BY ab.fiscal_year, ab.chip_state) AS floored_group_sum,
                ROW_NUMBER() OVER (
                    PARTITION BY ab.fiscal_year, ab.chip_state
                    ORDER BY
                        COALESCE(
                            ab.exact_normalized_amount - (TRUNC(ab.exact_normalized_amount * 100) / 100),
                            -1
                        ) DESC,
                        ab.chip_row_id ASC
                ) AS normalized_remainder_rank
            FROM allocation_base AS ab
        )
        SELECT
            af.chip_row_id,
            af.chip_model_version,
            af.chip_run_id,
            af.chip_export_timestamp,
            af.chip_export_batch_id,
            af.chip_inclusion_flag,
            af.chip_inclusion_bucket,
            af.chip_inclusion_reason,
            af.chip_inclusion_reason_detail,
            af.chip_review_status,
            af.chip_state,
            af.chip_state_fips,
            af.state_assignment_method,
            af.state_assignment_confidence,
            af.chip_data_source_primary,
            af.chip_data_source_secondary,
            af.chip_join_method,
            af.chip_join_status,
            af.chip_join_confidence,
            af.chip_normalization_method,
            af.chip_raw_amount,
            af.chip_net_amount_for_model,
            CASE
                WHEN af.chip_inclusion_flag IS TRUE AND af.chip_normalization_target_total IS NULL THEN NULL
                WHEN af.chip_inclusion_flag IS TRUE AND COALESCE(af.state_year_weight_total, 0) = 0 THEN 0::numeric(18, 2)
                WHEN af.chip_inclusion_flag IS TRUE THEN
                    (
                        COALESCE(af.floored_normalized_amount, 0)
                        + CASE
                            WHEN af.normalized_remainder_rank <= COALESCE(
                                ((af.chip_normalization_target_total - af.floored_group_sum) * 100)::integer,
                                0
                            )
                            THEN 0.01
                            ELSE 0
                        END
                    )::numeric(18, 2)
                WHEN af.chip_inclusion_flag IS FALSE THEN 0::numeric(18, 2)
                ELSE NULL
            END AS chip_normalized_amount,
            af.chip_provenance_notes,
            af.prov_usaspending_source_file,
            af.prov_usaspending_extract_date,
            af.prov_usaspending_table_name,
            af.prov_usaspending_record_id,
            af.prov_taggs_source_file,
            af.prov_taggs_extract_date,
            af.prov_taggs_table_name,
            af.prov_taggs_record_id,
            af.prov_merge_run_id,
            af.prov_transformation_stage,
            af.prov_last_modified_by_process,
            af.fiscal_year,
            af.dominant_program_candidate,
            af.chip_normalization_target_total,
            af.state_year_weight_total,
            af.usaspending_prime_transaction_raw,
            af.usaspending_prime_award_raw,
            af.usaspending_contract_raw,
            af.taggs_raw_award_raw
        FROM allocation_floor AS af
    """


def _build_transaction_select_sql(raw_field_specs: Sequence[RawFieldSpec], *, bucket: str) -> str:
    if bucket not in {"included", "excluded", NULL_BUCKET}:
        raise ValueError(f"Unsupported bucket: {bucket!r}")

    select_expressions = [
        "chip_row_id",
        "chip_model_version",
        "chip_run_id",
        "chip_export_timestamp",
        "chip_export_batch_id",
        "CASE WHEN chip_inclusion_flag IS TRUE THEN 'TRUE' WHEN chip_inclusion_flag IS FALSE THEN 'FALSE' ELSE NULL END",
        "chip_inclusion_bucket",
        "chip_inclusion_reason",
        "chip_inclusion_reason_detail",
        "chip_review_status",
        "chip_state",
        "chip_state_fips",
        "state_assignment_method",
        "state_assignment_confidence",
        "chip_data_source_primary",
        "chip_data_source_secondary",
        "chip_join_method",
        "chip_join_status",
        "chip_join_confidence",
        "chip_normalization_method",
        "chip_raw_amount",
        "chip_net_amount_for_model",
        "chip_normalized_amount",
        "chip_provenance_notes",
        *PROVENANCE_COLUMNS,
        *[_json_extract_expression(spec) for spec in raw_field_specs],
    ]
    select_sql = ",\n            ".join(select_expressions)
    return f"""
        SELECT
            {select_sql}
        FROM {TEMP_EXPORT_TABLE}
        WHERE chip_inclusion_bucket = { _sql_literal(bucket) }
        ORDER BY fiscal_year NULLS LAST, chip_state NULLS LAST, chip_row_id
    """


def _build_profile_select_sql() -> str:
    return f"""
        WITH included AS (
            SELECT *
            FROM {TEMP_EXPORT_TABLE}
            WHERE chip_inclusion_bucket = 'included'
        ),
        dominant_program_rank AS (
            SELECT *
            FROM (
                SELECT
                    chip_state,
                    chip_state_fips,
                    fiscal_year,
                    dominant_program_candidate,
                    SUM(COALESCE(chip_net_amount_for_model, 0)) AS dominant_program_amount,
                    ROW_NUMBER() OVER (
                        PARTITION BY chip_state, chip_state_fips, fiscal_year
                        ORDER BY
                            SUM(COALESCE(chip_net_amount_for_model, 0)) DESC,
                            dominant_program_candidate ASC
                    ) AS rn
                FROM included
                GROUP BY chip_state, chip_state_fips, fiscal_year, dominant_program_candidate
            ) AS ranked
            WHERE rn = 1
        )
        SELECT
            i.chip_state,
            i.chip_state_fips,
            i.fiscal_year,
            COUNT(*)::bigint AS transaction_count,
            COALESCE(SUM(i.chip_raw_amount), 0)::numeric(18, 2) AS total_raw_funding,
            COALESCE(SUM(i.chip_net_amount_for_model), 0)::numeric(18, 2) AS total_net_funding,
            COALESCE(SUM(i.chip_normalized_amount), 0)::numeric(18, 2) AS total_normalized_funding,
            COALESCE(MAX(dpr.dominant_program_candidate), 'unknown') AS dominant_program,
            ROUND(AVG(
                GREATEST(
                    0,
                    LEAST(
                        100,
                        CASE i.state_assignment_confidence
                            WHEN 'high' THEN 100
                            WHEN 'medium' THEN 85
                            WHEN 'low' THEN 70
                            ELSE 50
                        END
                        - CASE i.chip_join_status
                            WHEN 'matched_ambiguous' THEN 5
                            WHEN 'unmatched' THEN 10
                            WHEN 'not_attempted' THEN 15
                            ELSE 0
                        END
                    )
                )
            )::numeric, 2) AS data_quality_score,
            MAX(i.chip_model_version) AS model_version,
            MAX(i.chip_run_id) AS run_id
        FROM included AS i
        LEFT JOIN dominant_program_rank AS dpr
            ON dpr.chip_state = i.chip_state
           AND dpr.chip_state_fips = i.chip_state_fips
           AND dpr.fiscal_year = i.fiscal_year
        GROUP BY i.chip_state, i.chip_state_fips, i.fiscal_year
        ORDER BY i.fiscal_year, i.chip_state
    """


def _fetch_validation_metrics(
    connection: psycopg.Connection[Any],
) -> dict[str, Any]:
    query = f"""
        SELECT
            COUNT(*)::bigint AS total_candidate_rows,
            COUNT(*) FILTER (WHERE chip_inclusion_bucket = 'included')::bigint AS included_rows,
            COUNT(*) FILTER (WHERE chip_inclusion_bucket = 'excluded')::bigint AS excluded_rows,
            COUNT(*) FILTER (WHERE chip_inclusion_bucket = { _sql_literal(NULL_BUCKET) })::bigint AS unresolved_rows,
            COALESCE(SUM(chip_raw_amount) FILTER (WHERE chip_inclusion_bucket = 'included'), 0)::numeric(18, 2)
                AS included_raw_amount_sum,
            COALESCE(SUM(chip_net_amount_for_model) FILTER (WHERE chip_inclusion_bucket = 'included'), 0)::numeric(18, 2)
                AS included_net_amount_sum,
            COALESCE(SUM(chip_normalized_amount) FILTER (WHERE chip_inclusion_bucket = 'included'), 0)::numeric(18, 2)
                AS included_normalized_amount_sum,
            COALESCE(SUM(chip_net_amount_for_model) FILTER (WHERE chip_inclusion_bucket = 'excluded'), 0)::numeric(18, 2)
                AS excluded_net_amount_sum,
            COALESCE(SUM(chip_net_amount_for_model) FILTER (WHERE chip_inclusion_bucket = { _sql_literal(NULL_BUCKET) }), 0)::numeric(18, 2)
                AS unresolved_net_amount_sum,
            COUNT(*) FILTER (WHERE chip_data_source_secondary = 'TAGGS')::bigint AS matched_both_sources_count,
            COUNT(*) FILTER (WHERE chip_data_source_secondary IS NULL)::bigint AS usaspending_only_count,
            0::bigint AS taggs_only_count,
            COUNT(*) FILTER (WHERE chip_state IS NULL)::bigint AS unknown_state_count,
            (COUNT(*) - COUNT(DISTINCT chip_row_id))::bigint AS duplicate_row_id_count,
            FALSE AS schema_mismatch_flag,
            COUNT(*) FILTER (
                WHERE chip_inclusion_bucket = 'included'
                  AND chip_normalization_target_total IS NULL
            )::bigint AS missing_normalization_target_count,
            COUNT(*) FILTER (
                WHERE chip_inclusion_bucket = 'included'
                  AND COALESCE(state_year_weight_total, 0) = 0
                  AND COALESCE(chip_normalization_target_total, 0) <> 0
            )::bigint AS zero_weight_target_count
        FROM {TEMP_EXPORT_TABLE}
    """
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query)
        row = cursor.fetchone() or {}
    return dict(row)


def _copy_query_to_csv(
    connection: psycopg.Connection[Any],
    *,
    path: Path,
    header: Sequence[str],
    select_sql: str,
    logger: logging.Logger,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as header_handle:
        writer = csv.writer(header_handle)
        writer.writerow(list(header))

    with path.open("ab") as data_handle:
        with connection.cursor() as cursor:
            logger.info("Streaming COPY to %s", path)
            copy_sql = f"COPY ({select_sql}) TO STDOUT WITH CSV"
            with cursor.copy(copy_sql) as copy:
                while chunk := copy.read():
                    data_handle.write(chunk)


def _base_meta(
    *,
    display_name: str,
    source_system: str,
    source_subsystem: str,
    source_column_name: str,
    column_group: str,
    data_type: str,
    format_value: str,
    allowed_values: str,
    null_allowed: str,
    definition: str,
    provenance_description: str,
    transformation_rule: str,
    example_value: str,
    appears_in_files: str,
) -> dict[str, str]:
    return {
        "display_name": display_name,
        "source_system": source_system,
        "source_subsystem": source_subsystem,
        "source_column_name": source_column_name,
        "column_group": column_group,
        "data_type": data_type,
        "format": format_value,
        "allowed_values": allowed_values,
        "null_allowed": null_allowed,
        "definition": definition,
        "provenance_description": provenance_description,
        "transformation_rule": transformation_rule,
        "example_value": example_value,
        "appears_in_files": appears_in_files,
    }


def _display_name(value: str) -> str:
    return " ".join(piece.capitalize() for piece in value.replace("_", " ").split())


def _transaction_column_meta() -> dict[str, dict[str, str]]:
    return {
        "chip_row_id": _base_meta(
            display_name="CHIP Row ID",
            source_system="CHIP",
            source_subsystem="audit_export",
            source_column_name="chip_row_id",
            column_group="chip_audit",
            data_type="string",
            format_value="source_system:source_transaction_id",
            allowed_values="",
            null_allowed="no",
            definition="Stable row identifier for the CHIP state audit export.",
            provenance_description="Derived from the underlying transaction source and source transaction identifier.",
            transformation_rule="Concatenate source_system and source_transaction_id with a colon.",
            example_value="assistance:12345",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_model_version": _base_meta(
            display_name="CHIP Model Version",
            source_system="CHIP",
            source_subsystem="audit_export",
            source_column_name="chip_model_version",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="no",
            definition="Combined funding-model and state-audit export logic version.",
            provenance_description="Built from the CHIP funding model version, profile-scope methodology version, and export logic version.",
            transformation_rule="Populate once per run from module constants.",
            example_value=CHIP_MODEL_VERSION,
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_run_id": _base_meta(
            display_name="CHIP Run ID",
            source_system="CHIP",
            source_subsystem="audit_export",
            source_column_name="chip_run_id",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="no",
            definition="Unique identifier for the export execution.",
            provenance_description="Generated once at runtime and reused across all output artifacts.",
            transformation_rule="Timestamp plus deterministic hash seed.",
            example_value="chip_state_audit_20260321T120000Z_abcd1234ef56",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_export_timestamp": _base_meta(
            display_name="CHIP Export Timestamp",
            source_system="CHIP",
            source_subsystem="audit_export",
            source_column_name="chip_export_timestamp",
            column_group="chip_audit",
            data_type="timestamp",
            format_value="ISO-8601 UTC",
            allowed_values="",
            null_allowed="no",
            definition="UTC timestamp captured at the start of the export run.",
            provenance_description="Runtime metadata repeated on every exported transaction row.",
            transformation_rule="Populate once per export run.",
            example_value="2026-03-21T12:00:00+00:00",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_export_batch_id": _base_meta(
            display_name="CHIP Export Batch ID",
            source_system="CHIP",
            source_subsystem="audit_export",
            source_column_name="chip_export_batch_id",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="no",
            definition="Deterministic dated batch label for the export folder.",
            provenance_description="Matches the dated export directory name.",
            transformation_rule="Use chip_state_audit_export_YYYYMMDD.",
            example_value="chip_state_audit_export_20260321",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_inclusion_flag": _base_meta(
            display_name="CHIP Inclusion Flag",
            source_system="CHIP",
            source_subsystem="profile_scope",
            source_column_name="include_in_profile_scope",
            column_group="chip_audit",
            data_type="boolean",
            format_value="TRUE/FALSE/blank",
            allowed_values="TRUE,FALSE,NULL",
            null_allowed="yes",
            definition="Final inclusion decision used for the state-model audit export.",
            provenance_description="Starts from recon.profile_scope_transactions.include_in_profile_scope and is forced to NULL for rows without a resolved state.",
            transformation_rule="Keep model decision when state assignment succeeds; otherwise set to NULL.",
            example_value="TRUE",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_inclusion_bucket": _base_meta(
            display_name="CHIP Inclusion Bucket",
            source_system="CHIP",
            source_subsystem="audit_export",
            source_column_name="chip_inclusion_bucket",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="included,excluded,unresolved",
            null_allowed="no",
            definition="Human-readable partition derived from chip_inclusion_flag.",
            provenance_description="Used to route rows into the three transaction files.",
            transformation_rule="TRUE -> included, FALSE -> excluded, NULL -> unresolved.",
            example_value="included",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_inclusion_reason": _base_meta(
            display_name="CHIP Inclusion Reason",
            source_system="CHIP",
            source_subsystem="audit_export",
            source_column_name="chip_inclusion_reason",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values=(
                "included_valid_state_model_row,non_cdc_or_out_of_scope,duplicate_transaction,"
                "negative_adjustment_excluded,missing_state,invalid_state_mapping,"
                "no_relevant_program_mapping,outside_fiscal_scope,failed_join,manual_review_required"
            ),
            null_allowed="no",
            definition="Controlled reason describing why the transaction is included, excluded, or unresolved.",
            provenance_description="Derived from model flags, state assignment success, join status, and profile-scope context fields.",
            transformation_rule="Apply deterministic export-time reason mapping.",
            example_value="included_valid_state_model_row",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_inclusion_reason_detail": _base_meta(
            display_name="CHIP Inclusion Reason Detail",
            source_system="CHIP",
            source_subsystem="profile_scope",
            source_column_name="inclusion_reason/exclusion_reason/decision_context",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="yes",
            definition="More detailed narrative about the inclusion decision.",
            provenance_description="Built from the profile-scope reason fields, decision context, state assignment method, and join status.",
            transformation_rule="Concatenate non-empty reason fragments with a pipe separator.",
            example_value="core_public_health | state_assignment=usaspending_recipient_state | join_status=matched",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_review_status": _base_meta(
            display_name="CHIP Review Status",
            source_system="CHIP",
            source_subsystem="audit_export",
            source_column_name="chip_review_status",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="auto_included,auto_excluded,manual_review_required",
            null_allowed="no",
            definition="Review workflow status for the row.",
            provenance_description="Derived from the final inclusion flag, manual review markers, and state resolution success.",
            transformation_rule="Rows with unresolved state or manual review flags are marked manual_review_required.",
            example_value="auto_included",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_state": _base_meta(
            display_name="CHIP State",
            source_system="CHIP",
            source_subsystem="state_assignment",
            source_column_name="chip_state",
            column_group="chip_audit",
            data_type="string",
            format_value="2-letter state code",
            allowed_values="",
            null_allowed="yes",
            definition="Resolved state used for state-level aggregation in the export.",
            provenance_description="Assigned from USAspending recipient state, then USAspending place of performance state, then TAGGS state.",
            transformation_rule="Apply explicit state assignment precedence rules.",
            example_value="AL",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_state_fips": _base_meta(
            display_name="CHIP State FIPS",
            source_system="CHIP",
            source_subsystem="dim_state_boundary",
            source_column_name="state_fips",
            column_group="chip_audit",
            data_type="string",
            format_value="2-digit FIPS",
            allowed_values="",
            null_allowed="yes",
            definition="State FIPS corresponding to chip_state.",
            provenance_description="Resolved from public.dim_state_boundary after the state assignment step.",
            transformation_rule="Lookup state_fips from the resolved state code or name.",
            example_value="01",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "state_assignment_method": _base_meta(
            display_name="State Assignment Method",
            source_system="CHIP",
            source_subsystem="state_assignment",
            source_column_name="state_assignment_method",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="usaspending_recipient_state,usaspending_place_of_performance_state,taggs_state,unknown",
            null_allowed="no",
            definition="State assignment rule that produced chip_state.",
            provenance_description="Tracks which source won the state assignment precedence chain.",
            transformation_rule="Recipient state beats place of performance; place of performance beats TAGGS; otherwise unknown.",
            example_value="usaspending_recipient_state",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "state_assignment_confidence": _base_meta(
            display_name="State Assignment Confidence",
            source_system="CHIP",
            source_subsystem="state_assignment",
            source_column_name="state_assignment_confidence",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="high,medium,low",
            null_allowed="yes",
            definition="Confidence label associated with the selected state assignment method.",
            provenance_description="Recipient state is treated as highest confidence, place of performance as medium, and TAGGS fallback as low.",
            transformation_rule="Map state assignment method to a fixed confidence label.",
            example_value="high",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_data_source_primary": _base_meta(
            display_name="CHIP Data Source Primary",
            source_system="CHIP",
            source_subsystem="audit_export",
            source_column_name="chip_data_source_primary",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="USAspending",
            null_allowed="no",
            definition="Primary transaction backbone for the exported audit row.",
            provenance_description="The candidate transaction universe is USAspending-backed.",
            transformation_rule="Set to USAspending for every transaction row.",
            example_value="USAspending",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_data_source_secondary": _base_meta(
            display_name="CHIP Data Source Secondary",
            source_system="CHIP",
            source_subsystem="audit_export",
            source_column_name="chip_data_source_secondary",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="TAGGS",
            null_allowed="yes",
            definition="Secondary enrichment source attached to the row when a TAGGS match exists.",
            provenance_description="Only populated when the assistance transaction join finds a TAGGS record.",
            transformation_rule="Set to TAGGS for matched or ambiguously matched assistance rows; blank otherwise.",
            example_value="TAGGS",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_join_method": _base_meta(
            display_name="CHIP Join Method",
            source_system="CHIP",
            source_subsystem="taggs_match",
            source_column_name="chip_join_method",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="award_number_state_year,award_number_fiscal_year,aln_state_year,aln_fiscal_year,not_applicable",
            null_allowed="yes",
            definition="Best TAGGS join path selected for the row.",
            provenance_description="Derived from the deterministic TAGGS candidate ranking logic.",
            transformation_rule="Populate only when a TAGGS record is attached; contracts are marked not_applicable.",
            example_value="award_number_state_year",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_join_status": _base_meta(
            display_name="CHIP Join Status",
            source_system="CHIP",
            source_subsystem="taggs_match",
            source_column_name="chip_join_status",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="matched,matched_ambiguous,unmatched,not_attempted,not_applicable",
            null_allowed="no",
            definition="Outcome of the best-effort TAGGS transaction match.",
            provenance_description="Derived from whether a TAGGS candidate was found and how many equally ranked matches existed.",
            transformation_rule="Contracts are not_applicable; assistance rows are matched, matched_ambiguous, unmatched, or not_attempted.",
            example_value="matched",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_join_confidence": _base_meta(
            display_name="CHIP Join Confidence",
            source_system="CHIP",
            source_subsystem="taggs_match",
            source_column_name="chip_join_confidence",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="high,medium,low",
            null_allowed="yes",
            definition="Confidence label for the selected TAGGS join method.",
            provenance_description="Copied from the ranked TAGGS matching candidate.",
            transformation_rule="Exact award-number joins outrank ALN-only joins.",
            example_value="high",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_normalization_method": _base_meta(
            display_name="CHIP Normalization Method",
            source_system="CHIP",
            source_subsystem="normalized_state_funding",
            source_column_name="normalization_method",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="yes",
            definition="State normalization method used to derive chip_normalized_amount.",
            provenance_description="Copied from recon.normalized_state_funding.normalization_method when a state-year target exists.",
            transformation_rule="Pass through the state-year normalization method for the resolved state.",
            example_value="funding_scope_reconstruction_calibration_layer",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_raw_amount": _base_meta(
            display_name="CHIP Raw Amount",
            source_system="CHIP",
            source_subsystem="profile_scope",
            source_column_name="raw_amount",
            column_group="chip_audit",
            data_type="numeric",
            format_value="decimal(18,2)",
            allowed_values="",
            null_allowed="yes",
            definition="Raw transaction amount from the profile-scope candidate universe.",
            provenance_description="Copied from recon.profile_scope_transactions.raw_amount.",
            transformation_rule="Pass through the candidate transaction raw amount.",
            example_value="125000.00",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_net_amount_for_model": _base_meta(
            display_name="CHIP Net Amount For Model",
            source_system="CHIP",
            source_subsystem="profile_scope",
            source_column_name="normalized_profile_scope_amount",
            column_group="chip_audit",
            data_type="numeric",
            format_value="decimal(18,2)",
            allowed_values="",
            null_allowed="yes",
            definition="Net row contribution used by the state model before state normalization.",
            provenance_description="Comes from recon.profile_scope_transactions.normalized_profile_scope_amount for included rows.",
            transformation_rule="Included rows keep their model net amount; excluded rows are zero; unresolved rows remain blank.",
            example_value="110000.00",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_normalized_amount": _base_meta(
            display_name="CHIP Normalized Amount",
            source_system="CHIP",
            source_subsystem="normalized_state_funding",
            source_column_name="chip_normalized_amount",
            column_group="chip_audit",
            data_type="numeric",
            format_value="decimal(18,2)",
            allowed_values="",
            null_allowed="yes",
            definition="Row-level allocation of the state-year normalized target total.",
            provenance_description="Calculated within the export by proportionally allocating the state-year normalized amount across included rows.",
            transformation_rule="Allocate cents by state-year weight share with deterministic remainder handling.",
            example_value="100000.00",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "chip_provenance_notes": _base_meta(
            display_name="CHIP Provenance Notes",
            source_system="CHIP",
            source_subsystem="audit_export",
            source_column_name="chip_provenance_notes",
            column_group="chip_audit",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="yes",
            definition="Compact provenance note describing the row's transformation path.",
            provenance_description="Includes methodology, state assignment, join status, and normalization context.",
            transformation_rule="Concatenate major export-time provenance fragments with semicolons.",
            example_value="profile_scope_methodology=profile_scope_v5; state_assignment=usaspending_recipient_state; join_status=matched",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "prov_usaspending_source_file": _base_meta(
            display_name="USAspending Source File",
            source_system="Provenance",
            source_subsystem="audit_export",
            source_column_name="prov_usaspending_source_file",
            column_group="provenance",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="no",
            definition="USAspending source file name for the primary transaction row.",
            provenance_description="Copied from the USAspending-backed ingest tables.",
            transformation_rule="Prefer the primary transaction source file name.",
            example_value="prime_transactions.csv",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "prov_usaspending_extract_date": _base_meta(
            display_name="USAspending Extract Date",
            source_system="Provenance",
            source_subsystem="audit_export",
            source_column_name="prov_usaspending_extract_date",
            column_group="provenance",
            data_type="date",
            format_value="YYYY-MM-DD",
            allowed_values="",
            null_allowed="yes",
            definition="Best available extract or import date for the USAspending source row.",
            provenance_description="Uses the import date when a source extract date is not tracked separately.",
            transformation_rule="Render the best available source timestamp as an ISO date.",
            example_value="2026-03-20",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "prov_usaspending_table_name": _base_meta(
            display_name="USAspending Table Name",
            source_system="Provenance",
            source_subsystem="audit_export",
            source_column_name="prov_usaspending_table_name",
            column_group="provenance",
            data_type="string",
            format_value="schema.table",
            allowed_values=f"{PRIME_TX_TABLE},{CONTRACT_TABLE}",
            null_allowed="no",
            definition="Fully qualified USAspending-backed source table used for the row.",
            provenance_description="Set by the export based on the source system.",
            transformation_rule="Assistance rows map to cdc_funding.prime_transactions; contracts map to usaspending.contract_transactions_raw.",
            example_value=PRIME_TX_TABLE,
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "prov_usaspending_record_id": _base_meta(
            display_name="USAspending Record ID",
            source_system="Provenance",
            source_subsystem="audit_export",
            source_column_name="prov_usaspending_record_id",
            column_group="provenance",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="no",
            definition="Primary USAspending record identifier used to build the row.",
            provenance_description="Copied from the source transaction table.",
            transformation_rule="Prefer the source transaction unique key and fall back to the local row id.",
            example_value="abc123",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "prov_taggs_source_file": _base_meta(
            display_name="TAGGS Source File",
            source_system="Provenance",
            source_subsystem="audit_export",
            source_column_name="prov_taggs_source_file",
            column_group="provenance",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="yes",
            definition="TAGGS source file name for the matched enrichment row.",
            provenance_description="Copied from taggs.raw_awards when a match exists.",
            transformation_rule="Populate only for matched assistance rows.",
            example_value="CDC-1-4.csv",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "prov_taggs_extract_date": _base_meta(
            display_name="TAGGS Extract Date",
            source_system="Provenance",
            source_subsystem="audit_export",
            source_column_name="prov_taggs_extract_date",
            column_group="provenance",
            data_type="date",
            format_value="YYYY-MM-DD",
            allowed_values="",
            null_allowed="yes",
            definition="Best available extract or load date for the matched TAGGS row.",
            provenance_description="Derived from taggs.raw_awards.loaded_at.",
            transformation_rule="Render loaded_at as an ISO date.",
            example_value="2026-03-19",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "prov_taggs_table_name": _base_meta(
            display_name="TAGGS Table Name",
            source_system="Provenance",
            source_subsystem="audit_export",
            source_column_name="prov_taggs_table_name",
            column_group="provenance",
            data_type="string",
            format_value="schema.table",
            allowed_values=TAGGS_RAW_TABLE,
            null_allowed="yes",
            definition="Fully qualified TAGGS table used for the matched row.",
            provenance_description="Set by the export when a TAGGS raw award is attached.",
            transformation_rule="Populate with taggs.raw_awards for matched assistance rows only.",
            example_value=TAGGS_RAW_TABLE,
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "prov_taggs_record_id": _base_meta(
            display_name="TAGGS Record ID",
            source_system="Provenance",
            source_subsystem="audit_export",
            source_column_name="prov_taggs_record_id",
            column_group="provenance",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="yes",
            definition="Internal TAGGS raw-award record id selected during matching.",
            provenance_description="Copied from taggs.raw_awards.id.",
            transformation_rule="Populate only when a TAGGS match is selected.",
            example_value="1001",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "prov_merge_run_id": _base_meta(
            display_name="Merge Run ID",
            source_system="Provenance",
            source_subsystem="audit_export",
            source_column_name="prov_merge_run_id",
            column_group="provenance",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="no",
            definition="Run identifier shared across the output package.",
            provenance_description="Generated once at runtime by the state audit export pipeline.",
            transformation_rule="Set to chip_run_id for every exported transaction row.",
            example_value="chip_state_audit_20260321T120000Z_abcd1234ef56",
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "prov_transformation_stage": _base_meta(
            display_name="Transformation Stage",
            source_system="Provenance",
            source_subsystem="audit_export",
            source_column_name="prov_transformation_stage",
            column_group="provenance",
            data_type="string",
            format_value="",
            allowed_values=TRANSFORMATION_STAGE,
            null_allowed="no",
            definition="Named transformation stage that produced the exported row.",
            provenance_description="Static label emitted by the state audit export.",
            transformation_rule="Populate with the export transformation stage constant.",
            example_value=TRANSFORMATION_STAGE,
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
        "prov_last_modified_by_process": _base_meta(
            display_name="Last Modified By Process",
            source_system="Provenance",
            source_subsystem="audit_export",
            source_column_name="prov_last_modified_by_process",
            column_group="provenance",
            data_type="string",
            format_value="",
            allowed_values=EXPORT_PROCESS_NAME,
            null_allowed="no",
            definition="Process name responsible for the final exported row.",
            provenance_description="Static runtime label assigned by the export pipeline.",
            transformation_rule="Populate with the export process constant.",
            example_value=EXPORT_PROCESS_NAME,
            appears_in_files=TRANSACTION_APPEARS_IN_FILES,
        ),
    }


def _profile_column_meta() -> dict[str, dict[str, str]]:
    return {
        "state": _base_meta(
            display_name="State",
            source_system="CHIP",
            source_subsystem="state_profile",
            source_column_name="state",
            column_group="state_profile",
            data_type="string",
            format_value="2-letter state code",
            allowed_values="",
            null_allowed="no",
            definition="Resolved state code for the state-year funding profile row.",
            provenance_description="Grouped from included CHIP audit rows.",
            transformation_rule="Group included transaction rows by resolved chip_state and fiscal_year.",
            example_value="AL",
            appears_in_files=PROFILE_APPEARS_IN_FILES,
        ),
        "state_fips": _base_meta(
            display_name="State FIPS",
            source_system="CHIP",
            source_subsystem="state_profile",
            source_column_name="state_fips",
            column_group="state_profile",
            data_type="string",
            format_value="2-digit FIPS",
            allowed_values="",
            null_allowed="yes",
            definition="State FIPS corresponding to the profile row's state.",
            provenance_description="Carried from the resolved CHIP state assignment.",
            transformation_rule="Group included rows by chip_state_fips alongside chip_state.",
            example_value="01",
            appears_in_files=PROFILE_APPEARS_IN_FILES,
        ),
        "fiscal_year": _base_meta(
            display_name="Fiscal Year",
            source_system="CHIP",
            source_subsystem="state_profile",
            source_column_name="fiscal_year",
            column_group="state_profile",
            data_type="integer",
            format_value="YYYY",
            allowed_values="",
            null_allowed="yes",
            definition="Fiscal year for the state funding profile row.",
            provenance_description="Derived from the underlying included transaction rows.",
            transformation_rule="Group included rows by fiscal_year.",
            example_value="2025",
            appears_in_files=PROFILE_APPEARS_IN_FILES,
        ),
        "transaction_count": _base_meta(
            display_name="Transaction Count",
            source_system="CHIP",
            source_subsystem="state_profile",
            source_column_name="transaction_count",
            column_group="state_profile",
            data_type="integer",
            format_value="",
            allowed_values="",
            null_allowed="no",
            definition="Number of included transactions contributing to the state-year profile row.",
            provenance_description="Counted from the included transaction file universe.",
            transformation_rule="COUNT(*) over included rows in the state-year group.",
            example_value="42",
            appears_in_files=PROFILE_APPEARS_IN_FILES,
        ),
        "total_raw_funding": _base_meta(
            display_name="Total Raw Funding",
            source_system="CHIP",
            source_subsystem="state_profile",
            source_column_name="total_raw_funding",
            column_group="state_profile",
            data_type="numeric",
            format_value="decimal(18,2)",
            allowed_values="",
            null_allowed="no",
            definition="Sum of chip_raw_amount across included rows in the state-year profile row.",
            provenance_description="Aggregated from included transaction rows only.",
            transformation_rule="SUM(chip_raw_amount).",
            example_value="1250000.00",
            appears_in_files=PROFILE_APPEARS_IN_FILES,
        ),
        "total_net_funding": _base_meta(
            display_name="Total Net Funding",
            source_system="CHIP",
            source_subsystem="state_profile",
            source_column_name="total_net_funding",
            column_group="state_profile",
            data_type="numeric",
            format_value="decimal(18,2)",
            allowed_values="",
            null_allowed="no",
            definition="Sum of chip_net_amount_for_model across included rows in the state-year profile row.",
            provenance_description="Aggregated from included transaction rows only.",
            transformation_rule="SUM(chip_net_amount_for_model).",
            example_value="1175000.00",
            appears_in_files=PROFILE_APPEARS_IN_FILES,
        ),
        "total_normalized_funding": _base_meta(
            display_name="Total Normalized Funding",
            source_system="CHIP",
            source_subsystem="state_profile",
            source_column_name="total_normalized_funding",
            column_group="state_profile",
            data_type="numeric",
            format_value="decimal(18,2)",
            allowed_values="",
            null_allowed="no",
            definition="Sum of chip_normalized_amount across included rows in the state-year profile row.",
            provenance_description="Aggregated from included transaction rows only.",
            transformation_rule="SUM(chip_normalized_amount).",
            example_value="1150000.00",
            appears_in_files=PROFILE_APPEARS_IN_FILES,
        ),
        "dominant_program": _base_meta(
            display_name="Dominant Program",
            source_system="CHIP",
            source_subsystem="state_profile",
            source_column_name="dominant_program",
            column_group="state_profile",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="no",
            definition="Program descriptor contributing the largest net funding share within the state-year group.",
            provenance_description="Derived from the dominant program candidate stored on included transaction rows.",
            transformation_rule="Rank grouped program candidates by summed chip_net_amount_for_model and take the top row.",
            example_value="Immunization and Respiratory Diseases",
            appears_in_files=PROFILE_APPEARS_IN_FILES,
        ),
        "data_quality_score": _base_meta(
            display_name="Data Quality Score",
            source_system="CHIP",
            source_subsystem="state_profile",
            source_column_name="data_quality_score",
            column_group="state_profile",
            data_type="numeric",
            format_value="0-100 scale",
            allowed_values="",
            null_allowed="yes",
            definition="Average row-quality score for included rows in the state-year group.",
            provenance_description="Derived from state assignment confidence and TAGGS join status.",
            transformation_rule="Average per-row quality points with a 0-100 clamp.",
            example_value="91.25",
            appears_in_files=PROFILE_APPEARS_IN_FILES,
        ),
        "model_version": _base_meta(
            display_name="Model Version",
            source_system="CHIP",
            source_subsystem="state_profile",
            source_column_name="model_version",
            column_group="state_profile",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="no",
            definition="Model version shared by the state-year profile export rows.",
            provenance_description="Copied from the transaction export rows.",
            transformation_rule="MAX(chip_model_version) within each state-year group.",
            example_value=CHIP_MODEL_VERSION,
            appears_in_files=PROFILE_APPEARS_IN_FILES,
        ),
        "run_id": _base_meta(
            display_name="Run ID",
            source_system="CHIP",
            source_subsystem="state_profile",
            source_column_name="run_id",
            column_group="state_profile",
            data_type="string",
            format_value="",
            allowed_values="",
            null_allowed="no",
            definition="Export run identifier shared with the transaction rows.",
            provenance_description="Copied from the transaction export rows.",
            transformation_rule="MAX(chip_run_id) within each state-year group.",
            example_value="chip_state_audit_20260321T120000Z_abcd1234ef56",
            appears_in_files=PROFILE_APPEARS_IN_FILES,
        ),
    }


def _validation_column_meta() -> dict[str, dict[str, str]]:
    definitions = {
        "total_candidate_rows": "Total rows in the candidate transaction universe.",
        "included_rows": "Total rows exported to the included transaction file.",
        "excluded_rows": "Total rows exported to the excluded transaction file.",
        "unresolved_rows": "Total rows exported to the unresolved transaction file.",
        "included_raw_amount_sum": "Sum of chip_raw_amount across included rows.",
        "included_net_amount_sum": "Sum of chip_net_amount_for_model across included rows.",
        "included_normalized_amount_sum": "Sum of chip_normalized_amount across included rows.",
        "excluded_net_amount_sum": "Sum of chip_net_amount_for_model across excluded rows.",
        "unresolved_net_amount_sum": "Sum of chip_net_amount_for_model across unresolved rows.",
        "matched_both_sources_count": "Count of rows with both USAspending and TAGGS represented.",
        "usaspending_only_count": "Count of rows represented only by USAspending in the final export.",
        "taggs_only_count": "Count of rows represented only by TAGGS in the final export.",
        "unknown_state_count": "Count of rows that could not be assigned to a state.",
        "duplicate_row_id_count": "Count of duplicate chip_row_id values detected in the candidate universe.",
        "schema_mismatch_flag": "TRUE when the three transaction files do not share identical headers.",
    }
    meta: dict[str, dict[str, str]] = {}
    for column_name, definition in definitions.items():
        meta[column_name] = _base_meta(
            display_name=_display_name(column_name),
            source_system="CHIP",
            source_subsystem="validation",
            source_column_name=column_name,
            column_group="validation",
            data_type="boolean" if column_name.endswith("_flag") else ("numeric" if column_name.endswith("_sum") else "integer"),
            format_value="",
            allowed_values="TRUE,FALSE" if column_name.endswith("_flag") else "",
            null_allowed="no",
            definition=definition,
            provenance_description="Computed by the state audit export validation step.",
            transformation_rule="Aggregate directly from the staged transaction export table and file checks.",
            example_value="0" if not column_name.endswith("_flag") else "FALSE",
            appears_in_files=VALIDATION_APPEARS_IN_FILES,
        )
    return meta


def build_data_dictionary_rows(raw_field_specs: Sequence[RawFieldSpec]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []

    transaction_meta = _transaction_column_meta()
    profile_meta = _profile_column_meta()
    validation_meta = _validation_column_meta()

    for column_name in [*TRANSACTION_FIXED_COLUMNS, *PROVENANCE_COLUMNS]:
        meta = transaction_meta[column_name]
        rows.append({"column_name": column_name, **meta})

    for spec in raw_field_specs:
        rows.append(
            {
                "column_name": spec.output_column,
                "display_name": spec.original_key,
                "source_system": "USAspending" if spec.source_system == "usaspending" else "TAGGS",
                "source_subsystem": spec.source_subsystem,
                "source_column_name": spec.original_key,
                "column_group": f"{spec.source_system}_raw_source",
                "data_type": "string",
                "format": "",
                "allowed_values": "",
                "null_allowed": "yes",
                "definition": (
                    f"Raw source column preserved from the underlying {spec.source_system.upper()} payload."
                ),
                "provenance_description": "Flattened from the stored JSON payload at export time.",
                "transformation_rule": "Pass through jsonb_extract_path_text() for the original source key.",
                "example_value": "",
                "appears_in_files": TRANSACTION_APPEARS_IN_FILES,
            }
        )

    for column_name in PROFILE_COLUMNS:
        meta = profile_meta[column_name]
        rows.append({"column_name": column_name, **meta})

    for column_name in VALIDATION_COLUMNS:
        meta = validation_meta[column_name]
        rows.append({"column_name": column_name, **meta})

    return rows


def _write_methodology(
    path: Path,
    *,
    layout: ExportLayout,
    export_timestamp: datetime,
    export_batch_id: str,
    run_id: str,
    metrics: Mapping[str, Any],
) -> None:
    content = f"""# CHIP State Audit Export Methodology

## Purpose

This package documents the state-level transaction universe used for the CHIP state funding model audit.
It preserves raw USAspending and TAGGS source fields, adds explicit CHIP audit and provenance columns, and splits the transaction universe into included, excluded, and unresolved buckets.

- Export batch id: `{export_batch_id}`
- Run id: `{run_id}`
- Export timestamp (UTC): `{export_timestamp.isoformat()}`
- CHIP model version: `{CHIP_MODEL_VERSION}`

## Files

- `{EXPORT_FILE_NAMES["included"]}`: state-model candidate rows where `chip_inclusion_flag = TRUE`
- `{EXPORT_FILE_NAMES["excluded"]}`: state-model candidate rows where `chip_inclusion_flag = FALSE`
- `{EXPORT_FILE_NAMES["null"]}`: state-model candidate rows where `chip_inclusion_flag IS NULL`
- `{EXPORT_FILE_NAMES["profile"]}`: one row per state and fiscal year built from included rows only
- `{EXPORT_FILE_NAMES["dictionary"]}`: data dictionary for transaction, profile, and validation columns
- `{EXPORT_FILE_NAMES["validation"]}`: one-row validation summary for the export
- `{EXPORT_FILE_NAMES["methodology"]}`: this methodology document

## Row Definition

Each transaction row represents one USAspending-backed transaction from `recon.profile_scope_transactions`.
The export stays at the state level only.
It does not perform county allocation and does not join to PLACES or health outcome measures.

## State Assignment Rules

State assignment uses this precedence chain:

1. USAspending recipient state
2. USAspending place of performance state
3. TAGGS state
4. Unknown when none of the above resolve cleanly

The chosen rule is stored in `state_assignment_method`, and the associated confidence label is stored in `state_assignment_confidence`.
Rows without a resolved state remain unresolved in the export even if the profile-scope layer had an inclusion decision.

## Inclusion, Exclusion, and Unresolved Rules

The export begins with the profile-scope model decision in `recon.profile_scope_transactions.include_in_profile_scope`.
That decision is preserved when state assignment succeeds.
If a row does not resolve to a state, the export forces `chip_inclusion_flag` to NULL so reviewers can see it in `{EXPORT_FILE_NAMES["null"]}`.

Controlled `chip_inclusion_reason` values summarize the final routing decision and distinguish included model rows from out-of-scope, duplicate, missing-state, failed-join, and manual-review scenarios.

## Normalization Method

`chip_raw_amount` comes directly from the candidate universe raw amount field.
`chip_net_amount_for_model` reflects the model-ready row amount before state normalization.
`chip_normalized_amount` is allocated only for included rows.
The export uses the state-year targets in `recon.normalized_state_funding` and distributes those totals proportionally across included rows in the same resolved state and fiscal year.
The allocation logic handles fractional cents deterministically so the row-level total reconciles to the state-year normalized target.

## Provenance Strategy

USAspending remains the primary source backbone for the export.
TAGGS is attached as a secondary source when the export finds the best available assistance match.
Provenance columns capture source files, best available extract dates, source tables, record identifiers, the export run id, and the transformation stage label.

## Validation Checks

The export validates that:

- the three transaction CSVs share identical columns and column order
- duplicate `chip_row_id` values are not present in the candidate universe
- the expected row counts for included, excluded, and unresolved buckets reconcile to the candidate universe
- included normalized amounts aggregate cleanly
- unresolved state rows are surfaced explicitly

Validation summary snapshot:

- total candidate rows: `{_serialize_csv_cell(metrics["total_candidate_rows"])}`
- included rows: `{_serialize_csv_cell(metrics["included_rows"])}`
- excluded rows: `{_serialize_csv_cell(metrics["excluded_rows"])}`
- unresolved rows: `{_serialize_csv_cell(metrics["unresolved_rows"])}`
- included normalized amount sum: `{_serialize_csv_cell(metrics["included_normalized_amount_sum"])}`
- matched both sources count: `{_serialize_csv_cell(metrics["matched_both_sources_count"])}`
- unknown state count: `{_serialize_csv_cell(metrics["unknown_state_count"])}`

## Limitations

- The candidate universe is intentionally state-level only in this export.
- TAGGS enrichment remains a best-effort secondary join for assistance transactions.
- Rows with invalid or missing state evidence are preserved as unresolved rather than being dropped.
- Row-level normalized values are audit allocations, not raw source transaction values.

## Export Directories Used

- temp root: `{layout.tmp_root}`
- export root: `{layout.exports_root}`
- log root: `{layout.logs_root}`
- partial export staging directory: `{layout.partial_export_dir}`
- final export directory: `{layout.final_export_dir}`

## Temp Space Controls

The export script explicitly pins temporary file usage to `{layout.tmp_root}` by setting:

- `TMPDIR`
- `TEMP`
- `TMP`
- `TEMPDIR`
- `POLARS_TEMP_DIR`
- `JOBLIB_TEMP_FOLDER`
- `tempfile.tempdir` in Python

That keeps Python tempfile usage, pandas tempfile usage, polars tempfile usage, and GNU `sort` temporary files off `/tmp`, `/run`, and `/dev/shm`.
The PostgreSQL session also disables parallel query execution to avoid shared-memory pressure on `/dev/shm` during the staging phases.
Large CSV outputs are streamed directly to `{layout.partial_export_dir}` and atomically renamed into the final export directory after validation succeeds.
"""
    path.write_text(content, encoding="utf-8")


def _write_data_dictionary(path: Path, *, rows: Sequence[Mapping[str, Any]]) -> None:
    _write_rows_to_csv(
        path,
        fieldnames=[
            "column_name",
            "display_name",
            "source_system",
            "source_subsystem",
            "source_column_name",
            "column_group",
            "data_type",
            "format",
            "allowed_values",
            "null_allowed",
            "definition",
            "provenance_description",
            "transformation_rule",
            "example_value",
            "appears_in_files",
        ],
        rows=rows,
    )


def _write_validation_summary(path: Path, *, metrics: Mapping[str, Any]) -> None:
    ordered_row = {column_name: metrics.get(column_name) for column_name in VALIDATION_COLUMNS}
    _write_rows_to_csv(path, fieldnames=VALIDATION_COLUMNS, rows=[ordered_row])


def _prepare_state_audit_temp_table(
    connection: psycopg.Connection[Any],
    *,
    export_timestamp: datetime,
    export_batch_id: str,
    run_id: str,
    logger: logging.Logger,
) -> None:
    with connection.cursor() as cursor:
        logger.info("Building staged state-audit transaction tables in PostgreSQL.")
        for table_name in (
            TEMP_EXPORT_TABLE,
            TEMP_TAGGS_MATCH_TABLE,
            TEMP_TAGGS_LOOKUP_TABLE,
            TEMP_ASSISTANCE_TABLE,
            TEMP_TX_BASE_TABLE,
        ):
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")

        logger.info("Phase 1/4: materializing USAspending-backed tx base.")
        cursor.execute(_build_tx_base_table_sql())
        cursor.execute(
            f"CREATE INDEX {TEMP_TX_BASE_TABLE}_source_tx_idx "
            f"ON {TEMP_TX_BASE_TABLE} (source_system, source_transaction_id)"
        )
        cursor.execute(f"ANALYZE {TEMP_TX_BASE_TABLE}")

        logger.info("Phase 2/4: materializing assistance join inputs.")
        cursor.execute(_build_assistance_table_sql())
        cursor.execute(f"CREATE INDEX {TEMP_ASSISTANCE_TABLE}_tx_idx ON {TEMP_ASSISTANCE_TABLE} (source_transaction_id)")
        cursor.execute(
            f"CREATE INDEX {TEMP_ASSISTANCE_TABLE}_award_idx "
            f"ON {TEMP_ASSISTANCE_TABLE} (award_number_key, fiscal_year, usaspending_state_key)"
        )
        cursor.execute(
            f"CREATE INDEX {TEMP_ASSISTANCE_TABLE}_aln_idx "
            f"ON {TEMP_ASSISTANCE_TABLE} (normalized_usaspending_aln, fiscal_year, usaspending_state_key)"
        )
        cursor.execute(f"ANALYZE {TEMP_ASSISTANCE_TABLE}")

        logger.info("Phase 3/4: building slim TAGGS lookup table with composite temp indexes.")
        cursor.execute(_build_taggs_lookup_table_sql())
        cursor.execute(
            f"CREATE INDEX {TEMP_TAGGS_LOOKUP_TABLE}_award_state_idx "
            f"ON {TEMP_TAGGS_LOOKUP_TABLE} (award_number_key, funding_fiscal_year, taggs_state_key)"
        )
        cursor.execute(
            f"CREATE INDEX {TEMP_TAGGS_LOOKUP_TABLE}_award_idx "
            f"ON {TEMP_TAGGS_LOOKUP_TABLE} (award_number_key, funding_fiscal_year)"
        )
        cursor.execute(
            f"CREATE INDEX {TEMP_TAGGS_LOOKUP_TABLE}_aln_state_idx "
            f"ON {TEMP_TAGGS_LOOKUP_TABLE} (normalized_taggs_aln, funding_fiscal_year, taggs_state_key)"
        )
        cursor.execute(
            f"CREATE INDEX {TEMP_TAGGS_LOOKUP_TABLE}_aln_idx "
            f"ON {TEMP_TAGGS_LOOKUP_TABLE} (normalized_taggs_aln, funding_fiscal_year)"
        )
        cursor.execute(f"ANALYZE {TEMP_TAGGS_LOOKUP_TABLE}")

        logger.info("Phase 4/4: matching TAGGS rows and assembling the final export table.")
        cursor.execute(_build_taggs_match_table_sql())
        cursor.execute(
            f"CREATE INDEX {TEMP_TAGGS_MATCH_TABLE}_tx_idx "
            f"ON {TEMP_TAGGS_MATCH_TABLE} (source_transaction_id)"
        )
        cursor.execute(f"ANALYZE {TEMP_TAGGS_MATCH_TABLE}")

        cursor.execute(
            _build_final_export_table_sql(),
            {
                "chip_model_version": CHIP_MODEL_VERSION,
                "run_id": run_id,
                "export_timestamp": export_timestamp.isoformat(),
                "export_batch_id": export_batch_id,
            },
        )
        cursor.execute(f"CREATE INDEX {TEMP_EXPORT_TABLE}_bucket_idx ON {TEMP_EXPORT_TABLE} (chip_inclusion_bucket)")
        cursor.execute(f"CREATE INDEX {TEMP_EXPORT_TABLE}_row_id_idx ON {TEMP_EXPORT_TABLE} (chip_row_id)")
        cursor.execute(
            f"CREATE INDEX {TEMP_EXPORT_TABLE}_export_idx ON {TEMP_EXPORT_TABLE} "
            "(chip_inclusion_bucket, fiscal_year, chip_state, chip_row_id)"
        )
        cursor.execute(f"ANALYZE {TEMP_EXPORT_TABLE}")
    logger.info("Finished staging PostgreSQL temp table %s.", TEMP_EXPORT_TABLE)


def _validate_metrics(metrics: Mapping[str, Any]) -> None:
    if int(metrics.get("duplicate_row_id_count") or 0) != 0:
        raise RuntimeError("Duplicate chip_row_id values detected in the candidate universe.")
    if int(metrics.get("missing_normalization_target_count") or 0) != 0:
        raise RuntimeError("Included rows are missing state normalization targets.")
    if int(metrics.get("zero_weight_target_count") or 0) != 0:
        raise RuntimeError("Included rows encountered non-zero normalization targets with zero allocation weight.")


def _export_transaction_files(
    connection: psycopg.Connection[Any],
    *,
    raw_field_specs: Sequence[RawFieldSpec],
    output_dir: Path,
    logger: logging.Logger,
) -> dict[str, Path]:
    header = [*TRANSACTION_FIXED_COLUMNS, *PROVENANCE_COLUMNS, *[spec.output_column for spec in raw_field_specs]]
    paths: dict[str, Path] = {}
    for bucket_name in ("included", "excluded", NULL_BUCKET):
        file_key = TRANSACTION_BUCKET_TO_FILE_KEY[bucket_name]
        output_path = output_dir / EXPORT_FILE_NAMES[file_key]
        _copy_query_to_csv(
            connection,
            path=output_path,
            header=header,
            select_sql=_build_transaction_select_sql(raw_field_specs, bucket=bucket_name),
            logger=logger,
        )
        paths[bucket_name] = output_path
    return paths


def _export_state_profile(
    connection: psycopg.Connection[Any],
    *,
    output_path: Path,
    logger: logging.Logger,
) -> None:
    _copy_query_to_csv(
        connection,
        path=output_path,
        header=PROFILE_COLUMNS,
        select_sql=_build_profile_select_sql(),
        logger=logger,
    )


def _validate_transaction_exports(
    paths: Mapping[str, Path],
    *,
    metrics: dict[str, Any],
) -> None:
    headers_by_file = {
        bucket_name: _read_csv_header(path)
        for bucket_name, path in paths.items()
    }
    schema_matches = headers_are_identical(headers_by_file)
    metrics["schema_mismatch_flag"] = not schema_matches
    if not schema_matches:
        raise RuntimeError("Transaction export headers do not match across included, excluded, and unresolved files.")

    expected_counts = {
        "included": int(metrics["included_rows"]),
        "excluded": int(metrics["excluded_rows"]),
        NULL_BUCKET: int(metrics["unresolved_rows"]),
    }
    observed_counts = {
        bucket_name: _count_csv_data_rows(path)
        for bucket_name, path in paths.items()
    }
    for bucket_name, expected in expected_counts.items():
        observed = observed_counts[bucket_name]
        if observed != expected:
            raise RuntimeError(
                f"File row count mismatch for {bucket_name}: expected {expected}, observed {observed}."
            )

    if sum(observed_counts.values()) != int(metrics["total_candidate_rows"]):
        raise RuntimeError("Transaction file row counts do not sum to the candidate universe total.")


def run_export(
    *,
    db_url: str,
    tmp_root: Path,
    exports_root: Path,
    logs_root: Path,
    export_date: date,
    min_free_gb: int,
    overwrite: bool,
) -> Path:
    export_timestamp = datetime.now(timezone.utc)
    run_id = _build_run_id(export_timestamp)
    export_batch_id = _build_export_batch_id(export_date)
    layout = _build_layout(
        tmp_root=tmp_root,
        exports_root=exports_root,
        logs_root=logs_root,
        export_batch_id=export_batch_id,
        run_id=run_id,
        overwrite=overwrite,
    )

    logger = _setup_logger(layout.log_file)
    logger.info("Starting CHIP state audit export run_id=%s batch_id=%s", run_id, export_batch_id)

    mount_root = DEFAULT_MOUNT_ROOT
    _configure_temp_environment(layout.tmp_root, logger)
    _log_disk_usage(logger, "Before export", mount_root)
    _ensure_free_space(mount_root, min_free_gb=min_free_gb, logger=logger)

    dsn = _psycopg_connect_dsn(db_url)
    try:
        with psycopg.connect(dsn) as connection:
            _configure_postgres_session(connection, logger=logger)
            _require_tables(
                connection,
                [
                    PROFILE_SCOPE_TX_TABLE,
                    ASSISTANCE_PROFILE_TABLE,
                    CONTRACT_PROFILE_TABLE,
                    NORMALIZED_TABLE,
                    PRIME_TX_TABLE,
                    PRIME_AWARD_TABLE,
                    CONTRACT_TABLE,
                    TAGGS_RAW_TABLE,
                    TAGGS_SUMMARY_TABLE,
                    STATE_DIM_TABLE,
                ],
            )
            raw_field_specs = _discover_raw_field_specs(connection, logger=logger)
            _prepare_state_audit_temp_table(
                connection,
                export_timestamp=export_timestamp,
                export_batch_id=export_batch_id,
                run_id=run_id,
                logger=logger,
            )

            metrics = _fetch_validation_metrics(connection)
            _validate_metrics(metrics)
            _log_disk_usage(logger, "After staging", mount_root)

            transaction_paths = _export_transaction_files(
                connection,
                raw_field_specs=raw_field_specs,
                output_dir=layout.partial_export_dir,
                logger=logger,
            )
            _export_state_profile(
                connection,
                output_path=layout.partial_export_dir / EXPORT_FILE_NAMES["profile"],
                logger=logger,
            )
            _log_disk_usage(logger, "After transaction/profile exports", mount_root)

            _validate_transaction_exports(transaction_paths, metrics=metrics)

            dictionary_rows = build_data_dictionary_rows(raw_field_specs)
            _write_data_dictionary(
                layout.partial_export_dir / EXPORT_FILE_NAMES["dictionary"],
                rows=dictionary_rows,
            )
            _write_validation_summary(
                layout.partial_export_dir / EXPORT_FILE_NAMES["validation"],
                metrics=metrics,
            )
            _write_methodology(
                layout.partial_export_dir / EXPORT_FILE_NAMES["methodology"],
                layout=layout,
                export_timestamp=export_timestamp,
                export_batch_id=export_batch_id,
                run_id=run_id,
                metrics=metrics,
            )

            connection.commit()

        layout.partial_export_dir.rename(layout.final_export_dir)
        _remove_tree(layout.scratch_dir)
        _log_disk_usage(logger, "After export", mount_root)
        logger.info("CHIP state audit export completed successfully: %s", layout.final_export_dir)
        return layout.final_export_dir
    except Exception:
        logger.exception("CHIP state audit export failed.")
        _remove_tree(layout.partial_export_dir)
        _remove_tree(layout.scratch_dir)
        raise


def main() -> None:
    args = parse_args()
    export_dir = run_export(
        db_url=args.db_url,
        tmp_root=Path(args.tmp_root),
        exports_root=Path(args.exports_root),
        logs_root=Path(args.logs_root),
        export_date=_parse_export_date(args.export_date),
        min_free_gb=int(args.min_free_gb),
        overwrite=bool(args.overwrite),
    )
    print(str(export_dir))


if __name__ == "__main__":
    main()
