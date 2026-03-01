#!/usr/bin/env python3
"""Ingest HRSA HPSA designation-level CSVs and rebuild county summary.

Example:
  python backend/scripts/ingest_hpsa.py \
    --pc /mnt/data/BCD_HPSA_FCT_DET_PC.csv \
    --mh /mnt/data/BCD_HPSA_FCT_DET_MH.csv \
    --dh /mnt/data/BCD_HPSA_FCT_DET_DH.csv \
    --rebuild-summary
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, text

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_PC_PATH = "/mnt/data/BCD_HPSA_FCT_DET_PC.csv"
DEFAULT_MH_PATH = "/mnt/data/BCD_HPSA_FCT_DET_MH.csv"
DEFAULT_DH_PATH = "/mnt/data/BCD_HPSA_FCT_DET_DH.csv"
BATCH_SIZE = 5000

COUNTY_FIPS_KEYS = (
    "common state county fips code",
    "common_state_county_fips_code",
    "state and county federal information processing standard code",
    "state_and_county_federal_information_processing_standard_code",
    "county or county equivalent federal information processing standard code",
    "county_or_county_equivalent_federal_information_processing_standard_code",
    "county_fips",
    "countyfips",
    "cnty_fips",
    "county_fips_code",
    "county_fips5",
    "fips",
    "fipscounty",
    "county_code",
)
COUNTY_FIPS3_KEYS = (
    "countyfp",
    "county_fips3",
    "countyfips3",
    "cnty_fips3",
    "county_code3",
)
STATE_FIPS_KEYS = (
    "common state fips code",
    "primary state fips code",
    "state fips code",
    "common_state_fips_code",
    "primary_state_fips_code",
    "state_fips_code",
    "state_fips",
    "statefips",
    "stfips",
    "state_code",
    "statefp",
    "st",
)
SCORE_KEYS = ("hpsa_score", "score", "hpsascore")
STATUS_KEYS = (
    "designation_status",
    "status",
    "desig_status",
    "hpsa status",
    "hpsa_status",
)
STATUS_CODE_KEYS = ("hpsa status code", "hpsa_status_code", "status code", "status_code")
POPULATION_KEYS = (
    "hpsa designation population",
    "hpsa_designation_population",
    "designated_population",
    "population",
    "pop",
    "designated_pop",
)
GEO_DESCRIPTION_KEYS = (
    "geo_description",
    "geodescription",
    "hpsa name",
    "common county name",
    "hpsa_name",
    "hpsa_name_or_description",
    "name",
)

COVERAGE_POP_AGGREGATION_METHOD = "MAX"
COVERAGE_OVERLAP_CAVEAT = (
    "HPSA designated populations may overlap across partial-county, population-group, and "
    "facility designations. Population covered is aggregated conservatively using MAX to reduce "
    "double counting; coverage_pct should be interpreted as an approximate upper-bound proxy for "
    "coverage within the county."
)
COVERAGE_PCT_DEFINITION = (
    "coverage_pct = (population_covered / population_denominator) * 100, clamped to 0-100; "
    "population_denominator uses adult 18+ when available, otherwise total population."
)
COVERAGE_METHOD_TEXT = (
    "MAX designated population among active designations in county (conservative; overlaps possible)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest HRSA HPSA Data Mart files.")
    parser.add_argument("--pc", default=DEFAULT_PC_PATH, help=f"Path to PC CSV (default: {DEFAULT_PC_PATH})")
    parser.add_argument("--mh", default=DEFAULT_MH_PATH, help=f"Path to MH CSV (default: {DEFAULT_MH_PATH})")
    parser.add_argument("--dh", default=DEFAULT_DH_PATH, help=f"Path to DH CSV (default: {DEFAULT_DH_PATH})")
    parser.add_argument(
        "--db-url",
        default=os.getenv("DATABASE_URL", DEFAULT_DB_URL),
        help="Database URL (default: DATABASE_URL env or local default).",
    )
    parser.add_argument(
        "--truncate-staging",
        action="store_true",
        help="Truncate hpsa_designations_raw before loading this run.",
    )
    parser.add_argument(
        "--rebuild-summary",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Rebuild county_hpsa_summary after staging load (default: true).",
    )
    return parser.parse_args()


def normalize_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(key or "").strip().lower())


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def digits_only(value: Any) -> str:
    return re.sub(r"[^0-9]", "", str(value or ""))


def parse_int(value: Any) -> int | None:
    text_value = normalize_text(value)
    if text_value is None:
        return None
    compact = text_value.replace(",", "")
    if re.fullmatch(r"-?\d+", compact):
        return int(compact)
    try:
        as_float = float(compact)
    except ValueError:
        return None
    if not math.isfinite(as_float):
        return None
    return int(as_float)


def first_present(normalized_row: dict[str, Any], candidates: Iterable[str]) -> str | None:
    for candidate in candidates:
        value = normalize_text(normalized_row.get(normalize_key(candidate)))
        if value is not None:
            return value
    return None


def normalize_state_fips(value: Any) -> str | None:
    raw_digits = digits_only(value)
    if not raw_digits:
        return None
    if len(raw_digits) == 1:
        return raw_digits.zfill(2)
    return raw_digits[:2]


def extract_state_fips(normalized_row: dict[str, Any]) -> str | None:
    direct = first_present(normalized_row, STATE_FIPS_KEYS)
    if direct is not None:
        normalized = normalize_state_fips(direct)
        if normalized is not None:
            return normalized

    county_fips_candidate = first_present(normalized_row, COUNTY_FIPS_KEYS)
    county_digits = digits_only(county_fips_candidate)
    if len(county_digits) == 5:
        return county_digits[:2]
    return None


def normalize_county_fips(value: Any, *, state_fips: str | None) -> str | None:
    raw_digits = digits_only(value)
    if not raw_digits:
        return None
    if len(raw_digits) == 5:
        return raw_digits
    if len(raw_digits) == 3 and state_fips is not None:
        return f"{state_fips}{raw_digits.zfill(3)}"
    return None


def extract_county_fips(normalized_row: dict[str, Any], *, state_fips: str | None) -> str | None:
    direct = first_present(normalized_row, COUNTY_FIPS_KEYS)
    county_fips = normalize_county_fips(direct, state_fips=state_fips)
    if county_fips is not None and len(county_fips) == 5:
        return county_fips

    county3 = first_present(normalized_row, COUNTY_FIPS3_KEYS)
    county3_digits = digits_only(county3)
    if county3_digits and len(county3_digits) <= 3 and state_fips is not None:
        return f"{state_fips}{county3_digits.zfill(3)}"
    return None


def canonical_row_hash(designation_type: str, cleaned_row: dict[str, Any]) -> str:
    payload = {"designation_type": designation_type, "row": cleaned_row}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def ensure_required_tables(engine) -> None:
    with engine.begin() as conn:
        for table_name in (
            "hpsa_designations_raw",
            "county_hpsa_summary",
            "hpsa_domain_quartiles",
            "v_county_population",
        ):
            exists = conn.execute(
                text("SELECT to_regclass(:name)"),
                {"name": f"public.{table_name}"},
            ).scalar()
            if exists is None:
                raise RuntimeError(
                    f"Required table is missing: {table_name}. Run alembic upgrade head first."
                )


def ensure_temp_table(cursor) -> None:
    cursor.execute(
        """
        CREATE TEMP TABLE IF NOT EXISTS hpsa_designations_raw_load (
            designation_type text NOT NULL,
            load_batch_id uuid NOT NULL,
            source_file text NULL,
            row_hash text NOT NULL,
            county_fips text NULL,
            state_fips text NULL,
            hpsa_score int NULL,
            designation_status text NULL,
            designated_population int NULL,
            geo_description text NULL,
            data jsonb NOT NULL
        ) ON COMMIT PRESERVE ROWS
        """
    )


def flush_batch(cursor, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    with cursor.copy(
        """
        COPY hpsa_designations_raw_load (
            designation_type,
            load_batch_id,
            source_file,
            row_hash,
            county_fips,
            state_fips,
            hpsa_score,
            designation_status,
            designated_population,
            geo_description,
            data
        ) FROM STDIN
        """
    ) as copy:
        for record in records:
            copy.write_row(
                (
                    record["designation_type"],
                    record["load_batch_id"],
                    record["source_file"],
                    record["row_hash"],
                    record["county_fips"],
                    record["state_fips"],
                    record["hpsa_score"],
                    record["designation_status"],
                    record["designated_population"],
                    record["geo_description"],
                    json.dumps(record["data"], sort_keys=True, ensure_ascii=False),
                )
            )

    cursor.execute(
        """
        INSERT INTO hpsa_designations_raw (
            designation_type,
            load_batch_id,
            source_file,
            row_hash,
            county_fips,
            state_fips,
            hpsa_score,
            designation_status,
            designated_population,
            geo_description,
            data
        )
        SELECT
            designation_type,
            load_batch_id,
            source_file,
            row_hash,
            county_fips,
            state_fips,
            hpsa_score,
            designation_status,
            designated_population,
            geo_description,
            data
        FROM hpsa_designations_raw_load
        ON CONFLICT (load_batch_id, row_hash) DO NOTHING
        """
    )
    cursor.execute("TRUNCATE TABLE hpsa_designations_raw_load")


def normalize_row(
    *,
    designation_type: str,
    source_file: str,
    load_batch_id: str,
    row: dict[str, Any],
) -> dict[str, Any]:
    cleaned_row: dict[str, Any] = {}
    normalized_row: dict[str, Any] = {}
    for key, value in row.items():
        if key is None:
            continue
        clean_key = str(key).strip()
        if not clean_key:
            continue
        clean_value = normalize_text(value)
        cleaned_row[clean_key] = clean_value
        normalized_row[normalize_key(clean_key)] = clean_value

    state_fips = extract_state_fips(normalized_row)
    county_fips = extract_county_fips(normalized_row, state_fips=state_fips)
    if county_fips is not None and state_fips is None:
        state_fips = county_fips[:2]

    hpsa_score = parse_int(first_present(normalized_row, SCORE_KEYS))
    designation_status = normalize_text(first_present(normalized_row, STATUS_KEYS))
    if designation_status is None:
        designation_status = normalize_text(first_present(normalized_row, STATUS_CODE_KEYS))
    designated_population = parse_int(first_present(normalized_row, POPULATION_KEYS))
    geo_description = normalize_text(first_present(normalized_row, GEO_DESCRIPTION_KEYS))

    return {
        "designation_type": designation_type,
        "load_batch_id": load_batch_id,
        "source_file": source_file,
        "row_hash": canonical_row_hash(designation_type, cleaned_row),
        "county_fips": county_fips,
        "state_fips": state_fips,
        "hpsa_score": hpsa_score,
        "designation_status": designation_status,
        "designated_population": designated_population,
        "geo_description": geo_description,
        "data": cleaned_row,
    }


def ingest_file(
    *,
    engine,
    csv_path: Path,
    designation_type: str,
    load_batch_id: str,
) -> int:
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing CSV file: {csv_path}")

    rows_seen = 0
    buffer: list[dict[str, Any]] = []
    raw_conn = engine.raw_connection()
    try:
        cursor = raw_conn.cursor()
        ensure_temp_table(cursor)

        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise RuntimeError(f"CSV has no headers: {csv_path}")

            for row in reader:
                rows_seen += 1
                buffer.append(
                    normalize_row(
                        designation_type=designation_type,
                        source_file=str(csv_path),
                        load_batch_id=load_batch_id,
                        row=row,
                    )
                )
                if len(buffer) >= BATCH_SIZE:
                    flush_batch(cursor, buffer)
                    raw_conn.commit()
                    buffer.clear()

            if buffer:
                flush_batch(cursor, buffer)
                raw_conn.commit()
                buffer.clear()
    finally:
        raw_conn.close()

    print(f"[load] type={designation_type} rows_read={rows_seen} file={csv_path}")
    return rows_seen


def rebuild_summary(engine, *, load_batch_id: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE county_hpsa_summary"))
        conn.execute(
            text(
                """
                WITH eligible AS (
                    SELECT
                        county_fips,
                        state_fips,
                        designation_type,
                        hpsa_score,
                        designated_population,
                        lower(coalesce(designation_status, '')) AS status_norm
                    FROM hpsa_designations_raw
                    WHERE county_fips IS NOT NULL
                      AND county_fips ~ '^[0-9]{5}$'
                      AND designation_type IN ('pc', 'mh', 'dh')
                      AND load_batch_id = :load_batch_id
                ),
                filtered AS (
                    SELECT
                        county_fips,
                        MAX(state_fips) AS state_fips,
                        designation_type,
                        MAX(hpsa_score) AS score_max,
                        MAX(designated_population) AS pop_cov,
                        COUNT(*)::integer AS raw_rows_count
                    FROM eligible
                    WHERE status_norm LIKE '%designat%'
                      AND status_norm NOT LIKE '%withdraw%'
                      AND status_norm NOT LIKE '%propos%'
                      AND status_norm NOT LIKE '%not designat%'
                      AND status_norm NOT LIKE '%de-designat%'
                      AND status_norm NOT IN ('w', 'p')
                    GROUP BY county_fips, designation_type
                ),
                pivoted AS (
                    SELECT
                        county_fips,
                        MAX(state_fips) AS state_fips,
                        BOOL_OR(designation_type = 'pc') AS pc_designated,
                        MAX(score_max) FILTER (WHERE designation_type = 'pc') AS pc_hpsa_score_max,
                        MAX(pop_cov) FILTER (WHERE designation_type = 'pc') AS pc_population_covered,
                        MAX(raw_rows_count) FILTER (WHERE designation_type = 'pc') AS raw_rows_in_county_pc,
                        BOOL_OR(designation_type = 'mh') AS mh_designated,
                        MAX(score_max) FILTER (WHERE designation_type = 'mh') AS mh_hpsa_score_max,
                        MAX(pop_cov) FILTER (WHERE designation_type = 'mh') AS mh_population_covered,
                        MAX(raw_rows_count) FILTER (WHERE designation_type = 'mh') AS raw_rows_in_county_mh,
                        BOOL_OR(designation_type = 'dh') AS dh_designated,
                        MAX(score_max) FILTER (WHERE designation_type = 'dh') AS dh_hpsa_score_max,
                        MAX(pop_cov) FILTER (WHERE designation_type = 'dh') AS dh_population_covered,
                        MAX(raw_rows_count) FILTER (WHERE designation_type = 'dh') AS raw_rows_in_county_dh
                    FROM filtered
                    GROUP BY county_fips
                ),
                with_pop AS (
                    SELECT
                        p.*,
                        cp.population_adult_18p,
                        cp.population_total,
                        CASE
                            WHEN cp.population_adult_18p IS NOT NULL AND cp.population_adult_18p > 0 THEN 'adult_18p'
                            WHEN cp.population_total IS NOT NULL AND cp.population_total > 0 THEN 'total'
                            ELSE NULL
                        END AS population_denominator_type,
                        CASE
                            WHEN cp.population_adult_18p IS NOT NULL AND cp.population_adult_18p > 0 THEN cp.population_adult_18p::integer
                            WHEN cp.population_total IS NOT NULL AND cp.population_total > 0 THEN cp.population_total::integer
                            ELSE NULL
                        END AS population_denominator,
                        CASE
                            WHEN cp.population_adult_18p IS NOT NULL AND cp.population_adult_18p > 0 THEN 'dim_county_total_pop_18_plus'
                            WHEN cp.population_total IS NOT NULL AND cp.population_total > 0 THEN 'dim_county_total_population'
                            ELSE NULL
                        END AS population_denominator_source
                    FROM pivoted AS p
                    LEFT JOIN v_county_population AS cp
                        ON cp.county_fips = p.county_fips
                )
                INSERT INTO county_hpsa_summary (
                    county_fips,
                    state_fips,
                    pc_designated,
                    pc_hpsa_score_max,
                    pc_population_covered,
                    pc_coverage_pct,
                    mh_designated,
                    mh_hpsa_score_max,
                    mh_population_covered,
                    mh_coverage_pct,
                    dh_designated,
                    dh_hpsa_score_max,
                    dh_population_covered,
                    dh_coverage_pct,
                    population_denominator_type,
                    population_denominator,
                    population_denominator_source,
                    coverage_population_aggregation_method,
                    coverage_overlap_caveat,
                    coverage_pct_definition,
                    pc_coverage_method,
                    mh_coverage_method,
                    dh_coverage_method,
                    raw_rows_in_county_pc,
                    raw_rows_in_county_mh,
                    raw_rows_in_county_dh,
                    as_of_date,
                    updated_at
                )
                SELECT
                    county_fips,
                    state_fips,
                    pc_designated,
                    pc_hpsa_score_max,
                    pc_population_covered,
                    CASE
                        WHEN population_denominator IS NULL
                            OR population_denominator <= 0
                            OR pc_population_covered IS NULL THEN NULL
                        ELSE LEAST(
                            100.000::numeric(6,3),
                            GREATEST(
                                0::numeric,
                                ROUND((pc_population_covered::numeric / population_denominator::numeric) * 100.0, 3)
                            )
                        )
                    END AS pc_coverage_pct,
                    mh_designated,
                    mh_hpsa_score_max,
                    mh_population_covered,
                    CASE
                        WHEN population_denominator IS NULL
                            OR population_denominator <= 0
                            OR mh_population_covered IS NULL THEN NULL
                        ELSE LEAST(
                            100.000::numeric(6,3),
                            GREATEST(
                                0::numeric,
                                ROUND((mh_population_covered::numeric / population_denominator::numeric) * 100.0, 3)
                            )
                        )
                    END AS mh_coverage_pct,
                    dh_designated,
                    dh_hpsa_score_max,
                    dh_population_covered,
                    CASE
                        WHEN population_denominator IS NULL
                            OR population_denominator <= 0
                            OR dh_population_covered IS NULL THEN NULL
                        ELSE LEAST(
                            100.000::numeric(6,3),
                            GREATEST(
                                0::numeric,
                                ROUND((dh_population_covered::numeric / population_denominator::numeric) * 100.0, 3)
                            )
                        )
                    END AS dh_coverage_pct,
                    population_denominator_type,
                    population_denominator,
                    population_denominator_source,
                    :coverage_population_aggregation_method AS coverage_population_aggregation_method,
                    :coverage_overlap_caveat AS coverage_overlap_caveat,
                    :coverage_pct_definition AS coverage_pct_definition,
                    :coverage_method_text AS pc_coverage_method,
                    :coverage_method_text AS mh_coverage_method,
                    :coverage_method_text AS dh_coverage_method,
                    raw_rows_in_county_pc,
                    raw_rows_in_county_mh,
                    raw_rows_in_county_dh,
                    CURRENT_DATE AS as_of_date,
                    now() AS updated_at
                FROM with_pop
                """
            ),
            {
                "load_batch_id": load_batch_id,
                "coverage_population_aggregation_method": COVERAGE_POP_AGGREGATION_METHOD,
                "coverage_overlap_caveat": COVERAGE_OVERLAP_CAVEAT,
                "coverage_pct_definition": COVERAGE_PCT_DEFINITION,
                "coverage_method_text": COVERAGE_METHOD_TEXT,
            },
        )
        conn.execute(
            text(
                """
                WITH domains AS (
                    SELECT 'pc'::text AS domain
                    UNION ALL SELECT 'mh'::text
                    UNION ALL SELECT 'dh'::text
                ),
                scored AS (
                    SELECT
                        d.domain,
                        CASE d.domain
                            WHEN 'pc' THEN s.pc_designated
                            WHEN 'mh' THEN s.mh_designated
                            WHEN 'dh' THEN s.dh_designated
                            ELSE FALSE
                        END AS designated,
                        CASE d.domain
                            WHEN 'pc' THEN s.pc_hpsa_score_max::numeric
                            WHEN 'mh' THEN s.mh_hpsa_score_max::numeric
                            WHEN 'dh' THEN s.dh_hpsa_score_max::numeric
                            ELSE NULL
                        END AS score
                    FROM county_hpsa_summary AS s
                    CROSS JOIN domains AS d
                ),
                eligible AS (
                    SELECT domain, score
                    FROM scored
                    WHERE designated IS TRUE
                      AND score IS NOT NULL
                ),
                quartiles AS (
                    SELECT
                        d.domain,
                        percentile_cont(0.25) WITHIN GROUP (ORDER BY e.score) AS q25,
                        percentile_cont(0.50) WITHIN GROUP (ORDER BY e.score) AS q50,
                        percentile_cont(0.75) WITHIN GROUP (ORDER BY e.score) AS q75,
                        COUNT(e.score)::integer AS n_counties
                    FROM domains AS d
                    LEFT JOIN eligible AS e
                        ON e.domain = d.domain
                    GROUP BY d.domain
                ),
                summary_as_of AS (
                    SELECT COALESCE(MAX(as_of_date), CURRENT_DATE) AS as_of_date
                    FROM county_hpsa_summary
                )
                INSERT INTO hpsa_domain_quartiles (
                    domain,
                    q25,
                    q50,
                    q75,
                    n_counties,
                    as_of_date,
                    updated_at
                )
                SELECT
                    q.domain,
                    q.q25,
                    q.q50,
                    q.q75,
                    q.n_counties,
                    a.as_of_date,
                    now() AS updated_at
                FROM quartiles AS q
                CROSS JOIN summary_as_of AS a
                ON CONFLICT (domain) DO UPDATE
                SET
                    q25 = EXCLUDED.q25,
                    q50 = EXCLUDED.q50,
                    q75 = EXCLUDED.q75,
                    n_counties = EXCLUDED.n_counties,
                    as_of_date = EXCLUDED.as_of_date,
                    updated_at = EXCLUDED.updated_at
                """
            )
        )


def print_verification(engine, load_batch_id: str) -> None:
    with engine.begin() as conn:
        rows_by_type = conn.execute(
            text(
                """
                SELECT designation_type, COUNT(*) AS row_count
                FROM hpsa_designations_raw
                WHERE load_batch_id = :load_batch_id
                GROUP BY designation_type
                ORDER BY designation_type
                """
            ),
            {"load_batch_id": load_batch_id},
        ).mappings().all()

        summary_stats = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) AS total_counties,
                    COUNT(*) FILTER (WHERE pc_designated) AS counties_pc_designated,
                    COUNT(*) FILTER (WHERE mh_designated) AS counties_mh_designated,
                    COUNT(*) FILTER (WHERE dh_designated) AS counties_dh_designated,
                    COUNT(*) FILTER (WHERE population_denominator IS NOT NULL) AS counties_with_denominator,
                    COUNT(*) FILTER (
                        WHERE population_denominator IS NOT NULL
                          AND population_denominator_source IS NULL
                    ) AS counties_missing_denominator_source,
                    COUNT(*) FILTER (
                        WHERE county_fips IS NULL
                           OR char_length(county_fips) <> 5
                    ) AS invalid_county_fips
                FROM county_hpsa_summary
                """
            )
        ).mappings().one()

        pct_stats = conn.execute(
            text(
                """
                SELECT
                    MIN(pc_coverage_pct) FILTER (WHERE pc_coverage_pct IS NOT NULL) AS pc_min,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY pc_coverage_pct) AS pc_median,
                    MAX(pc_coverage_pct) FILTER (WHERE pc_coverage_pct IS NOT NULL) AS pc_max,
                    MIN(mh_coverage_pct) FILTER (WHERE mh_coverage_pct IS NOT NULL) AS mh_min,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY mh_coverage_pct) AS mh_median,
                    MAX(mh_coverage_pct) FILTER (WHERE mh_coverage_pct IS NOT NULL) AS mh_max,
                    MIN(dh_coverage_pct) FILTER (WHERE dh_coverage_pct IS NOT NULL) AS dh_min,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY dh_coverage_pct) AS dh_median,
                    MAX(dh_coverage_pct) FILTER (WHERE dh_coverage_pct IS NOT NULL) AS dh_max,
                    COUNT(*) FILTER (
                        WHERE population_denominator > 0
                          AND pc_population_covered IS NOT NULL
                          AND ((pc_population_covered::numeric / population_denominator::numeric) * 100.0) > 100.0
                    ) AS pc_gt_100_preclamp,
                    COUNT(*) FILTER (
                        WHERE population_denominator > 0
                          AND mh_population_covered IS NOT NULL
                          AND ((mh_population_covered::numeric / population_denominator::numeric) * 100.0) > 100.0
                    ) AS mh_gt_100_preclamp,
                    COUNT(*) FILTER (
                        WHERE population_denominator > 0
                          AND dh_population_covered IS NOT NULL
                          AND ((dh_population_covered::numeric / population_denominator::numeric) * 100.0) > 100.0
                    ) AS dh_gt_100_preclamp
                FROM county_hpsa_summary
                """
            )
        ).mappings().one()

        method_defaults = conn.execute(
            text(
                """
                SELECT
                    COUNT(*) FILTER (
                        WHERE coverage_population_aggregation_method = :coverage_population_aggregation_method
                    ) AS rows_with_expected_aggregation_method,
                    COUNT(*) FILTER (
                        WHERE coverage_overlap_caveat = :coverage_overlap_caveat
                    ) AS rows_with_expected_overlap_caveat,
                    COUNT(*) FILTER (
                        WHERE coverage_pct_definition = :coverage_pct_definition
                    ) AS rows_with_expected_pct_definition
                FROM county_hpsa_summary
                """
            ),
            {
                "coverage_population_aggregation_method": COVERAGE_POP_AGGREGATION_METHOD,
                "coverage_overlap_caveat": COVERAGE_OVERLAP_CAVEAT,
                "coverage_pct_definition": COVERAGE_PCT_DEFINITION,
            },
        ).mappings().one()

        raw_rows_stats = conn.execute(
            text(
                """
                SELECT
                    MIN(raw_rows_in_county_pc) FILTER (WHERE raw_rows_in_county_pc IS NOT NULL) AS pc_min_raw_rows,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY raw_rows_in_county_pc) AS pc_median_raw_rows,
                    MAX(raw_rows_in_county_pc) FILTER (WHERE raw_rows_in_county_pc IS NOT NULL) AS pc_max_raw_rows,
                    MIN(raw_rows_in_county_mh) FILTER (WHERE raw_rows_in_county_mh IS NOT NULL) AS mh_min_raw_rows,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY raw_rows_in_county_mh) AS mh_median_raw_rows,
                    MAX(raw_rows_in_county_mh) FILTER (WHERE raw_rows_in_county_mh IS NOT NULL) AS mh_max_raw_rows,
                    MIN(raw_rows_in_county_dh) FILTER (WHERE raw_rows_in_county_dh IS NOT NULL) AS dh_min_raw_rows,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY raw_rows_in_county_dh) AS dh_median_raw_rows,
                    MAX(raw_rows_in_county_dh) FILTER (WHERE raw_rows_in_county_dh IS NOT NULL) AS dh_max_raw_rows
                FROM county_hpsa_summary
                """
            )
        ).mappings().one()

        quartiles = conn.execute(
            text(
                """
                SELECT
                    domain,
                    q25,
                    q50,
                    q75,
                    n_counties,
                    as_of_date
                FROM hpsa_domain_quartiles
                ORDER BY domain
                """
            )
        ).mappings().all()

        samples = conn.execute(
            text(
                """
                SELECT
                    county_fips,
                    state_fips,
                    population_denominator_type,
                    population_denominator,
                    population_denominator_source,
                    pc_population_covered,
                    pc_coverage_pct,
                    raw_rows_in_county_pc,
                    mh_population_covered,
                    mh_coverage_pct,
                    raw_rows_in_county_mh,
                    dh_population_covered,
                    dh_coverage_pct,
                    raw_rows_in_county_dh,
                    as_of_date
                FROM county_hpsa_summary
                ORDER BY pc_coverage_pct DESC NULLS LAST, county_fips
                LIMIT 10
                """
            )
        ).mappings().all()

    print("\n[verify] staging rows loaded per type (current batch)")
    if not rows_by_type:
        print("  none")
    for row in rows_by_type:
        print(f"  type={row['designation_type']} rows={row['row_count']}")

    print("\n[verify] summary counts")
    print(f"  total_counties={summary_stats['total_counties']}")
    print(f"  counties_pc_designated={summary_stats['counties_pc_designated']}")
    print(f"  counties_mh_designated={summary_stats['counties_mh_designated']}")
    print(f"  counties_dh_designated={summary_stats['counties_dh_designated']}")
    print(f"  counties_with_denominator={summary_stats['counties_with_denominator']}")
    print(
        "  counties_missing_denominator_source="
        f"{summary_stats['counties_missing_denominator_source']}"
    )
    print(f"  invalid_county_fips_length={summary_stats['invalid_county_fips']}")

    print("\n[verify] method defaults")
    print(
        "  aggregation_method="
        f"{COVERAGE_POP_AGGREGATION_METHOD} "
        f"(rows={method_defaults['rows_with_expected_aggregation_method']})"
    )
    print(
        "  overlap_caveat_populated="
        f"{method_defaults['rows_with_expected_overlap_caveat']}"
    )
    print(
        "  pct_definition_populated="
        f"{method_defaults['rows_with_expected_pct_definition']}"
    )

    print("\n[verify] coverage pct stats (min/median/max)")
    print(
        "  pc_coverage_pct="
        f"{pct_stats['pc_min']} / {pct_stats['pc_median']} / {pct_stats['pc_max']}"
    )
    print(
        "  mh_coverage_pct="
        f"{pct_stats['mh_min']} / {pct_stats['mh_median']} / {pct_stats['mh_max']}"
    )
    print(
        "  dh_coverage_pct="
        f"{pct_stats['dh_min']} / {pct_stats['dh_median']} / {pct_stats['dh_max']}"
    )
    print(
        "  preclamp_gt_100_counts="
        f"pc:{pct_stats['pc_gt_100_preclamp']} "
        f"mh:{pct_stats['mh_gt_100_preclamp']} "
        f"dh:{pct_stats['dh_gt_100_preclamp']}"
    )

    print("\n[verify] raw rows per county/type stats (min/median/max)")
    print(
        "  raw_rows_in_county_pc="
        f"{raw_rows_stats['pc_min_raw_rows']} / "
        f"{raw_rows_stats['pc_median_raw_rows']} / {raw_rows_stats['pc_max_raw_rows']}"
    )
    print(
        "  raw_rows_in_county_mh="
        f"{raw_rows_stats['mh_min_raw_rows']} / "
        f"{raw_rows_stats['mh_median_raw_rows']} / {raw_rows_stats['mh_max_raw_rows']}"
    )
    print(
        "  raw_rows_in_county_dh="
        f"{raw_rows_stats['dh_min_raw_rows']} / "
        f"{raw_rows_stats['dh_median_raw_rows']} / {raw_rows_stats['dh_max_raw_rows']}"
    )

    print("\n[verify] quartiles by domain")
    if not quartiles:
        print("  none")
    for row in quartiles:
        print(
            f"  {row['domain']}: q25={row['q25']} q50={row['q50']} "
            f"q75={row['q75']} n={row['n_counties']} as_of={row['as_of_date']}"
        )

    print("\n[verify] sample top 10 by pc_coverage_pct")
    for row in samples:
        print(dict(row))


def main() -> None:
    args = parse_args()

    source_files = {
        "pc": Path(args.pc).expanduser().resolve(),
        "mh": Path(args.mh).expanduser().resolve(),
        "dh": Path(args.dh).expanduser().resolve(),
    }

    engine = create_engine(args.db_url, future=True)
    ensure_required_tables(engine)

    load_batch_id = str(uuid.uuid4())
    print(f"[run] load_batch_id={load_batch_id}")
    print(f"[run] db_url={args.db_url}")

    if args.truncate_staging:
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE hpsa_designations_raw"))
        print("[run] truncated hpsa_designations_raw")

    rows_seen_total = 0
    for designation_type, file_path in source_files.items():
        rows_seen_total += ingest_file(
            engine=engine,
            csv_path=file_path,
            designation_type=designation_type,
            load_batch_id=load_batch_id,
        )

    if args.rebuild_summary:
        rebuild_summary(engine, load_batch_id=load_batch_id)
        print("[run] rebuilt county_hpsa_summary")
    else:
        print("[run] skipped summary rebuild (--no-rebuild-summary)")

    print(f"[run] total_rows_read={rows_seen_total}")
    print_verification(engine, load_batch_id=load_batch_id)


if __name__ == "__main__":
    main()
