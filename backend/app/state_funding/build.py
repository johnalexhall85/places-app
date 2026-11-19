"""Build the CDC state funding read model from File C and award metadata."""

from __future__ import annotations

import argparse
import json
import logging
import re
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.db import DATABASE_URL
from app.funding_report.keys import nofo_key

LOG = logging.getLogger(__name__)
METHOD = "state-funding-v1"


def clean(value):
    return str(value).strip() if value is not None and str(value).strip() else None


def state_code(value):
    return clean(value).upper() if clean(value) else "__"


def is_state_government(values, *, contract=False):
    """True if any prime says state government, false if primes exist, else unknown."""
    if not values:
        return None
    return any(
        (
            str(value).strip().lower() in ("t", "true", "1", "yes")
            if contract
            else "STATE GOVERNMENT" in str(value).upper()
        )
        for value in values
    )


def grant_name(grants_gov, profiles, project, listing, description, award_id):
    for value, source in (
        (grants_gov, "grants_gov_nofo_title"),
        (profiles, "cdc_funding_profiles_nofo_title"),
        (project, "taggs_award_title"),
        (listing, "assistance_listing_title"),
    ):
        if clean(value):
            return clean(value), source
    value = clean(description) or clean(award_id) or "Unknown award"
    if len(value) > 200:
        value = value[:201].rsplit(" ", 1)[0] or value[:200]
    return value, "award_description"


def q(conn, sql, params=None):
    return conn.execute(text(sql), params or {})


def check_budget_categories(conn):
    """Require an exact category for every source account before writing a build."""
    missing = (
        q(
            conn,
            """SELECT DISTINCT f.federal_account_symbol
        FROM sf_file f LEFT JOIN state_funding.budget_category c
          ON c.federal_account_symbol = f.federal_account_symbol
        WHERE c.federal_account_symbol IS NULL ORDER BY 1""",
        )
        .scalars()
        .all()
    )
    if missing:
        raise RuntimeError(f"Unmapped federal account symbols: {', '.join(missing)}")
    rows = q(conn, "SELECT source, count(*) FROM state_funding.budget_category GROUP BY source").all()
    return {"sources": {source: count for source, count in rows}, "row_count": sum(count for _, count in rows)}


def stage(conn):
    steps = [
        """CREATE TEMP TABLE sf_file ON COMMIT DROP AS
           SELECT fiscal_year, coalesce(nullif(upper(trim(recipient_state)),''),'__') state,
                  award_unique_key, coalesce(nullif(trim(federal_account_symbol),''),'') federal_account_symbol,
                  coalesce(nullif(trim(federal_account_name),''),'') federal_account_name,
                  emergency='Emergency' is_supplemental, transaction_obligated_amount amount,
                  grant_or_contract, award_id_fain, award_id_piid, recipient_name, recipient_uei,
                  submission_period, prime_award_base_transaction_description description,
                  cfda_number, cfda_title, usaspending_permalink, import_run_id
             FROM cdc_funding.cdc_funding_awards WHERE fiscal_year BETWEEN 2021 AND 2026""",
        "CREATE INDEX ON sf_file (award_unique_key)",
        "CREATE INDEX ON sf_file (fiscal_year, federal_account_symbol)",
        """CREATE TEMP TABLE sf_names ON COMMIT DROP AS
           SELECT DISTINCT ON (fiscal_year,federal_account_symbol)
                  fiscal_year,federal_account_symbol,federal_account_name
           FROM sf_file WHERE federal_account_name<>'' GROUP BY 1,2,3
           ORDER BY fiscal_year,federal_account_symbol,count(*) DESC,federal_account_name""",
        "CREATE INDEX ON sf_names (fiscal_year,federal_account_symbol)",
        """CREATE TEMP TABLE sf_prime ON COMMIT DROP AS
           SELECT raw_record->>'assistance_award_unique_key' auk,
                  nullif(trim(raw_record->>'funding_opportunity_number'),'') fon,
                  raw_record->>'business_types_description' business_type,
                  source_file_name
             FROM cdc_funding.raw_usaspending_assistance_prime_transactions
            WHERE raw_record->>'assistance_award_unique_key' IN
                  (SELECT DISTINCT award_unique_key FROM sf_file)""",
        "CREATE INDEX ON sf_prime (auk)",
        """CREATE TEMP TABLE sf_contract ON COMMIT DROP AS
           SELECT raw_record->>'contract_award_unique_key' auk,
                  raw_record->>'us_state_government' state_flag, source_file_name
             FROM cdc_funding.raw_usaspending_contracts_prime_transactions
            WHERE raw_record->>'contract_award_unique_key' IN
                  (SELECT DISTINCT award_unique_key FROM sf_file)""",
        "CREATE INDEX ON sf_contract (auk)",
        """CREATE TEMP TABLE sf_awardbase ON COMMIT DROP AS
           SELECT DISTINCT award_unique_key auk FROM sf_file""",
        "CREATE INDEX ON sf_awardbase (auk)",
    ]
    for statement in steps:
        start = time.monotonic()
        q(conn, statement)
        LOG.info("stage %.1fs: %s", time.monotonic() - start, statement.splitlines()[0][:65])


def metadata(conn):
    periods = {
        str(r[0]): re.sub(r"(FY\d{4})P", r"\1 P", r[1]) if r[1] else f"FY{r[0]}"
        for r in q(conn, "SELECT fiscal_year, max(submission_period) FROM sf_file GROUP BY 1")
    }
    imports = [
        dict(r)
        for r in q(
            conn,
            """SELECT DISTINCT ON (fiscal_year) fiscal_year, import_run_id, submission_period
        FROM sf_file ORDER BY fiscal_year, submission_period DESC, import_run_id DESC""",
        ).mappings()
    ]
    taggs_run = (
        q(
            conn,
            """SELECT id, finished_at FROM taggs.ingestion_runs
            WHERE status='success' ORDER BY finished_at DESC NULLS LAST, id DESC LIMIT 1""",
        )
        .mappings()
        .first()
    )
    files = {
        kind: [
            r[0]
            for r in q(
                conn, f"SELECT DISTINCT source_file_name FROM {table} WHERE source_file_name IS NOT NULL ORDER BY 1"
            )
        ]
        for kind, table in (("assistance", "sf_prime"), ("contracts", "sf_contract"))
    }
    titles = {r[0]: r[1] for r in q(conn, "SELECT source, count(*) FROM state_funding.nofo_title GROUP BY source")}
    return {
        "file_c_imports": imports,
        "periods": periods,
        "taggs_ingestion_run": dict(taggs_run) if taggs_run else None,
        "prime_transaction_files": files,
        "nofo_title_counts": titles,
        "contracts_state_government_column": (
            "raw_usaspending_contracts_prime_transactions.raw_record.us_state_government"
        ),
    }


def make_awards(conn, build_id):
    steps = [
        """CREATE TEMP TABLE sf_file_meta ON COMMIT DROP AS
         SELECT b.auk, id.award_id, typ.award_type, nm.recipient_name, ue.recipient_uei,
                des.description, cf.cfda_number,cf.cfda_title, url.usaspending_url,
                nullif(trim(id.award_id_fain),'') fain
         FROM sf_awardbase b
         LEFT JOIN (SELECT DISTINCT ON (award_unique_key) award_unique_key,
              coalesce(nullif(trim(award_id_fain),''),nullif(trim(award_id_piid),''),award_unique_key) award_id,
              award_id_fain FROM sf_file
              ORDER BY award_unique_key,fiscal_year DESC,submission_period DESC
         ) id ON id.award_unique_key=b.auk
         LEFT JOIN (SELECT DISTINCT ON (award_unique_key) award_unique_key,
              CASE WHEN grant_or_contract='Grant' THEN 'grant' ELSE 'contract' END award_type
              FROM sf_file ORDER BY award_unique_key,abs(amount) DESC NULLS LAST,fiscal_year DESC
         ) typ ON typ.award_unique_key=b.auk
         LEFT JOIN (SELECT DISTINCT ON (award_unique_key) award_unique_key,trim(recipient_name) recipient_name
              FROM sf_file WHERE nullif(trim(recipient_name),'') IS NOT NULL
              ORDER BY award_unique_key,submission_period DESC,fiscal_year DESC) nm ON nm.award_unique_key=b.auk
         LEFT JOIN (SELECT DISTINCT ON (award_unique_key) award_unique_key,trim(recipient_uei) recipient_uei
              FROM sf_file WHERE nullif(trim(recipient_uei),'') IS NOT NULL
              ORDER BY award_unique_key,submission_period DESC,fiscal_year DESC) ue ON ue.award_unique_key=b.auk
         LEFT JOIN (SELECT DISTINCT ON (award_unique_key) award_unique_key,trim(description) description
              FROM sf_file WHERE nullif(trim(description),'') IS NOT NULL
              ORDER BY award_unique_key,length(trim(description)) DESC) des ON des.award_unique_key=b.auk
         LEFT JOIN (SELECT DISTINCT ON (award_unique_key) award_unique_key,
                   trim(cfda_number) cfda_number,trim(cfda_title) cfda_title
              FROM sf_file ORDER BY award_unique_key,abs(amount) DESC NULLS LAST) cf ON cf.award_unique_key=b.auk
         LEFT JOIN (SELECT DISTINCT ON (award_unique_key) award_unique_key,trim(usaspending_permalink) usaspending_url
              FROM sf_file WHERE nullif(trim(usaspending_permalink),'') IS NOT NULL
              ORDER BY award_unique_key,fiscal_year DESC,submission_period DESC) url ON url.award_unique_key=b.auk""",
        "CREATE INDEX ON sf_file_meta (fain)",
        """CREATE TEMP TABLE sf_prime_meta ON COMMIT DROP AS
         SELECT auk,array_agg(business_type) assistance_types,
            (array_agg(fon ORDER BY n DESC,fon) FILTER (WHERE fon IS NOT NULL))[1] prime_fon
         FROM (SELECT auk,fon,business_type,count(*) OVER (PARTITION BY auk,fon) n FROM sf_prime) x
         GROUP BY auk""",
        "CREATE INDEX ON sf_prime_meta (auk)",
        """CREATE TEMP TABLE sf_contract_meta ON COMMIT DROP AS
         SELECT auk,array_agg(state_flag) contract_types FROM sf_contract GROUP BY auk""",
        "CREATE INDEX ON sf_contract_meta (auk)",
        """CREATE TEMP TABLE sf_taggs_raw ON COMMIT DROP AS
         SELECT award_number fain,nullif(trim(fon),'') fon,nullif(trim(award_title),'') project_title
         FROM taggs.raw_awards WHERE award_number IN (SELECT fain FROM sf_file_meta WHERE fain IS NOT NULL)""",
        "CREATE INDEX ON sf_taggs_raw (fain)",
        """CREATE TEMP TABLE sf_taggs_fon ON COMMIT DROP AS
         SELECT DISTINCT ON (fain) fain,fon FROM sf_taggs_raw WHERE fon IS NOT NULL
         GROUP BY fain,fon ORDER BY fain,count(*) DESC,fon""",
        "CREATE INDEX ON sf_taggs_fon (fain)",
        """CREATE TEMP TABLE sf_taggs_title ON COMMIT DROP AS
         SELECT DISTINCT ON (fain) fain,project_title FROM sf_taggs_raw WHERE project_title IS NOT NULL
         GROUP BY fain,project_title ORDER BY fain,count(*) DESC,project_title""",
        "CREATE INDEX ON sf_taggs_title (fain)",
        """CREATE TEMP TABLE sf_taggs ON COMMIT DROP AS
         SELECT r.fain,f.fon taggs_fon,t.project_title FROM (SELECT DISTINCT fain FROM sf_taggs_raw) r
         LEFT JOIN sf_taggs_fon f USING(fain) LEFT JOIN sf_taggs_title t USING(fain)""",
        "CREATE INDEX ON sf_taggs (fain)",
    ]
    for statement in steps:
        began = time.monotonic()
        q(conn, statement)
        LOG.info("award stage %.1fs: %s", time.monotonic() - began, statement.splitlines()[0][:60])
    rows = q(
        conn,
        """SELECT b.auk,b.award_id,b.award_type,b.recipient_name,b.recipient_uei,b.description,
             b.cfda_number,b.cfda_title,b.usaspending_url,p.assistance_types,c.contract_types,
             p.prime_fon,t.taggs_fon,t.project_title
             FROM sf_file_meta b LEFT JOIN sf_prime_meta p ON p.auk=b.auk
             LEFT JOIN sf_contract_meta c ON c.auk=b.auk LEFT JOIN sf_taggs t ON t.fain=b.fain""",
    ).mappings()
    titles = {(r[0], r[1]): r[2] for r in q(conn, "SELECT fon_key, source, title FROM state_funding.nofo_title")}
    insert = text(
        """INSERT INTO state_funding.award
      (build_id,award_unique_key,award_id,award_type,recipient_name,recipient_uei,is_state_government,
       fon,fon_key,grant_name,name_source,project_title,description,cfda_number,cfda_title,usaspending_url,search_text)
      VALUES (:build_id,:award_unique_key,:award_id,:award_type,:recipient_name,:recipient_uei,:is_state_government,
       :fon,:fon_key,:grant_name,:name_source,:project_title,:description,
       :cfda_number,:cfda_title,:usaspending_url,:search_text)"""
    )
    batch = []
    for row in rows:
        r = dict(row)
        fon = clean(r["prime_fon"]) if r["award_type"] == "grant" else None
        fon = fon or (clean(r["taggs_fon"]) if r["award_type"] == "grant" else None)
        key = nofo_key(fon)
        name, source = grant_name(
            titles.get((key, "grants_gov")),
            titles.get((key, "cdc_funding_profiles")),
            r["project_title"],
            r["cfda_title"],
            r["description"],
            r["award_id"],
        )
        state_gov = is_state_government(
            r["assistance_types"] if r["award_type"] == "grant" else r["contract_types"],
            contract=r["award_type"] == "contract",
        )
        data = {
            "build_id": build_id,
            "award_unique_key": r["auk"],
            "award_id": r["award_id"],
            "award_type": r["award_type"],
            "recipient_name": r["recipient_name"] or r["award_id"],
            "recipient_uei": r["recipient_uei"],
            "is_state_government": state_gov,
            "fon": fon,
            "fon_key": key,
            "grant_name": name,
            "name_source": source,
            "project_title": r["project_title"],
            "description": r["description"],
            "cfda_number": r["cfda_number"],
            "cfda_title": r["cfda_title"],
            "usaspending_url": r["usaspending_url"],
        }
        data["search_text"] = " ".join(
            str(data.get(k) or "")
            for k in ("grant_name", "project_title", "description", "recipient_name", "award_id", "fon", "cfda_number")
        ).lower()
        batch.append(data)
        if len(batch) >= 1000:
            conn.execute(insert, batch)
            batch.clear()
    if batch:
        conn.execute(insert, batch)


def build(*, allow_live=False):
    db_name = make_url(DATABASE_URL).database
    if db_name != "places_staging" and not allow_live:
        raise RuntimeError(
            f"Refusing state funding build on {db_name!r}; use --allow-live for an explicitly approved live build"
        )
    start = time.monotonic()
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    with engine.begin() as conn:
        stage(conn)
        sources = metadata(conn)
        sources["budget_category_crosswalk"] = check_budget_categories(conn)
        build_id = q(
            conn,
            "INSERT INTO state_funding.build_run (method_version) VALUES (:method) RETURNING build_id",
            {"method": METHOD},
        ).scalar_one()
        q(
            conn,
            """INSERT INTO state_funding.obligation
          (build_id,fiscal_year,state,award_unique_key,federal_account_symbol,
           federal_account_name,is_supplemental,amount)
          SELECT :build_id, f.fiscal_year, f.state, f.award_unique_key, f.federal_account_symbol,
            coalesce(n.federal_account_name,''), f.is_supplemental, coalesce(sum(f.amount),0)
          FROM sf_file f LEFT JOIN sf_names n
            ON n.fiscal_year=f.fiscal_year AND n.federal_account_symbol=f.federal_account_symbol
          GROUP BY f.fiscal_year,f.state,f.award_unique_key,f.federal_account_symbol,
                   n.federal_account_name,f.is_supplemental""",
            {"build_id": build_id},
        )
        LOG.info("obligations %.1fs", time.monotonic() - start)
        make_awards(conn, build_id)
        LOG.info("awards %.1fs", time.monotonic() - start)
        mismatch = q(
            conn,
            """WITH src AS (SELECT fiscal_year,sum(amount) v FROM sf_file GROUP BY 1),
          dst AS (SELECT fiscal_year,sum(amount) v FROM state_funding.obligation WHERE build_id=:id GROUP BY 1)
          SELECT src.fiscal_year,src.v,dst.v FROM src FULL JOIN dst USING (fiscal_year)
          WHERE src.v IS DISTINCT FROM dst.v""",
            {"id": build_id},
        ).all()
        if mismatch:
            raise RuntimeError(f"File C reconciliation failed: {mismatch}")
        counts = {
            "award_rows": q(
                conn, "SELECT count(*) FROM state_funding.award WHERE build_id=:id", {"id": build_id}
            ).scalar(),
            "obligation_rows": q(
                conn, "SELECT count(*) FROM state_funding.obligation WHERE build_id=:id", {"id": build_id}
            ).scalar(),
            "name_source": dict(
                q(
                    conn,
                    "SELECT name_source,count(*) FROM state_funding.award WHERE build_id=:id GROUP BY 1",
                    {"id": build_id},
                ).all()
            ),
            "unattributed_dollars": {
                str(y): str(v)
                for y, v in q(
                    conn,
                    """SELECT fiscal_year,sum(amount) FROM state_funding.obligation
                    WHERE build_id=:id AND state='__' GROUP BY 1 ORDER BY 1""",
                    {"id": build_id},
                )
            },
        }
        q(
            conn,
            """UPDATE state_funding.build_run
            SET status='complete',finished_at=now(),sources=cast(:sources AS jsonb),
                counts=cast(:counts AS jsonb) WHERE build_id=:id""",
            {
                "sources": json.dumps(sources, default=str),
                "counts": json.dumps(counts),
                "id": build_id,
            },
        )
        q(
            conn,
            """INSERT INTO state_funding.active_build(singleton,build_id) VALUES (true,:id)
            ON CONFLICT(singleton) DO UPDATE SET build_id=excluded.build_id,activated_at=now()""",
            {"id": build_id},
        )
        q(
            conn,
            """DELETE FROM state_funding.build_run WHERE build_id NOT IN
            (SELECT build_id FROM state_funding.build_run WHERE status='complete'
             ORDER BY build_id DESC LIMIT 2) AND build_id<>:id""",
            {"id": build_id},
        )
    LOG.info("build %s complete in %.1fs: %s", build_id, time.monotonic() - start, counts)
    return build_id, counts, time.monotonic() - start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    print(build(allow_live=args.allow_live))


if __name__ == "__main__":
    main()
