#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.db_fqtn import cdc_funding_table  # noqa: E402
from app.db_schemas import CDC_FUNDING_SCHEMA  # noqa: E402
from app.funding.classification import classify_funding_row  # noqa: E402

DEFAULT_DB_URL = "postgresql+psycopg://places:places@localhost:5432/places"
DEFAULT_BASE_DIR = REPO_ROOT / "data" / "usaspending" / "chipfunding"
DEFAULT_PROFILE_PATH = BACKEND_ROOT / "data_profiles" / "usaspending_funding_file_profile.json"
DEFAULT_CHUNK_SIZE = 10_000
DB_UPSERT_BATCH_SIZE = 500

FILE_TYPE_ASSISTANCE_PRIME = "assistance_prime_transactions"
FILE_TYPE_ASSISTANCE_SUBAWARDS = "assistance_subawards"
FILE_TYPE_CONTRACTS_PRIME = "contracts_prime_transactions"
FILE_TYPE_CONTRACTS_SUBAWARDS = "contracts_subawards"
PRIME_FILE_TYPES = {FILE_TYPE_ASSISTANCE_PRIME, FILE_TYPE_CONTRACTS_PRIME}

RAW_TABLE_BY_FILE_TYPE = {
    FILE_TYPE_ASSISTANCE_PRIME: "raw_usaspending_assistance_prime_transactions",
    FILE_TYPE_ASSISTANCE_SUBAWARDS: "raw_usaspending_assistance_subawards",
    FILE_TYPE_CONTRACTS_PRIME: "raw_usaspending_contracts_prime_transactions",
    FILE_TYPE_CONTRACTS_SUBAWARDS: "raw_usaspending_contracts_subawards",
}

FUNDING_MECHANISM_BY_FILE_TYPE = {
    FILE_TYPE_ASSISTANCE_PRIME: "grants_cooperative_agreements",
    FILE_TYPE_CONTRACTS_PRIME: "contracts",
}

CDC_FUNDING_AGENCY_NAME = "Department of Health and Human Services"
CDC_FUNDING_SUB_AGENCY_NAME = "Centers for Disease Control and Prevention"

NULL_TOKENS = {"", "na", "n/a", "nan", "none", "null"}


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    token = str(value).strip()
    if token.lower() in NULL_TOKENS:
        return None
    return token or None


def parse_amount(value: Any) -> Decimal | None:
    token = clean_text(value)
    if token is None:
        return None
    negative_parentheses = token.startswith("(") and token.endswith(")")
    token = token.strip("()").replace("$", "").replace(",", "").strip()
    if not token:
        return None
    try:
        amount = Decimal(token)
    except InvalidOperation:
        return None
    return -abs(amount) if negative_parentheses else amount


def parse_int(value: Any) -> int | None:
    token = clean_text(value)
    if token is None:
        return None
    try:
        return int(float(token))
    except ValueError:
        return None


def parse_date(value: Any) -> date | None:
    token = clean_text(value)
    if token is None:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(token, fmt).date()
        except ValueError:
            pass
    parsed = pd.to_datetime(token, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def parse_timestamp(value: Any) -> datetime | None:
    token = clean_text(value)
    if token is None:
        return None
    parsed = pd.to_datetime(token, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime().replace(tzinfo=None)


def normalize_county_fips(value: Any) -> str | None:
    token = clean_text(value)
    if token is None:
        return None
    digits = re.sub(r"[^0-9]", "", token)
    if not digits or len(digits) > 5:
        return None
    return digits.zfill(5)


def normalize_state_code(value: Any) -> str | None:
    token = clean_text(value)
    if token is None:
        return None
    letters = re.sub(r"[^A-Za-z]", "", token).upper()
    if len(letters) == 2:
        return letters
    digits = re.sub(r"[^0-9]", "", token)
    if len(digits) == 2:
        return digits
    return None


def fiscal_year_from_folder(value: str | int | None) -> int | None:
    if value is None:
        return None
    token = str(value).strip().lower()
    match = re.fullmatch(r"fy(\d{2})", token)
    if match:
        return 2000 + int(match.group(1))
    match = re.fullmatch(r"20\d{2}", token)
    if match:
        return int(token)
    match = re.fullmatch(r"\d{2}", token)
    if match:
        return 2000 + int(token)
    return None


def normalize_fiscal_year_arg(value: int) -> int:
    return 2000 + value if 0 <= value < 100 else value


def row_hash(raw_record: dict[str, Any]) -> str:
    payload = json.dumps(raw_record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def is_cdc_funded(raw: dict[str, Any]) -> bool:
    return (
        clean_text(raw.get("funding_agency_name")) == CDC_FUNDING_AGENCY_NAME
        and clean_text(raw.get("funding_sub_agency_name")) == CDC_FUNDING_SUB_AGENCY_NAME
    )


def supplemental_amounts(raw: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, bool]:
    covid = Decimal("0")
    iija = Decimal("0")
    other = Decimal("0")
    for key, value in raw.items():
        lower_key = key.lower()
        if "outlay" in lower_key:
            continue
        if "obligated" not in lower_key and "obligation" not in lower_key:
            continue
        if not any(token in lower_key for token in ("covid", "iija", "supplemental", "emergency")):
            continue
        amount = parse_amount(value) or Decimal("0")
        if "covid" in lower_key:
            covid += amount
        elif "iija" in lower_key:
            iija += amount
        else:
            other += amount
    return covid, iija, other, any(amount > 0 for amount in (covid, iija, other))


def choose_map_geography(raw: dict[str, Any]) -> dict[str, str | None]:
    pop_fips = normalize_county_fips(raw.get("prime_award_transaction_place_of_performance_county_fips_code"))
    recipient_fips = normalize_county_fips(raw.get("prime_award_transaction_recipient_county_fips_code"))

    recipient_state_code = normalize_state_code(raw.get("recipient_state_code"))
    recipient_state_name = clean_text(raw.get("recipient_state_name"))
    pop_state_code = normalize_state_code(raw.get("primary_place_of_performance_state_code"))
    pop_state_name = clean_text(raw.get("primary_place_of_performance_state_name"))

    if pop_fips:
        return {
            "map_geography_source": "place_of_performance",
            "map_county_fips": pop_fips,
            "map_county_name": clean_text(raw.get("primary_place_of_performance_county_name")),
            "map_state_code": pop_state_code or pop_fips[:2],
            "map_state_name": pop_state_name,
        }
    if recipient_fips:
        return {
            "map_geography_source": "recipient_fallback",
            "map_county_fips": recipient_fips,
            "map_county_name": clean_text(raw.get("recipient_county_name")),
            "map_state_code": recipient_state_code or recipient_fips[:2],
            "map_state_name": recipient_state_name,
        }
    return {
        "map_geography_source": "unmapped",
        "map_county_fips": None,
        "map_county_name": None,
        "map_state_code": recipient_state_code or pop_state_code,
        "map_state_name": recipient_state_name or pop_state_name,
    }


def skip_reasons(
    *,
    is_prime_award: bool,
    is_positive_obligation: bool,
    is_cdc: bool,
    is_supplemental: bool,
    map_county_fips: str | None,
) -> str | None:
    reasons: list[str] = []
    if not is_prime_award:
        reasons.append("not_prime_award")
    if not is_positive_obligation:
        reasons.append("non_positive_obligation")
    if not is_cdc:
        reasons.append("not_cdc_funded")
    if is_supplemental:
        reasons.append("covid_or_emergency_supplemental")
    if map_county_fips is None:
        reasons.append("unmapped_county")
    return ";".join(reasons) if reasons else None


def default_map_eligible(
    *,
    is_prime_award: bool,
    is_positive_obligation: bool,
    is_cdc: bool,
    is_supplemental: bool,
    map_county_fips: str | None,
) -> bool:
    return (
        is_prime_award
        and is_positive_obligation
        and is_cdc
        and not is_supplemental
        and map_county_fips is not None
    )


def canonicalize_prime_row(raw_row: dict[str, Any], raw_meta: dict[str, Any]) -> dict[str, Any]:
    file_type = raw_meta["source_file_type"]
    funding_mechanism = FUNDING_MECHANISM_BY_FILE_TYPE[file_type]
    federal_action_obligation = parse_amount(raw_row.get("federal_action_obligation"))
    is_positive = bool(federal_action_obligation is not None and federal_action_obligation > 0)
    cdc_funded = is_cdc_funded(raw_row)
    covid_amount, iija_amount, other_supp_amount, is_supplemental = supplemental_amounts(raw_row)
    geography = choose_map_geography(raw_row)
    is_prime_award = True
    eligible = default_map_eligible(
        is_prime_award=is_prime_award,
        is_positive_obligation=is_positive,
        is_cdc=cdc_funded,
        is_supplemental=is_supplemental,
        map_county_fips=geography["map_county_fips"],
    )
    classification = classify_funding_row(
        {
            **raw_row,
            "source_fiscal_year": raw_meta["source_fiscal_year"],
            "funding_mechanism": funding_mechanism,
        }
    )

    is_assistance = file_type == FILE_TYPE_ASSISTANCE_PRIME
    return {
        "source_raw_table": raw_meta["source_raw_table"],
        "source_raw_id": raw_meta["source_raw_id"],
        "source_fiscal_year": raw_meta["source_fiscal_year"],
        "source_file_type": file_type,
        "source_file_name": raw_meta["source_file_name"],
        "source_row_number": raw_meta["source_row_number"],
        "row_hash": raw_meta["row_hash"],
        "funding_mechanism": funding_mechanism,
        "transaction_unique_key": clean_text(
            raw_row.get("assistance_transaction_unique_key" if is_assistance else "contract_transaction_unique_key")
        ),
        "award_unique_key": clean_text(
            raw_row.get("assistance_award_unique_key" if is_assistance else "contract_award_unique_key")
        ),
        "generated_unique_award_id": clean_text(raw_row.get("generated_unique_award_id")),
        "award_id_piid": clean_text(raw_row.get("award_id_piid")),
        "parent_award_id": clean_text(raw_row.get("parent_award_id_piid")),
        "modification_number": clean_text(raw_row.get("modification_number")),
        "federal_action_obligation": federal_action_obligation,
        "action_date": parse_date(raw_row.get("action_date")),
        "action_date_fiscal_year": parse_int(raw_row.get("action_date_fiscal_year")),
        "funding_agency_name": clean_text(raw_row.get("funding_agency_name")),
        "funding_sub_agency_name": clean_text(raw_row.get("funding_sub_agency_name")),
        "funding_office_name": clean_text(raw_row.get("funding_office_name")),
        "awarding_agency_name": clean_text(raw_row.get("awarding_agency_name")),
        "awarding_sub_agency_name": clean_text(raw_row.get("awarding_sub_agency_name")),
        "awarding_office_name": clean_text(raw_row.get("awarding_office_name")),
        "recipient_uei": clean_text(raw_row.get("recipient_uei")),
        "recipient_name": clean_text(raw_row.get("recipient_name")),
        "recipient_parent_uei": clean_text(raw_row.get("recipient_parent_uei")),
        "recipient_parent_name": clean_text(raw_row.get("recipient_parent_name")),
        "recipient_country_code": clean_text(raw_row.get("recipient_country_code")),
        "recipient_state_code": normalize_state_code(raw_row.get("recipient_state_code")),
        "recipient_state_name": clean_text(raw_row.get("recipient_state_name")),
        "recipient_county_name": clean_text(raw_row.get("recipient_county_name")),
        "recipient_county_fips": normalize_county_fips(
            raw_row.get("prime_award_transaction_recipient_county_fips_code")
        ),
        "recipient_zip": clean_text(raw_row.get("recipient_zip_code") or raw_row.get("recipient_zip_4_code")),
        "pop_country_code": clean_text(raw_row.get("primary_place_of_performance_country_code")),
        "pop_state_code": normalize_state_code(raw_row.get("primary_place_of_performance_state_code"))
        or clean_text(raw_row.get("prime_award_transaction_place_of_performance_state_fips_code")),
        "pop_state_name": clean_text(raw_row.get("primary_place_of_performance_state_name")),
        "pop_county_name": clean_text(raw_row.get("primary_place_of_performance_county_name")),
        "pop_county_fips": normalize_county_fips(
            raw_row.get("prime_award_transaction_place_of_performance_county_fips_code")
        ),
        "pop_zip": clean_text(raw_row.get("primary_place_of_performance_zip_4")),
        **geography,
        "federal_accounts_funding_this_award": clean_text(raw_row.get("federal_accounts_funding_this_award")),
        "treasury_accounts_funding_this_award": clean_text(raw_row.get("treasury_accounts_funding_this_award")),
        "object_classes_funding_this_award": clean_text(raw_row.get("object_classes_funding_this_award")),
        "program_activities_funding_this_award": clean_text(raw_row.get("program_activities_funding_this_award")),
        "assistance_listing_number": clean_text(raw_row.get("cfda_number")),
        "assistance_listing_title": clean_text(raw_row.get("cfda_title")),
        "award_type_code": clean_text(raw_row.get("award_type_code")),
        "award_type_description": clean_text(raw_row.get("award_type")),
        "assistance_type_code": clean_text(raw_row.get("assistance_type_code")),
        "assistance_type_description": clean_text(raw_row.get("assistance_type_description")),
        "naics_code": clean_text(raw_row.get("naics_code")),
        "naics_description": clean_text(raw_row.get("naics_description")),
        "product_or_service_code": clean_text(raw_row.get("product_or_service_code")),
        "product_or_service_code_description": clean_text(raw_row.get("product_or_service_code_description")),
        "national_interest_action_code": clean_text(raw_row.get("national_interest_action_code")),
        "national_interest_action": clean_text(raw_row.get("national_interest_action")),
        "transaction_description": clean_text(raw_row.get("transaction_description")),
        "prime_award_base_transaction_description": clean_text(
            raw_row.get("prime_award_base_transaction_description")
        ),
        "usaspending_permalink": clean_text(raw_row.get("usaspending_permalink")),
        "last_modified_date": parse_timestamp(raw_row.get("last_modified_date")),
        "covid_supplemental_obligated_amount": covid_amount,
        "iija_supplemental_obligated_amount": iija_amount,
        "other_supplemental_obligated_amount": other_supp_amount,
        "is_covid_or_emergency_supplemental": is_supplemental,
        "is_positive_obligation": is_positive,
        "is_cdc_funded": cdc_funded,
        "is_prime_award": is_prime_award,
        "is_default_map_eligible": eligible,
        **classification,
        "skip_reason": skip_reasons(
            is_prime_award=is_prime_award,
            is_positive_obligation=is_positive,
            is_cdc=cdc_funded,
            is_supplemental=is_supplemental,
            map_county_fips=geography["map_county_fips"],
        ),
        "raw_record": raw_row,
    }


def table_definitions() -> tuple[dict[str, sa.Table], sa.Table]:
    metadata = sa.MetaData(schema=CDC_FUNDING_SCHEMA)
    raw_tables = {
        table_name: sa.Table(
            table_name,
            metadata,
            sa.Column("id", sa.BigInteger),
            sa.Column("source_fiscal_year", sa.Integer),
            sa.Column("source_file_type", sa.Text),
            sa.Column("source_file_path", sa.Text),
            sa.Column("source_file_name", sa.Text),
            sa.Column("source_row_number", sa.Integer),
            sa.Column("row_hash", sa.Text),
            sa.Column("raw_record", postgresql.JSONB),
        )
        for table_name in RAW_TABLE_BY_FILE_TYPE.values()
    }
    canonical = sa.Table(
        "fact_cdc_funding_prime_transaction",
        metadata,
        *(sa.Column(name, postgresql.JSONB if name == "raw_record" else sa.Text) for name in ()),
    )
    for column_name, column_type in CANONICAL_COLUMN_TYPES.items():
        canonical.append_column(sa.Column(column_name, column_type))
    canonical.append_column(sa.Column("updated_at", sa.DateTime()))
    return raw_tables, canonical


CANONICAL_COLUMN_TYPES: dict[str, sa.types.TypeEngine] = {
    "source_raw_table": sa.Text(),
    "source_raw_id": sa.BigInteger(),
    "source_fiscal_year": sa.Integer(),
    "source_file_type": sa.Text(),
    "source_file_name": sa.Text(),
    "source_row_number": sa.Integer(),
    "row_hash": sa.Text(),
    "funding_mechanism": sa.Text(),
    "transaction_unique_key": sa.Text(),
    "award_unique_key": sa.Text(),
    "generated_unique_award_id": sa.Text(),
    "award_id_piid": sa.Text(),
    "parent_award_id": sa.Text(),
    "modification_number": sa.Text(),
    "federal_action_obligation": sa.Numeric(),
    "action_date": sa.Date(),
    "action_date_fiscal_year": sa.Integer(),
    "funding_agency_name": sa.Text(),
    "funding_sub_agency_name": sa.Text(),
    "funding_office_name": sa.Text(),
    "awarding_agency_name": sa.Text(),
    "awarding_sub_agency_name": sa.Text(),
    "awarding_office_name": sa.Text(),
    "recipient_uei": sa.Text(),
    "recipient_name": sa.Text(),
    "recipient_parent_uei": sa.Text(),
    "recipient_parent_name": sa.Text(),
    "recipient_country_code": sa.Text(),
    "recipient_state_code": sa.Text(),
    "recipient_state_name": sa.Text(),
    "recipient_county_name": sa.Text(),
    "recipient_county_fips": sa.Text(),
    "recipient_zip": sa.Text(),
    "pop_country_code": sa.Text(),
    "pop_state_code": sa.Text(),
    "pop_state_name": sa.Text(),
    "pop_county_name": sa.Text(),
    "pop_county_fips": sa.Text(),
    "pop_zip": sa.Text(),
    "map_state_code": sa.Text(),
    "map_state_name": sa.Text(),
    "map_county_name": sa.Text(),
    "map_county_fips": sa.Text(),
    "map_geography_source": sa.Text(),
    "federal_accounts_funding_this_award": sa.Text(),
    "treasury_accounts_funding_this_award": sa.Text(),
    "object_classes_funding_this_award": sa.Text(),
    "program_activities_funding_this_award": sa.Text(),
    "assistance_listing_number": sa.Text(),
    "assistance_listing_title": sa.Text(),
    "award_type_code": sa.Text(),
    "award_type_description": sa.Text(),
    "assistance_type_code": sa.Text(),
    "assistance_type_description": sa.Text(),
    "naics_code": sa.Text(),
    "naics_description": sa.Text(),
    "product_or_service_code": sa.Text(),
    "product_or_service_code_description": sa.Text(),
    "national_interest_action_code": sa.Text(),
    "national_interest_action": sa.Text(),
    "transaction_description": sa.Text(),
    "prime_award_base_transaction_description": sa.Text(),
    "usaspending_permalink": sa.Text(),
    "last_modified_date": sa.DateTime(),
    "covid_supplemental_obligated_amount": sa.Numeric(),
    "iija_supplemental_obligated_amount": sa.Numeric(),
    "other_supplemental_obligated_amount": sa.Numeric(),
    "is_covid_or_emergency_supplemental": sa.Boolean(),
    "is_positive_obligation": sa.Boolean(),
    "is_cdc_funded": sa.Boolean(),
    "is_prime_award": sa.Boolean(),
    "is_default_map_eligible": sa.Boolean(),
    "defc_codes": postgresql.JSONB(),
    "defc_classification": sa.Text(),
    "has_defc_q": sa.Boolean(),
    "has_defc_non_q": sa.Boolean(),
    "has_defc_covid": sa.Boolean(),
    "has_defc_arp": sa.Boolean(),
    "has_defc_other_emergency": sa.Boolean(),
    "has_overall_award_supplemental_history": sa.Boolean(),
    "is_likely_vfc": sa.Boolean(),
    "is_covid_era_immunization_response": sa.Boolean(),
    "is_profile_aligned_emergency_supplemental": sa.Boolean(),
    "funding_profiles_comparison_excluded": sa.Boolean(),
    "funding_profiles_exclusion_reason": sa.Text(),
    "skip_reason": sa.Text(),
    "raw_record": postgresql.JSONB(),
}


def dataframe_records(chunk: pd.DataFrame) -> list[dict[str, Any]]:
    normalized = chunk.where(pd.notna(chunk), None)
    records: list[dict[str, Any]] = []
    for row in normalized.to_dict(orient="records"):
        records.append({key: clean_text(value) for key, value in row.items()})
    return records


def raw_rows_for_chunk(
    *,
    records: list[dict[str, Any]],
    source_fiscal_year: int,
    source_file_type: str,
    source_file_path: Path,
    row_offset: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        rows.append(
            {
                "source_fiscal_year": source_fiscal_year,
                "source_file_type": source_file_type,
                "source_file_path": str(source_file_path),
                "source_file_name": source_file_path.name,
                "source_row_number": row_offset + index,
                "row_hash": row_hash(record),
                "raw_record": record,
            }
        )
    return rows


def upsert_raw_rows(
    connection: sa.Connection,
    table: sa.Table,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    returned_rows: list[dict[str, Any]] = []
    for batch_start in range(0, len(rows), DB_UPSERT_BATCH_SIZE):
        batch = rows[batch_start : batch_start + DB_UPSERT_BATCH_SIZE]
        insert_stmt = pg_insert(table).values(batch)
        update_columns = {
            "source_file_path": insert_stmt.excluded.source_file_path,
            "row_hash": insert_stmt.excluded.row_hash,
            "raw_record": insert_stmt.excluded.raw_record,
        }
        stmt = (
            insert_stmt.on_conflict_do_update(
                index_elements=[
                    "source_fiscal_year",
                    "source_file_type",
                    "source_file_name",
                    "source_row_number",
                ],
                set_=update_columns,
            )
            .returning(
                table.c.id,
                table.c.source_fiscal_year,
                table.c.source_file_type,
                table.c.source_file_name,
                table.c.source_row_number,
                table.c.row_hash,
                table.c.raw_record,
            )
        )
        returned_rows.extend(dict(row._mapping) for row in connection.execute(stmt))
    return returned_rows


def upsert_canonical_rows(
    connection: sa.Connection,
    table: sa.Table,
    rows: list[dict[str, Any]],
) -> int:
    if not rows:
        return 0
    row_count = 0
    for batch_start in range(0, len(rows), DB_UPSERT_BATCH_SIZE):
        batch = rows[batch_start : batch_start + DB_UPSERT_BATCH_SIZE]
        insert_stmt = pg_insert(table).values(batch)
        update_columns = {
            key: getattr(insert_stmt.excluded, key)
            for key in CANONICAL_COLUMN_TYPES
            if key not in {"source_raw_table", "source_raw_id"}
        }
        update_columns["updated_at"] = text("now()")
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=["source_raw_table", "source_raw_id"],
            set_=update_columns,
        )
        connection.execute(stmt)
        row_count += len(batch)
    return row_count


def canonical_rows_from_raw_records(
    raw_table_name: str,
    returned_raw_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in returned_raw_rows:
        file_type = raw["source_file_type"]
        if file_type not in PRIME_FILE_TYPES:
            continue
        rows.append(
            canonicalize_prime_row(
                raw["raw_record"],
                {
                    "source_raw_table": raw_table_name,
                    "source_raw_id": raw["id"],
                    "source_fiscal_year": raw["source_fiscal_year"],
                    "source_file_type": raw["source_file_type"],
                    "source_file_name": raw["source_file_name"],
                    "source_row_number": raw["source_row_number"],
                    "row_hash": raw["row_hash"],
                },
            )
        )
    return rows


def load_profile(profile_path: Path) -> dict[str, Any]:
    return json.loads(profile_path.read_text(encoding="utf-8"))


def selected_profile_files(
    profile: dict[str, Any],
    *,
    base_dir: Path,
    fiscal_years: set[int] | None,
) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for file_profile in profile.get("files", []):
        file_type = file_profile.get("inferred_file_type")
        if file_type not in RAW_TABLE_BY_FILE_TYPE:
            continue
        fiscal_year = fiscal_year_from_folder(file_profile.get("inferred_fiscal_year"))
        if fiscal_year is None:
            continue
        if fiscal_years is not None and fiscal_year not in fiscal_years:
            continue
        source_path = Path(file_profile["file_path"])
        if not source_path.exists():
            source_path = base_dir / file_profile["inferred_fiscal_year"] / file_profile["file_name"]
        files.append(
            {
                **file_profile,
                "source_fiscal_year_int": fiscal_year,
                "resolved_path": source_path,
            }
        )
    return sorted(files, key=lambda item: (item["source_fiscal_year_int"], item["inferred_file_type"]))


def delete_existing(
    connection: sa.Connection,
    *,
    fiscal_years: set[int] | None,
    delete_raw: bool,
    delete_canonical: bool,
) -> None:
    year_filter = ""
    params: dict[str, Any] = {}
    if fiscal_years is not None:
        year_filter = " WHERE source_fiscal_year = ANY(:years)"
        params["years"] = sorted(fiscal_years)

    if delete_canonical:
        connection.execute(
            text(f"DELETE FROM {cdc_funding_table('fact_cdc_funding_prime_transaction')}{year_filter}"),
            params,
        )
    if delete_raw:
        for table_name in RAW_TABLE_BY_FILE_TYPE.values():
            connection.execute(text(f"DELETE FROM {cdc_funding_table(table_name)}{year_filter}"), params)


def refresh_aggregate(connection: sa.Connection) -> None:
    connection.execute(text(f"REFRESH MATERIALIZED VIEW {cdc_funding_table('mv_cdc_funding_map_county')}"))
    connection.execute(
        text(f"REFRESH MATERIALIZED VIEW {cdc_funding_table('mv_cdc_funding_map_state_all_positive')}")
    )


def ingest_file(
    connection: sa.Connection,
    *,
    raw_tables: dict[str, sa.Table],
    canonical_table: sa.Table,
    file_profile: dict[str, Any],
    chunk_size: int,
    skip_raw: bool,
    skip_canonical: bool,
) -> dict[str, int]:
    path = Path(file_profile["resolved_path"])
    if not path.exists():
        raise FileNotFoundError(path)

    file_type = file_profile["inferred_file_type"]
    raw_table_name = RAW_TABLE_BY_FILE_TYPE[file_type]
    raw_table = raw_tables[raw_table_name]
    stats = Counter()
    row_offset = 0
    reader = pd.read_csv(path, dtype=str, chunksize=chunk_size, low_memory=False)
    for chunk in reader:
        records = dataframe_records(chunk)
        if skip_raw:
            row_offset += len(records)
            continue
        raw_rows = raw_rows_for_chunk(
            records=records,
            source_fiscal_year=file_profile["source_fiscal_year_int"],
            source_file_type=file_type,
            source_file_path=path,
            row_offset=row_offset,
        )
        returned_raw_rows = upsert_raw_rows(connection, raw_table, raw_rows)
        stats["raw_rows"] += len(returned_raw_rows)
        if not skip_canonical and file_type in PRIME_FILE_TYPES:
            canonical_rows = canonical_rows_from_raw_records(raw_table_name, returned_raw_rows)
            stats["canonical_rows"] += upsert_canonical_rows(connection, canonical_table, canonical_rows)
            for row in canonical_rows:
                stats[f"geo_{row['map_geography_source']}"] += 1
                stats["positive_obligation" if row["is_positive_obligation"] else "non_positive_obligation"] += 1
                stats["cdc_funded" if row["is_cdc_funded"] else "not_cdc_funded"] += 1
                stats["supplemental" if row["is_covid_or_emergency_supplemental"] else "non_supplemental"] += 1
                if row["skip_reason"]:
                    for reason in row["skip_reason"].split(";"):
                        stats[f"skip_{reason}"] += 1
        row_offset += len(records)
    return dict(stats)


def canonicalize_existing_raw(
    connection: sa.Connection,
    *,
    canonical_table: sa.Table,
    fiscal_years: set[int] | None,
    chunk_size: int,
) -> dict[str, int]:
    stats = Counter()
    year_clause = ""
    params: dict[str, Any] = {"limit": chunk_size, "offset": 0}
    if fiscal_years is not None:
        year_clause = "WHERE source_fiscal_year = ANY(:years)"
        params["years"] = sorted(fiscal_years)

    for file_type in PRIME_FILE_TYPES:
        raw_table_name = RAW_TABLE_BY_FILE_TYPE[file_type]
        offset = 0
        while True:
            params["offset"] = offset
            rows = [
                dict(row._mapping)
                for row in connection.execute(
                    text(
                        f"""
                        SELECT
                            id,
                            source_fiscal_year,
                            source_file_type,
                            source_file_name,
                            source_row_number,
                            row_hash,
                            raw_record
                        FROM {cdc_funding_table(raw_table_name)}
                        {year_clause}
                        ORDER BY id
                        LIMIT :limit OFFSET :offset
                        """
                    ),
                    params,
                )
            ]
            if not rows:
                break
            canonical_rows = canonical_rows_from_raw_records(raw_table_name, rows)
            stats["canonical_rows"] += upsert_canonical_rows(connection, canonical_table, canonical_rows)
            offset += len(rows)
    return dict(stats)


def validation_summary(connection: sa.Connection) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    raw_counts: dict[str, list[dict[str, Any]]] = {}
    for file_type, table_name in RAW_TABLE_BY_FILE_TYPE.items():
        raw_counts[file_type] = [
            dict(row._mapping)
            for row in connection.execute(
                text(
                    f"""
                    SELECT source_fiscal_year, source_file_type, COUNT(*)::bigint AS row_count
                    FROM {cdc_funding_table(table_name)}
                    GROUP BY source_fiscal_year, source_file_type
                    ORDER BY source_fiscal_year, source_file_type
                    """
                )
            )
        ]
    summary["raw_row_counts"] = raw_counts
    fact_table = cdc_funding_table("fact_cdc_funding_prime_transaction")
    summary["canonical_row_counts"] = [
        dict(row._mapping)
        for row in connection.execute(
            text(
                f"""
                SELECT source_fiscal_year, funding_mechanism, COUNT(*)::bigint AS row_count
                FROM {fact_table}
                GROUP BY source_fiscal_year, funding_mechanism
                ORDER BY source_fiscal_year, funding_mechanism
                """
            )
        )
    ]
    for name, sql in {
        "positive_obligation_counts": "is_positive_obligation",
        "cdc_funded_counts": "is_cdc_funded",
        "supplemental_counts": "is_covid_or_emergency_supplemental",
    }.items():
        summary[name] = [
            dict(row._mapping)
            for row in connection.execute(
                text(
                    f"""
                    SELECT {sql} AS bucket, COUNT(*)::bigint AS row_count
                    FROM {fact_table}
                    GROUP BY {sql}
                    ORDER BY {sql}
                    """
                )
            )
        ]
    summary["geography_counts"] = [
        dict(row._mapping)
        for row in connection.execute(
            text(
                f"""
                SELECT map_geography_source, COUNT(*)::bigint AS row_count
                FROM {fact_table}
                GROUP BY map_geography_source
                ORDER BY map_geography_source
                """
            )
        )
    ]
    mv_table = cdc_funding_table("mv_cdc_funding_map_county")
    summary["aggregate_row_counts"] = [
        dict(row._mapping)
        for row in connection.execute(
            text(
                f"""
                SELECT source_fiscal_year, funding_mechanism, COUNT(*)::bigint AS row_count
                FROM {mv_table}
                GROUP BY source_fiscal_year, funding_mechanism
                ORDER BY source_fiscal_year, funding_mechanism
                """
            )
        )
    ]
    summary["state_aggregate_row_counts"] = [
        dict(row._mapping)
        for row in connection.execute(
            text(
                f"""
                SELECT source_fiscal_year, funding_mechanism, COUNT(*)::bigint AS row_count
                FROM {cdc_funding_table("mv_cdc_funding_map_state_all_positive")}
                GROUP BY source_fiscal_year, funding_mechanism
                ORDER BY source_fiscal_year, funding_mechanism
                """
            )
        )
    ]
    latest_year = connection.execute(text(f"SELECT MAX(source_fiscal_year) FROM {mv_table}")).scalar()
    summary["latest_fiscal_year"] = latest_year
    if latest_year is not None:
        summary["top_counties_latest_fy"] = [
            dict(row._mapping)
            for row in connection.execute(
                text(
                    f"""
                    SELECT
                        map_state_code,
                        map_county_fips,
                        map_county_name,
                        SUM(total_obligations) AS total_obligations
                    FROM {mv_table}
                    WHERE source_fiscal_year = :latest_year
                    GROUP BY map_state_code, map_county_fips, map_county_name
                    ORDER BY total_obligations DESC NULLS LAST
                    LIMIT 10
                    """
                ),
                {"latest_year": latest_year},
            )
        ]
        summary["top_assistance_listings_latest_fy"] = [
            dict(row._mapping)
            for row in connection.execute(
                text(
                    f"""
                    SELECT
                        assistance_listing_number,
                        assistance_listing_title,
                        SUM(total_obligations) AS total_obligations
                    FROM {mv_table}
                    WHERE source_fiscal_year = :latest_year
                      AND assistance_listing_number IS NOT NULL
                    GROUP BY assistance_listing_number, assistance_listing_title
                    ORDER BY total_obligations DESC NULLS LAST
                    LIMIT 10
                    """
                ),
                {"latest_year": latest_year},
            )
        ]
    return summary


def print_validation(summary: dict[str, Any]) -> None:
    print("\nValidation summary")
    print("Raw row counts:")
    for file_type, rows in summary["raw_row_counts"].items():
        total = sum(row["row_count"] for row in rows)
        print(f"  {file_type}: {total:,}")
    print("Canonical row counts:")
    for row in summary["canonical_row_counts"]:
        print(f"  FY{row['source_fiscal_year']} {row['funding_mechanism']}: {row['row_count']:,}")
    print("Positive obligation counts:")
    for row in summary["positive_obligation_counts"]:
        print(f"  {row['bucket']}: {row['row_count']:,}")
    print("CDC-funded counts:")
    for row in summary["cdc_funded_counts"]:
        print(f"  {row['bucket']}: {row['row_count']:,}")
    print("Geography counts:")
    for row in summary["geography_counts"]:
        print(f"  {row['map_geography_source']}: {row['row_count']:,}")
    print("Supplemental counts:")
    for row in summary["supplemental_counts"]:
        print(f"  {row['bucket']}: {row['row_count']:,}")
    print("Aggregate row counts:")
    for row in summary["aggregate_row_counts"]:
        print(f"  FY{row['source_fiscal_year']} {row['funding_mechanism']}: {row['row_count']:,}")
    print("State aggregate row counts:")
    for row in summary["state_aggregate_row_counts"]:
        print(f"  FY{row['source_fiscal_year']} {row['funding_mechanism']}: {row['row_count']:,}")
    if summary.get("latest_fiscal_year") is not None:
        print(f"Top counties for FY{summary['latest_fiscal_year']}:")
        for row in summary.get("top_counties_latest_fy", []):
            print(f"  {row['map_county_fips']} {row['map_county_name']}: {row['total_obligations']}")
        print(f"Top assistance listings for FY{summary['latest_fiscal_year']}:")
        for row in summary.get("top_assistance_listings_latest_fy", []):
            print(
                f"  {row['assistance_listing_number']} {row['assistance_listing_title']}: "
                f"{row['total_obligations']}"
            )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest USAspending CDC funding rebuild CSVs.")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL", DEFAULT_DB_URL))
    parser.add_argument("--base-dir", type=Path, default=DEFAULT_BASE_DIR)
    parser.add_argument("--profile-path", type=Path, default=DEFAULT_PROFILE_PATH)
    parser.add_argument("--fiscal-year", action="append", type=int, default=[])
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--skip-raw", action="store_true")
    parser.add_argument("--skip-canonical", action="store_true")
    parser.add_argument(
        "--refresh-aggregates",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Refresh county aggregate materialized view after loading (default: true).",
    )
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    args = parse_args(argv)
    selected_years = {normalize_fiscal_year_arg(year) for year in args.fiscal_year} or None
    profile = load_profile(args.profile_path.expanduser().resolve())
    profile_files = selected_profile_files(
        profile,
        base_dir=args.base_dir.expanduser().resolve(),
        fiscal_years=selected_years,
    )
    if not profile_files and not args.skip_raw:
        raise RuntimeError("No USAspending funding files selected for ingestion.")

    engine = sa.create_engine(args.db_url, future=True)
    raw_tables, canonical_table = table_definitions()
    totals = Counter()

    with engine.begin() as connection:
        if args.replace:
            delete_existing(
                connection,
                fiscal_years=selected_years,
                delete_raw=not args.skip_raw,
                delete_canonical=not args.skip_canonical,
            )

        if args.skip_raw and args.skip_canonical:
            print("Skipping raw and canonical load; running aggregate refresh/validation only.", flush=True)
        elif args.skip_raw and not args.skip_canonical:
            totals.update(
                canonicalize_existing_raw(
                    connection,
                    canonical_table=canonical_table,
                    fiscal_years=selected_years,
                    chunk_size=args.chunk_size,
                )
            )
        else:
            for file_profile in profile_files:
                print(
                    f"Loading FY{file_profile['source_fiscal_year_int']} "
                    f"{file_profile['inferred_file_type']} from {file_profile['file_name']}",
                    flush=True,
                )
                file_stats = ingest_file(
                    connection,
                    raw_tables=raw_tables,
                    canonical_table=canonical_table,
                    file_profile=file_profile,
                    chunk_size=args.chunk_size,
                    skip_raw=args.skip_raw,
                    skip_canonical=args.skip_canonical,
                )
                totals.update(file_stats)
                print(
                    f"  raw={file_stats.get('raw_rows', 0):,} "
                    f"canonical={file_stats.get('canonical_rows', 0):,}",
                    flush=True,
                )

        if args.refresh_aggregates:
            refresh_aggregate(connection)

        validation = validation_summary(connection)

    print("\nIngestion totals")
    for key in sorted(totals):
        print(f"  {key}: {totals[key]:,}")
    print_validation(validation)
    return {"totals": dict(totals), "validation": validation}


if __name__ == "__main__":
    main()
